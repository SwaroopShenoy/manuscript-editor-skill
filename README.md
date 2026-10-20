# manuscript-editor

A [Claude Code](https://claude.com/claude-code) Skill for doing async, chapter-by-chapter
copyediting, line-editing, and prose-habit passes on long-running novel manuscripts, safely —
without corrupting [novelWriter](https://novelwriter.io) project files or racing with the app
while it's open.

## Why this exists

novelWriter is a single-writer app: it locks its project directory while open and won't merge
external changes into a live session. That's incompatible with having an AI assistant "peer
review" chapters in real time. This skill instead hardlocks an async loop: pull a chapter →
propose edits → get explicit human approval → merge back only once the app is confirmed
closed, always with a backup first, and always logged.

It also supports plain flat-markdown manuscripts (a single `.md` file with chapter headings —
auto-detected at `#`, `##`, or `##`-from-a-novelWriter-build-export) for writers who don't use
novelWriter at all, or who work from an exported build.

## What's in this repo

- **`SKILL.md`** — the workflow instructions themselves (what Claude Code loads and follows):
  the core pull/propose/reconcile/merge/log loop, plus a "toolkit first, LLM only for judgment"
  prose-habits pass, a story-level read, and a per-chapter review/summary format.
- **`toolkit/nw_tool.py`** — the read/write core, safe by construction:
  - `list` / `flat-list` — show a project's/manuscript's chapters in order with word counts
  - `export` — dump a whole novelWriter manuscript to one clean text file
  - `get` / `flat-get` — pull one chapter's clean text out for editing
  - `set` / `flat-set` — write a whole edited chapter back in (auto-backup, refuses if the
    novelWriter project is currently open, handles both document formats: novelWriter 26.x `.md` files with a `+++` TOML header, and
    legacy `.nwd` files with `%%~` headers; refreshes the hash/date and keeps line endings)
  - `patch` / `flat-patch` — apply a list of targeted `{old, new}` string replacements as one
    all-or-nothing operation, with `--dry-run` to validate every replacement matches uniquely
    before anything is written — this is the normal way edits get applied, not `set`
  - `lint` / `flat-lint` — flag mechanical issues (curly-vs-straight apostrophes, 3-vs-4-dot
    ellipses, etc.) without touching the text
  - `log-append` — append a block of text to a manuscript's `_edits/edit_log.md`
- **`toolkit/prose_tools.py`** — deterministic prose-habit analysis, no LLM involved, output in
  the same patch JSON `nw_tool.py patch` consumes:
  - `tics` — dialogue-tag verbs + body-beat/adverb tics: counts, per-1000-word density, which
    are actually overused (`said` is exempt unless it's over 60% of tags)
  - `tags-patch` — propose varied dialogue-tag replacements for genuinely overused verbs
  - `paras` — one-sentence-paragraph habit stats, with exchange-beats (dialogue back-and-forth)
    excluded from the rate so a fast exchange doesn't read as a pacing problem
  - `merge-patch` — propose merging runs of consecutive one-sentence narration paragraphs
    (deliberate punch lines and chapter-ending beats are left alone)
  - `pauses` — find named pauses ("a beat", "for a moment", "silence stretched"...) with
    before/after context, report-only — replacements are hand-written from the scene's own
    objects/setting, never invented (see `SKILL.md`'s "unnamed pause" guidance)
  - `build-patch` — folds hand-written pause replacements and generated merges into one
    combined, validated patch file, ready for `nw_tool.py patch --dry-run`
  - `stats` — words, paragraphs, dialogue ratio, average paragraph length
- **`toolkit/init_tracking.py`** — scaffolds a per-manuscript `_edits/` folder (never
  overwrites existing files) from `toolkit/tracking_template/`:
  - `edit_log.md` — a running log of every editing pass
  - `open_issues.md` — continuity/craft issues tracked across sessions
  - `style_guide.md` — the author's voice rules and "don't touch this" list
  - `query_and_synopsis.md` — query letter / synopsis drafts, with history
  - `story_notes.md` — arcs, hook & momentum log, per-chapter reviews, and an overall-feel
    summary, kept current as chapters are read/edited

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

> "Run a prose-habits pass on chapter 5"

> "How's the story reading so far — what's working, what isn't?"

The skill takes it from there: pulls the chapter fresh, proposes edits (inline in chat for a
light pass, or as a saved proposal file under `_edits/proposals/` for a full deep-edit or
prose-habits pass), waits for your go-ahead, and only then writes anything back — never while
the project is open in novelWriter.

## Non-negotiable rules baked into the workflow

1. Never write to a novelWriter project while `nwProject.lock` exists in it.
2. Never merge an edit without explicit human approval first.
3. Every merge is backed up automatically before it's written.
4. Every merge gets logged to `_edits/edit_log.md`.

See `SKILL.md` for the full workflow this skill follows.

## Companion skill

For reader-facing chapter reviews (a continuous story analysis, or a simulated panel of beta
readers) rather than line-editing, see
[beta-reader-panel](https://github.com/SwaroopShenoy/beta-reader-panel-skill) — it reads
manuscripts through this skill's `nw_tool.py` but never edits them.
