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
  `.md` (novelWriter 26.x) or legacy `.nwd` document files (e.g. anything under `C:\Users\Acer\Documents\Novels\<Project>`). Use the
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
  against `_edits/open_issues.md`, `_edits/continuity.md` and any Living Reference for that
  project if one exists. Run the **Continuity pass** below on every chapter, and the
  **Action-beat pass** when the prose leans on reaction beats.

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
  (`swallowed`, `nodded`, `breath caught`, `glanced`) are handled by the **Action-beat pass**
  below, which decides keep / drop / trim / refine per beat — don't thin them by count alone.
- **One-sentence paragraphs**: `paras` reports the rate (>35% of narration = a habit worth
  checking). `merge-patch` proposes joining runs of consecutive *mid-length* narration one-liners
  (7+ words) into one paragraph; short punch lines (≤6 words) and dialogue are deliberately left
  alone since those usually work. LLM fallback: skim each proposed merge and drop any where the
  line break is doing real work (a beat, a reveal, a pacing pause).
- **Named pauses / "beats"** (`a beat`, `a pause`, `for a moment`, `silence stretched`, `no one
  spoke`…): `prose_tools.py pauses <file>` lists each one with the paragraphs before and after.
  It's **report-only on purpose** — the author wants a pause that *isn't named*: replace the
  label with a small action or an environment moment drawn from the scene itself (she settled
  back on the bench; leaves rustled overhead; the kettle ticked as it cooled), so the reader
  feels the pause without being told there is one. Build each replacement from objects, setting
  and habits already in the surrounding paragraphs — don't invent new props. Some hits are
  legitimate action (`hands braced on her thighs for a moment`) — judge each in context and
  leave those alone. Propose replacements as old→new patches like any other edit.
- **False positives — read the numbers with this in mind.** Dialogue back-and-forth looks like
  a pile of one-line paragraphs, but it's normal exchange rhythm. `paras` therefore excludes any
  paragraph containing spoken dialogue from "narration", and reports one-line beats that sit
  next to dialogue separately (as "exchange beats", not counted). The habit is the *standalone*
  one-liners and, above all, long unbroken runs of them. Same for `merge-patch`: it only ever
  joins consecutive narration-only one-liners, never anything with dialogue in it.
- Both patch files are the standard patch JSON: present them as a proposal (Propose step), get
  approval, then `nw_tool.py patch <dir> <handle> <file> --dry-run` and apply as usual — same
  lock check, backup, and logging rules as any other edit. Never apply without approval.

## Action-beat pass (toolkit finds and builds the patch, the editor decides)

An *action beat* is a short narration sentence that shows a reaction or gesture instead of
dialogue (`He nodded.` / `She looked away.` / `His jaw tightened.`). The author uses them on
purpose, and a beat that **replaces a line of dialogue with a reaction is a strength**. The
complaint to fix is the beats that repeat or pad. So the default for a beat is KEEP; you are
looking for the ones that don't earn their place.

```
python $env:USERPROFILE\.claude\skills\manuscript-editor\toolkit\beat_tools.py beats <file> --json <scratch>\beats.json
```
prints the beat density, **repeated stock beats** (`glanced x19: B5 B6 ...`), **dense exchanges**
(a beat on nearly every line of a back-and-forth), and the **candidates** (beats flagged by two or
more of: repeat, close-repeat, chain, kind-cluster, dense-exchange) each with the line before and
after. Beats that aren't flagged are left alone. `--all` lists everything, `--min-flags 1` widens it.

For each candidate — and for each repeated group as a whole — read it in the chapter and decide:

- **KEEP** — it carries something the words don't: subtext that contradicts the line, a reaction
  standing in for a reply, a shift in power or intimacy; or it is the *best single instance* of a
  gesture the scene needs once. In a repeated group, keep the best one or two.
- **DROP** — it restates the line (`"I'm sorry." He looked apologetic.`), repeats what the previous
  beat already told us, is a stock gesture with no job (a nod after an answer that was already
  clear), or slows a quick exchange. In a dense exchange most beats go; a beat lands best at the
  turn of the exchange, roughly one line in three or four.
- **TRIM** — the gesture is right but padded: a stacked second beat saying the same thing (keep
  the stronger), an adverb (`slowly`, `quietly`), `for a moment`, or a tag with a participle
  (`"No," she said, shaking her head.` → keep the tag, drop the participle).
- **REFINE** — the job is real but the gesture is generic and has appeared again and again.
  Replace it with something specific built from objects, setting and habits already in the scene
  (same rule as unnamed pauses — never invent props), or move it to a different channel (an action
  on an object, a change in distance, the environment) so the beat does one *new* thing.

Repetition is judged per chapter *and* across the run: the same key at most about three times a
chapter unless it is a deliberate motif (ask the author; note motifs in `_edits/style_guide.md`).
Also check a drop doesn't lose information — a beat that was the only attribution, a stage
direction the next line depends on, a plant the later chapters use. `beats-patch` warns when a drop
may blur who is speaking or fuse two quoted lines into one paragraph.

