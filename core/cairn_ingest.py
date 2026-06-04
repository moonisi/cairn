#!/usr/bin/env python3
# Cairn ingest: source 나열(list)·dedup 분기 후보(candidates)·page 기록(write)
# 결정적 헬퍼만 — 의미 reconcile 합성은 LLM(P2 §5.1). zero-dep.
import sys
import re
import difflib
import datetime
from pathlib import Path

import cairn_root as r
import cairn_nudge as nudge  # ingest-time turn 역조회용 정규화 함수 재사용(redact_url·qhash·queue I/O)

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
TAU = 0.7  # dedup 유사도 임계(D-P3-G, Gate 3 실측 확정)


# ─── multi-entry source 분해 (P2 §5.4) ───
def split_entries(text, anchor_cfg=None):
    """multi-entry md → [(anchor, title, entry_text, special_id)]. 가장 얕은 heading level이 entry 경계.
    anchor_cfg(refs.anchor: {pattern, prefix}) 있으면 heading→special anchor 규약 적용, 없으면 heading slug."""
    lines = text.split("\n")
    heads = []
    for i, ln in enumerate(lines):
        m = HEADING_RE.match(ln)
        if m:
            heads.append((i, len(m.group(1)), m.group(2).strip()))
    if not heads:
        # heading 0 = 단일지식 자원 전체(P2 §3.2). anchor None → locator = source 자체.
        return [(None, "", text, None)]
    min_level = min(h[1] for h in heads)
    bounds = [h for h in heads if h[1] == min_level]
    entries = []
    used = set()
    prefix = anchor_cfg.get("prefix") if anchor_cfg else None
    pat = re.compile(anchor_cfg["pattern"]) if (anchor_cfg and anchor_cfg.get("pattern")) else None
    for idx, (start, _lvl, title) in enumerate(bounds):
        end = bounds[idx + 1][0] if idx + 1 < len(bounds) else len(lines)
        entry_text = "\n".join(lines[start:end])
        # special anchor 규약은 어댑터 config(refs.anchor) 소관(D-P3-F). 패턴 비매칭 heading은 heading slug.
        m = pat.search(title) if pat else None
        special_id = m.group(1) if m else None
        anchor = r.anchor_of(title, special_id=special_id, prefix=prefix, used=used)
        entries.append((anchor, title, entry_text, special_id))
    return entries


def source_units(source_rel, cd, kind="file", anchor_cfg=None):
    """source 파일 → [{anchor,title,kind,locator,hash}]. anchor_cfg = refs.anchor(없으면 heading slug)."""
    path = r.resolve_path(source_rel, cd)
    text = Path(path).read_text(encoding="utf-8")
    units = []
    for anchor, title, entry_text, _sid in split_entries(text, anchor_cfg):
        # single-resource(heading 0, anchor None) = source 자체가 locator. multi-entry만 <path>#<anchor>.
        raw = source_rel if anchor is None else f"{source_rel}#{anchor}"
        units.append({
            "anchor": anchor,
            "title": title,
            "kind": kind,
            "locator": r.make_locator(raw),
            "hash": r.content_hash(entry_text),
        })
    return units


# ─── 기존 page 스캔 ───
def iter_pages(cd, config):
    pages_dir = cd / config.get("vault", {}).get("pagesDir", "pages")
    if not pages_dir.exists():
        return []
    out = []
    for p in sorted(pages_dir.rglob("*.md")):
        fm, body = r.parse_frontmatter(p.read_text(encoding="utf-8"))
        prov = [r.parse_provenance(x) for x in fm.get("provenance", [])]
        out.append({
            "slug": fm.get("slug", p.stem),
            "type": fm.get("type", ""),
            "title": fm.get("title", ""),
            "tags": fm.get("tags", []),
            "provenance": prov,  # [(kind,locator,hash)]
            "fm": fm, "body": body, "path": p,
        })
    return out


def _sim_fields(page):
    """비교 대상 필드(slug·title·tags 연결). 길이편향 회피 위해 필드별·연결 max로 비교."""
    return [page["slug"], page["title"],
            " ".join([page["slug"], page["title"]] + list(page["tags"]))]


def _similarity(unit_key, page):
    return max(difflib.SequenceMatcher(None, unit_key, f).ratio() for f in _sim_fields(page))


