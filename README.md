# manuscript-editor

A [Claude Code](https://claude.com/claude-code) Skill for doing async, chapter-by-chapter
copyediting and line-editing on long-running novel manuscripts, safely — without corrupting
[novelWriter](https://novelwriter.io) project files or racing with the app while it's open.

## Why this exists

novelWriter is a single-writer app: it locks its project directory while open and won't merge
external changes into a live session. That's incompatible with having an AI assistant "peer
review" chapters in real time. This skill instead hardlocks an async loop: pull a chapter →
propose edits → get explicit human approval → merge back only once the app is confirmed
closed, always with a backup first.

It also supports plain flat-markdown manuscripts (a single `.md` file with `# ` chapter
headings) for writers who don't use novelWriter at all.

## What's in this repo

- **`SKILL.md`** — the workflow instructions themselves (what Claude Code loads and follows).
- **`toolkit/nw_tool.py`** — the actual read/write logic:
  - `list` / `flat-list` — show a project's/manuscript's chapters in order with word counts
  - `export` — dump a whole novelWriter manuscript to one clean text file
  - `get` / `flat-get` — pull one chapter's clean text out for editing
  - `set` / `flat-set` — write an edited chapter back in (auto-backup, refuses if the
    novelWriter project is currently open, preserves the `.nwd` header format)
- **`toolkit/init_tracking.py`** — scaffolds a per-manuscript `_edits/` folder (never
  overwrites existing files) with:
  - `edit_log.md` — a running log of every editing pass
  - `open_issues.md` — continuity/craft issues tracked across sessions
  - `style_guide.md` — the author's voice rules and "don't touch this" list
  - `query_and_synopsis.md` — query letter / synopsis drafts, with history

## Install

Requires [Python 3](https://www.python.org/) on PATH. No other dependencies.

```
git clone https://github.com/SwaroopShenoy/manuscript-editor-skill "%USERPROFILE%\.claude\skills\manuscript-editor"
```

(On macOS/Linux: `git clone https://github.com/SwaroopShenoy/manuscript-editor-skill ~/.claude/skills/manuscript-editor`)

Claude Code auto-discovers skills under `~/.claude/skills/` — no further setup needed. It's
also directly callable as `/manuscript-editor`.

## Usage

Just ask, in a Claude Code session:

> "Let's edit chapter 3 of \<project\>"

The skill takes it from there: pulls the chapter fresh, proposes edits (inline in chat for a
light pass, or as a saved proposal file under `_edits/proposals/` for a full deep-edit pass),
waits for your go-ahead, and only then writes anything back — never while the project is open
in novelWriter.

## Non-negotiable rules baked into the workflow

1. Never write to a novelWriter project while `nwProject.lock` exists in it.
2. Never merge an edit without explicit human approval first.
3. Every merge is backed up automatically before it's written.
4. Every merge gets logged to `_edits/edit_log.md`.

See `SKILL.md` for the full workflow this skill follows.
