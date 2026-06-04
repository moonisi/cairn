#!/usr/bin/env python3
# Cairn Gate 1 self-test: 결정적 부분 전수 검증. 전부 pass(종료코드 0) = Gate 1 통과조건(전역 규율 §7).
import os
import sys
import json
import importlib.util
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import cairn_root as r
import cairn_ingest as ing
import cairn_query as q
import cairn_lint as lint
import cairn_nudge as nudge
import cairn_handoff as handoff

PASS = 0
FAIL = 0


def check(name, cond):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}")


def setup_vault(tmp):
    """임시 CAIRN_DIR 구성. workspace_root=tmp, CAIRN_DIR=tmp/.cairn."""
    cd = Path(tmp) / ".cairn"
    cd.mkdir(parents=True, exist_ok=True)
    config = {
        "version": "2",
        "vault": {"root": ".cairn", "pagesDir": "pages", "sourcesDir": "sources"},
        "pageTypes": ["lesson", "decision", "note"],
        "taxonomy": {"mode": "non-hierarchical", "aliases": {"k8s": "kubernetes"}},
        "paths": {"refsScope": "specs", "defaultIngestSource": "specs/lessons.md"},
        "refs": {"pattern": r"^feature:(\d{3})$", "dir": "features",
                 "idPattern": r"^(\d{3})",
                 "anchor": {"pattern": r"(?i)feature[\s:#_-]*(\d{3})", "prefix": "feature"}},
        "nudge": {"triggers": ["WebFetch", "WebSearch"],
                  "throttle": {"perSession": 1, "boundary": ["Stop", "PreCompact"]},
                  "dedup": True, "redact": ["query", "hash", "userinfo"],
                  "hitRateThreshold": 0.2},
    }
    (cd / "cairn.config.json").write_text(json.dumps(config), encoding="utf-8")
    os.environ["CAIRN_DIR"] = str(cd)
    return cd, config


# ── 1. frontmatter roundtrip ──
def t_frontmatter():
    print("[1] frontmatter roundtrip")
    doc = "---\nslug: x\ntype: lesson\ntags: [a, b]\nneeds_review: false\nprovenance: [file:loc@abc123]\n---\nbody\nline2"
    fm, body = r.parse_frontmatter(doc)
    check("parse tags list", fm["tags"] == ["a", "b"])
    check("parse bool", fm["needs_review"] is False)
    fm2, body2 = r.parse_frontmatter(r.dump_frontmatter(fm, body))
    check("roundtrip fm", fm2 == fm)
    check("roundtrip body", body2 == body)
    check("no-fence passthrough", r.parse_frontmatter("no fm here") == ({}, "no fm here"))


# ── 2. normalize/hash 결정성 ──
def t_normalize():
    print("[2] normalize_unit / content_hash 결정성")
    a = "## Heading\nfoo  \r\nbar\n"
    b = "# Other\nfoo\nbar"
    check("CRLF·heading 무관 동일 hash", r.content_hash(a) == r.content_hash(b))
    check("hash 길이 12", len(r.content_hash(a)) == 12)
    check("내부 blank 보존 → 다른 hash",
          r.content_hash("foo\n\nbar") != r.content_hash("foo\nbar"))
    # [2b] 자기 heading만 제외, 내부 하위 heading 보존
    check("하위 heading 보존",
          r.normalize_unit("## Entry\nIntro\n### Details\nBody") == "Intro\n### Details\nBody")


# ── 3. anchor ──
def t_anchor():
    print("[3] anchor_of")
    check("heading slug", r.anchor_of("My Heading!") == "my-heading")
    check("special_id+prefix 우선", r.anchor_of("Feature 042 stuff", special_id="042", prefix="feature") == "feature-042")
    check("prefix 없으면 heading slug", r.anchor_of("Feature 042 stuff", special_id="042") == "feature-042-stuff")
    check("도메인 중립 prefix", r.anchor_of("Ticket 77", special_id="77", prefix="ticket") == "ticket-77")
    used = set()
    check("충돌 suffix", [r.anchor_of("h", used=used), r.anchor_of("h", used=used)] == ["h", "h-2"])


# ── 4. dedup 3분기 ──
def t_dedup():
    print("[4] dedup 3분기 (no-op·provenance-append·갱신·merge·신규)")
    HASH_A, LOC_A, LOC_B = "aaaaaaaaaaaa", "fileA", "fileB"
    pages = [{
        "slug": "zero-dep-bm25", "type": "lesson", "title": "zero-dep BM25 retrieval",
        "tags": ["retrieval", "bm25"],
        "provenance": [("file", LOC_A, HASH_A)],
        "fm": {}, "body": "", "path": None,
    }]
    no_op = ing.classify_unit({"hash": HASH_A, "locator": LOC_A, "title": "t"}, pages)
    check("no-op", no_op["branch"] == "no-op")
    pa = ing.classify_unit({"hash": HASH_A, "locator": LOC_B, "title": "t"}, pages)
    check("provenance-append", pa["branch"] == "provenance-append")
    up = ing.classify_unit({"hash": "newhashvalue", "locator": LOC_A, "title": "t"}, pages)
    check("갱신(update)", up["branch"] == "update")
    mg = ing.classify_unit({"hash": "h2", "locator": "fileC", "title": "zero-dep BM25 retrieval"}, pages)
    check("merge(유사≥τ)", mg["branch"] == "merge")
    nw = ing.classify_unit({"hash": "h3", "locator": "fileD", "title": "quantum cooking recipe xyz"}, pages)
    check("신규(유사<τ)", nw["branch"] == "new")


# ── 5. BM25 sanity ──
def t_bm25():
    print("[5] BM25 랭킹 sanity")
    chunks = [
        ("a", "the bm25 ranking algorithm scores documents by term frequency", "a"),
        ("b", "a recipe for chocolate cake with sugar and flour", "b"),
        ("c", "bm25 retrieval bm25 ranking zero dep python", "c"),
    ]
    ranked = q.bm25_rank("bm25 ranking", chunks)
    check("관련 청크 상위", ranked[0][2] in ("a", "c"))
    check("무관 청크 하위", ranked[-1][2] == "b")
    check("점수 내림차순", all(ranked[i][1] >= ranked[i+1][1] for i in range(len(ranked)-1)))
    # [5b] 한글 토큰화 + BM25 동작
    check("한글 tokenize", q.tokenize("정규화 검색") == ["정규화", "검색"])
    ko = q.bm25_rank("정규화 검색", [
        ("k1", "정규화 검색 알고리즘 본문", "k1"),
        ("k2", "전혀 무관한 요리 레시피", "k2"),
    ])
    check("한글 BM25 >0 & 관련 상위", ko[0][1] > 0 and ko[0][2] == "k1")


# ── 6. locator/provenance roundtrip ──
def t_locator():
    print("[6] locator quote/unquote + provenance roundtrip")
    raw = "specs/lessons.md#feature-001"
    loc = r.make_locator(raw)
    check("quote safe='' (slash 인코딩)", "/" not in loc and "#" not in loc)
    check("unquote roundtrip", r.parse_locator(loc) == raw)
    item = r.format_provenance("file", loc, "a1b2c3d4e5f6")
    check("provenance parse", r.parse_provenance(item) == ("file", loc, "a1b2c3d4e5f6"))


# ── 7. nudge qhash + clear consumed-only ──
def t_nudge_clear(tmp):
    print("[7] nudge qhash 결정성 + clear consumed-only")
    cd, config = setup_vault(tmp)
    check("qhash 결정성", nudge.qhash("websearch:foo") == nudge.qhash("websearch:foo"))
    rows = [
        {"ts": "t1", "tool": "WebSearch", "ref": "p", "qhash": "q1", "status": "pending"},
        {"ts": "t2", "tool": "WebFetch", "ref": "i", "qhash": "q2", "status": "ingested"},
        {"ts": "t3", "tool": "WebSearch", "ref": "s", "qhash": "q3", "status": "suppressed"},
    ]
    nudge.write_queue(cd, rows)
    nudge.clear(cd)
    after = nudge.parse_queue(cd)
    statuses = {f["qhash"]: f["status"] for f in after}
    check("pending 보존", statuses.get("q1") == "pending")
    check("ingested 제거", "q2" not in statuses)
    check("suppressed 제거", "q3" not in statuses)


