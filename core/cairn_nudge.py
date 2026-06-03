#!/usr/bin/env python3
# Cairn nudge: collect(무음 적재)·emit(경계 통합제안)·clear(consumed-only purge)
# PostToolUse payload extractor는 실측 확정 구조(WebSearch{query}·WebFetch{url,prompt})만 처리(P3b §7 #8 차단체크).
# zero-dep. Vault 쓰기 0(emit은 gitignored 텔레메트리만). 결정적 부분만 — 알림·LLM 제안은 호출측.
import sys
import os
import json
import fnmatch
import hashlib
import datetime
import urllib.parse
from pathlib import Path

import cairn_root as r

QUEUE = "nudge-queue.md"      # sessions/ (gitignored)
METRICS = "nudge-metrics.md"  # sessions/ (gitignored)
WINDOW = 10                   # self-measure rolling window(세션)
HITRATE_FLOOR = 0.2


def _now():
    return datetime.datetime.now().astimezone().replace(microsecond=0).isoformat(timespec="minutes")


def qhash(redacted_locator):
    return hashlib.sha256(redacted_locator.encode("utf-8")).hexdigest()[:12]


# ─── extractor: 실측 확정 payload → (tool, ref, locator) | None ───
def redact_url(url, redact):
    p = urllib.parse.urlsplit(url)
    host = p.hostname or ""
    if "userinfo" not in redact and p.username:
        host = (p.username + (":" + p.password if p.password else "") + "@") + host
    scheme = p.scheme + "://" if p.scheme else ""
    locator = f"{scheme}{host}{p.path}"
    if "query" not in redact and p.query:
        locator += "?" + p.query
    if "hash" not in redact and p.fragment:
        locator += "#" + p.fragment
    ref = f"{host}{p.path}".strip("/")
    return locator, ref


def extract(payload, triggers, redact):
    """PostToolUse payload → {tool,ref,locator} | None (비트리거)."""
    tool = payload.get("tool_name")
    if tool not in triggers:
        return None
    ti = payload.get("tool_input", {})
    if tool == "WebSearch":
        q = ti.get("query", "")
        return {"tool": tool, "ref": q, "locator": f"websearch:{q}"}
    if tool == "WebFetch":
        loc, ref = redact_url(ti.get("url", ""), redact)
        return {"tool": tool, "ref": ref, "locator": loc}
    # 그 외 트리거 = 어댑터별 extractor 분리 대상(현재 미지원)
    return None


# turn 식별(session_turn 산출)은 런타임별 transcript 포맷에 의존 → 어댑터 책임(KC-Fn-41·43).
# CC = hooks/cairn_cc_turn.py, Codex = hooks/cairn-codex-transcript-scan.py. 코어는 turn을 받기만 한다.


# ─── queue 파일 I/O ───
def _qpath(cd):
    return cd / "sessions" / QUEUE


def _mpath(cd):
    return cd / "sessions" / METRICS


def parse_queue(cd):
    p = _qpath(cd)
    if not p.exists():
        return []
    rows = []
    for ln in p.read_text(encoding="utf-8").split("\n"):
        ln = ln.strip()
        if not ln.startswith("- "):
            continue
        fields = {}
        for part in ln[2:].split("|"):
            k, _, v = part.strip().partition(":")
            fields[k.strip()] = v.strip()
        rows.append(fields)
    return rows


def write_queue(cd, rows):
    p = _qpath(cd)
    p.parent.mkdir(parents=True, exist_ok=True)
    out = ["# nudge-queue (volatile — gitignored)"]
    for f in rows:
        out.append(f"- ts: {f['ts']} | tool: {f['tool']} | ref: {f['ref']} | locator: {f.get('locator') or ''} | qhash: {f['qhash']} | status: {f['status']} | turn: {f.get('turn') or ''}")
    p.write_text("\n".join(out) + "\n", encoding="utf-8")


def append_metric(cd, event, qh, session):
    p = _mpath(cd)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(f"{event} | ts: {_now()} | qhash: {qh} | session: {session}\n")


def parse_metrics(cd):
    p = _mpath(cd)
    if not p.exists():
        return []
    rows = []
    for ln in p.read_text(encoding="utf-8").split("\n"):
        if "|" not in ln:
            continue
        ev, _, rest = ln.partition("|")
        fields = {"event": ev.strip()}
        for part in rest.split("|"):
            k, _, v = part.strip().partition(":")
            fields[k.strip()] = v.strip()
        rows.append(fields)
    return rows


def load_cairnignore(cd):
    p = cd / ".cairnignore"
    if not p.exists():
        return []
    return [ln.strip() for ln in p.read_text(encoding="utf-8").split("\n")
            if ln.strip() and not ln.startswith("#")]


