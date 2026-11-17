#!/usr/bin/env python3
"""
continuity_tools.py - continuity ledger + mechanical continuity flags, within and between
scenes (and across chapters when several files are given in reading order).

The tool does the bookkeeping a person loses track of: who is in each scene, time of day,
weather, places, injuries, clothing, timeline phrases ("three weeks", "two years old"), spelling
variants of names, a character acting after they left. Everything it flags is a *question for the
editor*, not a verdict - flashbacks, dreams and deliberate nicknames trip it, and only someone who
has read the scene can tell. No LLM inside.

Usage:
  python continuity_tools.py ledger <file>... [--brief] [--known "Karni=Karnika,Shesh=Shesha"]
      one block per scene (words, time, weather, places, who, body state, clothing, timeline
      phrases) followed by FLAGS. Pass chapters in reading order to get between-scene and
      between-chapter flags. --brief prints only the flags.
  python continuity_tools.py names <file>... [--known ...]
      proper-noun counts + spelling variants only
  python continuity_tools.py state <file> [--append <path>]
      the end-of-chapter state (last scene) as a markdown block, for _edits/continuity.md, so the
      next chapter's pass starts from where this one ended

Files come from `nw_tool.py get/flat-get --out FILE` (or `export`).
"""
import argparse
import difflib
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prose_tools import read, words, TAG_VERBS  # noqa: E402

SCENE_BREAK = re.compile(r"^[ \t]*(?:~+|\*[ \t]*\*[ \t]*\*|\*{3,}|-{3,})[ \t]*$", re.M)
INTERJ = {"Hey", "Hmm", "Mmm", "Ahh", "Huh", "Yeah", "Okay", "Alright", "Nope", "Yep", "Err", "Umm", "Uhh", "Ooh", "Aww",
          "Oof", "Tch", "Heh", "Ugh", "Ouch", "Whoa", "Damn", "Shit", "Fuck", "God", "Mom", "Dad"}
DAYS_MONTHS = {"Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday", "January", "February",
               "March", "April", "June", "July", "August", "September", "October", "November", "December"}

TIME_RX = {
    "morning": r"\b(?:dawn|sunrise|early morning|morning|breakfast|daybreak)\b",
    "noon": r"\b(?:noon|midday|lunch(?:time)?)\b",
    "afternoon": r"\bafternoon\b",
    "evening": r"\b(?:evening|dusk|sunset|twilight|dinner|nightfall)\b",
    "night": r"\b(?:night|midnight|moonlight|moon|stars|after dark|past midnight)\b",
}
TIME_ORDER = {"morning": 1, "noon": 2, "afternoon": 2, "evening": 3, "night": 4}
ADVANCE_RX = re.compile(
    r"\b(?:next (?:day|morning|evening|week|month)|the following|(?:days?|weeks?|months?|years?) later|"
    r"that (?:evening|night|morning|afternoon)|yesterday|tomorrow|the (?:day|night) before|"
    r"(?:a|one|two|three|four|five|six|several) (?:days?|weeks?|months?|years?) (?:later|after)|by morning|the morning after)\b", re.I)
FLASH_RX = re.compile(r"\b(?:memory|dissolv\w*|flashback|years ago|back then|the park came back|came back into focus)\b", re.I)
WEATHER_RX = {
    "sun": r"\b(?:sunny|sunlight|sunshine|sun)\b", "clouds": r"\b(?:clouds?|cloudy|overcast)\b",
    "rain": r"\b(?:rain(?:ing|ed|y)?|drizzle|downpour|umbrellas?)\b", "storm": r"\b(?:storm|thunder|lightning)\b",
    "wind": r"\b(?:breeze|wind)\b", "fog": r"\b(?:fog|mist)\b",
}
BODY_RX = re.compile(r"\b(?:bruis\w+|bleed\w*|blood\w*|split lip|swollen|limp(?:ed|ing|s)?|crutch(?:es)?|stitch(?:es)?|bandag\w+|"
                     r"sling|black eye|wounds?|wounded|sprain\w*|plaster|scar(?:s|red)?|dettol|swab)\b", re.I)