def t_nudge_collect(tmp):
    print("[7b] nudge collect dedup")
    cd, config = setup_vault(tmp)
    payload = {"tool_name": "WebSearch", "tool_input": {"query": "bm25 zero dep"}}
    r1 = nudge.collect(cd, config, payload)
    check("collect queued", r1["action"] == "queued")
    r2 = nudge.collect(cd, config, payload)
    check("재적재 dedup(pending)", r2["action"] == "deduped" and r2["reason"] == "pending")
    bash = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
    check("비트리거 ignored", nudge.collect(cd, config, bash)["action"] == "ignored")
    # turn 인자 라운드트립(코어는 수용만, 산출 안 함 — KC-Fn-41 어댑터 분리)
    r3 = nudge.collect(cd, config, {"tool_name": "WebSearch", "tool_input": {"query": "turn round"}}, turn="sess#5")
    check("collect turn 수용", r3.get("turn") == "sess#5")
    check("parse_queue turn 보존", any(f.get("turn") == "sess#5" for f in nudge.parse_queue(cd)))
    # redacted locator 저장·라운드트립(소비처 skill용 url provenance 재구성 — :// 콜론 보존)
    URL = "https://example.com/docs/page?q=1#frag"
    nudge.collect(cd, config, {"tool_name": "WebFetch", "tool_input": {"url": URL}}, turn="sess#6")
    loc_exp = nudge.redact_url(URL, config["nudge"]["redact"])[0]
    fw = next(f for f in nudge.parse_queue(cd) if f.get("turn") == "sess#6")
    check("queue locator 저장(redact 후 값)", fw.get("locator") == loc_exp)
    check("locator :// 콜론 라운드트립 보존", fw["locator"] == "https://example.com/docs/page")
    check("locator → qhash 동치(Phase C 매칭 보장)", nudge.qhash(fw["locator"]) == fw["qhash"])
    # pending 서브명령(소비처 surface) — status:pending만, ingested/suppressed 제외
    rows = nudge.parse_queue(cd)
    rows.append({"ts": "ti", "tool": "WebFetch", "ref": "done.com", "locator": "https://done.com",
                 "qhash": nudge.qhash("https://done.com"), "status": "ingested", "turn": "s#1"})
    nudge.write_queue(cd, rows)
    pend = nudge.pending(cd)
    check("pending = status:pending만(ingested 제외)", all(p["turn"] != "s#1" for p in pend))
    pf6 = next(p for p in pend if p["turn"] == "sess#6")
    check("pending 항목 locator·qhash·turn 노출",
          pf6["locator"] == loc_exp and pf6["qhash"] == nudge.qhash(loc_exp))
    check("pending CLI(json) 동치", nudge.main(["pending"]) == 0)
    # --text 모드(SessionStart 주입용 사람-읽기 라인)
    import io as _io
    buf = _io.StringIO()
    saved_out = sys.stdout
    sys.stdout = buf
    try:
        nudge.main(["pending", "--text"])
    finally:
        sys.stdout = saved_out
    txt = buf.getvalue()
    check("pending --text 라인 포맷(ref/turn/tool)",
          "- example.com/docs/page (turn: sess#6, tool: WebFetch)" in txt)
    check("pending --text 비 JSON(- prefix 라인)", txt.lstrip().startswith("- ") and "{" not in txt)
    # collect stdin 모드('-') — ⓒ PostToolUse hook wrapper 경로
    import io
    saved_in = sys.stdin
    sys.stdin = io.StringIO(json.dumps({"tool_name": "WebSearch", "tool_input": {"query": "stdin hook payload"}}))
    try:
        rc = nudge.main(["collect", "-"])
    finally:
        sys.stdin = saved_in
    check("collect stdin('-') 적재", rc == 0 and any(
        f["ref"] == "stdin hook payload" for f in nudge.parse_queue(cd)))


def t_nudge_suppress(tmp):
    print("[7g] nudge suppress(dismiss) — websearch 후보 정리(정책 A)")
    cd, config = setup_vault(tmp)
    ws = {"tool_name": "WebSearch", "tool_input": {"query": "dismiss me"}}
    nudge.collect(cd, config, ws, turn="s#2")
    nudge.collect(cd, config, {"tool_name": "WebFetch", "tool_input": {"url": "https://keep.com/x"}}, turn="s#3")
    ws_qh = nudge.qhash("websearch:dismiss me")
    url_qh = nudge.qhash("https://keep.com/x")
    # suppress websearch만 → 전환, url pending 유지
    res = nudge.suppress(cd, [ws_qh])
    check("suppress count=1", res["count"] == 1)
    st = {f["qhash"]: f["status"] for f in nudge.parse_queue(cd)}
    check("websearch → suppressed", st[ws_qh] == "suppressed")
    check("url pending 유지(오염 없음)", st[url_qh] == "pending")
    # dedup 재제안 차단
    check("suppressed 재collect 차단", nudge.collect(cd, config, ws)["reason"] == "suppressed")
    # clear purge(suppressed 제거, pending 잔존)
    nudge.clear(cd)
    after = {f["qhash"]: f["status"] for f in nudge.parse_queue(cd)}
    check("clear → suppressed purge", ws_qh not in after)
    check("clear → pending 잔존", after.get(url_qh) == "pending")
    # 없는 qhash → no-op 비파괴
    check("없는 qhash suppress no-op", nudge.suppress(cd, ["deadbeef0000"])["count"] == 0)
    check("suppress CLI(json) 동치", nudge.main(["suppress", url_qh]) == 0)


def t_nudge_branches(tmp):
    print("[7c] nudge 상태별 dedup 분기 (ingested·--refresh·suppressed·nudge-proposed)")
    cd, config = setup_vault(tmp)

    def pl(qq):
        return {"tool_name": "WebSearch", "tool_input": {"query": qq}}

    # ingested 억제 (기본)
    nudge.append_metric(cd, "nudge-ingested", nudge.qhash("websearch:alpha"), "s1")
    r1 = nudge.collect(cd, config, pl("alpha"))
    check("ingested 억제", r1["action"] == "deduped" and r1["reason"] == "ingested")
    # --refresh 재적재
    r2 = nudge.collect(cd, config, pl("alpha"), refresh=True)
    check("--refresh 재적재", r2["action"] == "queued")
    # suppressed dedup (세션 범위)
    rows = nudge.parse_queue(cd)
    rows.append({"ts": "t", "tool": "WebSearch", "ref": "beta",
                 "qhash": nudge.qhash("websearch:beta"), "status": "suppressed"})
    nudge.write_queue(cd, rows)
    r3 = nudge.collect(cd, config, pl("beta"))
    check("suppressed dedup", r3["action"] == "deduped" and r3["reason"] == "suppressed")
    # nudge-proposed 비차단 (dedup 기준 아님)
    nudge.append_metric(cd, "nudge-proposed", nudge.qhash("websearch:gamma"), "s1")
    r4 = nudge.collect(cd, config, pl("gamma"))
    check("nudge-proposed 비차단", r4["action"] == "queued")


