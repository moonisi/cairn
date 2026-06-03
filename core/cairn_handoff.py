#!/usr/bin/env python3
# Cairn handoff: log.md 최근 활동 수집 → session-state.md + hot.md draft 골격 + log append
# 골격만 기계 생성({status:draft,needs_review:true}). 검토·승인은 LLM/사람(P2 §3.3). zero-dep.
import sys
import datetime
from pathlib import Path

import cairn_root as r
import cairn_ingest as ing

RECENT = 20  # log.md 최근 이벤트 수집 한도


def collect_activity(cd):
    log_path = cd / "log.md"
    if not log_path.exists():
        return []
    lines = [ln for ln in log_path.read_text(encoding="utf-8").split("\n")
             if ln.startswith("- ")]
    return lines[-RECENT:]


def handoff(cd, config):
    sess = cd / "sessions"
    sess.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()
    activity = collect_activity(cd)

    # session-state.md — 활동 기록 draft
    fm_ss = {"status": "draft", "needs_review": True, "generated": now}
    body_ss = "## 최근 활동\n" + ("\n".join(activity) if activity else "(활동 없음)") \
        + "\n\n## 검토 메모\n(LLM/사용자 작성 — draft)"
    (sess / "session-state.md").write_text(r.dump_frontmatter(fm_ss, body_ss), encoding="utf-8")

    # hot.md — 재개 핫컨텍스트 draft 골격
    fm_hot = {"status": "draft", "needs_review": True, "generated": now}
    body_hot = "## 지금 무엇\n(draft — LLM 채움)\n\n## 다음 단계\n(draft)"
    (sess / "hot.md").write_text(r.dump_frontmatter(fm_hot, body_hot), encoding="utf-8")

    ing.append_log(cd, "handoff", f"draft 생성(session-state.md, hot.md), 활동 {len(activity)}건")
    return len(activity)


def approve(cd, draft_path):
    """협업게이트 승인 전이: status draft→approved, needs_review→false + log append.
    사용자/독립LLM 검토 후 호출(P3b §3.1 2단계 차등 모델). 골격 생성은 handoff, 승인은 본 함수."""
    p = Path(draft_path)
    if not p.is_absolute():
        p = cd / "sessions" / draft_path
    if not p.exists():
        return [f"draft 부재: {p}"]
    fm, body = r.parse_frontmatter(p.read_text(encoding="utf-8"))
    if fm.get("status") != "draft":
        return [f"승인 대상 아님(status={fm.get('status')!r}, draft 필요)"]
    fm["status"] = "approved"
    fm["needs_review"] = False
    fm["approved"] = datetime.datetime.now().astimezone().replace(microsecond=0).isoformat()
    p.write_text(r.dump_frontmatter(fm, body), encoding="utf-8")
    ing.append_log(cd, "handoff-approve", f"{p.name} status:draft→approved")
    return []


def main(argv):
    config, cd = r.load_config()
    if argv and argv[0] == "approve":
        if len(argv) < 2:
            print("usage: cairn_handoff.py approve <draft.md>")
            return 2
        errs = approve(cd, argv[1])
        if errs:
            for e in errs:
                print(f"INVALID: {e}")
            return 1
        print(f"승인 완료: {argv[1]} (status:approved, needs_review:false)")
        return 0
    n = handoff(cd, config)
    print(f"handoff draft 생성: session-state.md + hot.md (활동 {n}건, status:draft needs_review:true)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
