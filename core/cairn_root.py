#!/usr/bin/env python3
# Cairn 코어 공용 라이브러리: root 해석·config 로더·제한문법 frontmatter 파서·정규화/해시/anchor/locator·provenance
# zero-dep(stdlib only) — D-KC-05, D-P2-A. 결정적 헬퍼만(P2 §5.1 손/머리 분담).
import os
import sys
import re
import json
import hashlib
import urllib.parse
from pathlib import Path

CONFIG_NAME = "cairn.config.json"

# v1→v2 breaking rename(G2b-1, D-KC-15): 코어는 Kit 도메인 용어 하드코딩 금지.
# 자동 alias 아님 — 구키 발견 시 명시 경고만(사용자 config 갱신 유도).
LEGACY_PATH_KEYS = {"kitSpecs": "refsScope", "lessonsSource": "defaultIngestSource"}


# ─── root 해석 (D-P4-E: 상대경로 기준 = CAIRN_DIR의 parent = case workspace root) ───
def find_cairn_dir():
    """CAIRN_DIR env → Path. 미설정 시 ValueError."""
    cd = os.environ.get("CAIRN_DIR")
    if not cd:
        raise ValueError("CAIRN_DIR 환경변수 미설정")
    p = Path(cd)
    if not p.exists():
        raise ValueError(f"CAIRN_DIR 경로 부재: {p}")
    return p


def workspace_root(cairn_dir=None):
    """🔒 D-P4-E: 모든 config 상대경로의 기준 = CAIRN_DIR의 parent. repo root·.cairn 기준 아님."""
    cd = Path(cairn_dir) if cairn_dir else find_cairn_dir()
    return cd.parent


def load_config(cairn_dir=None):
    """cairn.config.json 로더. (config_dict, cairn_dir) 반환."""
    cd = Path(cairn_dir) if cairn_dir else find_cairn_dir()
    cfg_path = cd / CONFIG_NAME
    if not cfg_path.exists():
        raise ValueError(f"{CONFIG_NAME} 부재: {cfg_path}")
    with open(cfg_path, encoding="utf-8") as f:
        config = json.load(f)
    validate_config(config)
    for w in legacy_key_warnings(config):
        print(w, file=sys.stderr)
    return config, cd


def legacy_key_warnings(config):
    """v1 구키(paths.kitSpecs·lessonsSource) 잔존 시 friendly 경고 리스트(G2b-1 breaking).
    자동 변환 안 함 — 어느 키를 무엇으로 바꿀지 + version 2 명시. 결정적(테스트 가능)."""
    warns = []
    paths = config.get("paths") or {}
    for old, new in LEGACY_PATH_KEYS.items():
        if old in paths:
            warns.append(f"[cairn] config 'paths.{old}' → 'paths.{new}'로 변경됨"
                         f"(v2 breaking, D-KC-15). config 갱신 필요 — 자동 변환 안 함.")
    return warns


def validate_config(config):
    """config 정규식 사전 검증(KC-Fn-G2b-2): refs.{pattern,idPattern,anchor.pattern} re.compile.
    잘못된 패턴 주입 시 hook/스크립트 crash 대신 어느 키·패턴인지 friendly error."""
    refs = config.get("refs")
    if not isinstance(refs, dict):
        return
    checks = [("refs.pattern", refs.get("pattern")),
              ("refs.idPattern", refs.get("idPattern"))]
    anchor = refs.get("anchor")
    if isinstance(anchor, dict):
        checks.append(("refs.anchor.pattern", anchor.get("pattern")))
    for key, pat in checks:
        if pat is None:
            continue
        try:
            re.compile(pat)
        except re.error as e:
            raise ValueError(f"config {key} 정규식 오류: {pat!r} — {e}")


def resolve_path(rel, cairn_dir=None):
    """config 상대경로 → workspace_root 기준 절대경로(D-P4-E)."""
    return (workspace_root(cairn_dir) / rel).resolve()


# ─── 제한문법 frontmatter 파서 (평면 key:value + 인라인 [a,b]만. 중첩·블록시퀀스·풀YAML 미지원) ───
def _parse_scalar(raw):
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [x.strip() for x in inner.split(",") if x.strip() != ""]
    if raw in ("true", "false"):
        return raw == "true"
    return raw


