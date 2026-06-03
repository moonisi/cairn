#!/usr/bin/env python3
# Codex Stop payload의 transcript_path를 best-effort로 훑어 ingest 후보를 세션 큐에 남긴다.
import datetime
import hashlib
import json
import os
import re
import sys
from pathlib import Path


MAX_LINES = 250
MAX_CANDIDATES = 8
URL_RE = re.compile(r"https?://[^\s<>)\"']+")
WEB_TOOLS = {"WebSearch", "WebFetch"}
STATUSES = {"pending", "dismissed", "ingested"}
DEFAULT_STATUS = "pending"
CODEX_WEB_EVENT_TYPES = {"web_search_call", "web_search_end"}
URL_TRAILING = ".,;:!?)]}`'\"\\"
SKIP_STRING_KEYS = {
    "arguments",
    "base_instructions",
    "command",
    "encrypted_content",
    "output",
    "reason",
    "result",
    "tool_response",
}
SKIP_TEXT_MARKERS = (
    "codex-ingest-candidates",
    "<hook_prompt",
    "Cairn Codex ingest 후보",
    "transcript url",
)


def now():
    return datetime.datetime.now().astimezone().replace(microsecond=0).isoformat(timespec="minutes")


def signature(tool, ref):
    return hashlib.sha256(f"{tool}\0{ref}".encode("utf-8")).hexdigest()[:12]


def count_codex_user_turns(path):
    """Codex transcript user-turn 카운트 = turn ordinal(KC-Fn-43).
    규칙: event_msg.payload.type == "user_message"만. naive response_item.role=="user"는
    AGENTS/environment 주입까지 포함해 과대 산출 → 사용 금지. 전체 라인 스캔(MAX_LINES 미적용)."""
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return 0
    n = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (isinstance(o, dict) and o.get("type") == "event_msg"
                and isinstance(o.get("payload"), dict)
                and o["payload"].get("type") == "user_message"):
            n += 1
    return n


def codex_session_turn(payload):
    """Codex Stop payload → session_turn = "<session_id>#<ordinal>" | None.
    ordinal = transcript user_message 누적 카운트. payload.turn_id(opaque)는 adapter_turn_id로 별도 보존."""
    tp = payload.get("transcript_path")
    n = count_codex_user_turns(tp) if tp else 0
    if n <= 0:
        return None
    sid = payload.get("session_id", "")
    return f"{sid}#{n}" if sid else str(n)


