#!/usr/bin/env python3
# Cairn lint: 결정탐지 — frontmatter·dangling wikilink·orphan·stale·refs drift·provenance 형식·alias·index-drift
# (의미검토는 LLM/사용자, 본 스크립트는 결정탐지 6~8만; P3a §3.5, P3b §3.2). zero-dep.
import sys
import re
from pathlib import Path

import cairn_root as r
import cairn_ingest as ing

WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


class Finding:
    def __init__(self, sev, code, page, msg):
        self.sev, self.code, self.page, self.msg = sev, code, page, msg

    def __str__(self):
        return f"{self.sev}\t{self.code}\t{self.page}\t{self.msg}"


def refs_active(config):
    """refs 검증 활성 조건: refs 블록 + paths.refsScope + pattern/dir/idPattern 모두 존재 → 활성, 아니면 None gate."""
    refs = config.get("refs")
    scope = config.get("paths", {}).get("refsScope")
    if not (refs and scope and refs.get("pattern") and refs.get("dir") and refs.get("idPattern")):
        return None
    return refs, scope


def ref_target_ids(cd, config):
    """refs.dir 실재 target ID 집합(refs.idPattern group(1)). refs 미설정 → None(검증 스킵)."""
    act = refs_active(config)
    if act is None:
        return None
    refs, scope = act
    root = r.resolve_path(f"{scope}/{refs['dir']}", cd)
    if not root.exists():
        return set()
    id_re = re.compile(refs["idPattern"])
    ids = set()
    for d in root.iterdir():
        if d.is_dir():
            m = id_re.match(d.name)
            if m:
                ids.add(m.group(1))
    return ids


_IDX_FIELDS = ["type", "title", "tags", "refs", "updated"]


def parse_index_rows(cd):
    """index.md 표 → {slug: {type,title,tags,refs,updated}}. update_index 행 형식과 round-trip."""
    idx = cd / "index.md"
    if not idx.exists():
        return {}
    rows = {}
    for line in idx.read_text(encoding="utf-8").split("\n"):
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")]
        # split → ['', slug, type, title, tags, refs, updated, ''] = 8 cell
        if len(cells) < 8:
            continue
        slug = cells[1]
        if slug in ("slug", "---", ""):  # header·separator·빈 행 스킵
            continue
        rows[slug] = dict(zip(_IDX_FIELDS, cells[2:7]))
    return rows


def index_drift(cd, pages):
    """index.md ↔ page fm indexed 필드 정합 검사(KC-Fn-G2-2). 불일치 = CRIT(index 기반 coarse 라우팅 안전망)."""
    findings = []
    rows = parse_index_rows(cd)
    slugs = {pg["slug"] for pg in pages}
    for pg in pages:
        fm = pg["fm"]
        row = rows.get(pg["slug"])
        if row is None:
            findings.append(Finding("CRIT", "index-drift", pg["slug"], "index.md 행 부재(저널 미경유 의심)"))
            continue
        expect = {
            "type": fm.get("type", ""),
            "title": fm.get("title", ""),
            "tags": ",".join(fm.get("tags", [])),
            "refs": ",".join(fm.get("refs", [])),
            "updated": str(fm.get("updated", "")),
        }
        for f in _IDX_FIELDS:
            if row.get(f, "") != expect[f]:
                findings.append(Finding("CRIT", "index-drift", pg["slug"],
                                        f"{f} stale: index={row.get(f,'')!r} page={expect[f]!r}"))
    for slug in rows:
        if slug not in slugs:
            findings.append(Finding("CRIT", "index-drift", slug, "index 행에 대응 page 부재"))
    return findings


def lint(cd, config):
    pages = ing.iter_pages(cd, config)
    findings = []
    slugs = {pg["slug"] for pg in pages}
    feats = ref_target_ids(cd, config)
    act = refs_active(config)
    ref_re = re.compile(act[0]["pattern"]) if act else None
    ref_dir = f"{act[1]}/{act[0]['dir']}" if act else ""
    aliases = config.get("taxonomy", {}).get("aliases", {})

    # backlink 그래프(orphan 탐지용)
    referenced = set()
    for pg in pages:
        targets = set(WIKILINK_RE.findall(pg["body"])) | set(pg["fm"].get("links", []))
        for t in targets:
            referenced.add(t)
            # dangling wikilink
        for t in WIKILINK_RE.findall(pg["body"]):
            if t not in slugs:
                findings.append(Finding("WARN", "dangling", pg["slug"], f"[[{t}]] index 미등록"))

    superseded_targets = {}  # target -> by
    for pg in pages:
        fm = pg["fm"]
        # 1) frontmatter 형식
        for e in ing.validate_page(fm, config):
            findings.append(Finding("CRIT", "frontmatter", pg["slug"], e))
        # 6) provenance 형식
        for item in fm.get("provenance", []):
            k, l, h = r.parse_provenance(item)
            if not (k and l and h):
                findings.append(Finding("CRIT", "provenance", pg["slug"], f"형식 위반: {item}"))
        # 5) refs drift
        if feats is not None:
            for ref in fm.get("refs", []):
                m = ref_re.match(ref)
                if not m:
                    findings.append(Finding("WARN", "refs-format", pg["slug"], f"refs 형식 위반: {ref}"))
                elif m.group(1) not in feats:
                    findings.append(Finding("WARN", "refs-drift", pg["slug"], f"{ref} → {ref_dir}/ 부재"))
        # 7) alias 표기
        for t in fm.get("tags", []):
            if t.lower() in aliases:
                findings.append(Finding("WARN", "alias", pg["slug"], f"tag '{t}' → 정규형 '{aliases[t.lower()]}' 권장"))
        # stale 준비
        for s in fm.get("supersedes", []):
            superseded_targets[s] = pg["slug"]

    # 3) orphan — 아무도 참조 안 함(manual self 제외 권장이나 WARN)
    for pg in pages:
        if pg["slug"] not in referenced:
            findings.append(Finding("WARN", "orphan", pg["slug"], "역링크 0"))

    # 4) stale — supersedes 대상이 deprecated 아님
    by_slug = {pg["slug"]: pg for pg in pages}
    for target, by in superseded_targets.items():
        tp = by_slug.get(target)
        if tp and tp["fm"].get("status") != "deprecated":
            findings.append(Finding("WARN", "stale", target, f"{by}가 supersede → status:deprecated 필요"))

    # 8) index-drift — index.md ↔ page fm 정합(저널 경유 강제 net, KC-Fn-G2-2)
    findings.extend(index_drift(cd, pages))

    return findings


def main(argv):
    config, cd = r.load_config()
    findings = lint(cd, config)
    crit = sum(1 for f in findings if f.sev == "CRIT")
    for f in findings:
        print(f)
    print(f"--- {len(findings)} findings ({crit} critical) ---")
    return 1 if crit else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
