#!/usr/bin/env python3
"""
prose_tools.py - deterministic prose-habit analysis and patch generation. Works on a plain
text chapter file (get one with `nw_tool.py get/flat-get --out FILE`). No LLM involved; output
patch files are in the same JSON format `nw_tool.py patch` consumes, so the flow is:
analyze -> propose patch JSON -> user approves -> `nw_tool.py patch --dry-run` -> apply.

Commands:
  tics <file>                 dialogue-tag verbs + body-beat/adverb tics: counts, per-1000-word
                               density, and which are overused
  tags-patch <file> [--out F]  propose varied dialogue tags for overused verbs (patch JSON)
  paras <file>                one-sentence-paragraph stats + where they cluster
  merge-patch <file> [--out F] propose merging runs of one-sentence narration paragraphs
                               (patch JSON); deliberate short punch lines are left alone
  stats <file>                words, paragraphs, dialogue ratio, avg paragraph length
"""
import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

TAG_VERBS = [
    "said", "replied", "asked", "muttered", "whispered", "murmured", "snapped", "called",
    "shouted", "added", "answered", "breathed", "sighed", "groaned", "laughed", "chuckled",
    "hummed", "scoffed", "quipped", "declared", "admitted", "warned", "pressed", "cut in",
]
BODY_TICS = [
    r"swallow(?:ed|s)?", r"breath (?:caught|hitched|left)", r"heart (?:hammered|thudded|skipped|lurched|pounded|raced)",
    r"throat (?:tightened|closed|bobbed)", r"nodded", r"shrugged", r"jaw (?:tensed|tightened|clenched)",
    r"eyes (?:widened|softened|narrowed)", r"exhaled", r"blinked", r"stiffened", r"frowned",
    r"smiled (?:faintly|slightly|softly)", r"a beat", r"for a moment", r"for a second",
    r"quietly", r"softly", r"faintly", r"slowly", r"gently", r"slightly",
]
OPENERS_MIN_REPEAT = 4

# Alternatives grouped by what the line does. Kept plain on purpose - "said" stays the workhorse.
ALT_STATEMENT = ["said", "offered", "put in", "went on", "continued", "remarked", "noted"]
ALT_QUESTION = ["asked", "pressed", "wondered aloud", "prodded"]
ALT_EXCLAIM = ["called", "snapped", "shot back", "cried", "protested"]
ALT_QUIET = ["murmured", "said quietly", "admitted", "confessed"]
ALT_REPLY = ["answered", "returned", "countered", "shot back", "said"]

CLOSE_Q = "”\""  # curly and straight closing quotes


def read(path):
    return Path(path).read_text(encoding="utf-8-sig")


def words(text):
    return len(re.findall(r"\b[\w'’-]+\b", text))


def paragraphs(text):
    return [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]


def is_dialogue(p):
    """Any paragraph that contains spoken dialogue - starts with a quote, or has a quoted line
    embedded (e.g. 'She whispered, "No."'). These are exchange lines, never narration."""
    return "“" in p or '"' in p


def sentence_count(p):
    return len([s for s in re.split(r"(?<=[.!?])[”\"')\]]*\s+", p.strip()) if s.strip()])


def is_break_or_heading(p):
    s = p.strip()
    return s.startswith("#") or s in ("~", "* * *", "***", "---")


# ---------------------------------------------------------------- tics

TAG_RE = re.compile(
    r"([" + CLOSE_Q + r"])(\s*,?\s*)((?:[A-Z][a-z]+|he|she|they|I)\s+)?(" + "|".join(TAG_VERBS) + r")\b",
    re.IGNORECASE,
)


def tag_hits(text):
    return [m for m in TAG_RE.finditer(text)]


def cmd_tics(args):
    text = read(args.file)
    wc = max(words(text), 1)
    per1k = lambda n: round(n * 1000 / wc, 1)

    hits = tag_hits(text)
    verb_counts = Counter(m.group(4).lower() for m in hits)
    total_tags = sum(verb_counts.values())
    print(f"== Dialogue tags ({total_tags} found, {per1k(total_tags)}/1k words) ==")
    for verb, n in verb_counts.most_common():
        share = round(100 * n / total_tags) if total_tags else 0
        flag = "  <-- overused" if verb != "said" and n >= 4 and share >= 15 else ""
        print(f"  {verb:<12} {n:>3}  ({share}%){flag}")

    print("\n== Body-beat / adverb tics ==")
    rows = []
    for pat in BODY_TICS:
        n = len(re.findall(pat, text, re.IGNORECASE))
        if n:
            rows.append((n, pat))
    for n, pat in sorted(rows, reverse=True):
        flag = "  <-- watch" if n >= 4 else ""
        print(f"  {pat:<38} {n:>3}  ({per1k(n)}/1k){flag}")

    print("\n== Repeated sentence openers ==")
    openers = Counter()
    for s in re.split(r"(?<=[.!?])\s+", text):
        m = re.match(r"\W*([A-Z][a-z']+)", s)
        if m:
            openers[m.group(1)] += 1
    rep = [(w, n) for w, n in openers.most_common(8) if n >= OPENERS_MIN_REPEAT and w not in ("The", "A")]
    for w, n in rep:
        print(f"  {w:<10} {n}")
    if not rep:
        print("  none notable")


