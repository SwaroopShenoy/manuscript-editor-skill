---
name: manuscript-editor
description: Async chapter-by-chapter line editing and copyediting workflow for the user's novelWriter projects (under C:\Users\Acer\Documents\Novels) and flat-markdown manuscripts (e.g. C:\Users\Acer\Manuscripts\Roadmap). Use whenever the user asks to edit/copyedit/line-edit a chapter, review a manuscript, merge edits back into novelWriter, or otherwise work on a specific novel/book chapter by chapter over an extended, multi-session project.
---

# Manuscript editor workflow

Toolkit lives inside this skill's own folder, at `toolkit\` next to this file
(`$env:USERPROFILE\.claude\skills\manuscript-editor\toolkit\`) — `nw_tool.py`,
`init_tracking.py`, `tracking_template\`. It travels with the skill, so this file never
hardcodes a machine-specific path outside the skill directory. This skill is the hardlocked
process for using it. Follow it exactly — don't improvise shortcuts around the safety steps,
even if asked to hurry.

## Non-negotiable rules

1. **Never write to a novelWriter project's files while it's open in the app.**
   `nw_tool.py set`/`patch` already refuse if `nwProject.lock` exists in the project root —
   never bypass, delete, or ignore that lock file to force a write. If it's locked, tell the
   user and wait for them to close novelWriter.
2. **Never merge an edit the user hasn't explicitly approved.** Proposing edits and applying
   them are separate steps with a human checkpoint in between, always.
3. **Every merge is backed up automatically by the toolkit** (`_edits/backups/` next to the
   project, or next to the manuscript file for flat-md). Don't skip this by editing files
   directly with Read/Edit tools instead of the toolkit.
4. **Log every pass.** After a merge, append a row to `_edits/edit_log.md` (use `log-append`
   — see below, don't re-read the whole growing file just to anchor an edit). If the pass
   surfaced or resolved a continuity/craft issue, update `_edits/open_issues.md` too.

## Identify the manuscript type

- novelWriter project: a directory containing `nwProject.nwx` and a `content/` folder of
  `.nwd` files (e.g. anything under `C:\Users\Acer\Documents\Novels\<Project>`). Use the
  plain (non-`flat-`) toolkit commands.
- Flat markdown manuscript: a single `.md` file with `# ` chapter headings (e.g.
  `C:\Users\Acer\Manuscripts\Roadmap\The Roadmap Series - Book 1.md`). Use the `flat-*`
  toolkit commands.

If `_edits/` doesn't exist yet next to the project/manuscript, run:
```
python $env:USERPROFILE\.claude\skills\manuscript-editor\toolkit\init_tracking.py <project_or_manuscript_dir> "<Project Name>"
```
It's safe to re-run any time — it never overwrites existing tracking files.

## The loop

**1. Pull** — get the current chapter text fresh from disk (never rely on a stale copy from
an earlier session):
```
python $env:USERPROFILE\.claude\skills\manuscript-editor\toolkit\nw_tool.py list <project_dir>
python $env:USERPROFILE\.claude\skills\manuscript-editor\toolkit\nw_tool.py get <project_dir> "<handle-or-title>" --out <scratch_file>
```
or for flat markdown:
```
python $env:USERPROFILE\.claude\skills\manuscript-editor\toolkit\nw_tool.py flat-list <manuscript.md>
python $env:USERPROFILE\.claude\skills\manuscript-editor\toolkit\nw_tool.py flat-get <manuscript.md> "<heading substring>" --out <scratch_file>
```
Check `_edits/style_guide.md` first if it has content — respect the author's stated voice
rules and "don't fix" list before proposing changes.

Optionally run a lint pass to catch the common contamination patterns (straight quotes/
apostrophes pasted in from elsewhere, triple-dot "..." instead of a proper ellipsis, doubled
words) before reading the chapter by eye:
```
python $env:USERPROFILE\.claude\skills\manuscript-editor\toolkit\nw_tool.py lint <project_dir> "<handle-or-title>"
```
or `flat-lint <manuscript.md> "<heading substring>"` for flat markdown. It's a mechanical regex
pass, not a substitute for reading the chapter — still read it in full for grammar, dialogue-tag
punctuation, and craft/continuity issues.

**2. Propose** — never silently rewrite. Present:
- Line-level copyedits (typos, grammar, redundancy, awkward phrasing) as old → new with a
  short reason each.
- Story/craft notes (pacing, continuity, characterization) as prose commentary, cross-checked
  against `_edits/open_issues.md` and any Living Reference / continuity doc for that project
  if one exists.

For a light pass (a handful of edits), do this directly in chat. For a full deep-edit pass
(many changes across a whole chapter), instead write the proposal to
`<project_or_manuscript_dir>/_edits/proposals/<chapter-name>_<yyyy-mm-dd>.md` and point the
user to it — chat gets unreadable past a dozen edits. Use a clear old/new or table format in
that file so the user can mark it up directly.

**3. Reconcile** — wait for the user to accept, reject, or edit the proposal (in chat or by
editing the proposal file). Do not proceed to merge until they've confirmed what's final.

**4. Merge** — confirm the project is closed, then write the agreed final text back. Two ways
to do this:

- **`patch`** (preferred when the approved changes are a list of discrete old→new fixes,
  which is the common case for a copyedit pass): write the approved fixes as a JSON array to a
  scratch file — `[{"old": "...", "new": "...", "count": 1}, ...]` (see `nw_tool.py --help` for
  the full format, including `replace_all`) — then apply them in one call instead of many
  individual find/replace edits:
  ```
  python $env:USERPROFILE\.claude\skills\manuscript-editor\toolkit\nw_tool.py patch <project_dir> <handle> <patch_file.json> --dry-run
  python $env:USERPROFILE\.claude\skills\manuscript-editor\toolkit\nw_tool.py patch <project_dir> <handle> <patch_file.json>
  ```
  or `flat-patch <manuscript.md> "<heading substring>" <patch_file.json>` for flat markdown.
  Always `--dry-run` first — it validates every patch matches (reporting exactly which one
  doesn't, if any) without touching the file. It's all-or-nothing: if any patch fails to match,
  nothing is written, so there's no risk of a half-applied chapter.
- **`set`** (for a full-body rewrite, e.g. when the whole chapter was reworked in the scratch
  file rather than as a list of discrete substitutions):
  ```
  python $env:USERPROFILE\.claude\skills\manuscript-editor\toolkit\nw_tool.py set <project_dir> <handle> <final_file>
  ```
  or `flat-set <manuscript.md> "<heading substring>" <final_file>`.

If either refuses due to the lock file, stop and tell the user to close novelWriter — do not
retry with a workaround.

**5. Log and hand back** — append a row to `_edits/edit_log.md` using `log-append` (write the
new row to a small scratch file, then append it — no need to read the whole growing log just to
anchor an edit):
```
python $env:USERPROFILE\.claude\skills\manuscript-editor\toolkit\nw_tool.py log-append <project_dir>\_edits\edit_log.md <row_file>
```
(chapter, pass type, date, notes — same format as existing rows). Update `_edits/open_issues.md`
if relevant, and tell the user to reopen novelWriter (it will re-index the changed file itself).

## Prose habits pass (toolkit first, LLM only for judgment)

Run this on any chapter before/alongside the normal read. Get the chapter to a scratch file
(`get`/`flat-get --out`), then use `toolkit\prose_tools.py` (all deterministic, zero tokens):

```
python $env:USERPROFILE\.claude\skills\manuscript-editor\toolkit\prose_tools.py tics <file>        # repeated tag verbs + body-beat/adverb tics, per-1k density
python $env:USERPROFILE\.claude\skills\manuscript-editor\toolkit\prose_tools.py paras <file>       # one-sentence-paragraph rate and clustering
python $env:USERPROFILE\.claude\skills\manuscript-editor\toolkit\prose_tools.py tags-patch <file> --out <tags.json>
python $env:USERPROFILE\.claude\skills\manuscript-editor\toolkit\prose_tools.py merge-patch <file> --out <merge.json>
```

- **Tics** (`said/replied/asked…`, `swallowed`, `nodded`, `for a moment`, `quietly`…): the tool
  counts and flags overuse. `tags-patch` proposes context-aware swaps for overused *dialogue tags
  only* (question → asked/pressed, exclamation → called/snapped, etc.), rotating so no new verb
  gets overused. Those are mechanical picks — **read each one and improve or drop it** (LLM
  fallback: some tags are better replaced by an action beat or removed entirely). Body-beat tics
  (`swallowed`, `nodded`, `breath caught`) are report-only: propose fitting replacements by hand,
  since a good swap depends on the scene.
- **One-sentence paragraphs**: `paras` reports the rate (>35% of narration = a habit worth
  checking). `merge-patch` proposes joining runs of consecutive *mid-length* narration one-liners
  (7+ words) into one paragraph; short punch lines (≤6 words) and dialogue are deliberately left
  alone since those usually work. LLM fallback: skim each proposed merge and drop any where the
  line break is doing real work (a beat, a reveal, a pacing pause).
- Both patch files are the standard patch JSON: present them as a proposal (Propose step), get
  approval, then `nw_tool.py patch <dir> <handle> <file> --dry-run` and apply as usual — same
  lock check, backup, and logging rules as any other edit. Never apply without approval.

## Story read (judgment — this is the LLM's job)

When asked how the story is going, or after a batch of chapters, give a reader-level read and
keep it in `_edits/story_notes.md` (template created by `init_tracking.py`): are you hooked, and
where did momentum dip; what's working; what could be better; how each main character's arc is
progressing (started → now → working?); open threads. Ground it in `stats`/`paras` numbers where
they help (e.g. pacing = dialogue ratio and paragraph length) rather than vibes alone. Be honest
and specific — quote the moment, not the general feeling.

## Chapter review & overall feel

After any chapter pass (or on request), give a short review in this shape — keep it tight, one
block per chapter, and append it to `_edits/story_notes.md` under "Chapter reviews":

```
### <Chapter label> — <hook rating: hooked / steady / drifting>
**Summary:** 2-3 sentences of what actually happens (plot, not vibes).
**Overall feel:** one or two sentences on tone, pacing, emotional temperature, and how it lands
as a reader (tense, warm, rushed, slack, earned…).
**Best moment:** the line/scene that worked, quoted or pinpointed.
**Weakest moment:** what dragged, confused, or felt unearned — and why.
**Habits this chapter:** one line from `prose_tools.py` (tag-verb overuse, one-sentence-paragraph
rate, top body-beat tic) so trends are visible chapter to chapter.
```

Get the numbers from the toolkit (`stats`, `paras`, `tics`) first, then write the judgment
around them. When reviewing a batch, finish with a brief **overall feel** paragraph across the
whole run — trajectory (building / plateauing / sagging), how the character arcs are moving, and
the single most valuable thing to fix next.

## Query letters / synopses

If asked to draft or revise a query letter, synopsis, or comp titles for a manuscript, work in
`_edits/query_and_synopsis.md` for that project — append new drafts under a `---` separator
rather than deleting old ones, so draft history isn't lost.