# ─── dedup 3분기 (D-P3-E, P3a §5.1·§5.3) ───
def classify_unit(unit, pages):
    """unit → {branch, page_slug?, locators_present?}.
    branches: no-op / provenance-append / update / merge / new."""
    hash_index = {}   # hash -> page
    loc_index = {}    # locator -> page
    for pg in pages:
        for (k, loc, h) in pg["provenance"]:
            hash_index.setdefault(h, pg)
            loc_index.setdefault(loc, pg)

    h, loc = unit["hash"], unit["locator"]
    # 1) hash 일치 → no-op (locator 새것이면 provenance-append)
    if h in hash_index:
        pg = hash_index[h]
        page_locs = {l for (_k, l, _h) in pg["provenance"]}
        if loc in page_locs:
            return {"branch": "no-op", "page_slug": pg["slug"]}
        return {"branch": "provenance-append", "page_slug": pg["slug"]}
    # 2) locator 일치 + hash 다름 → 갱신
    if loc in loc_index:
        return {"branch": "update", "page_slug": loc_index[loc]["slug"]}
    # 3) 둘다 불일치 → 유사도 ≥ τ → merge / 미만 → 신규
    best, best_score = None, 0.0
    unit_key = unit["title"] or r.parse_locator(loc)
    for pg in pages:
        score = _similarity(unit_key, pg)
        if score > best_score:
            best, best_score = pg, score
    if best and best_score >= TAU:
        return {"branch": "merge", "page_slug": best["slug"], "score": round(best_score, 3)}
    return {"branch": "new"}


# ─── write: frontmatter 검증 → page 기록 + index/log 갱신 ───
REQUIRED = ["slug", "type", "title"]


def validate_page(fm, config):
    errs = []
    for k in REQUIRED:
        if not fm.get(k):
            errs.append(f"필수 필드 부재: {k}")
    if fm.get("type") and fm["type"] not in config.get("pageTypes", []):
        errs.append(f"type '{fm.get('type')}' ∉ pageTypes {config.get('pageTypes')}")
    prov = fm.get("provenance", [])
    if not prov:
        errs.append("provenance 1+ 필요")
    for item in prov:
        k, l, hh = r.parse_provenance(item)
        if not (k and l and hh):
            errs.append(f"provenance 형식 위반: {item}")
    return errs


def _now():
    return datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()


def update_index(cd, config, fm):
    idx_path = cd / "index.md"
    header = "| slug | type | title | tags | refs | updated |"
    sep = "| --- | --- | --- | --- | --- | --- |"
    tags = ",".join(fm.get("tags", []))
    refs = ",".join(fm.get("refs", []))
    row = f"| {fm['slug']} | {fm.get('type','')} | {fm.get('title','')} | {tags} | {refs} | {fm.get('updated','')} |"
    if idx_path.exists():
        lines = idx_path.read_text(encoding="utf-8").split("\n")
    else:
        lines = ["# index — page 카탈로그", "", header, sep]
    # 동일 slug 행 교체 또는 append
    replaced = False
    for i, ln in enumerate(lines):
        if ln.startswith(f"| {fm['slug']} |"):
            lines[i] = row
            replaced = True
            break
    if not replaced:
        lines.append(row)
    idx_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def remove_index_row(cd, slug):
    """index.md에서 해당 slug 행 제거(move로 slug 변경 시 구 행 정리). 없으면 no-op."""
    idx_path = cd / "index.md"
    if not idx_path.exists():
        return
    lines = idx_path.read_text(encoding="utf-8").split("\n")
    kept = [ln for ln in lines if not ln.startswith(f"| {slug} |")]
    idx_path.write_text("\n".join(kept).rstrip() + "\n", encoding="utf-8")


def append_log(cd, event, detail, turn=None):
    log_path = cd / "log.md"
    line = f"- {_now()} | {event} | {detail}"
    if turn:  # turn 명시 시에만 태깅(없으면 기존 라인 불변 — 하위호환)
        line += f" | turn: {turn}"
    prefix = "" if log_path.exists() else "# log — append-only 활동 로그\n\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(prefix + line + "\n")


