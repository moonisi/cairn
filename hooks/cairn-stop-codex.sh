#!/usr/bin/env bash
# ⓑ-codex: Codex Stop hook용 handoff draft 생성 + nudge emit + transcript 후보 스캔 wrapper.
set -uo pipefail

: "${CAIRN_DIR:?CAIRN_DIR 환경변수 필요}"
DIR="$(cd "$(dirname "$0")" && pwd)"
CORE="${CAIRN_CORE:-$DIR/../core}"
SESSION="${CAIRN_SESSION:-s}"
PAYLOAD_FILE="$(mktemp "${TMPDIR:-/tmp}/cairn-stop-codex.XXXXXX")" || exit 0
trap 'rm -f "$PAYLOAD_FILE"' EXIT

cat > "$PAYLOAD_FILE" || true

# handoff draft(status:draft, needs_review:true) — 검토·승인은 사람/독립LLM
PYTHONPATH="$CORE" python3 "$CORE/cairn_handoff.py" >/dev/null 2>&1 || true
# 경계 nudge emit(perSession=1 통합 제안, cadence 자가튜닝)
PYTHONPATH="$CORE" python3 "$CORE/cairn_nudge.py" emit "$SESSION" >/dev/null 2>&1 || true
# Codex transcript 기반 ingest 후보 스캔. 후보가 있으면 Stop JSON만 stdout으로 반환.
CAIRN_DIR="$CAIRN_DIR" python3 "$DIR/cairn-codex-transcript-scan.py" < "$PAYLOAD_FILE" || true

exit 0
