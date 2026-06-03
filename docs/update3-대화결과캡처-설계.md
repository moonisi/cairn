# update3 — 대화/세션 결과물 캡처 경로 설계

> 상태: **설계 확정 · 구현 후속**. 작성 2026-06-03.
> 트리거: "WebFetch/WebSearch 외부 지식만 nudge 큐에 적재하나? 대화 토론 결과물도 적재하기로 하지 않았나?" 질의.

## 0. 요약

🔵 자동 nudge 큐는 **외부 도구(WebFetch/WebSearch/Skill)만** 캡처한다. 대화/토론 결과물은 적재하지 않으며, 적재하도록 설계된 적도 없다(트리거 협소 = 의도). 대화 결론을 Vault page로 흡수하는 **명시적 HITL 경로가 비어 있다** — 이 갭을 수동 capture skill로 메운다(자동화 아님).

## 1. 현 메커니즘 실측

| 경로 | 대상 | 기제 | 대화 결과 캡처? |
|---|---|---|---|
| **nudge 큐** | 외부 지식 | `cairn_nudge.collect()` = PostToolUse payload(WebFetch/WebSearch)만 | 🔴 구조적 불가 |
| **handoff** | 세션 연속성 | Stop hook → `session-state.md`·`hot.md` **골격만** 생성(log.md 최근 20줄 + 플레이스홀더) | 🟡 골격뿐, 영속 page 아님 |
| **ingest** | web 후보 → page | `/cairn:ingest` 수동 흡수 | 🔴 web 후보 전용 |

- 🔵 `log.md`엔 page write/reconcile/handoff **액션만** 기록 — 대화 turn·결정 자체는 안 들어감.
- 🔵 `decision`/`lesson` page를 대화 결론으로 직접 쓰는 진입점 **부재**(skill = setup·ingest 둘뿐).
- 🔵 트리거 확장(대화·결정 감지)은 **P4b 적중률 보고 후 유보** + 트리거 협소 원칙(오탐 > 누락, 마스터 §3.3 위험감소 #1).

**갭**: 사용자가 기억한 "토론 결과물 적재"는 자동 nudge로 설계된 적 없고, handoff는 핫컨텍스트용 골격일 뿐. 대화 결론 → 영속 decision/lesson page 경로가 비어 있음.

## 2. 권장 설계 — 수동 HITL `/cairn:capture` skill

대화/토론 결론을 사용자가 명시 시점에 `decision`/`lesson`/`note` page로 합성·흡수하는 수동 skill. `/cairn:ingest`와 동형(HITL, 단일 audit 경로).

절차:
1. LLM이 현 대화에서 결정/합의/교훈 요지를 page 본문으로 합성(없는 내용 생성 금지).
2. frontmatter provenance = `conversation:<session_turn>@<body hash>` (locator=turn, hash=본문).
3. **HITL**: draft 전문 제시 → 승인 후에만 `cairn_ingest.py write <draft> --turn <st>` 경유 기록.

### 실현 가능성 (코드 실측)
- 🔵 `write_page(page_md_path, cd, config, turn=None, source_url=None)` — `--turn` 직접 지원(우선순위 명시>역조회>None). (`core/cairn_ingest.py:266,388`)
- 🔵 `format_provenance(kind, locator, h)` — kind 임의 문자열 → `conversation:` 유효. (`core/cairn_root.py:212`)
- 🔵 `validate_page`는 provenance 1+ 요구 — frontmatter 자체 명시로 통과. (`cairn_ingest.py:142`)

### 코어 touch (단일 결정 포인트)
conversation provenance 민팅을 (a) skill이 frontmatter에 직접 작성 vs (b) `write_page`에 `--session-source` 플래그 추가(`--source-url` 미러, `conversation:<turn>@content_hash(body)` 결정적 민팅). → **(b) 권장**(--source-url과 대칭, 민팅 결정적, skill 단순화).

### 경계 준수
- 🔵 자동 트리거 **없음** — 수동 invoke만. P4b 유보·트리거 협소 원칙과 **무충돌**(nudge 트리거 확장 아님).
- 🔵 HITL·zero-dep·markdown+git 정합. 기존 `write_page`/`format_provenance` 재사용.

## 3. 기각 대안

- **안 2 — nudge 트리거를 대화/결정 자동 감지로 확장**: 🔴 §3.3 트리거 협소 정면 위반, P4b 유보, "결정 도달" 감지 = LLM 휴리스틱 오탐 다발. **기각**.
- **안 3 — Stop hook handoff 본문 자동 합성**: hook = command hook(D-KC-08)·대화 미접근(stdin transcript 미수집)·LLM 호출 불가 → 본문 합성은 결국 skill 필요. 안 1로 수렴. **부분 기각**(handoff는 연속성 용도 유지).

## 4. 구현 범위 (후속)

- `skills/capture/SKILL.md` 신규(setup·ingest 패턴 동형).
- (선택) `cairn_ingest.py` `--session-source` 플래그 + `_selftest.py` 케이스 추가.
- README·안내서·영문판에 skill 3종 반영.
- 신규 skill = 기존 소비자 surface 패턴 내 → 별도 D-KC 채번 불요로 판단. 단 conversation provenance kind는 코어 계약 추가 → 구현 전 사용자 승인.

## 반대 관점·반례

- 🟡 **"수동이라 결국 안 쓴다"**: 자동 nudge가 망각을 막는 것처럼, 대화 결정도 수동이면 흡수율이 낮을 수 있음. → 보완책으로 Stop hook handoff가 "이번 세션 결정 N건 — capture?" 경계 nudge를 *제안*하게 할 수 있으나, 결정 감지가 어려워 오탐 위험. 1차는 순수 수동으로 두고 적중률 관측 후 판단.
- 🟡 **decision vs lesson 경계 모호**: 대화 결론이 "결정"인지 "교훈"인지 사용자 판단 필요 — capture skill이 type을 묻는 HITL 단계로 흡수. 단 lesson은 KC-Fn-24 source-ingest(compound-learner) 경로와 출처가 겹칠 수 있어, capture lesson은 provenance kind를 `conversation`으로 명확히 구분해야 이중화 방지.