def commit_page(fm, body, cd, config, event, turn=None):
    """🔒 단일 mutation 경로(KC-Fn-G2-2): page 파일 기록 + index + log 동시 갱신.
    모든 page 쓰기(ingest·reconcile)는 본 함수 경유 → audit trail·indexed 필드 일관 보장.
    기존 slug의 type 변경은 거부(구 type 경로 잔존 + 중복 page 방지) — 명시적 이동 필요. errs 반환."""
    existing = find_page_path(cd, config, fm["slug"])
    if existing is not None and existing.parent.name != fm["type"]:
        return [f"type 변경 거부: {fm['slug']} ({existing.parent.name}→{fm['type']}). 명시적 이동/삭제 필요"]
    if turn:  # Phase B: turn 명시 시 fm에 대표값(최신) 보존. None이면 기존 fm["turn"] 비파괴.
        fm["turn"] = turn
    pages_dir = cd / config.get("vault", {}).get("pagesDir", "pages") / fm["type"]
    pages_dir.mkdir(parents=True, exist_ok=True)
    dest = pages_dir / f"{fm['slug']}.md"
    dest.write_text(r.dump_frontmatter(fm, body), encoding="utf-8")
    update_index(cd, config, fm)
    append_log(cd, event, f"{fm['slug']} → pages/{fm['type']}/", turn=turn)
    return []


def find_page_path(cd, config, slug):
    """slug → 기존 page 파일 경로(없으면 None)."""
    pages_dir = cd / config.get("vault", {}).get("pagesDir", "pages")
    if not pages_dir.exists():
        return None
    for p in pages_dir.rglob("*.md"):
        fm, _ = r.parse_frontmatter(p.read_text(encoding="utf-8"))
        if fm.get("slug", p.stem) == slug:
            return p
    return None


def lookup_turn(fm, cd, config):
    """ingest-time turn 역조회(#3 Phase C): page fm의 url provenance를 nudge redact 규칙으로
    재정규화 → qhash → nudge-queue pending 역조회 → (turn, [matched_qhash]) 반환.
    정규화 계약 = config.nudge.redact 단일 진실원(collect-time qhash 재현). 매칭 0건이면 (None, [])."""
    redact = config.get("nudge", {}).get("redact", ["query", "hash", "userinfo"])
    pending = {f["qhash"]: f for f in nudge.parse_queue(cd) if f["status"] == "pending"}
    matched = []  # (ts, turn, qhash)
    for item in fm.get("provenance", []):
        kind, loc, _h = r.parse_provenance(item)
        if kind != "url":  # url kind만 대상(file/kit/manual 스킵 — websearch 비대상)
            continue
        raw = r.parse_locator(loc)  # quote된 locator → raw URL 복원(sha256 vs quote 불일치 해소)
        rloc, _ref = nudge.redact_url(raw, redact)
        f = pending.get(nudge.qhash(rloc))
        if f and f.get("turn"):
            matched.append((f.get("ts", ""), f["turn"], f["qhash"]))
    if not matched:
        return None, []
    matched.sort(key=lambda t: t[0])  # 대표값 = 최신 ts 스칼라(Phase B 정책 정합)
    return matched[-1][1], [qh for _ts, _tn, qh in matched]


def _mark_ingested(cd, config, qhashes):
    """역조회 매칭된 queue 항목을 pending→ingested 전환 + nudge-ingested 메트릭 append.
    self-measure 적중률 루프 완성(emit 제안 → 실제 ingest 닫힘)."""
    qset = set(qhashes)
    rows = nudge.parse_queue(cd)
    changed = False
    for f in rows:
        if f["qhash"] in qset and f["status"] == "pending":
            f["status"] = "ingested"
            changed = True
    if changed:
        nudge.write_queue(cd, rows)
    session = config.get("nudge", {}).get("session") or "ingest"
    for qh in qhashes:
        nudge.append_metric(cd, "nudge-ingested", qh, session)


