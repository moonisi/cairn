#!/usr/bin/env python3
# Claude Code 어댑터: PostToolUse payload → session_turn 산출(KC-Fn-41).
# CC transcript jsonl 포맷 전용 규칙. 코어(cairn_nudge)는 turn을 받기만 하고, 산출은 이 어댑터 책임.
# zero-dep. CC payload엔 turn_id 직접 부재 → transcript user-turn 카운트로 ordinal 산출.
import sys
import json
from pathlib import Path


def count_user_turns(transcript_path):
    """CC transcript jsonl의 진짜 user 프롬프트 수 = turn ordinal.
    실측(2026-06-01): type:user 중 대부분이 tool_result(도구 응답이 user role로 적재)라
    naive 카운트는 과대. tool_result·isMeta(시스템 주입)·isCompactSummary(압축 요약) 제외."""
    p = Path(transcript_path)
    if not p.exists():
        return 0
    n = 0
    for ln in p.read_text(encoding="utf-8").split("\n"):
        ln = ln.strip()
        if not ln:
            continue
        try:
            o = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if o.get("type") != "user" or o.get("isMeta") or o.get("isCompactSummary"):
            continue
        c = o.get("message", {}).get("content")
        if isinstance(c, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            continue
        n += 1
    return n


def session_turn(payload):
    """CC PostToolUse payload → session_turn = "<session_id>#<ordinal>" | None.
    transcript_path 부재 또는 카운트 0 → None(코어 collect turn=None fallback)."""
    tp = payload.get("transcript_path")
    if not tp:
        return None
    n = count_user_turns(tp)
    if n <= 0:
        return None
    sid = payload.get("session_id", "")
    return f"{sid}#{n}" if sid else str(n)


def main(argv):
    """stdin payload → session_turn 한 줄 출력(없으면 빈 줄). cairn-posttooluse.sh 배선용."""
    raw = sys.stdin.read()
    payload = json.loads(raw) if raw.strip() else {}
    st = session_turn(payload)
    print(st or "")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