# ─── collect ───
def collect(cd, config, payload, refresh=False, turn=None):
    nudge = config.get("nudge", {})
    triggers = nudge.get("triggers", ["WebFetch", "WebSearch"])
    redact = nudge.get("redact", ["query", "hash", "userinfo"])
    ext = extract(payload, triggers, redact)
    if ext is None:
        return {"action": "ignored", "reason": "non-trigger"}
    globs = load_cairnignore(cd)
    if any(fnmatch.fnmatch(ext["ref"], g) or fnmatch.fnmatch(ext["locator"], g) for g in globs):
        return {"action": "discarded", "reason": "cairnignore"}
    qh = qhash(ext["locator"])
    rows = parse_queue(cd)
    metrics = parse_metrics(cd)
    # 상태별 dedup
    pending_q = {f["qhash"] for f in rows if f["status"] == "pending"}
    suppressed_q = {f["qhash"] for f in rows if f["status"] == "suppressed"}
    ingested_q = {m["qhash"] for m in metrics if m["event"] == "nudge-ingested"}
    if qh in pending_q:
        return {"action": "deduped", "reason": "pending", "qhash": qh}
    if qh in suppressed_q:
        return {"action": "deduped", "reason": "suppressed", "qhash": qh}
    if qh in ingested_q and not refresh:
        # 🔒 TTL 미구현(P4a) — 기본 억제, --refresh 시에만 재적재
        return {"action": "deduped", "reason": "ingested", "qhash": qh}
    rows.append({"ts": _now(), "tool": ext["tool"], "ref": ext["ref"], "locator": ext["locator"],
                 "qhash": qh, "status": "pending", "turn": turn})
    write_queue(cd, rows)
    return {"action": "queued", "qhash": qh, "turn": turn}


# ─── emit cadence helpers (P3b §4.3 self-governing) ───
def _trailing_lowhit(cd):
    """텔레메트리 끝에서 연속 nudge-lowhit 수(nudge-okhit 만나면 중단). consec_low."""
    n = 0
    for m in reversed(parse_metrics(cd)):
        if m["event"] == "nudge-lowhit":
            n += 1
        elif m["event"] == "nudge-okhit":
            break
    return n


def _boundaries_since_last_emit(cd):
    """마지막 nudge-emit 이후(포함 X) nudge-boundary 수. emit 없으면 전체 boundary."""
    metrics = parse_metrics(cd)
    last_emit = -1
    for i, m in enumerate(metrics):
        if m["event"] == "nudge-emit":
            last_emit = i
    return sum(1 for m in metrics[last_emit + 1:] if m["event"] == "nudge-boundary")


def _cadence_interval(hitrate, consec_low, floorM):
    """적중률 None/≥floor → 1(매 경계). <floor 2회연속부터 2·4·8… 단 floor M 상한."""
    if hitrate is None or consec_low < 2:
        return 1
    return min(2 ** (consec_low - 1), floorM)


# ─── emit (Stop/PreCompact) — cadence 축소 + floor 자가튜닝(P3b §4.3) ───
def emit(cd, config, session="s"):
    nudge = config.get("nudge", {})
    floorM = nudge.get("floorSessions", WINDOW)
    # 0) perSession 가드(D-P3b-C) — 동일 session 내 emit 횟수 제한. Stop/PreCompact 동시·재진입 시
    #    같은 pending 반복 제안 차단. cadence·boundary 기록 전에 조기 반환(텔레메트리 오염 방지).
    perSession = nudge.get("throttle", {}).get("perSession", 1)
    emitted = sum(1 for m in parse_metrics(cd)
                  if m["event"] == "nudge-emit" and m.get("session") == session)
    if emitted >= perSession:
        append_metric(cd, "nudge-skip", "", session)
        return {"action": "throttled", "reason": "perSession", "emitted": emitted}
    # 1) window 적중률 측정 + lowhit/okhit 마커(분모 0이면 미기록)
    hr = self_measure(cd)["hitrate"]
    if hr is not None:
        append_metric(cd, "nudge-lowhit" if hr < HITRATE_FLOOR else "nudge-okhit", "", session)
    consec_low = _trailing_lowhit(cd)
    interval = _cadence_interval(hr, consec_low, floorM)
    # 2) 경계 기록 + cadence 판정(floor 보장: M경계 누적 시 강제)
    append_metric(cd, "nudge-boundary", "", session)
    since_last = _boundaries_since_last_emit(cd)
    floor_hit = since_last >= floorM
    if not (since_last >= interval or floor_hit):
        append_metric(cd, "nudge-skip", "", session)
        return {"action": "throttled", "interval": interval, "since_last": since_last}
    # 3) emit — pending 통합 제안(포인터만). Vault 쓰기 0 — gitignored 텔레메트리만.
    #    pending→proposed status 전환 안 함(consumed-only purge 설계: pending은 ingest까지 보존).
    #    세션 내 재제안은 perSession 가드(0), 세션 간 미ingest 재알림은 정상(리마인더).
    rows = parse_queue(cd)
    pending = [f for f in rows if f["status"] == "pending"]
    if not pending:
        return {"action": "noop", "pending": 0, "interval": interval}
    append_metric(cd, "nudge-emit", "", session)
    for f in pending:
        append_metric(cd, "nudge-proposed", f["qhash"], session)  # ref 미기록
    return {"action": "proposed", "pending": len(pending), "interval": interval,
            "floor": floor_hit, "refs": [f["ref"] for f in pending],
            "turns": [f.get("turn") for f in pending]}


