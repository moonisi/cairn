# Cairn

런타임·도메인 무관 **연속성/지식축적 코어**. 세션이 끊겨도 맥락이 이어지고, 작업 중 본
외부 지식이 흩어지지 않게 모아두는 plugin. 저장소는 **markdown + git뿐**(zero 외부 의존).

> 🌐 **English**: [README.en.md](README.en.md) · [Getting Started](GETTING-STARTED.en.md)
> 처음이라면 [안내서.md](안내서.md)부터 읽으세요 — 개념과 설치를 단계별로 풀어 씁니다.

---

## 무엇을 하나

세 가지 자동 동작 + 한 가지 수동 동작으로 구성됩니다.

| 시점 | 동작 | 무엇을 |
|---|---|---|
| 세션 시작 (SessionStart) | **핫컨텍스트 주입** | 직전 세션의 `hot.md`·`session-state`를 대화 첫머리에 다시 띄움 → 끊긴 맥락 복원. |
| 웹 도구 사용 후 (PostToolUse) | **nudge 후보 수집** | `WebFetch`/`WebSearch`로 본 외부 지식을 "흡수 후보"로 조용히 큐에 적재(무음, write 안 함). |
| 세션 종료 (Stop) | **handoff draft** | 이번 세션 활동을 다음 세션용 `session-state` + `hot.md` 초안으로 정리. |
| 사용자 호출 | **`/cairn:setup` skill** | 소비자 프로젝트에 Vault(`.cairn/`) + `cairn.config.json`을 HITL로 부트스트랩(최초 1회). |
| 사용자 호출 | **`/cairn:ingest` skill** | 큐에 쌓인 후보를 사용자 승인(HITL) 후 Vault page로 흡수. 자동 write 없음. |
| 사용자 호출 | **`/cairn:capture` skill** | *현재 대화*의 결정·합의·교훈을 사용자 승인(HITL) 후 Vault page로 흡수. 대화 자체가 출처 — nudge 큐 무관. |

**핵심 원칙**: 자동으로 기록을 *쌓지* 않는다. 자동은 "후보 제안"까지만, 실제 page write는
항상 사람이 승인. (이른바 자동 영구 ingest는 의도적으로 제외.)

---

## 구조

```
cairn/
├── .claude-plugin/plugin.json   # Claude 매니페스트(hooks 필드 없음)
├── .codex-plugin/plugin.json    # Codex 매니페스트(skill·문서·보조 산출물, hooks 필드 없음)
├── adapters/codex/hooks.json.example # Codex repo-local .codex/hooks.json adapter 템플릿
├── hooks/
│   ├── hooks.json               # Claude 직접 설치 호환 copy
│   ├── claude/hooks.json        # Claude 배선 source of truth
│   └── *.sh, *.py               # hook 스크립트 (런타임 공유, 무수정)
├── core/                        # 런타임·도메인 무관 코어 6 모듈 + self-test
│   └── *.py                     # zero-dep (Python stdlib만)
└── skills/
    ├── setup/SKILL.md           # /cairn:setup skill (Vault 부트스트랩)
    ├── ingest/SKILL.md          # /cairn:ingest skill (후보 흡수)
    └── capture/SKILL.md         # /cairn:capture skill (대화 결론 흡수)
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
claude plugin details cairn@cairn   # 설치 검증(Skills 3·Hooks 3 확인)
```

설치하면 `hooks/hooks.json`의 hook 3종이 자동 배선되고 `/cairn:setup`·`/cairn:ingest`·`/cairn:capture` skill이 등록됩니다.
(표준 `hooks/hooks.json`은 **자동 로드**되므로 plugin.json에 `hooks` 필드를 두지 **않습니다** —
중복 선언 시 hook 로드가 실패합니다.) hook은 대화형 세션에서 최초 신뢰(trust) 확인을 받습니다.

> 단일 plugin만 빠르게 시험하려면 marketplace 없이: `claude --plugin-dir ~/projects/cairn`.

### 방법 B — standalone (`.claude/` 직접 배선)

plugin 시스템 대신 hook을 직접 배선하려는 경우의 대안. 프로젝트 `.claude/settings.json`에
hook을 직접 등록하고 스크립트 경로를 절대경로로 지정하세요. (자세한 양식은 [안내서.md](안내서.md))

> 주의: 이 방법은 `allowManagedHooksOnly` managed 정책의 **차단을 우회하지 못합니다**(user/project
> hook도 차단됨). 자세한 내용은 아래 "⚠️ managed policy 환경 주의" 참고.

---

## 업데이트

새 버전을 받으려면 marketplace 갱신 후 plugin을 업데이트합니다.

```bash
/plugin marketplace update cairn   # repo 최신 커밋 당겨오기
/plugin update cairn@cairn         # 설치본 갱신
```