def pick_pool(quote_text, tag_text):
    q = quote_text.rstrip(CLOSE_Q + " ,").rstrip()
    if q.endswith("?"):
        return ALT_QUESTION
    if q.endswith("!"):
        return ALT_EXCLAIM
    if len(q) < 25:
        return ALT_REPLY
    return ALT_STATEMENT


def cmd_tags_patch(args):
    text = read(args.file)
    hits = tag_hits(text)
    counts = Counter(m.group(4).lower() for m in hits)
    total = sum(counts.values())
    overused = {v for v, n in counts.items() if v != "said" and n >= 4 and n * 100 / max(total, 1) >= 15}
    # "said" is invisible; only trim it if it's dominating (>60%)
    if counts.get("said", 0) * 100 / max(total, 1) > 60:
        overused.add("said")

    patches, used, seen_old = [], Counter(), set()
    seen_verb_idx = Counter()
    for m in hits:
        verb = m.group(4).lower()
        if verb not in overused:
            continue
        seen_verb_idx[verb] += 1
        keep_every = 3 if verb == "said" else 2  # leave every Nth occurrence as-is
        if seen_verb_idx[verb] % keep_every == 1:
            continue
        # context: back up to the start of the quote so the "old" string is unique
        start = text.rfind("“", 0, m.start())
        if start == -1:
            start = text.rfind('"', 0, m.start())
        if start == -1 or m.end() - start > 400:
            continue
        old = text[start:m.end()]
        if old in seen_old or text.count(old) != 1:
            continue
        pool = [w for w in pick_pool(text[start:m.start() + 1], m.group(4)) if w != verb]
        if not pool:
            continue
        new_verb = min(pool, key=lambda w: used[w])
        used[new_verb] += 1
        new = old[: len(old) - len(m.group(4))] + new_verb
        patches.append({"old": old, "new": new})
        seen_old.add(old)

    out = json.dumps(patches, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
        print(f"{len(patches)} dialogue-tag variation(s) proposed -> {args.out}")
        print("Review them - each is a mechanical suggestion, not a verdict. Then: nw_tool.py patch ... --dry-run")
    else:
        print(out)


# ---------------------------------------------------------- paragraphs

def narration_one_liners(paras):
    return [i for i, p in enumerate(paras)
            if not is_dialogue(p) and not is_break_or_heading(p) and sentence_count(p) == 1]


def cmd_paras(args):
    text = read(args.file)
    paras = [p for p in paragraphs(text) if not is_break_or_heading(p)]
    narr = [p for p in paras if not is_dialogue(p)]
    one = [p for p in narr if sentence_count(p) == 1]
    # A one-line beat next to a dialogue paragraph is normal exchange rhythm (he said / she
    # looked away), not the habit - count only one-liners with no dialogue neighbour.
    beats = 0
    for i, p in enumerate(paras):
        if p in one and ((i > 0 and is_dialogue(paras[i - 1])) or (i + 1 < len(paras) and is_dialogue(paras[i + 1]))):
            beats += 1
    standalone = len(one) - beats
    short = [p for p in one if words(p) <= 6]
    ratio = round(100 * standalone / max(len(narr), 1))
    print(f"paragraphs: {len(paras)}  narration: {len(narr)}  one-sentence narration: {len(one)}")
    print(f"  exchange beats (next to dialogue, excluded): {beats}   standalone one-liners: {standalone} ({ratio}% of narration)")
    print(f"of the one-liners, punchy (<=6 words): {len(short)}   mid-length: {len(one) - len(short)}")
    runs, cur = [], 0
    flat = [(not is_dialogue(p) and sentence_count(p) == 1) for p in paras]
    for f in flat + [False]:
        if f:
            cur += 1
        else:
            if cur >= 2:
                runs.append(cur)
            cur = 0
    print(f"runs of 2+ consecutive one-sentence narration paragraphs: {len(runs)} (longest {max(runs) if runs else 0})")
    verdict = "high" if ratio >= 35 else "moderate" if ratio >= 20 else "low"
    print(f"habit level: {verdict}")


def merge_patches(text, keep_last=True):
    """Merge candidates: runs (max 4) of consecutive mid-length narration one-liners. The final
    paragraph of the chapter is never merged into a run (keep_last) - chapter endings are
    usually deliberate punch lines."""
    blocks = re.split(r"(\n\s*\n)", text.rstrip())
    paras = blocks[0::2]
    seps = blocks[1::2]
    flags = []
    for idx, p in enumerate(paras):
        s = p.strip()
        flags.append(bool(s) and not is_dialogue(s) and not is_break_or_heading(s)
                     and sentence_count(s) == 1 and words(s) > 6  # >6 words: not a punch line
                     and not (keep_last and idx == len(paras) - 1))

    patches, i = [], 0
    while i < len(paras):
        if not flags[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(paras) and flags[j + 1] and j - i < 3:
            j += 1
        if j > i:
            old = "".join(paras[k] + (seps[k] if k < j else "") for k in range(i, j + 1))
            new = " ".join(paras[k].strip() for k in range(i, j + 1))
            if text.count(old) == 1:
                patches.append({"old": old, "new": new})
        i = j + 1
    return patches


def cmd_build_patch(args):
    """One combined patch: auto merges (chapter ending kept intact) + hand-written
    replacements (e.g. unnamed-pause rewrites). Replacements that fall inside a merged span are
    folded into that merge's result so the patches never overlap; the rest become standalone
    edits. Every 'old' must appear exactly once in the chapter or it's reported and skipped."""
    text = read(args.file)
    repls = json.loads(Path(args.replacements).read_text(encoding="utf-8-sig")) if args.replacements else []
    merges = merge_patches(text)
    used, problems = set(), []
    for r in repls:
        if text.count(r["old"]) != 1:
            problems.append(f"replacement not unique/found ({text.count(r['old'])}x): {r['old'][:60]!r}")
    for m in merges:
        for k, r in enumerate(repls):
            if r["old"] in m["old"] and text.count(r["old"]) == 1:
                head = " ".join(m["old"].split())  # spaces-normalised merged form
                m["new"] = m["new"].replace(r["old"], r["new"]) if r["old"] in m["new"] else m["new"]
                used.add(k)
    patches = list(merges)
    for k, r in enumerate(repls):
        if k not in used and text.count(r["old"]) == 1:
            patches.append({"old": r["old"], "new": r["new"]})
    Path(args.out).write_text(json.dumps(patches, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(patches)} patches ({len(merges)} merges, {len(repls) - len(problems)} replacements applied) -> {args.out}")
    for p in problems:
        print("  PROBLEM:", p)


def cmd_merge_patch(args):
    text = read(args.file)
    patches = merge_patches(text)

    out = json.dumps(patches, ensure_ascii=False, indent=2)
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
        print(f"{len(patches)} paragraph merge(s) proposed -> {args.out}")
        print("Only mid-length narration runs are proposed; short punch lines and dialogue are untouched. Review before applying.")
    else:
        print(out)


PAUSE_PATTERNS = [
    r"\ba beat\b(?: passed)?", r"\bbeat of silence\b", r"\ba pause\b", r"\bpaused\b",
    r"\bfor a (?:long )?(?:moment|second|while)\b", r"\bafter a (?:moment|beat|pause|while)\b",
    r"\bsilence (?:stretched|settled|hung|fell|lingered|filled)\b", r"\bfell silent\b",
    r"\bno one (?:spoke|said anything)\b", r"\bneither (?:of them )?(?:spoke|said anything)\b",
    r"\bthe (?:room|air) (?:went|grew|fell) (?:quiet|still|silent)\b", r"\bhush\b",
]
PAUSE_RE = re.compile("|".join(PAUSE_PATTERNS), re.IGNORECASE)


def cmd_pauses(args):
    """Locate every *named* pause (a beat, a pause, for a moment, silence stretched...) with its
    surrounding paragraphs. Report-only on purpose: the fix is an unnamed pause built from the
    scene itself (a small action, an object, the environment), which needs scene knowledge."""
    text = read(args.file)
    paras = [p for p in paragraphs(text) if not is_break_or_heading(p)]
    n = 0
    for i, p in enumerate(paras):
        m = PAUSE_RE.search(p)
        if not m:
            continue
        n += 1
        prev = paras[i - 1][:110].replace("\n", " ") if i > 0 else ""
        nxt = paras[i + 1][:110].replace("\n", " ") if i + 1 < len(paras) else ""
        print(f"[{n}] para {i + 1}  \"{m.group(0)}\"")
        if prev:
            print(f"     before: {prev}")
        print(f"     HERE:   {p[:160].replace(chr(10), ' ')}")
        if nxt:
            print(f"     after:  {nxt}")
    wc = max(words(text), 1)
    print(f"\n{n} named pause(s), {round(n * 1000 / wc, 1)}/1k words")


def cmd_stats(args):
    text = read(args.file)
    paras = [p for p in paragraphs(text) if not is_break_or_heading(p)]
    dia = [p for p in paras if is_dialogue(p)]
    wc = words(text)
    print(f"words: {wc}  paragraphs: {len(paras)}  avg words/paragraph: {round(wc / max(len(paras), 1), 1)}")
    print(f"dialogue paragraphs: {len(dia)} ({round(100 * len(dia) / max(len(paras), 1))}%)")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, has_out in [("tics", cmd_tics, False), ("tags-patch", cmd_tags_patch, True),
                              ("paras", cmd_paras, False), ("merge-patch", cmd_merge_patch, True),
                              ("pauses", cmd_pauses, False), ("stats", cmd_stats, False)]:
        p = sub.add_parser(name)
        p.add_argument("file")
        if has_out:
            p.add_argument("--out")
        p.set_defaults(func=fn)
    p = sub.add_parser("build-patch", help="merges + hand-written replacements -> one combined patch")
    p.add_argument("file")
    p.add_argument("--replacements", help="JSON [{old,new}] of hand-written edits (e.g. unnamed pauses)")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_build_patch)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