# ─── clear (consumed-only purge) ───
def clear(cd):
    rows = parse_queue(cd)
    kept = [f for f in rows if f["status"] not in ("ingested", "suppressed")]  # pending 보존
    write_queue(cd, kept)
    # 텔레메트리 rolling window(N) 밖 prune
    metrics = parse_metrics(cd)
    sessions = []
    for m in metrics:
        s = m.get("session")
        if s and s not in sessions:
            sessions.append(s)
    keep_sessions = set(sessions[-WINDOW:])
    pruned = [m for m in metrics if m.get("session") in keep_sessions]
    if pruned != metrics:
        p = _mpath(cd)
        with open(p, "w", encoding="utf-8") as f:
            for m in pruned:
                f.write(f"{m['event']} | ts: {m.get('ts','')} | qhash: {m.get('qhash','')} | session: {m.get('session','')}\n")
    return {"action": "cleared", "kept_pending": sum(1 for f in kept if f["status"] == "pending")}


# ─── pending (소비처 surface — skill·SessionStart 재사용) ───
def pending(cd):
    """ingest 대기 후보 = status:pending row. skill이 locator로 url provenance 재구성 →
    Phase C 자동 turn 연결. 결정적(코어, 런타임무관) — 판단·page 합성은 호출측(skill)."""
    return [{"ts": f.get("ts", ""), "tool": f.get("tool", ""), "ref": f.get("ref", ""),
             "locator": f.get("locator", ""), "qhash": f.get("qhash", ""), "turn": f.get("turn", "")}
            for f in parse_queue(cd) if f["status"] == "pending"]


def suppress(cd, qhashes):
    """pending row를 suppressed로 전환(dismiss). dedup이 재제안 차단, clear가 purge.
    websearch 등 turn-linkage 비대상 후보 정리용(정책 A). 메트릭 미append(비적중 — self-measure 무관)."""
    qset = set(qhashes)
    rows = parse_queue(cd)
    n = 0
    for f in rows:
        if f["qhash"] in qset and f["status"] == "pending":
            f["status"] = "suppressed"
            n += 1
    if n:
        write_queue(cd, rows)
    return {"action": "suppressed", "count": n}


# ─── self-measure (§4.3) ───
def self_measure(cd):
    metrics = parse_metrics(cd)
    sessions = []
    for m in metrics:
        s = m.get("session")
        if s and s not in sessions:
            sessions.append(s)
    window = set(sessions[-WINDOW:])
    proposed = {m["qhash"] for m in metrics if m["event"] == "nudge-proposed" and m.get("session") in window}
    ingested = {m["qhash"] for m in metrics if m["event"] == "nudge-ingested" and m.get("session") in window}
    if not proposed:
        return {"hitrate": None, "proposed": 0}  # 분모 0 → 제외
    hr = len(ingested & proposed) / len(proposed)
    return {"hitrate": round(hr, 3), "proposed": len(proposed),
            "below_floor": hr < HITRATE_FLOOR}


def main(argv):
    if not argv:
        print("usage: cairn_nudge.py collect <payload.json> [--refresh] [--turn <session_turn>] | emit | clear | measure | pending | suppress <qhash>...")
        return 2
    config, cd = r.load_config()
    cmd = argv[0]
    if cmd == "collect":
        if len(argv) < 2:
            print("usage: collect <payload.json|-> [--refresh] [--turn <session_turn>]")
            return 2
        # '-' = stdin(PostToolUse hook wrapper용). 그 외 = 파일 경로.
        raw = sys.stdin.read() if argv[1] == "-" else Path(argv[1]).read_text(encoding="utf-8")
        payload = json.loads(raw) if raw.strip() else {}
        # --turn <session_turn>: 어댑터가 산출한 session_turn 전달(코어는 산출 안 함).
        turn = None
        if "--turn" in argv:
            i = argv.index("--turn")
            turn = argv[i + 1] if i + 1 < len(argv) else None
        res = collect(cd, config, payload, refresh="--refresh" in argv, turn=turn)
        print(json.dumps(res, ensure_ascii=False))
        return 0
    if cmd == "emit":
        session = argv[1] if len(argv) > 1 else "s"
        print(json.dumps(emit(cd, config, session), ensure_ascii=False))
        return 0
    if cmd == "clear":
        print(json.dumps(clear(cd), ensure_ascii=False))
        return 0
    if cmd == "measure":
        print(json.dumps(self_measure(cd), ensure_ascii=False))
        return 0
    if cmd == "pending":
        rows = pending(cd)
        if "--text" in argv:  # 사람-읽기 라인(SessionStart 주입용). 주입 헤더·명령 안내는 어댑터 소관.
            for f in rows:
                print(f"- {f['ref']} (turn: {f['turn'] or '-'}, tool: {f['tool']})")
        else:
            print(json.dumps(rows, ensure_ascii=False))
        return 0
    if cmd == "suppress":
        print(json.dumps(suppress(cd, argv[1:]), ensure_ascii=False))
        return 0
    print(f"unknown command: {cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