CLI(headless):

```bash
claude plugin marketplace update cairn
claude plugin update cairn@cairn
claude plugin details cairn@cairn   # 갱신 확인(Skills 3·Hooks 3)
```

> 🔴 **캐시 주의**: skill 개명·삭제처럼 **파일 경로가 바뀌는 변경**은 plugin 캐시
> (`~/.claude/plugins/cache/cairn/...`)에 구버전이 남아 신구가 섞일 수 있습니다. 명령이 옛
> 이름으로 잡히면 `/plugin uninstall cairn@cairn` 후 재설치하거나 캐시 디렉토리를 지우세요.
> (예: `/cairn:init` → `/cairn:setup` 개명 시.)

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
설치 후 **`/cairn:setup`**를 한 번 실행하면 이 config를 HITL로 부트스트랩합니다(맨손 작성 불필요).
config가 없으면 hook은 발동해도 handoff draft를 만들지 않으니, 최초 1회 setup이 필요합니다.

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

Codex에서는 Cairn을 두 부분으로 씁니다.

1. Codex plugin은 `/cairn:setup`, `/cairn:ingest`, `/cairn:capture` skill을 제공합니다.
2. 세션 hook은 Cairn을 쓸 프로젝트마다 repo-local `.codex/hooks.json` adapter로 따로 설치합니다.

plugin 자체가 hook을 자동 등록하지는 않습니다. skill은 한 번 설치하고, 세션 연속성이 필요한
프로젝트에만 hook을 명시적으로 켜는 구조입니다.

### Codex plugin 설치

Cairn을 내려받고 로컬 Codex marketplace로 등록합니다.

```bash
git clone https://github.com/moonisi/cairn.git ~/cairn
cd ~/cairn
codex plugin marketplace add "$(pwd)"
codex plugin add cairn@cairn
codex plugin list
```

`codex plugin list`에서 `cairn@cairn`이 `installed, enabled`로 보이면 설치된 것입니다. 설치
후에는 새 Codex 세션을 열어야 새 skill 목록이 반영됩니다. 새 세션에서 아래 skill을 호출할 수
있어야 합니다.

- `/cairn:setup`
- `/cairn:ingest`
- `/cairn:capture`

### 프로젝트에 hook 켜기

Cairn으로 세션 맥락을 이어갈 프로젝트 루트에서 실행합니다.

```bash
CAIRN_ROOT="$HOME/cairn"
mkdir -p .codex
cp "$CAIRN_ROOT/adapters/codex/hooks.json.example" .codex/hooks.json
CAIRN_ROOT_ABS="$(cd "$CAIRN_ROOT" && pwd)"
sed -i "s#<CAIRN_ROOT_ABS>#$CAIRN_ROOT_ABS#g" .codex/hooks.json
```

- `CAIRN_DIR`은 기본적으로 소비자 repo의 `$(pwd)/.cairn`를 가리킵니다(override 가능).
- Codex에서 `/hooks`를 열어 `SessionStart`와 `Stop` hook을 검토하고 trust하세요.
- 프로젝트에서 `/cairn:setup`을 한 번 실행해 `.cairn/cairn.config.json`을 만드세요.

첫 세션에는 아직 보여줄 내용이 없을 수 있습니다. Codex 응답이 한 번 끝나면 Stop hook이
`.cairn/sessions/` 아래에 handoff draft를 만들고, 다음 세션에서 그 내용을 다시 읽습니다.

Codex hook은 repo-local adapter로 설치합니다. adapter는 `SessionStart`와 `Stop`을 사용하며,
웹 후보는 Stop 시점 transcript scan으로 수집합니다(`cairn-stop-codex.sh`).

---

## 검증 (self-check)

포팅·수정 후 zero-dep 무결성을 확인하려면:

```bash
python3 core/_selftest.py                       # 코어 6 모듈 회귀 (195 케이스)
python3 hooks/_selftest_codex_transcript_scan.py # Codex scanner 회귀
```

외부 의존·네트워크 없이 도는 결정적 테스트입니다.

### 라이브 hook 확인 (설치 후)

```bash
# 새 세션 → 웹 fetch 1회 → 응답 종료(Stop) → 확인
ls .cairn/sessions/   # hot.md · session-state.md · nudge-metrics.md 출현 = 정상
```

SessionStart hook은 **읽기 전용**이라 직전 세션 산출물이 없으면 무음입니다. 산출물 생성 주체는
Stop hook이므로, 첫 세션은 응답을 한 번 끝내기 전까지 `sessions/`가 비어 있는 것이 정상입니다
(세션을 막 열고 `ls` 하면 비어 있다고 해서 hook 미발동이 아닙니다).

---

## 라이선스

MIT — [LICENSE](LICENSE).