def t_nudge_persession(tmp):
    print("[7e] nudge emit perSession 가드 (재진입 재제안 차단)")
    cd, config = setup_vault(tmp)  # config.nudge.throttle.perSession = 1
    nudge.write_queue(cd, [{"ts": "t", "tool": "WebSearch", "ref": "x",
                            "qhash": nudge.qhash("websearch:x"), "status": "pending"}])
    r1 = nudge.emit(cd, config, "sess1")
    check("동일 session 첫 emit 제안", r1["action"] == "proposed")
    r2 = nudge.emit(cd, config, "sess1")  # 동일 session 재진입
    check("동일 session 둘째 throttled(perSession)",
          r2["action"] == "throttled" and r2.get("reason") == "perSession")
    r3 = nudge.emit(cd, config, "sess2")  # 다른 session
    check("다른 session emit 가능", r3["action"] == "proposed")
    # perSession=2 → 동일 session 2회 허용(fresh vault로 cadence 격리)
    cd2, config2 = setup_vault(tmp + "_b")
    config2["nudge"]["throttle"]["perSession"] = 2
    nudge.write_queue(cd2, [{"ts": "t", "tool": "WebSearch", "ref": "y",
                             "qhash": nudge.qhash("websearch:y"), "status": "pending"}])
    a1 = nudge.emit(cd2, config2, "sx")
    a2 = nudge.emit(cd2, config2, "sx")
    a3 = nudge.emit(cd2, config2, "sx")
    check("perSession=2 → 1·2회 허용", a1["action"] == "proposed" and a2["action"] == "proposed")
    check("perSession=2 → 3회 throttled", a3["action"] == "throttled" and a3.get("reason") == "perSession")


def t_nudge_cadence(tmp):
    print("[7d] nudge emit cadence 축소 + floor (P3b §4.3 self-governing)")
    cd, config = setup_vault(tmp)
    config["nudge"]["floorSessions"] = 3  # 테스트용 작은 floor(기본 WINDOW=10)
    # pending 1건 시드(emit가 제안할 대상 — emit는 status 미변경이라 잔존)
    nudge.write_queue(cd, [{"ts": "t", "tool": "WebSearch", "ref": "x",
                            "qhash": nudge.qhash("websearch:x"), "status": "pending"}])
    # 저적중률(제안만·ingest 0) 경계 6회 → cadence 거동 관찰
    actions = []
    for i in range(6):
        res = nudge.emit(cd, config, f"s{i}")
        actions.append((res["action"], res.get("interval"), res.get("floor")))
    first = actions[0]
    check("첫 emit 제안(매 경계)", first[0] == "proposed" and first[1] == 1)
    check("저적중률 → throttled 발생", any(a[0] == "throttled" for a in actions))
    check("throttled interval 증가(≥2)", any(a[0] == "throttled" and a[1] >= 2 for a in actions))
    # throttle 이후 floor 강제 emit 복원(0 도달 금지)
    floor_restore = any(a[0] == "proposed" and a[2] for a in actions[1:])
    check("floor 강제 emit 복원", floor_restore)
    # 정상 적중률(ingested=proposed) → interval 1 유지
    cd2, config2 = setup_vault(tmp + "_ok") if False else (cd, config)
    # okhit 경로: proposed에 대응 ingested 기록 → 다음 측정 hr≥floor
    for m in nudge.parse_metrics(cd):
        if m["event"] == "nudge-proposed":
            nudge.append_metric(cd, "nudge-ingested", m["qhash"], "sok")
            break
    res_ok = nudge.emit(cd, config, "sok")
    check("적중 회복 시 interval 1", res_ok.get("interval") == 1)


def _load_hook_module(name, filename):
    """hooks/ 어댑터 모듈을 파일 경로로 로드(core sys.path 밖). turn 카운트 = 어댑터 책임."""
    path = HERE.parent / "hooks" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _jl(*objs):
    return "\n".join(json.dumps(o, ensure_ascii=False) for o in objs) + "\n"


def t_turn_count(tmp):
    print("[7f] turn_id: CC 어댑터 user-turn 카운트 + session_turn (KC-Fn-41)")
    cc = _load_hook_module("cairn_cc_turn", "cairn_cc_turn.py")
    tp = Path(tmp) / "transcript.jsonl"
    # 진짜 프롬프트 2(str 1 + text-block 1) + tool_result 1 + assistant 2 + meta 1 + compact 1
    tp.write_text(_jl(
        {"type": "user", "message": {"content": "첫 질문"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "답"}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "결과"}]}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "또 답"}]}},
        {"type": "user", "message": {"content": [{"type": "text", "text": "둘째 질문"}]}},
        {"type": "user", "isMeta": True, "message": {"content": "시스템 주입"}},
        {"type": "user", "isCompactSummary": True, "message": {"content": "요약"}},
    ), encoding="utf-8")
    check("진짜 프롬프트만 카운트(tool_result·meta·compact 제외)", cc.count_user_turns(str(tp)) == 2)
    check("결정성(반복 동일)", cc.count_user_turns(str(tp)) == cc.count_user_turns(str(tp)))
    check("부재 transcript → 0", cc.count_user_turns(str(Path(tmp) / "none.jsonl")) == 0)
    # session_turn = session_id#ordinal
    check("session_turn 조립", cc.session_turn({"session_id": "abc", "transcript_path": str(tp)}) == "abc#2")
    check("transcript_path 부재 → None", cc.session_turn({"tool_name": "WebSearch"}) is None)
    check("session_id 부재 → ordinal만", cc.session_turn({"transcript_path": str(tp)}) == "2")
    # 깨진/빈 라인 무시
    tp2 = Path(tmp) / "t2.jsonl"
    tp2.write_text("not json\n\n" + _jl({"type": "user", "message": {"content": "q"}}), encoding="utf-8")
    check("깨진/빈 라인 무시", cc.count_user_turns(str(tp2)) == 1)
    # 빈 transcript → None
    empty = Path(tmp) / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    check("빈 transcript → session_turn None", cc.session_turn({"transcript_path": str(empty)}) is None)
    # multi-turn 누적(KC-Fn-41 한계 보강): 3-turn → ordinal 3
    tp3 = Path(tmp) / "multi.jsonl"
    tp3.write_text(_jl(
        {"type": "user", "message": {"content": "q1"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "a1"}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "content": "r"}]}},
        {"type": "user", "message": {"content": "q2"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "a2"}]}},
        {"type": "user", "message": {"content": "q3"}},
    ), encoding="utf-8")
    check("multi-turn 3 누적", cc.count_user_turns(str(tp3)) == 3)
    check("multi-turn session_turn", cc.session_turn({"session_id": "s", "transcript_path": str(tp3)}) == "s#3")


