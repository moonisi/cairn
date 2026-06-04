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
| User-invoked | **`/cairn:capture` skill** | Absorbs decisions / agreements / lessons from the *current conversation* into Vault pages (HITL). The conversation itself is the source — no nudge queue involved. |

**Core principle**: Cairn never *accumulates* records automatically. Automation goes only as far
as *proposing candidates*; the actual page write always requires a human approval. (So-called
automatic permanent ingest is deliberately excluded.)

---

## Structure

```
cairn/
├── .claude-plugin/plugin.json   # Claude manifest (no hooks field)
├── .codex-plugin/plugin.json    # Codex manifest (skills/docs/aux artifacts, no hooks field)
├── adapters/codex/hooks.json.example # Codex repo-local .codex/hooks.json adapter template
├── hooks/
│   ├── hooks.json               # Claude direct-install compatible copy
│   ├── claude/hooks.json        # Claude wiring source of truth
│   └── *.sh, *.py               # hook scripts (shared across runtimes, unmodified)
├── core/                        # runtime/domain-agnostic core: 6 modules + self-test
│   └── *.py                     # zero-dep (Python stdlib only)
└── skills/
    ├── setup/SKILL.md           # /cairn:setup skill (Vault bootstrap)
    ├── ingest/SKILL.md          # /cairn:ingest skill (candidate absorption)
    └── capture/SKILL.md         # /cairn:capture skill (conversation absorption)
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
claude plugin details cairn@cairn   # verify install (Skills 3 · Hooks 3)
```

On install, the 3 hooks in `hooks/hooks.json` are wired automatically and the `/cairn:setup`,
`/cairn:ingest` and `/cairn:capture` skills are registered. (The standard `hooks/hooks.json` is **auto-loaded**, so the
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
claude plugin details cairn@cairn   # confirm update (Skills 3 · Hooks 3)
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

Codex uses Cairn in two pieces:

1. The Codex plugin provides the `/cairn:setup`, `/cairn:ingest`, and `/cairn:capture` skills.
2. The session hooks are installed separately in each project with a repo-local `.codex/hooks.json`
   adapter.

The plugin does **not** register hooks by itself. This keeps installation explicit: skills are
installed once, and hooks are enabled only in the projects where you want session continuity.

### Install the Codex plugin

Clone Cairn and add it as a local Codex marketplace:

```bash
git clone https://github.com/moonisi/cairn.git ~/cairn
cd ~/cairn
codex plugin marketplace add "$(pwd)"
codex plugin add cairn@cairn
codex plugin list
```

`codex plugin list` should show `cairn@cairn` as `installed, enabled`. Start a new Codex session
after installing so the new skills are loaded. You should then be able to call:

- `/cairn:setup`
- `/cairn:ingest`
- `/cairn:capture`

### Enable hooks in a project

Run this from the project where you want Cairn to keep session context:

```bash
CAIRN_ROOT="$HOME/cairn"
mkdir -p .codex
cp "$CAIRN_ROOT/adapters/codex/hooks.json.example" .codex/hooks.json
CAIRN_ROOT_ABS="$(cd "$CAIRN_ROOT" && pwd)"
sed -i "s#<CAIRN_ROOT_ABS>#$CAIRN_ROOT_ABS#g" .codex/hooks.json
```

- `CAIRN_DIR` defaults to the consumer repo's `$(pwd)/.cairn` (overridable).
- Open `/hooks` in Codex, review the `SessionStart` and `Stop` hooks, and trust them.
- Run `/cairn:setup` once in the project to create `.cairn/cairn.config.json`.

The first session may not have anything to show yet. After you finish a Codex response, the Stop
hook writes handoff drafts under `.cairn/sessions/`; the next session can read them back.

Codex hooks are intentionally installed with the repo-local adapter. The adapter uses `SessionStart`
and `Stop`; web candidates are collected during the Stop-time transcript scan (`cairn-stop-codex.sh`).

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

## Future considerations

- **User-scoped memory (deferred)** — The Vault is currently project-scoped (D-KC-05):
  every project owns its own `.cairn/`. A dual-vault model — a user-level Vault at
  `~/.cairn` (env `CAIRN_USER_DIR`) holding cross-project durable pages
  (`lesson`/`note`/`preference`) alongside each project Vault — was evaluated and **deferred**.
  - Why: preferences and working habits are already covered by the harness's global memory
    (`~/.claude/CLAUDE.md`); the only genuine gap is cross-project *lessons*, and there is no
    demonstrated demand yet → YAGNI.
  - Re-entry trigger: once ≥3–5 pages you actually want shared accumulate across 2+ projects,
    start with the minimal variant — read-only injection of a `CAIRN_USER_DIR` index at
    SessionStart, **without** write routing or cross-vault dedup.

---

## License

MIT — [LICENSE](LICENSE).
