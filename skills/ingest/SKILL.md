---
name: ingest
description: Cairn nudge-queue의 pending ingest 후보(WebFetch로 본 외부 지식)를 Vault page로 흡수한다. "/cairn:ingest", "nudge 후보 ingest", "대기 중인 ingest 후보 처리", "수집한 웹 지식 정리" 요청 시, 또는 SessionStart가 "ingest 후보 대기"를 노출한 뒤 사용자가 처리를 원할 때 사용. WebFetch 후보는 page로 ingest(turn 자동 연결), WebSearch 후보는 dismiss. 항상 사용자 승인(HITL) 후 기록 — 자동 write 금지.
---

당신은 **Cairn ingest 보조자**다. nudge-queue의 pending 후보를 사용자와 함께 Vault page로 흡수한다.

## 경계 (먼저 읽어라)

- **자동 write 금지(D-KC-13 #5)**: page 합성은 draft로 제시하고 **사용자 승인 후에만** 기록. 임의 ingest 금지.
- **turn은 손대지 마라**: `--turn` 직접 전달 금지. `--source-url`로 locator만 넘기면 Phase C가 turn을 자동 연결한다(코어 책임).
- **WebSearch는 ingest 대상 아님(정책 A)**: 검색은 출처가 아니다(실제 출처 = 이어서 fetch한 url). WebSearch 후보는 dismiss(`suppress`)하거나 사용자가 manual page로 직접 작성.

## 도구 경로

`CAIRN_DIR` 환경변수(소비자 Vault) + 코어 모듈 경로를 확인한다. plugin 설치 시 코어는 `${CLAUDE_PLUGIN_ROOT}/core`. 아래 `python3` 호출은 `PYTHONPATH=<core>` 로 실행(`<core>` = plugin-root/core).

## 절차

### 1. pending 후보 조회
```
PYTHONPATH=<core> python3 <core>/cairn_nudge.py pending
```
JSON 리스트 반환: 각 `{ts, tool, ref, locator, qhash, turn}`.
- `tool == "WebFetch"` → **ingest 후보**.
- `tool == "WebSearch"` → **dismiss 후보**(아래 4).
- 0건이면 "대기 중 후보 없음" 안내 후 종료.

### 2. 사용자에게 제시 + 선택
후보를 표로 보여준다(ref · tool · turn). **1건씩 처리 권장**(일괄은 합성 품질 저하). 사용자가 처리할 후보를 고르게 한다.

### 3. WebFetch 후보 → page 흡수
선택된 후보 1건에 대해:

a. **지식 합성**: 해당 ref/locator에서 본 내용을 page 본문으로 합성한다. 현재 대화에 그 내용이 없으면 사용자에게 요지를 요청하거나 재-fetch를 제안한다(없는 내용을 지어내지 말 것).

b. **draft page.md 작성**(frontmatter + 본문). 필수 필드:
   - `slug`(kebab-case 고유), `type`(config.pageTypes 중 하나), `title`.
   - `tags`(선택), `status`, `updated`(YYYY-MM-DD).
   - **provenance는 비워둔다** — `--source-url`이 자동 민팅한다.
```
---
slug: <kebab-slug>
type: <pageType>
title: <제목>
tags: [<태그>]
status: approved
updated: <YYYY-MM-DD>
---
## <섹션>
<합성한 지식 본문>
```

c. **사용자 승인(HITL)**: draft 전문을 보여주고 승인받는다. 수정 요청 반영. **승인 전 write 금지.**

d. **기록**(승인 후): `locator`를 `--source-url`로 전달.
```
PYTHONPATH=<core> python3 <core>/cairn_ingest.py write <draft.md> --source-url "<후보 locator>"
```
- `--source-url`이 `url:<quote(locator)>@<body hash>` provenance를 민팅 → validate → **Phase C가 queue 역조회로 turn 자동 주입 + queue ingested 전환**.
- 출력 `OK` = 성공. `INVALID: …` = frontmatter 오류 수정 후 재시도.

e. **확인**: 결과 page frontmatter에 `turn`이 박혔는지, queue 해당 후보가 `ingested`로 빠졌는지 확인(`pending` 재조회 시 사라짐).

### 4. WebSearch 후보 → dismiss
검색 후보는 ingest하지 않는다. 사용자에게 dismiss 의사 확인 후:
```
PYTHONPATH=<core> python3 <core>/cairn_nudge.py suppress <qhash> [<qhash>...]
```
`suppressed` 전환 → 재제안 차단, `clear`가 purge. (검색 스니펫에서만 얻은 지식을 꼭 남기려면 사용자가 manual page로 직접 작성.)

## 한계

- 지식 본문은 사용자/대화 맥락에 의존(fetch 콘텐츠 자동 저장 없음). 없으면 재-fetch 또는 사용자 입력.
- turn 자동 연결은 WebFetch + url provenance 경로만(Phase C). WebSearch 미지원(정책 A).
- 기록은 항상 `cairn_ingest write` 단일 경로 경유(audit trail).
