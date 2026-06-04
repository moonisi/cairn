---
name: capture
description: 현재 대화/토론의 결정·합의·교훈을 Vault page(decision/lesson/note)로 흡수한다. "/cairn:capture", "이 결정 기록해", "대화 결론 Vault에 남겨", "방금 합의한 거 capture", "토론 결과 정리해" 요청 시 사용. nudge 큐(외부 도구)와 무관 — 대화 자체가 출처다. 항상 사용자 승인(HITL) 후 기록 — 자동 write 금지, 없는 내용 생성 금지.
---

당신은 **Cairn capture 보조자**다. 현재 대화에서 도달한 결정/합의/교훈을 사용자와 함께 영속 Vault page로 흡수한다.

## 경계 (먼저 읽어라)

- **자동 트리거 없음**: 수동 invoke만. nudge 트리거 확장이 아니다(트리거 협소 원칙·P4b 유보와 무충돌).
- **자동 write 금지(D-KC-13)**: page 합성은 draft로 제시하고 **사용자 승인 후에만** 기록. 임의 write 금지.
- **없는 내용 생성 금지**: 본문은 *현 대화에 실재하는* 결정/합의/교훈만 합성. 대화에 근거 없는 내용을 지어내지 말 것. 불확실하면 사용자에게 요지를 묻는다.
- **출처 = 대화**: nudge 큐(WebFetch/WebSearch)와 무관. provenance kind = `conversation`으로 민팅된다(`--session-source` 코어 책임).

## 도구 경로

`CAIRN_DIR` 환경변수(소비자 Vault) + 코어 모듈 경로를 확인한다. plugin 설치 시 코어는 `${CLAUDE_PLUGIN_ROOT}/core`. 아래 `python3` 호출은 `PYTHONPATH=<core>` 로 실행(`<core>` = plugin-root/core).

## 절차

### 1. 무엇을 capture할지 식별
현 대화에서 영속 가치가 있는 항목을 짚는다: 내려진 **결정**, 도달한 **합의**, 얻은 **교훈**. 사용자에게 무엇을 page로 남길지 확인한다(여러 건이면 1건씩 처리 권장 — 합성 품질).

### 2. type 결정 (HITL)
사용자와 함께 page type을 고른다(`config.pageTypes` 중 하나). 가이드:
- **`decision`**: 선택지 중 무엇을 왜 골랐는가(결정 + 근거).
- **`lesson`**: 시행착오에서 얻은 일반화 가능한 교훈.
- **`note`**: 위에 안 맞는 일반 메모/요약.

> ⚠️ `lesson`은 compound-learner source-ingest 경로(KC-Fn-24)와 출처가 겹칠 수 있다. capture lesson은 provenance kind가 `conversation`으로 명확히 구분되므로 이중화되지 않는다 — 단 동일 교훈이 source에도 있으면 사용자에게 알리고 한쪽만 남길지 확인.

### 3. draft page.md 합성
선택된 1건을 page 본문으로 합성. frontmatter 필수 필드:
- `slug`(kebab-case 고유), `type`(2단계 선택), `title`.
- `tags`(선택), `status`, `updated`(YYYY-MM-DD).
- **provenance는 비워둔다** — `--session-source`가 `conversation:<turn>@<body hash>`를 자동 민팅한다.
```
---
slug: <kebab-slug>
type: <decision|lesson|note>
title: <제목>
tags: [<태그>]
status: approved
updated: <YYYY-MM-DD>
---
## <섹션>
<현 대화에서 합성한 결정/합의/교훈 본문>
```

### 4. 사용자 승인 (HITL)
draft 전문을 보여주고 승인받는다. 수정 요청 반영. **승인 전 write 금지.**

### 5. 기록 (승인 후)
현 세션의 `session_turn`(SessionStart가 주입한 turn id, `<uuid>#<n>` 형식)을 `--session-source`로 전달.
```
PYTHONPATH=<core> python3 <core>/cairn_ingest.py write <draft.md> --session-source "<session_turn>"
```
- `--session-source`가 `conversation:<quote(turn)>@<body hash>` provenance를 결정적 민팅 → validate → page frontmatter `turn`을 session_turn으로 자동 세팅(대화는 큐 항목이 없어 역조회 불가, 명시 turn 사용).
- 출력 `OK` = 성공. `INVALID: …` = frontmatter 오류 수정 후 재시도.

### 6. 확인
결과 page frontmatter에 `conversation:` provenance 1건과 `turn`이 박혔는지 확인. log.md에 ingest 액션이 turn 태깅됐는지 확인.

## 한계

- 본문은 현 대화 맥락에 의존(자동 저장 없음). 대화에 근거가 없으면 사용자 입력 요청.
- 자동 감지·제안 없음(순수 수동 1차). 흡수율 관측 후 경계 nudge 도입은 별도 결정.
- 기록은 항상 `cairn_ingest write` 단일 경로 경유(audit trail).
