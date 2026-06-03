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
│   ├── hooks.json               # 표준 hook 위치(원본 repo는 Claude 직접 설치용)
│   ├── hooks.codex.json         # Codex legacy 배선 파일(PLUGIN_ROOT 기반)
│   ├── claude/hooks.json        # Claude 배선 source of truth
│   ├── codex/hooks.json         # Codex 배선 source of truth
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
/plugin marketplace add <이 repo 경로 또는 git URL>

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

## Codex (Gate D-1 B안)

Codex는 hook 표면이 다릅니다 — SessionStart·Stop 2종만 쓰고 PostToolUse 대신 Stop 시점
transcript scan으로 웹 후보를 잡습니다(`cairn-stop-codex.sh`). hook 스크립트 본체는 Claude와
**공유**하되 배선 파일은 런타임별로 분리합니다.

- `hooks/claude/hooks.json`: Claude 배선 source of truth.
- `hooks/codex/hooks.json`: Codex 배선 source of truth(`PLUGIN_ROOT` + session cwd 기반).
- `hooks/hooks.json`: 설치/패키징 표준 위치. 원본 repo에서는 Claude 직접 설치 호환을 위해 Claude 배선을 유지합니다.

Codex plugin validation은 `.codex-plugin/plugin.json`의 `hooks` 필드를 거부하므로, Codex 산출물은
manifest override 없이 기본 `hooks/hooks.json` 위치를 사용합니다. 런타임별 산출물은 zero-dep
패키징 스크립트로 만듭니다.

```bash
# Codex 산출물
scripts/package-plugin codex /tmp/cairn-codex-plugin

# Claude 산출물
scripts/package-plugin claude /tmp/cairn-claude-plugin
```

Codex local marketplace 실측에서는 validator 통과와 plugin add/cache 설치까지 확인했습니다. 다만
`codex exec --dangerously-bypass-hook-trust`에서 기본 `hooks/hooks.json` lifecycle 발동 증거는 아직
확보하지 못했습니다. Codex에서 plugin hook이 계속 미발동하면 fallback은 repo-local `.codex/hooks.json`
adapter(C안)입니다.

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
