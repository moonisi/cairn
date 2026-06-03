# Cairn — Getting Started (no experience needed)

> 🌐 **한국어**: [안내서.md](안내서.md) · Reference: [README.en.md](README.en.md)

This guide is written so that even someone new to programming or plugins can follow along. Take your time.

---

## 1. What even is Cairn?

**One-line analogy**: the *cairn* (stone stack) on a hiking trail. When the person ahead stacks stones
along the path, those who follow don't lose their way. Cairn plays that role in your work with AI.

Working with AI (Claude · Codex), two frustrations show up:

1. **When a session breaks, the context is gone.** What you discussed at length yesterday, the AI doesn't remember today.
2. **The material you looked up scatters.** Good docs you find on the web vanish if you don't file them away then and there.

Cairn solves both:

- When a session ends, it **leaves a memo of "what you did today"**, and at the next session start it **shows you that memo again.**
- Every time you look at material on the web, it **collects it as a "want to file this?" candidate**, and tidies it up when you choose to.

And all of these records are **just markdown files + git**. No special database, no internet connection
needed. They're plain text files inside your folder — open, read, and edit them anytime.

---

## 2. Just three core concepts

| Term | Plain explanation |
|---|---|
| **Vault** | The folder where all records are stored. Usually the `.cairn/` folder inside the project. It's yours. |
| **hook (automatic action)** | A small script Cairn runs automatically at certain moments (session start/end, after a web search). |
| **skill (`/cairn:setup`)** | A command you call yourself. Creates the Vault (`.cairn/`) and the config file, once. |
| **skill (`/cairn:ingest`)** | A command you call yourself. "Absorbs" collected candidates into real records. |

**The important promise**: Cairn never *accumulates* records without your permission. Automatic actions
go only as far as "proposing candidates." Actually storing something always happens after you approve
it with `/cairn:ingest`.

---

## 3. Installing (Claude Code)

### Check the prerequisites
- **Claude Code** must be installed.
- **Python 3** must be present. Check in a terminal:
  ```bash
  python3 --version
  ```
  A version number (e.g. `Python 3.11.x`) means you're good.

### Install in 3 steps

Inside Claude Code, type the following (exactly, including the leading `/`).

```
/plugin marketplace add https://github.com/moonisi/cairn.git
```
→ Means "register this folder as a plugin store."

```
/plugin install cairn@cairn
```
→ Actually turns Cairn on.

If you're asked **"do you trust this hook"** during install, review it and agree. (Hooks run code on
your computer, so there's a one-time check — that's normal.)

```
/cairn:setup
```
→ Run this **exactly once** in the project where you'll use Cairn. It creates the Vault (the `.cairn/`
folder) and the config file (`cairn.config.json`). It shows you the contents and asks "create it like
this?" — review and approve. **Without this config file, records won't be saved even if hooks run** —
that's why the one-time setup is required.

---

## 4. Checking that it worked

### Easiest check — run the self-check

In a terminal:

```bash
cd ~/projects/cairn
python3 core/_selftest.py
```

If `=== 195 passed, 0 failed ===` shows at the bottom, the core is healthy.

### Checking real behavior

1. First run `/cairn:setup` once in that project to create the config file (the 3 install steps above).
   Without it, records won't be saved even if hooks run.
2. Start a fresh Claude Code session in the same project.
3. Do a web search or page fetch once, then end the session (`/exit`, etc.).
4. Check whether `hot.md` / `session-state.md` appeared in that project's `.cairn/sessions/` folder. If
   they did, the hooks are running fine. (These files appear **after you finish the first session**, so
   it's normal for them to be empty right after setup.)

---

## 5. Tidying up collected material — `/cairn:ingest`

After you look at material on the web, Cairn collects it as a "candidate." When you want to tidy up:

```
/cairn:ingest
```

Then Cairn:
1. Shows you the list of collected candidates.
2. Lets you pick which to tidy up (one at a time recommended).
3. Shows a **draft** of the tidied content and asks **"save it like this?"**
4. Only once you approve does it save it as a page in the Vault.

It never saves before approval, so relax.

> Note: a plain *search (WebSearch)* is not a source, so it isn't an absorption target. Only a page you
> actually *opened (WebFetch)* becomes a tidy-up candidate.

---

## 6. Frequently asked questions

**Q. Where are records stored?**
A. In the `.cairn/` folder inside the project. All markdown files — they open in a plain text editor too.

**Q. Is it OK if my internet is down?**
A. Yes. Cairn itself uses no external server or database at all (zero dependency).

**Q. Hooks don't work on my work computer (managed policy).**
A. That's when the admin has turned on `allowManagedHooksOnly`. It blocks not just plugins but even
   hooks you added yourself (standalone can't get around it). **The only fix is to ask your org admin to
   force-enable `cairn@cairn` in the managed settings' `enabledPlugins`.**

**Q. Does it work in Codex too?**
A. Yes. But the current operating default is a repo-local `.codex/hooks.json` adapter rather than
   plugin-bundled hooks. Copy `adapters/codex/hooks.json.example` to your consumer repo's
   `.codex/hooks.json` and replace `<CAIRN_ROOT_ABS>` with this Cairn repo's absolute path. You also
   need to create `.cairn/cairn.config.json` first for the handoff draft to be produced. The Codex
   plugin installs skills/docs only and does not include hooks. After installing the adapter, confirm it
   in Codex via `/hooks` review or the trust record in `~/.codex/config.toml` (see the "Codex" section of
   [README.en.md](README.en.md)).

**Q. How do I update when a new version comes out?**
A. Two lines in Claude Code:
   ```
   /plugin marketplace update cairn
   /plugin update cairn@cairn
   ```
   After a big change that renames a command (e.g. the old `/cairn:init` → `/cairn:setup`), an old copy
   can linger in the cache and confuse things. If so, `/plugin uninstall cairn@cairn` then reinstall for a clean state.

**Q. Can I edit records by hand?**
A. Yes. If the format breaks, run the lint via `python3 -c` to check. It's just markdown — no pressure.

---

If you get stuck, read the matching section of [README.en.md](README.en.md) alongside this.
