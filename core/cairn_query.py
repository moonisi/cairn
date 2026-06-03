#!/usr/bin/env python3
# Cairn query: 2단계 라우팅(index coarse → BM25 fine) + grep fallback + MISS closest-slug
# zero-dep BM25 즉석계산(P3a §4·§6). 반환 = (slug, score, chunk) top-k — 답변 합성은 LLM(P4a §6).
import sys
import re
import math
from collections import Counter
from pathlib import Path

import cairn_root as r
import cairn_ingest as ing

N_CHUNK = 400      # page > N줄 → heading 섹션 분할(P3a §8)
K1, B = 1.5, 0.75  # BM25 파라미터 시작값(Gate 3 실측 확정)
TOPK = 5
GREP_FLOOR = 0.0   # BM25 top 점수 ≤ floor → grep fallback

# 유니코드 단어문자(한글·CJK·라틴·숫자), '_'·구두점 제외. 한글 = 공백분절(zero-dep, 형태소분석 없음 — P4b 재검토)
TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def tokenize(text):
    return TOKEN_RE.findall(text.lower())


# ─── 청크 분할: page > N줄 → heading(##) 섹션 / 이하 통째 ───
def chunk_page(page):
    body = page["body"]
    lines = body.split("\n")
    if len(lines) <= N_CHUNK:
        return [(page["slug"], body)]
    chunks, cur, cur_head = [], [], page["slug"]
    for ln in lines:
        if ing.HEADING_RE.match(ln) and cur:
            chunks.append((cur_head, "\n".join(cur)))
            cur, cur_head = [], ln.strip("# ").strip() or page["slug"]
        else:
            if ing.HEADING_RE.match(ln):
                cur_head = ln.strip("# ").strip() or page["slug"]
            cur.append(ln)
    if cur:
        chunks.append((cur_head, "\n".join(cur)))
    # slug#head 형태로 라벨(중복 head 무관 — 본문으로 식별)
    return [(f"{page['slug']}#{h}" if h != page["slug"] else page["slug"], c) for h, c in chunks]


# ─── BM25 (idf·tf 포화·doclen 정규화, 즉석계산) ───
def bm25_rank(query, chunks):
    """chunks=[(label, text, slug)]. 반환 [(label, score, slug, text)] 내림차순."""
    q_terms = tokenize(query)
    docs = [(lbl, tokenize(txt), slug, txt) for (lbl, txt, slug) in chunks]
    Ndoc = len(docs)
    if Ndoc == 0:
        return []
    avgdl = sum(len(d[1]) for d in docs) / Ndoc
    # df
    df = Counter()
    for _lbl, toks, _slug, _txt in docs:
        for t in set(toks):
            df[t] += 1
    scored = []
    for lbl, toks, slug, txt in docs:
        tf = Counter(toks)
        dl = len(toks)
        score = 0.0
        for qt in q_terms:
            if qt not in tf:
                continue
            idf = math.log(1 + (Ndoc - df[qt] + 0.5) / (df[qt] + 0.5))
            f = tf[qt]
            denom = f + K1 * (1 - B + B * dl / avgdl) if avgdl else 1
            score += idf * (f * (K1 + 1)) / denom
        scored.append((lbl, round(score, 4), slug, txt))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


# ─── coarse: index 테이블 + alias 정규화 ───
def normalize_terms(terms, aliases):
    return [aliases.get(t, t) for t in terms]


def coarse_filter(query, pages, config):
    """질의 토큰과 tag(별칭 정규화) 교집합 있는 page만. 매칭 0 → 전체 반환(fallback)."""
    aliases = config.get("taxonomy", {}).get("aliases", {})
    q_norm = set(normalize_terms(tokenize(query), aliases))
    sub = []
    for pg in pages:
        tags = set(normalize_terms([t.lower() for t in pg["tags"]], aliases))
        if q_norm & tags:
            sub.append(pg)
    return sub if sub else pages


# ─── grep fallback ───
def grep_search(query, pages):
    terms = tokenize(query)
    if not terms:
        return []
    pat = re.compile("|".join(re.escape(t) for t in terms), re.IGNORECASE)
    hits = []
    for pg in pages:
        cnt = len(pat.findall(pg["body"]))
        if cnt:
            hits.append((pg["slug"], cnt, pg["slug"], pg["body"][:200]))
    hits.sort(key=lambda x: x[1], reverse=True)
    return hits


def closest_slug(query, pages):
    import difflib
    slugs = [pg["slug"] for pg in pages]
    m = difflib.get_close_matches(r.heading_slug(query), slugs, n=1, cutoff=0.0)
    return m[0] if m else None


def query(q, cd, config, topk=TOPK):
    pages = ing.iter_pages(cd, config)
    if not pages:
        return {"mode": "empty", "results": []}
    candidates = coarse_filter(q, pages, config)
    chunks = []
    for pg in candidates:
        for label, text in chunk_page(pg):
            chunks.append((label, text, pg["slug"]))
    ranked = bm25_rank(q, chunks)
    top = [x for x in ranked if x[1] > GREP_FLOOR][:topk]
    if top:
        return {"mode": "bm25",
                "results": [{"slug": s, "score": sc, "chunk_label": lbl} for (lbl, sc, s, _t) in top]}
    # BM25 MISS → grep fallback
    g = grep_search(q, pages)
    if g:
        return {"mode": "grep",
                "results": [{"slug": s, "score": c, "chunk_label": lbl} for (lbl, c, s, _t) in g[:topk]]}
    # 완전 MISS → closest-slug
    return {"mode": "miss", "closest_slug": closest_slug(q, pages), "results": []}


def main(argv):
    if not argv:
        print("usage: cairn_query.py <query>")
        return 2
    config, cd = r.load_config()
    res = query(" ".join(argv), cd, config)
    print(f"mode: {res['mode']}")
    if res.get("closest_slug"):
        print(f"closest-slug: {res['closest_slug']}")
    for row in res["results"]:
        print(f"  {row['score']}\t{row['slug']}\t({row['chunk_label']})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