def t_codex_turn_count(tmp):
    print("[8c] Codex 어댑터 user-turn 카운트 (event_msg.user_message, KC-Fn-43)")
    mod = _load_hook_module("cairn_codex_transcript_scan", "cairn-codex-transcript-scan.py")
    tp = Path(tmp) / "codex.jsonl"
    # event_msg.user_message 2 + response_item.role=user 주입 1(naive 과대 유발) + 기타
    tp.write_text(_jl(
        {"type": "response_item", "payload": {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "# AGENTS.md instructions ..."}]}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "첫 turn"}},
        {"type": "event_msg", "payload": {"type": "task_started", "turn_id": "t1"}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": []}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "둘째 turn"}},
    ), encoding="utf-8")
    check("event_msg.user_message만 카운트(주입 제외)", mod.count_codex_user_turns(str(tp)) == 2)
    check("naive role=user 함정 회피(≠3)", mod.count_codex_user_turns(str(tp)) != 3)
    check("결정성", mod.count_codex_user_turns(str(tp)) == mod.count_codex_user_turns(str(tp)))
    check("codex session_turn", mod.codex_session_turn({"session_id": "cx", "transcript_path": str(tp)}) == "cx#2")
    check("transcript_path 부재 → None", mod.codex_session_turn({"tool_name": "Bash"}) is None)
    # 도구혼합 multi-turn(KC-Fn-47): function_call/function_call_output가 섞여도 카운트 불변
    tpx = Path(tmp) / "codex_tool.jsonl"
    tpx.write_text(_jl(
        {"type": "response_item", "payload": {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "<environment_context> ..."}]}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "turn1 echo"}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command",
            "arguments": "{\"cmd\":\"echo a\"}"}},
        {"type": "response_item", "payload": {"type": "function_call_output", "output": "a"}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "turn2 echo"}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "exec_command",
            "arguments": "{\"cmd\":\"echo b\"}"}},
        {"type": "response_item", "payload": {"type": "function_call_output", "output": "b"}},
    ), encoding="utf-8")
    check("도구 record 섞여도 user-message만 카운트", mod.count_codex_user_turns(str(tpx)) == 2)
    # apply_patch 도구혼합(KC-Fn-48): exec_command와 다른 record 타입.
    # custom_tool_call(name=apply_patch)/custom_tool_call_output + patch_apply_end event_msg.
    # patch_apply_end는 event_msg지만 user_message가 아니므로 카운트 불변.
    tpp = Path(tmp) / "codex_apply_patch.jsonl"
    tpp.write_text(_jl(
        {"type": "response_item", "payload": {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "<environment_context> ..."}]}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "turn1 patch"}},
        {"type": "response_item", "payload": {"type": "custom_tool_call", "status": "completed",
            "name": "apply_patch", "call_id": "c1"}},
        {"type": "event_msg", "payload": {"type": "patch_apply_end", "call_id": "c1", "success": True}},
        {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c1",
            "output": "Exit code: 0"}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "turn2 patch"}},
        {"type": "response_item", "payload": {"type": "custom_tool_call", "status": "completed",
            "name": "apply_patch", "call_id": "c2"}},
        {"type": "event_msg", "payload": {"type": "patch_apply_end", "call_id": "c2", "success": True}},
        {"type": "response_item", "payload": {"type": "custom_tool_call_output", "call_id": "c2",
            "output": "Exit code: 0"}},
    ), encoding="utf-8")
    check("apply_patch record·patch_apply_end 섞여도 user-message만 카운트",
          mod.count_codex_user_turns(str(tpp)) == 2)
    # MCP/web 도구혼합(KC-Fn-56): MCP=function_call(namespace=mcp__*)+mcp_tool_call_end,
    # web=web_search_call+web_search_end. 신규 event_msg 2종이나 user_message 아니므로 카운트 불변.
    # 실측(codex-cli 0.136.0): shell·apply_patch·MCP·web 4종 모두 user_message 화이트리스트 robust.
    tpm = Path(tmp) / "codex_mcp_web.jsonl"
    tpm.write_text(_jl(
        {"type": "response_item", "payload": {"type": "message", "role": "user",
            "content": [{"type": "input_text", "text": "<environment_context> ..."}]}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "turn1 mcp"}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "list_tasks",
            "namespace": "mcp__shrimp_task_manager", "arguments": "{\"status\":\"all\"}", "call_id": "m1"}},
        {"type": "event_msg", "payload": {"type": "mcp_tool_call_end", "call_id": "m1",
            "invocation": {"server": "shrimp-task-manager", "tool": "list_tasks"}}},
        {"type": "response_item", "payload": {"type": "function_call_output", "call_id": "m1", "output": "[]"}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "turn2 web"}},
        {"type": "response_item", "payload": {"type": "web_search_call", "status": "completed",
            "action": {"type": "open_page", "url": "https://openai.com/"}}},
        {"type": "event_msg", "payload": {"type": "web_search_end", "call_id": "ws1",
            "query": "https://openai.com/", "action": {"type": "open_page", "url": "https://openai.com/"}}},
        {"type": "event_msg", "payload": {"type": "user_message", "message": "turn3 mixed"}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "list_tasks",
            "namespace": "mcp__shrimp_task_manager", "arguments": "{\"status\":\"all\"}", "call_id": "m2"}},
        {"type": "event_msg", "payload": {"type": "mcp_tool_call_end", "call_id": "m2",
            "invocation": {"server": "shrimp-task-manager", "tool": "list_tasks"}}},
        {"type": "response_item", "payload": {"type": "web_search_call", "status": "completed",
            "action": {"type": "open_page", "url": "https://openai.com/"}}},
        {"type": "event_msg", "payload": {"type": "web_search_end", "call_id": "ws2",
            "query": "openai", "action": {"type": "open_page", "url": "https://openai.com/"}}},
    ), encoding="utf-8")
    check("MCP/web record·mcp_tool_call_end·web_search_end 섞여도 user-message만 카운트(=3)",
          mod.count_codex_user_turns(str(tpm)) == 3)
    check("MCP/web 신규 event_msg 타입 user-turn 미오염(≠naive)",
          mod.count_codex_user_turns(str(tpm)) == 3)


# ── 8. PostToolUse payload extractor (실측 fixture) ──
def t_extractor():
    print("[8] PostToolUse payload extractor (실측 fixture)")
    fixtures = json.loads((HERE / "_fixtures" / "posttooluse_payloads.json").read_text(encoding="utf-8"))
    triggers, redact = ["WebFetch", "WebSearch"], ["query", "hash", "userinfo"]
    for fx in fixtures:
        ext = nudge.extract(fx, triggers, redact)
        exp = fx.get("_expect")
        if exp is None:
            check(f"{fx['tool_name']} → None", ext is None)
        else:
            check(f"{fx['tool_name']} ref 추출", ext["ref"] == exp["ref"])


