#!/usr/bin/env bash
# ⓒ PostToolUse hook(command, CC): stdin의 hook payload(JSON)를 무음 nudge collect로 적재.
# 무음(stdout 비움 — block 불가 이벤트). 비트리거(WebFetch|WebSearch 외)는 core가 ignored 처리.
# zero-dep. 즉시가동 아님 — settings.example.json opt-in 후 발동(D-KC-10).
set -uo pipefail

: "${CAIRN_DIR:?CAIRN_DIR 환경변수 필요}"
DIR="$(cd "$(dirname "$0")" && pwd)"
CORE="${CAIRN_CORE:-$DIR/../core}"

# stdin payload를 변수로 1회 캡처(stdin은 한 번만 읽힘) → turn 산출 + collect 2단계.
PAYLOAD="$(cat)"
# CC 어댑터가 session_turn 산출(transcript user-turn 카운트, KC-Fn-41). 실패 시 빈 값.
ST="$(printf '%s' "$PAYLOAD" | python3 "$DIR/cairn_cc_turn.py" 2>/dev/null || true)"
# 코어 collect -(무음 적재). turn 있으면 --turn 전달, 없으면 생략. 결과·오류 삼킴(block 불가·방해 0).
if [ -n "$ST" ]; then
  printf '%s' "$PAYLOAD" | PYTHONPATH="$CORE" python3 "$CORE/cairn_nudge.py" collect - --turn "$ST" >/dev/null 2>&1 || true
else
  printf '%s' "$PAYLOAD" | PYTHONPATH="$CORE" python3 "$CORE/cairn_nudge.py" collect - >/dev/null 2>&1 || true
fi

exit 0
