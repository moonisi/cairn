# Cairn Gate D-1 Codex C안 적용 결과

> 작성일: 2026-06-03 KST
> 대상: `~/projects/cairn`
> 성격: Gate D-1 C안 확정안의 repo 반영. C안 판정 재실측은 아니며, 반영 후 adapter 동작 검증만 포함

## 목적

Codex Gate D-1 차단 해소안 중 C안을 `cairn` repo에 반영했다. Codex plugin은 skill·문서·보조 산출물 단위로 강등하고, Codex hook 운영은 repo-local `.codex/hooks.json` adapter로 단일화한다.

## 사전 게이트

- 🔵 확실: `docs/Cairn-Gate-D1-Codex-실측결과.md` 기준, Codex plugin-bundled hook은 KC-Fn-68/69/70으로 차단 판정됐다.
- 🔵 확실: `docs/Cairn-Gate-D1-차단해소안-비교.md` §C안과 §권고는 `plugin = skill/문서/보조 산출물`, `hook = repo-local .codex/hooks.json adapter` 분리를 권고한다.
- 🔵 확실: `docs/Cairn-배포경로-결정.md` §6.1은 D-1 fallback으로 Codex plugin-bundled hook을 1급 배포 경로에서 보류한다.
- 🔵 확실: 현재 `.codex-plugin/plugin.json`에는 `hooks` 필드가 없고, `interface.defaultPrompt`와 `interface.capabilities`를 포함한다.

## 차단 조건

- 🔵 확실: `.codex-plugin/plugin.json`에 `hooks` 필드를 다시 넣지 않았다. KC-Fn-68 회피 조건을 유지한다.
- 🔵 확실: Codex plugin-bundled hook source였던 `hooks/codex/hooks.json`를 제거했다. 운영 source는 `adapters/codex/hooks.json.example`뿐이다.
- 🔵 확실: `scripts/package-plugin codex <out>` 경로를 제거했다. Codex plugin hook packaging은 운영 절차가 아니다.
- 🔵 확실: fresh repo 적용 검증은 repo-local `.codex/hooks.json` adapter 설치 후 `codex exec`로 수행했다. 이는 C안 판정을 새로 내리는 실측이 아니라, 확정안 반영 후 설치 절차가 재현되는지 확인한 것이다.

현재 적용 작업 기준의 신규 차단은 없다. 단, 배포 목표가 "Codex plugin 설치만으로 hook까지 포함"이라면 C안 자체가 실패 조건이다.

## 핵심 위험

- 🔴 높음: Codex와 Claude의 배포 parity가 깨진다. Claude는 plugin hook을 사용하고, Codex는 repo-local hook adapter를 별도로 설치한다.
- 🟡 중간: Codex 사용자는 plugin 설치와 hook adapter 설치/trust를 분리해서 수행해야 한다.
- 🟡 중간: `<CAIRN_ROOT_ABS>`는 설치자가 Cairn repo 절대경로로 치환해야 한다. plugin-root/project-dir 변수 표면은 미확정 상태로 운영 계약에 쓰지 않는다.
- 🟢 낮음: `core/`와 hook script 본체는 수정하지 않았으므로 런타임 공유 로직의 회귀 위험은 낮다.

## 다음 단계

1. Codex 소비자 repo에서 `adapters/codex/hooks.json.example`를 `.codex/hooks.json`로 복사한다.
2. `<CAIRN_ROOT_ABS>`를 Cairn repo 절대경로로 치환한다.
3. `.cairn/cairn.config.json`를 먼저 만든다. config가 없으면 hook은 발동해도 handoff draft가 생성되지 않는다.
4. Codex `/hooks` review 또는 `~/.codex/config.toml`의 trust 기록을 확인한다.
5. Codex plugin은 hook 포함 여부가 아니라 skill·문서 설치 여부만 확인한다.

## 검증 기록