def write_page(page_md_path, cd, config, turn=None, source_url=None, session_source=None):
    text = Path(page_md_path).read_text(encoding="utf-8")
    fm, body = r.parse_frontmatter(text)
    if source_url:  # skill 경로: locator → url provenance 결정적 민팅(quote+body hash) → Phase C 자동연결
        item = r.format_provenance("url", r.make_locator(source_url), r.content_hash(body))
        prov = fm.get("provenance", [])
        if item not in prov:
            fm["provenance"] = prov + [item]
    if session_source:  # capture 경로: 대화 turn → conversation provenance 결정적 민팅(quote+body hash)
        item = r.format_provenance("conversation", r.make_locator(session_source), r.content_hash(body))
        prov = fm.get("provenance", [])
        if item not in prov:
            fm["provenance"] = prov + [item]
        if turn is None:  # turn 미지정 시 session_turn으로 로그 링크(대화는 큐 항목 없어 역조회 불가)
            turn = session_source
    errs = validate_page(fm, config)
    if errs:
        return errs
    matched = []
    if turn is None:  # turn 우선순위: 명시 --turn > 역조회 > None
        turn, matched = lookup_turn(fm, cd, config)
    errs = commit_page(fm, body, cd, config, "ingest", turn=turn)
    if not errs and matched:  # 커밋 성공 후에만 status 전환(validate 실패 시 queue 비파괴)
        _mark_ingested(cd, config, matched)
    return errs


# ─── reconcile: 저널 경유 강제 (KC-Fn-G2-2) ───
def reconcile_provenance_append(slug, source_rel, anchor, cd, config, turn=None):
    """결정적 provenance-append: source unit에서 locator/hash 재계산 → 기존 page slug에 항목 누적.
    이미 존재 시 no-op. commit_page 경유로 log·index 동시 갱신(audit trail 보장)."""
    p = find_page_path(cd, config, slug)
    if p is None:
        return [f"page 부재: {slug}"]
    anchor_cfg = config.get("refs", {}).get("anchor")
    units = {u["anchor"]: u for u in source_units(source_rel, cd, anchor_cfg=anchor_cfg)}
    u = units.get(anchor) if anchor else (source_units(source_rel, cd, anchor_cfg=anchor_cfg) or [None])[0]
    if u is None:
        return [f"source unit 부재: {source_rel}#{anchor}"]
    item = r.format_provenance(u["kind"], u["locator"], u["hash"])
    fm, body = r.parse_frontmatter(p.read_text(encoding="utf-8"))
    prov = fm.get("provenance", [])
    if item in prov:
        return []  # 이미 존재 = no-op(멱등)
    fm["provenance"] = prov + [item]
    fm["updated"] = _now()[:10]
    return commit_page(fm, body, cd, config, "reconcile:provenance-append", turn=turn)


def reconcile_write(page_md_path, branch, cd, config, turn=None):
    """update/merge: LLM이 합성한 page.md를 저널 경유 기록. body 합성은 LLM(손/머리 분담),
    기록은 반드시 commit_page 경유 강제. update/merge는 기존 slug 존재 요구."""
    if branch not in ("update", "merge"):
        return [f"reconcile branch 미지원: {branch}"]
    text = Path(page_md_path).read_text(encoding="utf-8")
    fm, body = r.parse_frontmatter(text)
    errs = validate_page(fm, config)
    if errs:
        return errs
    if find_page_path(cd, config, fm["slug"]) is None:
        return [f"reconcile {branch}: 기존 page 부재 {fm['slug']}"]
    return commit_page(fm, body, cd, config, f"reconcile:{branch}", turn=turn)


def reconcile_move(old_slug, new_slug, new_type, cd, config):
    """page 재분류(KC-Fn-G2b-3): slug·type 명시 이동. commit_page가 막는 type 변경의 유일 합법 경로.
    구 page 읽기 → 검증 → 구 파일·index 행 제거 → 신 slug/type로 commit_page(저널 경유 강제).
    검증은 파괴 전 수행(실패 시 구 page 무손실). wikilink 재지정은 lint(dangling)가 후속 탐지."""
    p = find_page_path(cd, config, old_slug)
    if p is None:
        return [f"page 부재: {old_slug}"]
    fm, body = r.parse_frontmatter(p.read_text(encoding="utf-8"))
    target_type = new_type or fm.get("type")
    new_fm = dict(fm)
    new_fm["slug"] = new_slug
    new_fm["type"] = target_type
    new_fm["updated"] = _now()[:10]
    errs = validate_page(new_fm, config)  # 파괴 전 검증
    if errs:
        return errs
    if new_slug != old_slug and find_page_path(cd, config, new_slug) is not None:
        return [f"reconcile move: 대상 slug 이미 존재 {new_slug}"]
    # 검증 통과 → 구 page·index 행 정리 후 신규 기록(commit_page existing None 통과)
    p.unlink()
    if new_slug != old_slug:
        remove_index_row(cd, old_slug)
    return commit_page(new_fm, body, cd, config, f"reconcile:move:{old_slug}→{new_slug}/{target_type}")


