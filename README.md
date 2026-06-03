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
├── .claude-plugin/plugin.json   # Claude 매니페스트(hooks 필드 없음)
├── .codex-plugin/plugin.json    # Codex 매니페스트(skill·문서·보조 산출물, hooks 필드 없음)
├── adapters/codex/hooks.json.example # Codex repo-local .codex/hooks.json fallback 템플릿
├── hooks/
│   ├── hooks.json               # Claude 직접 설치 호환 copy
│   ├── claude/hooks.json        # Claude 배선 source of truth
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
# 1) 이 repo를 marketplace로 추가 (.claude-plugin/marketplace.json 동봉됨)
/plugin marketplace add https://github.com/moonisi/cairn.git

# 2) cairn 설치 — plugin@marketplace 형식
/plugin install cairn@cairn
```

CLI(headless)로도 동일:

```bash
claude plugin marketplace add ~/projects/cairn
claude plugin install cairn@cairn
claude plugin details cairn@cairn   # 설치 검증(Skills 1·Hooks 3 확인)
```

설치하면 `hooks/hooks.json`의 hook 3종이 자동 배선되고 `/cairn:ingest` skill이 등록됩니다.
(표준 `hooks/hooks.json`은 **자동 로드**되므로 plugin.json에 `hooks` 필드를 두지 **않습니다** —
중복 선언 시 hook 로드가 실패합니다.) hook은 대화형 세션에서 최초 신뢰(trust) 확인을 받습니다.

> 단일 plugin만 빠르게 시험하려면 marketplace 없이: `claude --plugin-dir ~/projects/cairn`.

### 방법 B — standalone (`.claude/` 직접 배선)

plugin 시스템 대신 hook을 직접 배선하려는 경우의 대안. 프로젝트 `.claude/settings.json`에
hook을 직접 등록하고 스크립트 경로를 절대경로로 지정하세요. (자세한 양식은 [안내서.md](안내서.md))

> 주의: 이 방법은 `allowManagedHooksOnly` managed 정책의 **차단을 우회하지 못합니다**(user/project
> hook도 차단됨). 자세한 내용은 아래 "⚠️ managed policy 환경 주의" 참고.

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

🔵 공식문서(`permissions.md` §Managed-only settings, 2026-06-02): 엔터프라이즈 관리자가
`allowManagedHooksOnly: true`를 설정하면 **managed hook · SDK hook · managed settings의
`enabledPlugins`에 force-enable된 plugin hook만** 로드되고, **user · project · 그 외 모든
plugin hook은 차단**됩니다.

→ 이 정책이 켜진 환경에서 Cairn hook을 쓰려면 **조직 관리자가 managed settings의
`enabledPlugins`에 `cairn@cairn`를 force-enable** 해야 합니다. **유일한 방법입니다.**

> ⚠️ standalone `.claude/`(방법 B) **fallback은 이 경우 무효**입니다 — user/project hook도
> 똑같이 차단되기 때문입니다. `allowManagedHooksOnly`가 *꺼진* 일반 환경에서는 plugin hook이
> 정상 동작합니다(실 설치로 실증). 방법 B는 plugin 시스템을 쓰지 않으려는 경우의 대안일 뿐,
> managed 차단 우회 수단이 아닙니다.

---

## Codex

🔵 현재 운영 기본값은 **C안 fallback**입니다.

Codex plugin은 skill·문서·보조 산출물로만 설치하고, hook은 소비자 repo의
repo-local `.codex/hooks.json` adapter로 별도 배치합니다. 이유는 Gate D-1 실측에서 Codex plugin이
validation·install·cache 복사까지는 통과했지만, 기본 `hooks/hooks.json`가 `codex exec` runtime
lifecycle hook source로 자동 등록되지 않았기 때문입니다(KC-Fn-70).

### 운영 fallback — repo-local `.codex/hooks.json`

1. `adapters/codex/hooks.json.example`를 소비자 repo의 `.codex/hooks.json`로 복사합니다.
2. `<CAIRN_ROOT_ABS>`를 이 Cairn repo의 절대경로로 치환합니다. 예: `/home/mooni/projects/cairn`.
3. `CAIRN_DIR`은 기본적으로 소비자 repo의 `$(pwd)/.cairn`를 가리킵니다.
4. 소비자 repo에 `.cairn/cairn.config.json`를 먼저 만듭니다. config가 없으면 hook은 발동해도
   handoff draft를 만들지 않습니다.

이 방식은 `${PLUGIN_ROOT}`에 의존하지 않습니다. hook script 내부는 `$0` 기준으로 `../core`를 찾아
`CAIRN_CORE` 없이 동작합니다.

### Codex plugin 설치 — hook 없음

`.codex-plugin/plugin.json`에는 `hooks` 필드가 없습니다. Codex plugin은 `/cairn:ingest` skill과
문서·보조 산출물을 배포하는 단위이며, SessionStart/Stop hook을 설치하거나 trust 항목을 만들지
않습니다. 이 분리는 KC-Fn-68/69/70을 회피하기 위한 C안 계약입니다.

Codex에서 hook까지 쓰려면 반드시 위의 repo-local `.codex/hooks.json` adapter를 별도로 설치하고,
Codex의 `/hooks` review 또는 `~/.codex/config.toml`의 `[hooks.state]` trust 기록을 확인하세요.

### Packaging

```bash
# Claude 산출물
scripts/package-plugin claude /tmp/cairn-claude-plugin
```

Codex plugin-bundled hook packaging은 운영 경로에서 제거했습니다. Codex hook 표면은 repo-local
adapter에서만 SessionStart·Stop 2종을 씁니다. PostToolUse는 쓰지 않고, Stop 시점 transcript scan으로
웹 후보를 잡습니다(`cairn-stop-codex.sh`).

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