- `python3 /home/mooni/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py /home/mooni/projects/cairn`
- `python3 core/_selftest.py`
- `python3 hooks/_selftest_codex_transcript_scan.py`
- `scripts/package-plugin claude /tmp/cairn-claude-plugin-cplan`
- `scripts/package-plugin codex /tmp/cairn-codex-plugin-should-fail` → usage 출력과 exit 2로 거부 확인.
- `/tmp/cairn-codex-fresh.ljPBEw` fresh repo에서 `.codex/hooks.json` adapter를 설치하고 `<CAIRN_ROOT_ABS>`를 `/home/mooni/projects/cairn`로 치환했다.
- config 없이 `codex exec --ephemeral --dangerously-bypass-hook-trust -s workspace-write` 실행 시 SessionStart/Stop hook 발동은 확인됐지만 `.cairn` draft는 생성되지 않았다.
- `.cairn/cairn.config.json`와 `specs/`를 만든 뒤 같은 fresh repo에서 SessionStart/Stop hook이 발동했고, `.cairn/sessions/hot.md`, `.cairn/sessions/session-state.md`, `.cairn/log.md`, `.cairn/sessions/nudge-metrics.md` 생성이 확인됐다.
- 같은 fresh repo에서 bypass 없이 `codex exec --ephemeral -s workspace-write`를 실행해 SessionStart/Stop hook 발동과 handoff log append를 확인했다.
- `~/.codex/config.toml`에는 `[projects."/tmp/cairn-codex-fresh.ljPBEw"] trust_level = "trusted"`가 기록됐고, 해당 repo-local `.codex/hooks.json`의 hook별 `[hooks.state]` 항목은 생성되지 않았다. 임시 project trust 항목은 검증 기록 후 제거했다.

## 한계

- 🟡 근거 문서 3개는 이 repo의 `docs/`가 아니라 `/home/mooni/projects/llm-wiki-plugin/docs/`에서 확인했다. 이번 결과 문서부터 `~/projects/cairn/docs/`에 기록한다.
- 🔵 이번 변경은 C안 확정안의 repo 반영이며, Codex plugin-bundled hook에 대한 새 판정 실측이 아니다.
- 🔵 `core/`와 `hooks/*.sh`, `hooks/*.py` 본체는 수정하지 않았다.

## 다음 단계 추천 프롬프트

```text
~/projects/cairn에서 Gate D-1 C안 적용 후 fresh 소비자 repo 기준 Codex adapter 설치 절차를 재검증하라.
검증 대상은 repo-local `.codex/hooks.json`의 SessionStart/Stop 2-hook 발동, `.cairn/cairn.config.json` 초기화 후 공유 `CAIRN_DIR` vault 관통, `/hooks` review 또는 config trust 기록이다.
Codex plugin은 hook 배포 단위가 아니므로 plugin 설치 후 hook 미포함 여부만 명시적으로 확인한다.
core/와 hook script 본체는 수정하지 않는다.
```

## 반대 관점·반례

- 🟡 반대 관점: `hooks/codex/hooks.json`를 실험 후보로 남겨두면 후속 B안 재검증이 쉬워진다. 반례: C안 적용의 목적은 운영 배포 계약에서 plugin hook 경로를 제거하는 것이다. 실험 후보를 남기면 사용자가 `${PLUGIN_ROOT}` 기반 배선을 운영 source로 오해할 수 있다.
- 🟡 반대 관점: `scripts/package-plugin codex`를 유지하되 문서에서만 보류 표시하면 충분하다. 반례: script가 남아 있으면 Codex plugin-bundled hook 산출물을 계속 만들 수 있고, KC-Fn-70 차단 판정과 충돌한다.
- 🟡 반대 관점: Codex plugin hook이 향후 지원될 수 있으니 지금 제거하면 되돌리기 비용이 생긴다. 반례: D-KC-16 단일 repo와 Codex manifest는 유지된다. 후속 CLI/validator 계약이 바뀌면 별도 KC-Fn과 승인으로 hook packaging 경로를 다시 추가하면 된다.
