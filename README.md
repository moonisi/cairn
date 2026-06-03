# Cairn

런타임·도메인 무관 **연속성/지식축적 코어**. 세션이 끊겨도 맥락이 이어지고, 작업 중 본
외부 지식이 흩어지지 않게 모아두는 plugin. 저장소는 **markdown + git뿐**(zero 외부 의존).

> 처음이라면 [안내서.md](안내서.md)부터 읽으세요 — 개념과 설치를 단계별로 풀어 씁니다.

---

## 무엇을 하나

세 가지 자동 동작 + 한 가지 수동 동작으로 구성됩니다.

| 시점 | 동작 | 무엇을 |
|---|---|---|
| 세션 시작 (SessionStart) | **핫컨텍스트 주입** | 직전 세션의 `hot.md`·`session-state`를 대화 첫머리에 다시 띄움 → 끊긴 맥락 복원. |
| 웹 도구 사용 후 (PostToolUse) | **nudge 후보 수집** | `WebFetch`/`WebSearch`로 본 외부 지식을 "흡수 후보"로 조용히 큐에 적재(무음, write 안 함). |
| 세션 종료 (Stop) | **handoff draft** | 이번 세션 활동을 다음 세션용 `session-state` + `hot.md` 초안으로 정리. |
| 사용자 호출 | **`/cairn:ingest` skill** | 큐에 쌓인 후보를 사용자 승인(HITL) 후 Vault page로 흡수. 자동 write 없음. |

**핵심 원칙**: 자동으로 기록을 *쌓지* 않는다. 자동은 "후보 제안"까지만, 실제 page write는
항상 사람이 승인. (이른바 자동 영구 ingest는 의도적으로 제외.)

---

## 구조

```
cairn/
├── .claude-plugin/plugin.json   # Claude 매니페스트
├── .codex-plugin/plugin.json    # Codex 매니페스트 (🟡 초안 — 아래 "Codex" 참고)
├── hooks/
│   ├── hooks.json               # Claude hook 배선 (SessionStart/PostToolUse/Stop)
│   ├── hooks.codex.json         # Codex hook 배선 (🟡 초안)
│   └── *.sh, *.py               # hook 스크립트 (런타임 공유, 무수정)
├── core/                        # 런타임·도메인 무관 코어 6 모듈 + self-test
│   └── *.py                     # zero-dep (Python stdlib만)
└── skills/ingest/SKILL.md       # /cairn:ingest skill
```

코어 6 모듈: `cairn_root`(경로·frontmatter·hash) · `cairn_ingest`(흡수) ·
`cairn_nudge`(후보 큐) · `cairn_query`(검색) · `cairn_lint`(린트) · `cairn_handoff`(세션 인계).
전부 외부 패키지 없이 Python 표준 라이브러리만 씀.

---

## 설치 (Claude Code)

### 방법 A — plugin marketplace (권장)

```bash
# 1) 이 repo를 marketplace로 추가
/plugin marketplace add <이 repo 경로 또는 git URL>

# 2) cairn 설치
/plugin install cairn
```

설치하면 `hooks/hooks.json`의 hook 3종이 자동 배선되고 `/cairn:ingest` skill이 등록됩니다.
hook은 최초 1회 신뢰(trust) 확인을 받습니다.

### 방법 B — standalone (`.claude/` 직접 배선)

managed policy 환경 등 plugin hook이 막힌 경우의 fallback. 프로젝트 `.claude/settings.json`에
hook을 직접 등록하고 스크립트 경로를 절대경로로 지정하세요. (자세한 양식은 [안내서.md](안내서.md))

---

## Vault 위치 — `CAIRN_DIR`

기록물(Vault)은 **plugin이 아니라 소비자 프로젝트가 소유**합니다(D-KC-05). 기본값:

```
CAIRN_DIR = ${CLAUDE_PROJECT_DIR}/.cairn
```

즉 프로젝트 루트의 `.cairn/` 폴더가 Vault입니다. 다른 위치를 쓰려면 hook 배선의 `CAIRN_DIR`을
override 하세요. Vault 자체(pages·sessions·config)는 plugin에 동봉되지 않으며, 소비자
repo에 markdown+git으로 남습니다.

`.cairn/cairn.config.json`이 page 타입·refs 범위·nudge 파라미터를 정의합니다(소비자가 생성).

---

## ⚠️ managed policy 환경 주의

🔴 **확인 불가 (실측 대기)**: 공식문서(2026-06-02 기준)에 `allowManagedHooksOnly`라는
*Managed-Only Setting*이 존재합니다. 동작은 미문서화이나, 엔터프라이즈 관리자가 이를 켜면
**plugin이 제공하는 hook이 차단될 수 있습니다.** (`disableAllHooks`는 user/project/plugin
hook을 동일하게 끕니다 — plugin만 차등하지 않음.)

→ managed policy 하에서 plugin hook이 막히면 위 **방법 B(standalone `.claude/`)**로 fallback
하세요. 실 환경 실측 전까지는 미확정 사항입니다.

---

## Codex (🟡 초안)

`.codex-plugin/plugin.json`·`hooks/hooks.codex.json`은 **placeholder**입니다.
Codex는 hook 표면이 다릅니다 — SessionStart·Stop 2종만 쓰고 PostToolUse 대신 Stop 시점
transcript scan으로 웹 후보를 잡습니다(`cairn-stop-codex.sh`). hook 스크립트 본체는 Claude와
**공유**하되 배선 파일만 분리했습니다(KC-Fn-63).

단, Codex의 plugin-root·project-dir 변수명이 미확정(`<codex-plugin-root>` 등 placeholder).
실제 변수 치환은 Codex 환경 실측(Gate D-1, D-KC-09) 후입니다. **치환 전에는 Codex 배선이
동작하지 않습니다.**

---

## 검증 (self-check)

포팅·수정 후 zero-dep 무결성을 확인하려면:

```bash
python3 core/_selftest.py                       # 코어 6 모듈 회귀 (195 케이스)
python3 hooks/_selftest_codex_transcript_scan.py # Codex scanner 회귀
```

외부 의존·네트워크 없이 도는 결정적 테스트입니다.

---

## 라이선스

MIT — [LICENSE](LICENSE).