def iter_json_lines(path):
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for line in lines[-MAX_LINES:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            out.append(line)
    return out


def short_text(value, limit=220):
    if value is None:
        return ""
    if not isinstance(value, str):
        try:
            value = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            value = str(value)
    value = " ".join(value.split())
    return value[:limit]


def normalize_ref(ref):
    ref = short_text(ref, 500)
    ref = ref.rstrip(URL_TRAILING)
    for suffix in ("\\n", "\\r", "\\t"):
        while ref.endswith(suffix):
            ref = ref[: -len(suffix)].rstrip(URL_TRAILING)
    return ref


def collect_from_tool_object(obj):
    if not isinstance(obj, dict):
        return []
    tool = obj.get("tool_name") or obj.get("name") or obj.get("tool")
    if tool not in WEB_TOOLS:
        return []
    tool_input = obj.get("tool_input") or obj.get("input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    if tool == "WebSearch":
        ref = tool_input.get("query") or obj.get("query")
    else:
        ref = tool_input.get("url") or obj.get("url")
    ref = normalize_ref(ref)
    if not ref:
        return []
    note = short_text(obj.get("tool_response") or obj.get("output") or obj.get("result"))
    return [{"tool": tool, "ref": ref, "note": note}]


def collect_from_codex_web_action(obj):
    """Codex built-in web transcript event → 후보. action.{query,queries,url}만 관측면으로 인정."""
    if not isinstance(obj, dict):
        return []
    event_type = obj.get("type")
    payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
    if event_type not in CODEX_WEB_EVENT_TYPES and payload.get("type") not in CODEX_WEB_EVENT_TYPES:
        return []
    action = obj.get("action") if isinstance(obj.get("action"), dict) else payload.get("action")
    if not isinstance(action, dict):
        return []
    out = []
    query = normalize_ref(action.get("query"))
    if query:
        out.append({"tool": "WebSearch", "ref": query, "note": "codex transcript action.query"})
    queries = action.get("queries")
    if isinstance(queries, list):
        for q in queries:
            ref = normalize_ref(q)
            if ref:
                out.append({"tool": "WebSearch", "ref": ref, "note": "codex transcript action.queries"})
    url = normalize_ref(action.get("url"))
    if url:
        out.append({"tool": "WebFetch", "ref": url, "note": "codex transcript action.url"})
    return out


def should_scan_text(value, key=None):
    if key in SKIP_STRING_KEYS:
        return False
    return not any(marker in value for marker in SKIP_TEXT_MARKERS)


def walk(value, key=None, scan_text_urls=False):
    found = []
    if isinstance(value, dict):
        tool = value.get("tool_name") or value.get("name") or value.get("tool")
        if tool and tool not in WEB_TOOLS:
            return found
        found.extend(collect_from_codex_web_action(value))
        found.extend(collect_from_tool_object(value))
        for child_key, child in value.items():
            found.extend(walk(child, child_key, scan_text_urls))
    elif isinstance(value, list):
        for child in value:
            found.extend(walk(child, None, scan_text_urls))
    elif isinstance(value, str) and scan_text_urls and should_scan_text(value, key):
        # plain text URL fallback = opt-in(CAIRN_SCAN_TEXT_URLS). 기본 OFF — KC-Fn-32 과수집 차단.
        for url in URL_RE.findall(value):
            ref = normalize_ref(url)
            if ref:
                found.append({"tool": "WebFetch", "ref": ref, "note": "transcript url"})
    return found


def dedupe(candidates):
    seen = set()
    out = []
    for item in candidates:
        tool = item["tool"]
        ref = item["ref"]
        sig = signature(tool, ref)
        if sig in seen:
            continue
        seen.add(sig)
        out.append({**item, "sig": sig})
        if len(out) >= MAX_CANDIDATES:
            break
    return out


def existing_signatures(path):
    return set(candidate_statuses(path))


def candidate_statuses(path):
    if not path.exists():
        return {}
    statuses = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.search(r"\bsig:\s*([0-9a-f]{12})\b", line)
        if match:
            status = DEFAULT_STATUS
            status_match = re.search(r"\bstatus:\s*([a-z]+)\b", line)
            if status_match and status_match.group(1) in STATUSES:
                status = status_match.group(1)
            statuses[match.group(1)] = status
    return statuses


def set_line_status(line, status):
    if re.search(r"\bstatus:\s*[a-z]+\b", line):
        return re.sub(r"\s*\|\s*status:\s*[a-z]+\s*\|?\s*", f" | status: {status} | ", line, count=1)
    parts = line.split(" | ")
    for idx, part in enumerate(parts):
        if part.strip().startswith("tool:"):
            parts.insert(idx + 1, f"status: {status}")
            return " | ".join(parts)
    return line


def mark_candidates(cairn_dir, status, sigs):
    if status not in STATUSES:
        return {"action": "mark", "status": status, "count": 0, "error": "invalid_status"}
    sess = Path(cairn_dir) / "sessions"
    path = sess / "codex-ingest-candidates.md"
    if not path.exists():
        return {"action": "mark", "status": status, "count": 0, "path": str(path)}
    wanted = set(sigs)
    count = 0
    lines = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = re.search(r"\bsig:\s*([0-9a-f]{12})\b", line)
        if match and match.group(1) in wanted:
            updated = set_line_status(line, status)
            if updated != line:
                count += 1
            line = updated
        lines.append(line)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"action": "mark", "status": status, "count": count, "path": str(path)}


def append_candidates(cairn_dir, transcript_path, candidates):
    sess = Path(cairn_dir) / "sessions"
    sess.mkdir(parents=True, exist_ok=True)
    path = sess / "codex-ingest-candidates.md"
    known = existing_signatures(path)
    new_items = [item for item in candidates if item["sig"] not in known]
    if not new_items:
        return path, []
    lines = []
    if not path.exists():
        lines.append("# codex-ingest-candidates (volatile — gitignored)")
        lines.append("")
    ts = now()
    for item in new_items:
        note = item.get("note") or ""
        lines.append(
            f"- ts: {ts} | sig: {item['sig']} | tool: {item['tool']} | "
            f"status: {DEFAULT_STATUS} | ref: {item['ref']}"
        )
        lines.append(f"  - transcript: {transcript_path}")
        if note:
            lines.append(f"  - note: {note}")
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path, new_items


def continuation_json(candidate_path, count):
    reason = (
        f"Cairn Codex ingest 후보 {count}건이 {candidate_path}에 기록됐다. "
        "후보를 검토해 실제로 장기 보존할 가치가 있는 항목만 source/page draft로 정리하고, "
        "기존 Cairn write/reconcile 경로로 반영하라. 불확실하면 쓰지 말고 결과보고에 보류로 남겨라. "
        "검토 없는 자동 영구 기록은 금지한다."
    )
    return {"decision": "block", "reason": reason}


def main():
    argv = sys.argv[1:]
    if argv[:1] == ["mark"]:
        cairn_dir = os.environ.get("CAIRN_DIR")
        if not cairn_dir or len(argv) < 3:
            return 0
        result = mark_candidates(cairn_dir, argv[1], argv[2:])
        print(json.dumps(result, ensure_ascii=False))
        return 0

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        return 0
    cairn_dir = os.environ.get("CAIRN_DIR")
    transcript_path = payload.get("transcript_path")
    if not cairn_dir or not transcript_path:
        return 0
    objects = iter_json_lines(transcript_path)
    if not objects:
        return 0
    scan_text = os.environ.get("CAIRN_SCAN_TEXT_URLS", "").strip() not in ("", "0", "false", "False")
    candidates = dedupe([item for obj in objects for item in walk(obj, scan_text_urls=scan_text)])
    if not candidates:
        return 0
    candidate_path, new_items = append_candidates(cairn_dir, transcript_path, candidates)
    if not new_items or payload.get("stop_hook_active"):
        return 0
    print(json.dumps(continuation_json(candidate_path, len(new_items)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