# stems worth carrying across scenes (blood/scar/swab also show up as other people's injuries or props)
BODY_STEMS = ["bruis", "swollen", "limp", "crutch", "stitch", "bandag", "sling", "sprain", "wounded"]
COLORS = ("white|black|blue|red|green|yellow|pink|grey|gray|cream|brown|orange|purple|maroon|navy|charcoal|beige|"
          "golden|silver|khaki|turquoise|teal|lavender")
GARMENTS = ("shirt|kurta|dress|jacket|tie|saree|sari|hoodie|blouse|trousers|jeans|gown|lehenga|sweater|uniform|"
            "scarf|dupatta|coat|suit|shorts|skirt|pullover|t-shirt|tee")
CLOTH_RX = re.compile(r"\b(%s)\b[ -](?:\w+[ -]){0,2}?\b(%s)\b" % (COLORS, GARMENTS), re.I)
NUM_WORDS = ("one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
             "twenty|thirty|forty|fifty|sixty|hundred|couple of|few|several")
NUM_RX = re.compile(r"\b(?:(\d+)|(%s))(?:[- ](?:one|two|three|four|five|six|seven|eight|nine))?\s+(?:more |whole |good )?"
                    r"(years?|months?|weeks?|days?|hours?|minutes?|semesters?)\b(?:[- ](old)|\s+(ago|later|before|after|since))?"
                    % NUM_WORDS, re.I)
PLACE_RX = re.compile(r"\b(?:in|at|inside|outside|into|onto|across|beside|near|behind|from|to|through|under) the ([a-z]{3,})\b")
PLACE_SKIP = {"way", "moment", "middle", "end", "other", "back", "front", "rest", "same", "first", "next", "sound",
              "sight", "air", "world", "past", "dark", "light", "distance", "edge", "side", "top", "bottom"}
# Only unambiguous *leaving the scene* phrases; "stepped out" (of a car) / "walked away" (mid-walk) / "left him to it" are not.
EXIT_RX = r"(?:left(?= (?:the (?:room|house|hall|office|class(?:room)?|table|bench|park|building|stage|plaza|campus|car)|for\b|early|abruptly|without)|[.,])|" \
          r"walked out|stormed out|hurried out|rushed out|drove off|drove away|hung up|ended the call|" \
          r"went inside|headed (?:home|inside|upstairs))"
MOVE_RX = re.compile(r"\b(?:walked|walking|followed|continued|ran|hurried|drove|rode|turned|stepped|crossed)\b", re.I)
REENTRY_RX = re.compile(r"\b(?:returned|came back|re-?entered|walked in|stepped in|entered|arrived|appeared|joined|rejoined|"
                        r"came in|came over|was back|were back|got back|reached)\b", re.I)
PHONE_RX = re.compile(r"\b(?:phone|call|voice|text|message|line|speaker|on the other)\b", re.I)
_verbs = "|".join(v.replace(" ", r"\s+") for v in TAG_VERBS)


CAPS_MID = [Counter()]  # filled by corpus_names(); mid-sentence capitalised counts
TRANSITION_RX = re.compile(r"\b(?:dissolv\w*|came back into focus|slowly gave way|memory (?:faded|receded|slowly)|"
                           r"the (?:park|room|campus|scene) (?:came|settled|spread)\b)", re.I)


def split_sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?…”\"])\s+(?=[A-Z“\"])", text) if s.strip()]


def load(files):
    chapters = []
    for f in files:
        t = read(f)
        m = re.search(r"^#{1,6}\s+(.*\S)", t, re.M)
        label = m.group(1).strip() if m else Path(f).stem
        body = t[m.end():] if m else t
        scenes = []
        for part in SCENE_BREAK.split(body):
            cur = []
            for para in re.split(r"\n\s*\n", part.strip()):
                # a flashback/frame transition ("the park dissolved...") opens a new scene even without a ~ break
                if TRANSITION_RX.search(para) and cur:
                    scenes.append("\n\n".join(cur))
                    cur = []
                cur.append(para)
            if cur and "\n\n".join(cur).strip():
                scenes.append("\n\n".join(cur))
        chapters.append({"label": label, "file": f, "scenes": [s.strip() for s in scenes if s.strip()]})
    return chapters


