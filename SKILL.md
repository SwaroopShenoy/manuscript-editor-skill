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

## Query letters / synopses

If asked to draft or revise a query letter, synopsis, or comp titles for a manuscript, work in
`_edits/query_and_synopsis.md` for that project — append new drafts under a `---` separator
rather than deleting old ones, so draft history isn't lost.
