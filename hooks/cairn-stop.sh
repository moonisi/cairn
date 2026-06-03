#!/usr/bin/env bash
# ⓑ Stop hook(command, CC): 경계에서 handoff draft 생성 + nudge emit(통합 제안).
# 비차단(exit 0 고정 — Stop을 막지 않음, draft·제안은 비강제). zero-dep.
# 즉시가동 아님 — settings.example.json opt-in 후 발동(D-KC-10).
set -uo pipefail

: "${CAIRN_DIR:?CAIRN_DIR 환경변수 필요}"
DIR="$(cd "$(dirname "$0")" && pwd)"
CORE="${CAIRN_CORE:-$DIR/../core}"
SESSION="${CAIRN_SESSION:-s}"

# handoff draft(status:draft, needs_review:true) — 검토·승인은 사람/독립LLM
PYTHONPATH="$CORE" python3 "$CORE/cairn_handoff.py" 2>/dev/null || true
# 경계 nudge emit(perSession=1 통합 제안, cadence 자가튜닝)
PYTHONPATH="$CORE" python3 "$CORE/cairn_nudge.py" emit "$SESSION" 2>/dev/null || true

exit 0