def corpus_names(chapters):
    lower, caps = set(), Counter()
    texts = [s for c in chapters for s in c["scenes"]]
    for t in texts:
        for m in re.finditer(r"\b[a-z][a-z’']+\b", t):
            lower.add(m.group())
    for t in texts:
        for m in re.finditer(r"\b[A-Z][a-z]{2,}(?:[’']s)?\b(?![’']t\b)", t):
            w = re.sub(r"[’']s$", "", m.group())
            if w.lower() not in lower and w not in INTERJ and w not in DAYS_MONTHS:
                caps[w] += 1
    # A real name shows up capitalised *mid-sentence* ("said Karni", "with Samvardhak"); a capitalised
    # sentence-opener ("Deflecting", "Thanks") never does. Used to keep common words out of variant checks.
    mid = Counter()
    for t in texts:
        for m in re.finditer(r"(?:[a-z,;]|[”\"’'])[ \t]+([A-Z][a-z]{2,})(?:[’']s)?\b", t):
            if m.group(1) in caps:
                mid[m.group(1)] += 1
    CAPS_MID[0] = mid
    return caps  # every capitalised never-lowercase word, count>=1 (rare ones matter for typo detection)


def parse_known(spec):
    out = set()
    for pair in (spec or "").split(","):
        if "=" in pair:
            a, b = (x.strip() for x in pair.split("=", 1))
            out.add(frozenset((a, b)))
    return out


def name_variants(caps, known):
    names = sorted(caps)
    out = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if frozenset((a, b)) in known or a[0] != b[0]:
                continue
            if not (CAPS_MID[0][a] or CAPS_MID[0][b]):
                continue  # neither ever appears mid-sentence: probably ordinary sentence-opening words
            al, bl = a.lower(), b.lower()
            ratio = difflib.SequenceMatcher(None, al, bl).ratio()
            short = (al.startswith(bl) or bl.startswith(al)) and min(len(a), len(b)) >= 4
            dl = abs(len(a) - len(b))
            sim = (ratio >= 0.84 and dl <= 2) or (ratio >= 0.8 and min(len(a), len(b)) >= 6 and dl <= 1)
            if sim or short:
                lo, hi = sorted((caps[a], caps[b]))
                if hi < 3 and min(len(a), len(b)) < 6:
                    continue  # two rare short words resembling each other is noise; longer names (minor characters) still count
                typo = lo <= 3 and hi >= 10 and not short
                out.append((a, b, caps[a], caps[b], typo))
    return sorted(out, key=lambda x: (not x[4], x[0]))


def scene_info(text, names):
    info = {"words": words(text)}
    t_low = text.lower()
    tc = {k: len(re.findall(rx, t_low)) for k, rx in TIME_RX.items()}
    tc = {k: v for k, v in tc.items() if v}
    info["time"] = tc
    info["time_primary"] = max(tc, key=lambda k: (tc[k], TIME_ORDER[k])) if tc else None
    info["weather"] = {k: len(re.findall(rx, t_low)) for k, rx in WEATHER_RX.items() if re.search(rx, t_low)}
    info["advance"] = bool(ADVANCE_RX.search(text[:700]))
    info["flash"] = bool(FLASH_RX.search(text[:300]) or FLASH_RX.search(text[-300:]))
    pc = Counter(m.group(1) for m in PLACE_RX.finditer(text) if m.group(1).split()[0] not in PLACE_SKIP)
    info["places"] = [p for p, _ in pc.most_common(4)]
    who = Counter()
    for n in names:
        c = len(re.findall(r"\b%s\b" % re.escape(n), text))
        if c:
            who[n] = c
    info["who"] = who.most_common(7)
    info["body"] = sorted({m.group().lower() for m in BODY_RX.finditer(text)})
    clothes = []
    for s in split_sentences(text):
        for m in CLOTH_RX.finditer(s):
            owner = next((n for n in names if re.search(r"\b%s\b" % re.escape(n), s[: m.start()])), None)
            if not owner:
                pm = re.match(r"\W*(He|She|His|Her)\b", s)
                owner = {"he": "he", "his": "he", "she": "she", "her": "she"}.get(pm.group(1).lower()) if pm else "?"
            clothes.append((owner, m.group(1).lower(), m.group(2).lower()))
    info["clothes"] = sorted(set(clothes))
    nums = []
    for m in NUM_RX.finditer(text):
        nums.append(" ".join(m.group(0).split()))
    info["numbers"] = nums[:10]
    return info