def _dump_scalar(val):
    if isinstance(val, list):
        return "[" + ", ".join(str(x) for x in val) + "]"
    if isinstance(val, bool):
        return "true" if val else "false"
    return str(val)


def parse_frontmatter(text):
    """'---' fence 사이 frontmatter → (dict, body). fence 없으면 ({}, text)."""
    if not text.startswith("---"):
        return {}, text
    lines = text.split("\n")
    if lines[0].strip() != "---":
        return {}, text
    fm = {}
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, raw = line.partition(":")
        fm[key.strip()] = _parse_scalar(raw)
    if end is None:
        return {}, text  # 닫는 fence 없음 → frontmatter 아님
    body = "\n".join(lines[end + 1:])
    return fm, body


def dump_frontmatter(fm, body):
    """dict + body → '---' fence 문서. parse_frontmatter와 roundtrip."""
    out = ["---"]
    for k, v in fm.items():
        out.append(f"{k}: {_dump_scalar(v)}")
    out.append("---")
    doc = "\n".join(out)
    if body:
        doc += "\n" + body
    return doc


# ─── normalize_unit / content_hash (D-P3-G, D-P3-F) ───
def normalize_unit(text, drop_heading=True):
    """D-P3-G: CRLF/CR→LF·trailing ws 제거·선후행 blank trim·unit 자기 heading 줄 제외·trailing newline 없음.
    drop_heading = unit *자기*(최상위) heading 1줄만 제거. 내부 하위 heading(### Details)은 내용으로 보존."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.rstrip() for ln in text.split("\n")]
    if drop_heading:
        i = 0
        while i < len(lines) and lines[i].strip() == "":
            i += 1
        if i < len(lines) and lines[i].lstrip().startswith("#"):
            del lines[i]
    # 선·후행 blank line trim
    while lines and lines[0].strip() == "":
        lines.pop(0)
    while lines and lines[-1].strip() == "":
        lines.pop()
    return "\n".join(lines)


def content_hash(text, drop_heading=True):
    """D-P3-F: sha256(normalize_unit) 앞 12 hex. 알고리즘·길이 고정."""
    norm = normalize_unit(text, drop_heading=drop_heading)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:12]


# ─── anchor_of / slug (D-P3-F) ───
def heading_slug(text):
    """lowercase·영숫자외 '-'·연속 '-' 축약·양끝 trim. 비ASCII는 보존(원형)."""
    s = text.strip().lower()
    s = re.sub(r"[^0-9a-zÀ-￿]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s


def anchor_of(heading, special_id=None, prefix=None, used=None):
    """special_id+prefix 있으면 '{prefix}-{special_id}' 우선 → 없으면 heading slug.
    prefix·special_id 규약은 어댑터 config(refs.anchor) 소관 — 코어는 도메인 무관. used 충돌 시 -2,-3 suffix."""
    if special_id and prefix:
        base = f"{prefix}-{special_id}"
    else:
        base = heading_slug(heading)
    if used is None:
        return base
    anchor = base
    n = 2
    while anchor in used:
        anchor = f"{base}-{n}"
        n += 1
    used.add(anchor)
    return anchor


# ─── locator (D-P3-F: quote safe="") ───
def make_locator(raw):
    """raw(<path> 또는 <path>#<anchor>) → quote(safe=\"\")."""
    return urllib.parse.quote(raw, safe="")


def parse_locator(loc):
    """quote된 locator → raw."""
    return urllib.parse.unquote(loc)


# ─── provenance 항목 kind:locator@hash (P2 §3.2) ───
def format_provenance(kind, locator, h):
    return f"{kind}:{locator}@{h}"


def parse_provenance(item):
    """'kind:locator@hash' → (kind, locator, hash). rsplit('@',1)로 hash 분리, 첫 ':'로 kind 분리."""
    if "@" in item:
        body, h = item.rsplit("@", 1)
    else:
        body, h = item, ""
    kind, _, locator = body.partition(":")
    return kind, locator, h