def t_codex_transcript_scan():
    print("[8b] Codex Stop transcript scanner hardening fixture")
    scanner_path = HERE.parent / "hooks" / "cairn-codex-transcript-scan.py"
    spec = importlib.util.spec_from_file_location("cairn_codex_transcript_scan", scanner_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fixtures = json.loads((HERE.parent / "hooks" / "_fixtures" / "codex_transcript_scan_payloads.json").read_text(encoding="utf-8"))
    for fx in fixtures:
        scan_text = fx.get("_scan_text", False)
        candidates = mod.dedupe([item for obj in fx["objects"] for item in mod.walk(obj, scan_text_urls=scan_text)])
        refs = [item["ref"] for item in candidates]
        check(f"{fx['_name']} refs", refs == fx["_expect_refs"])
        if "_expect_tools" in fx:
            tools = [item["tool"] for item in candidates]
            check(f"{fx['_name']} tools", tools == fx["_expect_tools"])


# ── ingest write + query + lint (통합 결정부) ──
def t_ingest_query_lint(tmp):
    print("[9] ingest write → query → lint 통합")
    cd, config = setup_vault(tmp)
    page = ("---\nslug: zero-dep-bm25\ntype: lesson\ntitle: zero-dep BM25 retrieval\n"
            "tags: [retrieval, bm25]\nprovenance: [file:specs%2Flessons.md%23feature-001@a1b2c3d4e5f6]\n"
            "refs: [feature:001]\nstatus: approved\nupdated: 2026-05-31\n---\n"
            "## 본문\nbm25 ranking zero dep retrieval over markdown vault.\nsee [[markdown-vault]] for storage.")
    pf = Path(tmp) / "page.md"
    pf.write_text(page, encoding="utf-8")
    errs = ing.write_page(str(pf), cd, config)
    check("write_page 검증 통과", errs == [])
    check("page 파일 생성", (cd / "pages" / "lesson" / "zero-dep-bm25.md").exists())
    check("index.md 행", "zero-dep-bm25" in (cd / "index.md").read_text(encoding="utf-8"))
    check("log.md append", "ingest" in (cd / "log.md").read_text(encoding="utf-8"))
    res = q.query("bm25 retrieval", cd, config)
    check("query HIT", res["mode"] == "bm25" and res["results"][0]["slug"] == "zero-dep-bm25")
    # refs drift acceptance: feature:001 부재 → drift 경고 정확히 1
    findings = lint.lint(cd, config)
    drift = [f for f in findings if f.code == "refs-drift"]
    check("refs drift 경고 1건(feature 디렉터리 부재)", len(drift) == 1)
    check("dangling wikilink 탐지", any(f.code == "dangling" for f in findings))
    # 유효 refs: specs/features/001-x 생성 → drift 0
    (Path(tmp) / "specs" / "features" / "001-fixture").mkdir(parents=True, exist_ok=True)
    findings2 = lint.lint(cd, config)
    check("유효 refs 통과(경고 0)", not any(f.code == "refs-drift" for f in findings2))
    # index-drift: write_page 저널 경유 → clean 상태 0
    check("저널 경유 index-drift 0", not any(f.code == "index-drift" for f in findings2))
    # 손편집(저널 미경유)으로 page tags 변경 → index stale → CRIT index-drift 발생
    pgfile = cd / "pages" / "lesson" / "zero-dep-bm25.md"
    fm, body = r.parse_frontmatter(pgfile.read_text(encoding="utf-8"))
    fm["tags"] = ["retrieval", "bm25", "hand-edited"]
    pgfile.write_text(r.dump_frontmatter(fm, body), encoding="utf-8")  # index 미갱신
    findings3 = lint.lint(cd, config)
    idrift = [f for f in findings3 if f.code == "index-drift"]
    check("손편집 index-drift CRIT 탐지", len(idrift) >= 1 and all(f.sev == "CRIT" for f in idrift))


def t_log_turn_tag(tmp):
    print("[9b] ingest log turn 태깅 (#3 Phase A, turn 있/없 하위호환)")
    cd, config = setup_vault(tmp)
    # turn 명시 → log 라인에 | turn: 태깅
    ing.append_log(cd, "x", "detail-with-turn", turn="s#3")
    # turn 미지정 → 기존 라인 불변(turn: 미부착)
    ing.append_log(cd, "y", "detail-no-turn")
    log = (cd / "log.md").read_text(encoding="utf-8")
    turn_line = next(ln for ln in log.split("\n") if "detail-with-turn" in ln)
    plain_line = next(ln for ln in log.split("\n") if "detail-no-turn" in ln)
    check("turn 명시 라인 태깅", turn_line.endswith("| turn: s#3"))
    check("turn 미지정 라인 불변(turn: 미부착)", "turn:" not in plain_line)
    # write_page --turn 경로 → ingest 이벤트에 turn 태깅
    page = ("---\nslug: turn-tag\ntype: note\ntitle: turn tag\ntags: [t]\n"
            "provenance: [file:specs%2Flessons.md%23feature-001@a1b2c3d4e5f6]\n"
            "refs: []\nstatus: approved\nupdated: 2026-06-02\n---\n## 본문\nbody.")
    pf = Path(tmp) / "tp.md"
    pf.write_text(page, encoding="utf-8")
    errs = ing.write_page(str(pf), cd, config, turn="s#7")
    check("write_page turn 검증 통과", errs == [])
    ingest_line = next(ln for ln in (cd / "log.md").read_text(encoding="utf-8").split("\n")
                       if "turn-tag" in ln and "| ingest |" in ln)
    check("write_page ingest 라인 turn 태깅", ingest_line.endswith("| turn: s#7"))
    # A2: emit 반환에 turns 키(refs와 동일 길이)
    nudge.collect(cd, config, {"tool_name": "WebSearch", "tool_input": {"query": "turn emit q"}}, turn="s#9")
    res = nudge.emit(cd, config)
    if res.get("action") == "proposed":
        check("emit turns 키 존재", "turns" in res and len(res["turns"]) == len(res["refs"]))
        check("emit turns 값 carry", "s#9" in res["turns"])


def t_page_turn_fm(tmp):
    print("[9c] page frontmatter turn 필드 (#3 Phase B, 대표값 최신·비파괴)")
    cd, config = setup_vault(tmp)
    base = ("---\nslug: pb\ntype: note\ntitle: phase b\ntags: [t]\n"
            "provenance: [file:srcpb.md@a1b2c3d4e5f6]\nrefs: []\nstatus: approved\nupdated: 2026-06-02\n---\n"
            "## 본문\nphase b body.")
    pf = Path(tmp) / "pb.md"
    pf.write_text(base, encoding="utf-8")
    pgfile = cd / "pages" / "note" / "pb.md"
    # write_page --turn → fm["turn"] 주입
    ing.write_page(str(pf), cd, config, turn="s#7")
    fm, _ = r.parse_frontmatter(pgfile.read_text(encoding="utf-8"))
    check("write_page turn → fm turn 주입", fm.get("turn") == "s#7")
    # 재기록(reconcile turn=None) → 기존 fm turn 비파괴(read-modify-write 보존)
    (Path(tmp) / "mirror.md").write_text("phase b mirror.\n", encoding="utf-8")
    ing.reconcile_provenance_append("pb", "mirror.md", None, cd, config)
    fm2, _ = r.parse_frontmatter(pgfile.read_text(encoding="utf-8"))
    check("reconcile turn=None → 기존 turn 비파괴", fm2.get("turn") == "s#7")
    # multi-provenance turn 명시 → 대표값 최신으로 덮어쓰기
    (Path(tmp) / "mirror2.md").write_text("phase b mirror two.\n", encoding="utf-8")
    ing.reconcile_provenance_append("pb", "mirror2.md", None, cd, config, turn="s#9")
    fm3, _ = r.parse_frontmatter(pgfile.read_text(encoding="utf-8"))
    check("reconcile turn 명시 → 대표값 최신 덮어쓰기", fm3.get("turn") == "s#9")
    # turn 없는 신규 page → fm에 turn 키 미생성(하위호환)
    base2 = base.replace("slug: pb", "slug: pb-noturn")
    pf2 = Path(tmp) / "pb2.md"
    pf2.write_text(base2, encoding="utf-8")
    ing.write_page(str(pf2), cd, config)
    fm4, _ = r.parse_frontmatter((cd / "pages" / "note" / "pb-noturn.md").read_text(encoding="utf-8"))
    check("turn 미지정 → fm turn 키 미생성", "turn" not in fm4)


def t_ingest_reverse_lookup(tmp):
    print("[9d] ingest-time turn 자동 역조회 (#3 Phase C, 경로 A)")
    cd, config = setup_vault(tmp)

    def url_page(slug, urls, with_turn_line=False):
        prov = ", ".join(r.format_provenance("url", r.make_locator(u), "a1b2c3d4e5f6") for u in urls)
        text = (f"---\nslug: {slug}\ntype: note\ntitle: {slug}\ntags: [t]\n"
                f"provenance: [{prov}]\nrefs: []\nstatus: approved\nupdated: 2026-06-02\n---\n## 본문\nbody.")
        pf = Path(tmp) / f"{slug}.md"
        pf.write_text(text, encoding="utf-8")
        return pf, cd / "pages" / "note" / f"{slug}.md"

    # ── 1. 매칭 성공 (query 포함 URL → redact 정규화 일치) ──
    URL = "https://example.com/docs/page?q=1#frag"
    nudge.collect(cd, config, {"tool_name": "WebFetch", "tool_input": {"url": URL}}, turn="s#5")
    qh = nudge.qhash(nudge.redact_url(URL, config["nudge"]["redact"])[0])
    pf, pg = url_page("rl-hit", [URL])
    errs = ing.write_page(str(pf), cd, config)  # --turn 미명시 → 역조회 발동
    check("역조회 검증 통과", errs == [])
    fm, _ = r.parse_frontmatter(pg.read_text(encoding="utf-8"))
    check("역조회 → fm turn 자동 주입", fm.get("turn") == "s#5")
    row = next(f for f in nudge.parse_queue(cd) if f["qhash"] == qh)
    check("매칭 queue 항목 ingested 전환", row["status"] == "ingested")
    check("nudge-ingested 메트릭 append",
          any(m["event"] == "nudge-ingested" and m["qhash"] == qh for m in nudge.parse_metrics(cd)))

    # ── 6. 정규화 회귀가드: lookup 내부 qhash == collect-time qhash ──
    t_auto, matched = ing.lookup_turn({"provenance": [r.format_provenance("url", r.make_locator(URL), "x")]}, cd, config)
    # 이미 ingested 전환됐으므로 pending 부재 → 매칭 0(전환 후 재역조회 안 됨 = dedup 정합)
    check("정규화 회귀가드: 전환 후 pending 부재로 재매칭 안 됨", t_auto is None and matched == [])

    # ── 2. 매칭 실패 (무관 url) ──
    nudge.write_queue(cd, [{"ts": "t1", "tool": "WebFetch", "ref": "other.com",
                            "qhash": nudge.qhash("https://other.com/x"), "status": "pending", "turn": "s#1"}])
    pf2, pg2 = url_page("rl-miss", ["https://nomatch.com/y"])
    ing.write_page(str(pf2), cd, config)
    fm2, _ = r.parse_frontmatter(pg2.read_text(encoding="utf-8"))
    check("매칭 실패 → fm turn 키 미생성", "turn" not in fm2)
    check("매칭 실패 → queue 불변(pending 유지)",
          all(f["status"] == "pending" for f in nudge.parse_queue(cd)))

    # ── 3. --turn 명시 우선 (역조회 미호출 → status 미전환) ──
    URL3 = "https://example.com/explicit"
    nudge.write_queue(cd, [{"ts": "t3", "tool": "WebFetch", "ref": "example.com/explicit",
                            "qhash": nudge.qhash("https://example.com/explicit"), "status": "pending", "turn": "s#5"}])
    pf3, pg3 = url_page("rl-explicit", [URL3])
    ing.write_page(str(pf3), cd, config, turn="s#9")
    fm3, _ = r.parse_frontmatter(pg3.read_text(encoding="utf-8"))
    check("--turn 명시 우선", fm3.get("turn") == "s#9")
    check("명시 경로 → 역조회 미호출 → queue status 미전환",
          all(f["status"] == "pending" for f in nudge.parse_queue(cd)))

    # ── 4. turn=None 하위호환 (file kind만 → 역조회 무대상) ──
    base = ("---\nslug: rl-file\ntype: note\ntitle: rl file\ntags: [t]\n"
            "provenance: [file:srcrl.md@a1b2c3d4e5f6]\nrefs: []\nstatus: approved\nupdated: 2026-06-02\n---\n## 본문\nbody.")
    pf4 = Path(tmp) / "rl-file.md"
    pf4.write_text(base, encoding="utf-8")
    ing.write_page(str(pf4), cd, config)
    fm4, _ = r.parse_frontmatter((cd / "pages" / "note" / "rl-file.md").read_text(encoding="utf-8"))
    check("file kind만 → fm turn 키 미생성", "turn" not in fm4)

    # ── 5. multi-url 대표값 = 최신 ts + 두 qhash 모두 전환 ──
    Ua, Ub = "https://example.com/old", "https://example.com/new"
    qa, qb = nudge.qhash("https://example.com/old"), nudge.qhash("https://example.com/new")
    nudge.write_queue(cd, [
        {"ts": "2026-06-01T10:00", "tool": "WebFetch", "ref": "example.com/old", "qhash": qa, "status": "pending", "turn": "s#3"},
        {"ts": "2026-06-02T10:00", "tool": "WebFetch", "ref": "example.com/new", "qhash": qb, "status": "pending", "turn": "s#7"},
    ])
    pf5, pg5 = url_page("rl-multi", [Ua, Ub])
    ing.write_page(str(pf5), cd, config)
    fm5, _ = r.parse_frontmatter(pg5.read_text(encoding="utf-8"))
    check("multi-url 대표값 = 최신 ts turn", fm5.get("turn") == "s#7")
    rows5 = {f["qhash"]: f["status"] for f in nudge.parse_queue(cd)}
    check("multi-url 두 qhash 모두 ingested", rows5[qa] == "ingested" and rows5[qb] == "ingested")

    # ── 7. websearch 비대상 (kind=url만 역조회) ──
    nudge.write_queue(cd, [{"ts": "t7", "tool": "WebSearch", "ref": "ws q",
                            "qhash": nudge.qhash("websearch:ws q"), "status": "pending", "turn": "s#8"}])
    pf7, pg7 = url_page("rl-ws", ["https://example.com/notws"])
    ing.write_page(str(pf7), cd, config)
    fm7, _ = r.parse_frontmatter(pg7.read_text(encoding="utf-8"))
    check("websearch 비대상 → url page에 미매칭(turn 키 미생성)", "turn" not in fm7)
    check("websearch pending 불변", all(f["status"] == "pending" for f in nudge.parse_queue(cd)))

    # ── 8. --source-url 민팅 e2e(skill 경로): provenance 없는 draft + locator → 자동 연결 ──
    URL8 = "https://example.com/skill-flow?utm=x"
    loc8 = nudge.redact_url(URL8, config["nudge"]["redact"])[0]  # https://example.com/skill-flow
    nudge.write_queue(cd, [{"ts": "t8", "tool": "WebFetch", "ref": "example.com/skill-flow",
                            "locator": loc8, "qhash": nudge.qhash(loc8), "status": "pending", "turn": "s#11"}])
    draft = ("---\nslug: rl-skill\ntype: note\ntitle: skill flow\ntags: [t]\n"
             "refs: []\nstatus: approved\nupdated: 2026-06-02\n---\n## 본문\nskill draft body.")
    df = Path(tmp) / "rl-skill.md"
    df.write_text(draft, encoding="utf-8")
    errs8 = ing.write_page(str(df), cd, config, source_url=loc8)  # provenance 없는 draft, locator만
    check("--source-url draft 검증 통과(민팅 후)", errs8 == [])
    fm8, _ = r.parse_frontmatter((cd / "pages" / "note" / "rl-skill.md").read_text(encoding="utf-8"))
    check("url provenance 민팅(quote locator)", any(p.startswith("url:") for p in fm8["provenance"]))
    check("민팅→Phase C 자동 turn 연결", fm8.get("turn") == "s#11")
    check("queue ingested 전환", next(f for f in nudge.parse_queue(cd) if f["qhash"] == nudge.qhash(loc8))["status"] == "ingested")


def t_capture_session_source(tmp):
    print("[9e] capture --session-source: 대화 turn → conversation provenance 민팅 (update3)")
    cd, config = setup_vault(tmp)

    # provenance 없는 draft + session_turn → conversation provenance 결정적 민팅 + turn 자동 세팅
    st = "bba73fe0-13a9-4688-8684-c6a873f9fb9b#3"
    draft = ("---\nslug: cap-decision\ntype: note\ntitle: capture flow\ntags: [t]\n"
             "refs: []\nstatus: approved\nupdated: 2026-06-04\n---\n## 결정\ncapture draft body.")
    df = Path(tmp) / "cap-decision.md"
    df.write_text(draft, encoding="utf-8")
    errs = ing.write_page(str(df), cd, config, session_source=st)  # provenance 없는 draft, turn만
    check("--session-source draft 검증 통과(민팅 후)", errs == [])
    fm, _ = r.parse_frontmatter((cd / "pages" / "note" / "cap-decision.md").read_text(encoding="utf-8"))
    # 결정적 민팅: conversation:<quote(turn)>@<content_hash(body)>
    expect = r.format_provenance("conversation", r.make_locator(st), r.content_hash("## 결정\ncapture draft body."))
    check("conversation provenance 민팅(quote locator + body hash)", expect in fm["provenance"])
    check("turn 미지정 → session_turn 자동 세팅", fm.get("turn") == st)
    check("큐 항목 없어도 정상(역조회 미실행)", nudge.parse_queue(cd) == [])

    # 멱등: 동일 provenance 이미 있으면 중복 안 됨
    df.write_text(draft.replace("provenance: []", ""), encoding="utf-8")  # no-op(이미 provenance 없음)
    errs2 = ing.write_page(str(df), cd, config, session_source=st)
    check("재기록 검증 통과", errs2 == [])
    fm2, _ = r.parse_frontmatter((cd / "pages" / "note" / "cap-decision.md").read_text(encoding="utf-8"))
    check("conversation provenance 중복 안 됨", fm2["provenance"].count(expect) == 1)

    # --turn 명시 시 turn 우선(provenance는 여전히 session_source로 민팅)
    df3 = Path(tmp) / "cap-explicit.md"
    df3.write_text(draft.replace("cap-decision", "cap-explicit"), encoding="utf-8")
    ing.write_page(str(df3), cd, config, turn="s#99", session_source=st)
    fm3, _ = r.parse_frontmatter((cd / "pages" / "note" / "cap-explicit.md").read_text(encoding="utf-8"))
    check("--turn 명시 우선", fm3.get("turn") == "s#99")
    check("--turn 명시여도 conversation provenance 민팅", expect in fm3["provenance"])


def t_source_split(tmp):
    print("[10] multi-entry source 분해")
    cd, config = setup_vault(tmp)
    acfg = config["refs"]["anchor"]
    src = Path(tmp) / "specs" / "lessons.md"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("## Feature 001 auth\nlesson one body\n\n## Feature 002 cache\nlesson two body\n",
                   encoding="utf-8")
    units = ing.source_units("specs/lessons.md", cd, anchor_cfg=acfg)
    check("entry 2개 분해", len(units) == 2)
    check("anchor 규약 적용(special anchor)", units[0]["anchor"] == "feature-001")
    check("unit별 독립 hash", units[0]["hash"] != units[1]["hash"])
    check("multi-entry locator #anchor", "%23feature-001" in units[0]["locator"])
    # [10b] anchor 토글 OFF(anchor_cfg 없음) → heading slug(special anchor 미적용)
    units_off = ing.source_units("specs/lessons.md", cd)
    check("anchor 토글 OFF → heading slug", units_off[0]["anchor"] == "feature-001-auth")
    # [10c] single-resource(heading 없는 source) → locator = source 자체(no #anchor)
    single = Path(tmp) / "specs" / "note.md"
    single.write_text("just a single resource body\nno heading here\n", encoding="utf-8")
    su = ing.source_units("specs/note.md", cd, anchor_cfg=acfg)
    check("single-resource 1 unit", len(su) == 1 and su[0]["anchor"] is None)
    check("single-resource locator = source", r.parse_locator(su[0]["locator"]) == "specs/note.md")
    # [10d] anchor 패턴 비매칭 heading → special anchor 오인 안 함
    issue = Path(tmp) / "specs" / "issues.md"
    issue.write_text("## Issue 123 bug report\nbody\n", encoding="utf-8")
    iu = ing.source_units("specs/issues.md", cd, anchor_cfg=acfg)
    check("패턴 비매칭 → 오인 안 함", iu[0]["anchor"] != "feature-123")


# ── reconcile 저널 경유 강제 (KC-Fn-G2-2) ──
def t_reconcile(tmp):
    print("[11] reconcile 저널 경유(provenance-append·update)")
    cd, config = setup_vault(tmp)
    page = ("---\nslug: d-x\ntype: decision\ntitle: zero dep storage\n"
            "tags: [storage]\nprovenance: [file:src1.md@a1b2c3d4e5f6]\nupdated: 2026-05-31\n---\n"
            "본문 결정 내용.")
    config["pageTypes"].append("decision") if "decision" not in config["pageTypes"] else None
    pf = Path(tmp) / "page.md"
    pf.write_text(page, encoding="utf-8")
    ing.write_page(str(pf), cd, config)
    pgfile = cd / "pages" / "decision" / "d-x.md"
    # provenance-append: 동일 내용 미러 소스 → 신규 locator 누적(결정적)
    (Path(tmp) / "mirror.md").write_text("본문 결정 내용.\n", encoding="utf-8")
    errs = ing.reconcile_provenance_append("d-x", "mirror.md", None, cd, config)
    check("provenance-append 성공", errs == [])
    fm, _ = r.parse_frontmatter(pgfile.read_text(encoding="utf-8"))
    check("provenance 2항목 누적", len(fm.get("provenance", [])) == 2)
    check("log reconcile:provenance-append 기록", "reconcile:provenance-append" in (cd / "log.md").read_text(encoding="utf-8"))
    # 멱등: 재실행 → no-op(2항목 유지)
    ing.reconcile_provenance_append("d-x", "mirror.md", None, cd, config)
    fm2, _ = r.parse_frontmatter(pgfile.read_text(encoding="utf-8"))
    check("provenance-append 멱등", len(fm2.get("provenance", [])) == 2)
    # index-drift 0(저널 경유라 index 일관)
    check("reconcile 후 index-drift 0", not any(f.code == "index-drift" for f in lint.lint(cd, config)))
    # update: 기존 slug 존재 → 저널 경유 기록
    upd = ("---\nslug: d-x\ntype: decision\ntitle: zero dep storage\n"
           "tags: [storage, revised]\nprovenance: [file:src1.md@ffffffffffff]\nupdated: 2026-06-01\n---\n"
           "갱신된 본문.")
    uf = Path(tmp) / "upd.md"
    uf.write_text(upd, encoding="utf-8")
    check("update 성공", ing.reconcile_write(str(uf), "update", cd, config) == [])
    check("log reconcile:update 기록", "reconcile:update" in (cd / "log.md").read_text(encoding="utf-8"))
    check("update 후 index-drift 0", not any(f.code == "index-drift" for f in lint.lint(cd, config)))
    # update on 부재 slug → 거부
    nf = Path(tmp) / "none.md"
    nf.write_text(upd.replace("d-x", "d-none"), encoding="utf-8")
    check("부재 slug update 거부", ing.reconcile_write(str(nf), "update", cd, config) != [])
    # type 변경(decision→lesson) → 거부(중복 page 방지, commit_page 가드)
    tf = Path(tmp) / "typechg.md"
    tf.write_text(upd.replace("type: decision", "type: lesson"), encoding="utf-8")
    errs_tc = ing.reconcile_write(str(tf), "update", cd, config)
    check("type 변경 거부", errs_tc != [] and "type 변경 거부" in errs_tc[0])
    check("type 변경 거부 후 구 page 유지", (cd / "pages" / "decision" / "d-x.md").exists())
    check("type 변경 거부 후 신 type 경로 미생성", not (cd / "pages" / "lesson" / "d-x.md").exists())


# ── reconcile move: page 재분류(slug·type 이동, KC-Fn-G2b-3) ──
def t_reconcile_move(tmp):
    print("[11b] reconcile move 재분류(slug·type 이동)")
    cd, config = setup_vault(tmp)
    page_a = ("---\nslug: note-a\ntype: note\ntitle: alpha note\n"
              "tags: [x]\nprovenance: [file:srcA.md@a1b2c3d4e5f6]\nupdated: 2026-05-31\n---\n본문 A")
    page_b = ("---\nslug: note-b\ntype: note\ntitle: beta note\n"
              "tags: [y]\nprovenance: [file:srcB.md@b2c3d4e5f6a7]\nupdated: 2026-05-31\n---\n참조 [[note-a]] 본문 B")
    for name, txt in (("a.md", page_a), ("b.md", page_b)):
        pf = Path(tmp) / name
        pf.write_text(txt, encoding="utf-8")
        ing.write_page(str(pf), cd, config)
    # type 이동(note→lesson, slug 유지) — commit_page가 막는 type 변경의 합법 경로
    errs = ing.reconcile_move("note-a", "note-a", "lesson", cd, config)
    check("move type 변경 성공", errs == [])
    check("신 type 경로 생성", (cd / "pages" / "lesson" / "note-a.md").exists())
    check("구 type 경로 제거", not (cd / "pages" / "note" / "note-a.md").exists())
    check("move log 기록", "reconcile:move" in (cd / "log.md").read_text(encoding="utf-8"))
    check("move 후 index-drift 0(type)", not any(f.code == "index-drift" for f in lint.lint(cd, config)))
    # slug 이동(note-a → lesson-a)
    errs2 = ing.reconcile_move("note-a", "lesson-a", None, cd, config)
    check("move slug 변경 성공", errs2 == [])
    check("신 slug 파일 생성", (cd / "pages" / "lesson" / "lesson-a.md").exists())
    check("구 slug 파일 제거", not (cd / "pages" / "lesson" / "note-a.md").exists())
    idx = (cd / "index.md").read_text(encoding="utf-8")
    check("구 slug index 행 제거 + 신 행 존재", "| note-a |" not in idx and "| lesson-a |" in idx)
    check("move 후 index-drift 0(slug)", not any(f.code == "index-drift" for f in lint.lint(cd, config)))
    # 구 slug 향한 wikilink → dangling 탐지(재지정은 lint 후속, move 자동 안 함)
    check("구 slug wikilink dangling 탐지",
          any(f.code == "dangling" and "note-a" in f.msg for f in lint.lint(cd, config)))
    # 부재 slug move 거부
    check("부재 slug move 거부", ing.reconcile_move("nope", "x", None, cd, config) != [])
    # 대상 slug 이미 존재 → 충돌 거부
    check("대상 slug 충돌 거부", ing.reconcile_move("lesson-a", "note-b", None, cd, config) != [])
    # 무효 type move 거부 + 구 page 무손실(파괴 전 검증)
    before = (cd / "pages" / "lesson" / "lesson-a.md").read_text(encoding="utf-8")
    errs3 = ing.reconcile_move("lesson-a", "lesson-a", "nonexistent-type", cd, config)
    check("무효 type move 거부", errs3 != [])
    check("거부 후 구 page 무손실",
          (cd / "pages" / "lesson" / "lesson-a.md").exists() and
          (cd / "pages" / "lesson" / "lesson-a.md").read_text(encoding="utf-8") == before)


# ── 도메인 무관 입증: ticket-style config (D-KC-15) ──
def t_domain_neutral(tmp):
    print("[12] 도메인 무관 — ticket config로 anchor·refs 동작(코어 feature 하드코딩 부재 입증)")
    cd, config = setup_vault(tmp)
    config = dict(config)
    config["pageTypes"] = ["note"]
    config["refs"] = {"pattern": r"^ticket:(\d+)$", "dir": "tickets", "idPattern": r"^(\d+)",
                      "anchor": {"pattern": r"(?i)ticket[\s:#_-]*(\d+)", "prefix": "ticket"}}
    # anchor: "Ticket 77" → ticket-77 (feature 아님)
    src = Path(tmp) / "specs" / "tk.md"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("## Ticket 77 login bug\n본문\n", encoding="utf-8")
    u = ing.source_units("specs/tk.md", cd, anchor_cfg=config["refs"]["anchor"])
    check("ticket anchor 생성", u[0]["anchor"] == "ticket-77")
    # refs: ticket:077 → tickets/077 부재 시 drift 1
    page = ("---\nslug: n-x\ntype: note\ntitle: login note\n"
            "tags: [auth]\nprovenance: [file:specs%2Ftk.md%23ticket-77@a1b2c3d4e5f6]\n"
            "refs: [ticket:077]\nupdated: 2026-05-31\n---\n본문")
    pf = Path(tmp) / "n.md"
    pf.write_text(page, encoding="utf-8")
    ing.write_page(str(pf), cd, config)
    drift = [f for f in lint.lint(cd, config) if f.code == "refs-drift"]
    check("ticket refs drift 탐지(dir 부재)", len(drift) == 1)
    (Path(tmp) / "specs" / "tickets" / "077-login").mkdir(parents=True, exist_ok=True)
    drift2 = [f for f in lint.lint(cd, config) if f.code == "refs-drift"]
    check("ticket refs 유효 통과", len(drift2) == 0)


# ── 협업게이트: handoff draft → approve 전이 ──
def t_handoff_approve(tmp):
    print("[14] handoff draft → approve 승인 전이")
    cd, config = setup_vault(tmp)
    ing.append_log(cd, "ingest", "seed → pages/")  # 활동 1건
    handoff.handoff(cd, config)
    ss = cd / "sessions" / "session-state.md"
    fm, _ = r.parse_frontmatter(ss.read_text(encoding="utf-8"))
    check("draft 생성(status:draft·needs_review)", fm.get("status") == "draft" and fm.get("needs_review") is True)
    # 승인 전이
    errs = handoff.approve(cd, "session-state.md")
    check("approve 성공", errs == [])
    fm2, _ = r.parse_frontmatter(ss.read_text(encoding="utf-8"))
    check("status draft→approved", fm2.get("status") == "approved")
    check("needs_review→false", fm2.get("needs_review") is False)
    check("approve log append", "handoff-approve" in (cd / "log.md").read_text(encoding="utf-8"))
    # 이중 승인 거부(이미 approved)
    check("non-draft 승인 거부", handoff.approve(cd, "session-state.md") != [])
    # 부재 draft 거부
    check("부재 draft 거부", handoff.approve(cd, "nope.md") != [])


# ── config 정규식 검증 (KC-Fn-G2b-2) ──
def t_validate_config():
    print("[13] validate_config 정규식 사전검증")
    r.validate_config({"refs": {"pattern": r"^feature:(\d{3})$", "idPattern": r"^(\d{3})",
                                "anchor": {"pattern": r"(?i)feature[\s:#_-]*(\d{3})", "prefix": "feature"}}})
    check("유효 패턴 통과(예외 없음)", True)
    check("refs 부재 무검증", r.validate_config({}) is None)
    bad = False
    try:
        r.validate_config({"refs": {"pattern": "^feature:(\\d{3}", "idPattern": "^(\\d{3})"}})  # 닫힘 괄호 누락
    except ValueError as e:
        bad = "refs.pattern" in str(e)
    check("무효 패턴 friendly error", bad)
    bad2 = False
    try:
        r.validate_config({"refs": {"pattern": "^x$", "idPattern": "[", "anchor": {"pattern": "y"}}})
    except ValueError as e:
        bad2 = "refs.idPattern" in str(e)
    check("무효 idPattern 키 식별", bad2)


# ── legacy config 키 경고 (G2b-1 v1→v2 breaking rename) ──
def t_legacy_keys():
    print("[13b] legacy config 키 경고(kitSpecs·lessonsSource → v2)")
    new_cfg = {"paths": {"refsScope": "specs", "defaultIngestSource": "specs/lessons.md"}}
    check("신키 경고 없음", r.legacy_key_warnings(new_cfg) == [])
    old_cfg = {"paths": {"kitSpecs": "specs", "lessonsSource": "specs/lessons.md"}}
    warns = r.legacy_key_warnings(old_cfg)
    check("구키 2건 경고", len(warns) == 2)
    check("kitSpecs→refsScope 안내", any("kitSpecs" in w and "refsScope" in w for w in warns))
    check("lessonsSource→defaultIngestSource 안내",
          any("lessonsSource" in w and "defaultIngestSource" in w for w in warns))
    check("paths 부재 무경고", r.legacy_key_warnings({}) == [])


def main():
    t_frontmatter()
    t_normalize()
    t_anchor()
    t_dedup()
    t_bm25()
    t_locator()
    with tempfile.TemporaryDirectory() as tmp:
        t_nudge_clear(tmp)
    with tempfile.TemporaryDirectory() as tmp:
        t_nudge_collect(tmp)
    with tempfile.TemporaryDirectory() as tmp:
        t_nudge_suppress(tmp)
    with tempfile.TemporaryDirectory() as tmp:
        t_nudge_branches(tmp)
    with tempfile.TemporaryDirectory() as tmp:
        t_nudge_persession(tmp)
    with tempfile.TemporaryDirectory() as tmp:
        t_nudge_cadence(tmp)
    with tempfile.TemporaryDirectory() as tmp:
        t_turn_count(tmp)
    t_extractor()
    t_codex_transcript_scan()
    with tempfile.TemporaryDirectory() as tmp:
        t_codex_turn_count(tmp)
    with tempfile.TemporaryDirectory() as tmp:
        t_ingest_query_lint(tmp)
    with tempfile.TemporaryDirectory() as tmp:
        t_log_turn_tag(tmp)
    with tempfile.TemporaryDirectory() as tmp:
        t_page_turn_fm(tmp)
    with tempfile.TemporaryDirectory() as tmp:
        t_ingest_reverse_lookup(tmp)
    with tempfile.TemporaryDirectory() as tmp:
        t_capture_session_source(tmp)
    with tempfile.TemporaryDirectory() as tmp:
        t_source_split(tmp)
    with tempfile.TemporaryDirectory() as tmp:
        t_reconcile(tmp)
    with tempfile.TemporaryDirectory() as tmp:
        t_reconcile_move(tmp)
    with tempfile.TemporaryDirectory() as tmp:
        t_domain_neutral(tmp)
    with tempfile.TemporaryDirectory() as tmp:
        t_handoff_approve(tmp)
    t_validate_config()
    t_legacy_keys()
    print(f"\n=== {PASS} passed, {FAIL} failed ===")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