def exit_then_act(text, names):
    """A named character exits, then acts/speaks in the same scene with no re-entry cue."""
    sents = split_sentences(text)
    flags = []
    for n in names:
        nr = re.escape(n)
        exit_at = None
        for i, s in enumerate(sents):
            if exit_at is None:
                if re.match(r"\W*%s\b.{0,40}?\b%s\b" % (nr, EXIT_RX), s) or re.search(r"door (?:closed|shut|clicked) behind %s" % nr, s):
                    exit_at = i
                continue
            if i - exit_at < 3:
                continue
            if re.match(r"\W*%s\b" % nr, s) or re.search(r"[”\"]\s*%s\s+(?:\w+ly\s+)?(?:%s)\b" % (nr, _verbs), s):
                if MOVE_RX.search(s) or REENTRY_RX.search(s) or PHONE_RX.search(s) or PHONE_RX.search(sents[exit_at]):
                    exit_at = None if REENTRY_RX.search(s) else exit_at
                    continue
                flags.append((n, sents[exit_at], s))
                break
    return flags


def build_flags(scenes, caps, known):
    flags = []
    for a, b, ca, cb, typo in name_variants(caps, known):
        rare = a if ca < cb else b
        loc = next((f"{sc['label']} / scene {sc['n']}" for sc in scenes if re.search(r"\b%s\b" % rare, sc["text"])), "?")
        kind = "likely typo" if typo else "variant or nickname - confirm intended"
        flags.append(f"NAME {a} ({ca}) vs {b} ({cb}): {kind}; rarer form {rare!r} first seen {loc}")
    for sc in scenes:
        for n, ex, act in exit_then_act(sc["text"], [n for n, _ in sc["info"]["who"]]):
            flags.append(f"EXIT-THEN-ACT {sc['label']} / scene {sc['n']}: {n} leaves ({ex[:70]!r}) but later: {act[:90]!r}")
        byg = {}
        for owner, color, garment in sc["info"]["clothes"]:
            byg.setdefault((owner, garment), set()).add(color)
        for (owner, garment), cols in byg.items():
            if len(cols) > 1 and owner != "?":
                flags.append(f"CLOTHING {sc['label']} / scene {sc['n']}: {owner}'s {garment} is {' and '.join(sorted(cols))}")
        w = sc["info"]["weather"]
        if "rain" in w and "sun" in w:
            flags.append(f"WEATHER {sc['label']} / scene {sc['n']}: sun and rain both mentioned - transition shown?")
    for prev, cur in zip(scenes, scenes[1:]):
        same_ch = prev["label"] == cur["label"]
        pi, ci = prev["info"], cur["info"]
        quiet = ci["advance"] or pi["flash"] or ci["flash"]
        strong = pi["time_primary"] and ci["time_primary"] and pi["time"][pi["time_primary"]] >= 2 and ci["time"][ci["time_primary"]] >= 2
        if same_ch and not quiet and strong and TIME_ORDER[ci["time_primary"]] < TIME_ORDER[pi["time_primary"]]:
            flags.append(f"TIME {cur['label']} scene {prev['n']}->{cur['n']}: {pi['time_primary']} then {ci['time_primary']} with no time cue (flashback?)")
        if not quiet:
            lost = [s for s in BODY_STEMS if
                    len(re.findall(r"\b%s\w*" % s, prev["text"], re.I)) >= 3 and not re.search(r"\b%s\w*" % s, cur["text"], re.I)]
            if lost:
                flags.append(f"STATE {prev['label']}/{prev['n']} -> {cur['label']}/{cur['n']}: {', '.join(lost)} mentioned (2+x) then gone - healed or forgotten?")
            pc = {(o, g): c for o, c, g in []}
            for owner, color, garment in pi["clothes"]:
                for o2, c2, g2 in ci["clothes"]:
                    if owner == o2 and garment == g2 and color != c2 and owner != "?":
                        flags.append(f"CLOTHING {prev['label']}/{prev['n']} -> {cur['label']}/{cur['n']}: {owner}'s {garment} {color} then {c2}, no time cue")
    return flags