Write the decisions, then let the tool build the patch (validated, paragraph-level, same format as
every other patch):

```
decisions.json: [{"id":"B13","action":"drop","why":"turn is implied"},
                 {"id":"B16","action":"trim","new":"Karni laughed.","why":"stacked with B17"},
                 {"id":"B26","action":"refine","new":"He thumbed the strap of his bag.","why":"stock gesture"}]
python ...\beat_tools.py beats-patch <file> --cands <scratch>\beats.json --decisions <decisions.json> --out <patch.json> --md <proposal_table.md>
python ...\nw_tool.py patch <dir> <handle> <patch.json> --dry-run
```
`new` replaces the whole beat sentence (include its final punctuation). The `--md` table is the
before/after proposal for the Propose step: show it, wait for approval, then apply and log as usual
(note counts: `N beats dropped, N trimmed, N refined`). The tool refuses to build a patch if the
chapter changed since `beats --json` ran — re-run it.

## Continuity pass (toolkit keeps the ledger, the editor judges)

Continuity errors live *within* a scene (who is holding what, where people stand, what the light is
doing), *between* scenes (does scene N+1 start where N left off?) and *across* chapters (ages,
injuries, who knows what, how long ago). Do this on every chapter pass, and run it over several
chapters in reading order whenever you can.

1. **Start from canon.** Read `_edits/continuity.md` (template created by `init_tracking.py`): the
   facts already established and the previous chapter's end-state block. If the project has a
   Living Reference or character notes, skim those too.
2. **Run the ledger** on the chapter — and on the previous chapter before it, so between-chapter
   flags work:
   ```
   python $env:USERPROFILE\.claude\skills\manuscript-editor\toolkit\continuity_tools.py ledger <prev.txt> <this.txt> [--known "Karni=Karnika,Shesh=Shesha"]
   ```
   One block per scene (flashback transitions like "the park dissolved…" count as scene breaks):
   words, time of day, weather, places, who is present, body state, clothing, timeline phrases
   (`three weeks`, `nine year old`). Then **FLAGS** — name spelling variants (`Shrish` vs `Shirish`),
   someone acting after they left, clothing that changes colour, an injury that vanishes, time of
   day running backwards with no cue. `--brief` prints only flags; `names` prints just the names.
   Every flag is a *question*, not a verdict: flashbacks, dreams, deliberate nicknames and
   interrupted names (`"Lin—"`) trip it. Give each flag a verdict — real error (propose the fix),
   intentional (record it in `continuity.md` / `--known`), or false positive.
3. **Then read for what the tool can't see.** Check, scene by scene:
   - **Staging** — who is where; what is in whose hands; objects picked up and never put down;
     doors, seats, vehicles; a character speaking or acting from a place they can't be in.
   - **Time and weather in-scene** — light, meals, how long things take; the present-day frame
     keeps its own clock across the flashbacks (the weather and light there should progress).
   - **Bodies** — injuries, tiredness, illness, pregnancy stage, ages against the years stated,
     clothing; and what each does to what they can do next.
   - **Knowledge** — nobody knows something before they're told; nobody forgets what mattered.
   - **Timeline arithmetic** — compare the ledger's timeline phrases against each other and against
     `continuity.md` (`almost two years` here vs `four months` there).
   - **Names and address** — titles, nicknames, who calls whom what (consistent per speaker).
   - **Repeated facts** told twice differently (a backstory narrated in two chapters; a line quoted
     back inaccurately).
   - **Between scenes** — set the *end* of scene N against the *start* of scene N+1: place, time gap
     acknowledged, state carried over (mood, injuries, objects), anything that changed off-page
     that the reader needs.
4. **Propose.** A contradiction with an obvious fix → an old→new patch. A contradiction where the
   author must choose which fact is canon → don't guess: list it under **Continuity questions** in
   the proposal and in `_edits/open_issues.md`. Quote both places with chapter and scene.
5. **Close the loop.** After the chapter is final, add new canon facts to `continuity.md` and append
   the end state: `continuity_tools.py state <chapter.txt> --append <project>\_edits\continuity.md`
   (then add what only you know: promises made, what each character now knows).

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
**Habits this chapter:** one line from `prose_tools.py` / `beat_tools.py` (tag-verb overuse,
one-sentence-paragraph rate, beats per 1k words and the top repeated beat) so trends are visible
chapter to chapter.
```

Get the numbers from the toolkit (`stats`, `paras`, `tics`) first, then write the judgment
around them. When reviewing a batch, finish with a brief **overall feel** paragraph across the
whole run — trajectory (building / plateauing / sagging), how the character arcs are moving, and
the single most valuable thing to fix next.

## Query letters / synopses

If asked to draft or revise a query letter, synopsis, or comp titles for a manuscript, work in
`_edits/query_and_synopsis.md` for that project — append new drafts under a `---` separator
rather than deleting old ones, so draft history isn't lost.
