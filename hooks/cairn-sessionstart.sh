#!/usr/bin/env bash
# ⓐ SessionStart hook(command, CC): 재개 핫컨텍스트(hot.md + session-state.md)를 stdout으로 무음 주입.
# 부재 시 빈 출력(무음). 실 CC는 stdout을 additionalContext로 주입(P0 §3.1, block 불가).
# zero-dep. 즉시가동 아님 — settings.example.json opt-in 후 발동(D-KC-10).
set -euo pipefail

: "${CAIRN_DIR:?CAIRN_DIR 환경변수 필요}"
SESS="$CAIRN_DIR/sessions"
DIR="$(cd "$(dirname "$0")" && pwd)"
CORE="${CAIRN_CORE:-$DIR/../core}"

emit_file() {
  local f="$1" title="$2"
  if [ -f "$f" ]; then
    printf '## %s\n' "$title"
    cat "$f"
    printf '\n'
  fi
}

emit_file "$SESS/hot.md" "재개 핫컨텍스트 (hot)"
emit_file "$SESS/session-state.md" "세션 상태 (session-state)"

# ingest 후보 대기(pending nudge) 노출 — 있을 때만(0건이면 무음). 코어 pending --text 재사용.
PEND="$(PYTHONPATH="$CORE" python3 "$CORE/cairn_nudge.py" pending --text 2>/dev/null || true)"
if [ -n "$PEND" ]; then
  printf '## ingest 후보 대기 (/cairn:ingest)\n%s\n\n' "$PEND"
fi
exit 0