def prepare(files, known_spec):
    chapters = load(files)
    caps = corpus_names(chapters)
    scenes = []
    for ch in chapters:
        for n, text in enumerate(ch["scenes"], 1):
            scenes.append({"label": ch["label"], "n": n, "text": text})
    names = [n for n, c in caps.items() if c >= 3]
    for sc in scenes:
        sc["info"] = scene_info(sc["text"], names)
    return chapters, caps, scenes


def fmt_scene(sc):
    i = sc["info"]
    t = ", ".join(f"{k}x{v}" for k, v in i["time"].items()) or "-"
    w = ", ".join(i["weather"]) or "-"
    who = " ".join(f"{n}({c})" for n, c in i["who"]) or "-"
    cl = "; ".join(f"{o}: {c} {g}" for o, c, g in i["clothes"][:6]) or "-"
    mark = " [flashback?]" if i["flash"] else ""
    adv = " [time-advance cue]" if i["advance"] else ""
    lines = [f"[{sc['label']} | scene {sc['n']}] {i['words']}w{mark}{adv}",
             f"   time: {t}   weather: {w}   places: {', '.join(i['places']) or '-'}",
             f"   who: {who}",
             f"   body: {', '.join(i['body']) or '-'}   clothing: {cl}"]
    if i["numbers"]:
        lines.append(f"   timeline phrases: {'; '.join(i['numbers'])}")
    return "\n".join(lines)


def cmd_ledger(args):
    chapters, caps, scenes = prepare(args.files, None)
    if not args.brief:
        for sc in scenes:
            print(fmt_scene(sc))
        print()
    flags = build_flags(scenes, caps, parse_known(args.known))
    print(f"FLAGS ({len(flags)}) - each is a question for the editor, not a verdict:")
    for f in flags:
        print("  - " + f)
    if not flags:
        print("  none")


def cmd_names(args):
    chapters, caps, scenes = prepare(args.files, None)
    print("names (count>=2): " + ", ".join(f"{n} {c}" for n, c in caps.most_common(40)))
    for a, b, ca, cb, typo in name_variants(caps, parse_known(args.known)):
        print(f"  variant: {a} ({ca}) vs {b} ({cb}) - {'likely typo' if typo else 'nickname/variant? confirm'}")


def cmd_state(args):
    chapters, caps, scenes = prepare([args.file], None)
    sc = scenes[-1]
    i = sc["info"]
    last = " ".join(split_sentences(sc["text"])[-2:])
    block = [f"### {sc['label']} - end state (auto)",
             f"- scene {sc['n']} of {len(scenes)}; time: {', '.join(i['time']) or '?'}; weather: {', '.join(i['weather']) or '?'}; places: {', '.join(i['places']) or '?'}",
             f"- present/active: {', '.join(n for n, _ in i['who']) or '?'}",
             f"- body state: {', '.join(i['body']) or 'none noted'}",
             f"- clothing: {'; '.join(f'{o}: {c} {g}' for o, c, g in i['clothes']) or 'none noted'}",
             f"- last beat: {last[:240]}",
             "- (editor: add facts the next chapter must honour - injuries, who knows what, objects in hand, promises made)"]
    out = "\n".join(block) + "\n"
    if args.append:
        p = Path(args.append)
        with p.open("a", encoding="utf-8") as fh:
            fh.write("\n" + out)
        print(f"appended end-state block -> {p}")
    print(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ledger"); p.add_argument("files", nargs="+"); p.add_argument("--brief", action="store_true")
    p.add_argument("--known"); p.set_defaults(func=cmd_ledger)
    p = sub.add_parser("names"); p.add_argument("files", nargs="+"); p.add_argument("--known"); p.set_defaults(func=cmd_names)
    p = sub.add_parser("state"); p.add_argument("file"); p.add_argument("--append"); p.set_defaults(func=cmd_state)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