# ─── CLI ───
def main(argv):
    if not argv:
        print("usage: cairn_ingest.py list [source] | candidates <source> | write <page.md> [--turn <st>] | "
              "reconcile (append <slug> <source> [anchor] | <update|merge> <page.md> | "
              "move <old_slug> <new_slug> [new_type])")
        return 2
    config, cd = r.load_config()
    cmd = argv[0]
    anchor_cfg = config.get("refs", {}).get("anchor")

    if cmd == "list":
        src = argv[1] if len(argv) > 1 else config.get("paths", {}).get("defaultIngestSource")
        if not src:
            print("source 미지정(인자 또는 config.paths.defaultIngestSource)")
            return 2
        pages = iter_pages(cd, config)
        known_hashes = {h for pg in pages for (_k, _l, h) in pg["provenance"]}
        for u in source_units(src, cd, anchor_cfg=anchor_cfg):
            status = "ingested" if u["hash"] in known_hashes else "new"
            print(f"{status}\t{u['anchor']}\t{u['hash']}\t{u['locator']}")
        return 0

    if cmd == "candidates":
        if len(argv) < 2:
            print("usage: candidates <source>")
            return 2
        src = argv[1]
        pages = iter_pages(cd, config)
        for u in source_units(src, cd, anchor_cfg=anchor_cfg):
            res = classify_unit(u, pages)
            tail = res.get("page_slug", "")
            score = f" score={res['score']}" if "score" in res else ""
            print(f"{res['branch']}\t{u['anchor']}\t{tail}{score}")
        return 0

    if cmd == "write":
        if len(argv) < 2:
            print("usage: write <page.md> [--turn <session_turn>] [--source-url <locator>] [--session-source <session_turn>]")
            return 2
        # --turn <session_turn>: 어댑터/스킬이 carry한 session_turn 전달(코어는 산출 안 함, KC-Fn-41)
        turn = None
        if "--turn" in argv:
            i = argv.index("--turn")
            turn = argv[i + 1] if i + 1 < len(argv) else None
        # --source-url <locator>: skill이 pending locator 전달 → url provenance 민팅(Phase C 자동연결)
        source_url = None
        if "--source-url" in argv:
            i = argv.index("--source-url")
            source_url = argv[i + 1] if i + 1 < len(argv) else None
        # --session-source <session_turn>: capture skill이 대화 turn 전달 → conversation provenance 민팅
        session_source = None
        if "--session-source" in argv:
            i = argv.index("--session-source")
            session_source = argv[i + 1] if i + 1 < len(argv) else None
        errs = write_page(argv[1], cd, config, turn=turn, source_url=source_url, session_source=session_source)
        if errs:
            for e in errs:
                print(f"INVALID: {e}")
            return 1
        print("OK")
        return 0

    if cmd == "reconcile":
        # reconcile append <slug> <source_rel> [<anchor>]  |  reconcile <update|merge> <page.md>
        if len(argv) < 2:
            print("usage: reconcile append <slug> <source> [anchor] | reconcile <update|merge> <page.md> | "
                  "reconcile move <old_slug> <new_slug> [new_type]")
            return 2
        sub = argv[1]
        if sub == "append":
            if len(argv) < 4:
                print("usage: reconcile append <slug> <source_rel> [anchor]")
                return 2
            anchor = argv[4] if len(argv) > 4 else None
            errs = reconcile_provenance_append(argv[2], argv[3], anchor, cd, config)
        elif sub == "move":
            if len(argv) < 4:
                print("usage: reconcile move <old_slug> <new_slug> [new_type]")
                return 2
            new_type = argv[4] if len(argv) > 4 else None
            errs = reconcile_move(argv[2], argv[3], new_type, cd, config)
        else:
            if len(argv) < 3:
                print("usage: reconcile <update|merge> <page.md>")
                return 2
            errs = reconcile_write(argv[2], sub, cd, config)
        if errs:
            for e in errs:
                print(f"INVALID: {e}")
            return 1
        print("OK")
        return 0

    print(f"unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
