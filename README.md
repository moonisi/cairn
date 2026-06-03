# Cairn

A runtime- and domain-agnostic **continuity & knowledge-accretion core**. Cairn keeps your
context alive across broken sessions and gathers the external knowledge you hit mid-task so it
doesn't scatter. The entire store is **just markdown + git** — zero external dependencies.

> 🌐 **한국어**: [README.md](README.md) · [안내서.md](안내서.md) (beginner guide)
> New here? Start with [GETTING-STARTED.en.md](GETTING-STARTED.en.md) — concepts and install, step by step.

---

## What it does

Three automatic actions plus one manual action.

| When | Action | What |
|---|---|---|
| Session start (SessionStart) | **Hot-context injection** | Re-surfaces the previous session's `hot.md` / `session-state` at the top of the conversation → broken context restored. |
| After a web tool (PostToolUse) | **Nudge candidate collection** | External knowledge seen via `WebFetch` / `WebSearch` is quietly queued as an "ingest candidate" (silent — no write). |
| Session end (Stop) | **Handoff draft** | This session's activity is drafted into the next session's `session-state` + `hot.md`. |
| User-invoked | **`/cairn:setup` skill** | Bootstraps the Vault (`.cairn/`) + `cairn.config.json` in a consumer project (one-time, HITL). |
| User-invoked | **`/cairn:ingest` skill** | Absorbs queued candidates into Vault pages after your approval (HITL). Never writes automatically. |

**Core principle**: Cairn never *accumulates* records automatically. Automation goes only as far
as *proposing candidates*; the actual page write always requires a human approval. (So-called
automatic permanent ingest is deliberately excluded.)

---

## Structure

```
cairn/
├── .claude-plugin/plugin.json   # Claude manifest (no hooks field)
├── .codex-plugin/plugin.json    # Codex manifest (skills/docs/aux artifacts, no hooks field)
├── adapters/codex/hooks.json.example # Codex repo-local .codex/hooks.json fallback template
├── hooks/
│   ├── hooks.json               # Claude direct-install compatible copy
│   ├── claude/hooks.json        # Claude wiring source of truth
│   └── *.sh, *.py               # hook scripts (shared across runtimes, unmodified)
├── core/                        # runtime/domain-agnostic core: 6 modules + self-test
│   └── *.py                     # zero-dep (Python stdlib only)
└── skills/
    ├── setup/SKILL.md           # /cairn:setup skill (Vault bootstrap)
    └── ingest/SKILL.md          # /cairn:ingest skill (candidate absorption)
```

The 6 core modules: `cairn_root` (paths / frontmatter / hash) · `cairn_ingest` (absorption) ·
`cairn_nudge` (candidate queue) · `cairn_query` (search) · `cairn_lint` (lint) ·
`cairn_handoff` (session handoff). All run on the Python standard library alone — no external packages.

---

## Install (Claude Code)

### Option A — plugin marketplace (recommended)

```bash
# 1) Add this repo as a marketplace (.claude-plugin/marketplace.json is bundled)
/plugin marketplace add https://github.com/moonisi/cairn.git

# 2) Install cairn — plugin@marketplace form
/plugin install cairn@cairn
```

Same via CLI (headless):

```bash
claude plugin marketplace add ~/projects/cairn
claude plugin install cairn@cairn
claude plugin details cairn@cairn   # verify install (Skills 2 · Hooks 3)
```

On install, the 3 hooks in `hooks/hooks.json` are wired automatically and the `/cairn:setup` and
`/cairn:ingest` skills are registered. (The standard `hooks/hooks.json` is **auto-loaded**, so the
plugin.json carries **no** `hooks` field — declaring it twice breaks hook loading.) Hooks ask for a
one-time trust confirmation in an interactive session.

> To quickly try a single plugin without a marketplace: `claude --plugin-dir ~/projects/cairn`.

### Option B — standalone (`.claude/` direct wiring)

An alternative when you'd rather wire hooks yourself instead of using the plugin system. Register
the hooks directly in your project's `.claude/settings.json` and point the script paths at absolute
locations. (Full format in [GETTING-STARTED.en.md](GETTING-STARTED.en.md).)

> Note: this does **not** bypass the `allowManagedHooksOnly` managed policy (user/project hooks are
> blocked too). See "⚠️ Managed policy environments" below.

---

## Updating

To pull a new version, refresh the marketplace then update the plugin.

```bash
/plugin marketplace update cairn   # pull the repo's latest commit
/plugin update cairn@cairn         # refresh the installed copy
```

CLI (headless):

```bash
claude plugin marketplace update cairn
claude plugin update cairn@cairn
claude plugin details cairn@cairn   # confirm update (Skills 2 · Hooks 3)
```

> 🔴 **Cache caveat**: changes that move file paths — like renaming or deleting a skill — can leave a
> stale copy in the plugin cache (`~/.claude/plugins/cache/cairn/...`), mixing old and new. If a
> command still resolves to the old name, run `/plugin uninstall cairn@cairn` and reinstall, or
> delete the cache directory. (E.g. the `/cairn:init` → `/cairn:setup` rename.)

---

## Vault location — `CAIRN_DIR`

The store (Vault) is **owned by the consumer project, not the plugin** (D-KC-05). Default:

```
CAIRN_DIR = ${CLAUDE_PROJECT_DIR}/.cairn
```

So the `.cairn/` folder at the project root is the Vault. To use another location, override
`CAIRN_DIR` in the hook wiring. The Vault itself (pages / sessions / config) is not bundled with the
plugin — it lives in the consumer repo as markdown + git.

`.cairn/cairn.config.json` defines page types, refs scope, and nudge parameters (created by the
consumer). After install, run **`/cairn:setup`** once to bootstrap this config via HITL (no
hand-writing needed). Without a config, hooks fire but produce no handoff draft, so the one-time
setup is required.

---

## ⚠️ Managed policy environments

🔵 Official docs (`permissions.md` §Managed-only settings, 2026-06-02): if an enterprise admin sets
`allowManagedHooksOnly: true`, then **only managed hooks · SDK hooks · plugin hooks force-enabled via
managed settings' `enabledPlugins`** load — **user, project, and all other plugin hooks are blocked**.

→ To use Cairn hooks in such an environment, **the org admin must force-enable `cairn@cairn` in the
managed settings' `enabledPlugins`**. That is the **only** way.

> ⚠️ The standalone `.claude/` route (Option B) is **void in this case** — user/project hooks are
> blocked the same way. When `allowManagedHooksOnly` is *off* (a normal environment), plugin hooks
> work fine (proven on a live install). Option B is only an alternative for those not using the
> plugin system — not a way around the managed block.

---

## Codex

🔵 The current operating default is the **Option-C fallback**.

The Codex plugin installs skills/docs/aux artifacts only; hooks are placed separately as a
repo-local `.codex/hooks.json` adapter in the consumer repo. The reason: in Gate D-1 testing the
Codex plugin passed validation/install/cache-copy, but the default `hooks/hooks.json` was not
auto-registered as a `codex exec` runtime lifecycle hook source (KC-Fn-70).

### Operating fallback — repo-local `.codex/hooks.json`

From the consumer repo root (substitute the example absolute path for your own environment):

```bash
# 1) Copy the adapter template to the consumer repo's .codex/hooks.json
mkdir -p .codex
cp <CAIRN_ROOT_ABS>/adapters/codex/hooks.json.example .codex/hooks.json

# 2) Replace the <CAIRN_ROOT_ABS> placeholder with this Cairn repo's absolute path
#    (e.g. /home/mooni/projects/cairn) — via sed or an editor
sed -i "s#<CAIRN_ROOT_ABS>#$HOME/projects/cairn#g" .codex/hooks.json

# 3) Create the Vault config (without it, hooks fire but produce no handoff draft).
#    Share the .cairn/ you bootstrapped via /cairn:setup on the Claude Code side, or write it manually.
```

- `CAIRN_DIR` defaults to the consumer repo's `$(pwd)/.cairn` (overridable).
- This route does not depend on `${PLUGIN_ROOT}`. The hook scripts locate `../core` relative to `$0`,
  so they work without `CAIRN_CORE`.
- After install, confirm hook registration in Codex via `/hooks` review or the `[hooks.state]` trust
  record in `~/.codex/config.toml`.

> 🟡 **Codex verification scope**: the adapter contract/paths above are based on Gate D-1 confirmed
> artifacts (KC-Fn-68/69/70). However, **live verification of this install procedure itself must be
> done in a Codex session** to be accurate (per the D-KC-09 boundary: the Codex adapter is developed
> separately in Codex). It cannot be verified from a Claude Code environment.

### Codex plugin install — no hooks

`.codex-plugin/plugin.json` has no `hooks` field. The Codex plugin is the unit that ships the
`/cairn:ingest` skill plus docs/aux artifacts; it does not install SessionStart/Stop hooks or create
a trust entry. This separation is the Option-C contract that avoids KC-Fn-68/69/70.

To use hooks in Codex, you must install the repo-local `.codex/hooks.json` adapter above separately,
and check Codex's `/hooks` review or the `[hooks.state]` trust record in `~/.codex/config.toml`.

### Packaging

```bash
# Claude artifacts
scripts/package-plugin claude /tmp/cairn-claude-plugin
```

Codex plugin-bundled hook packaging was removed from the operating path. The Codex hook surface uses
only SessionStart · Stop (2 hooks) from the repo-local adapter. It does not use PostToolUse; instead
it catches web candidates via a Stop-time transcript scan (`cairn-stop-codex.sh`).

---

## Verification (self-check)

To check zero-dep integrity after porting/editing:

```bash
python3 core/_selftest.py                       # core 6-module regression (195 cases)
python3 hooks/_selftest_codex_transcript_scan.py # Codex scanner regression
```

These are deterministic tests that run with no external dependency or network.

### Live hook check (after install)

```bash
# New session → one web fetch → end the response (Stop) → check
ls .cairn/sessions/   # hot.md · session-state.md · nudge-metrics.md appearing = healthy
```

The SessionStart hook is **read-only**, so it stays silent when there's no prior-session artifact.
The artifacts are produced by the Stop hook, so it's normal for `sessions/` to be empty on the first
session until you finish one response (an empty `sessions/` right after opening a session is not a
sign the hook failed to fire).

---

## License

MIT — [LICENSE](LICENSE).
