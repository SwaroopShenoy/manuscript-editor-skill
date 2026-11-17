#!/usr/bin/env python3
"""
beat_tools.py - action-beat audit. An action beat is a short narration sentence that shows a
reaction or gesture instead of dialogue ("He nodded." / "She looked away." / "His jaw tightened.").
They are often the author's strength (a reaction that replaces a line), and also the commonest
source of padding when the same gesture repeats or restates what was just said.

This tool does the mechanical half: find every beat, group the repeated / stacked / over-dense
ones, and show each with its neighbours. The *decision* per beat - keep, drop, trim, or refine
into a better action - needs the scene, so the editor makes it and hands it back as a small
decisions file; `beats-patch` then turns decisions into a validated paragraph-level patch JSON
(same format `nw_tool.py patch` consumes). No LLM inside.

Commands:
  beats <file> [--json F] [--all] [--max N]
        report + (with --json) write every beat with offsets and an id (B1, B2...) for decisions
  beats-patch <file> --cands F --decisions F --out F [--md F]
        decisions: [{"id":"B7","action":"drop"}, {"id":"B9","action":"trim","new":"He nodded.","why":"..."},
                    {"id":"B12","action":"refine","new":"She turned the cup a quarter-turn."}]
        'new' replaces the whole beat sentence (include its final punctuation).
        --md writes a before/after proposal table.
"""
import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from prose_tools import read, words, TAG_VERBS  # noqa: E402

QUOTE_RE = re.compile(r"“[^”]*(?:”|$)|\"[^\"]*(?:\"|$)")
ABBREV = {"mr", "mrs", "ms", "dr", "st", "prof", "sr", "jr", "vs"}
REACTION_KINDS = {"gaze", "head", "face", "breath"}

BEAT_PATTERNS = {
    "gaze": [
        r"looked (?:away|down|up|back|aside|off|around)", r"looked at \w+", r"glanced", r"stared", r"gazed",
        r"held (?:his|her|their) gaze", r"eyes (?:met|dropped|lifted|flicked|darted|shifted|drifted|settled)",
        r"gaze (?:dropped|lifted|flicked|shifted|drifted|settled|stayed|remained)",
        r"averted (?:his|her) (?:eyes|gaze)", r"watched (?:him|her|them)", r"met (?:his|her) (?:eyes|gaze)",
    ],
    "head": [
        r"nodded", r"shook (?:his|her|their) head", r"tilted (?:his|her|their) head",
        r"head (?:dipped|tilted|snapped)", r"shrugged", r"lowered (?:his|her) (?:head|gaze|eyes)",
        r"bowed (?:his|her) head",
    ],
    "face": [
        r"smiled", r"grinned", r"frowned", r"scowled", r"smirked", r"grimaced", r"winced",
        r"raised (?:an |his |her )?eyebrows?", r"eyebrows? (?:rose|lifted|shot up)",
        r"brows? (?:drew|furrowed|knitted|rose|lifted|pulled)",
        r"(?:lips|mouth) (?:pressed|parted|curved|twitched|tugged|quirked|tightened|thinned)",
        r"(?:his|her) jaw (?:tightened|tensed|clenched|shifted|worked)", r"rolled (?:his|her) eyes",
        r"eyes (?:widened|narrowed|softened|glistened|stung|burned|shone)", r"corner of (?:his|her) mouth",
        r"flushed", r"blushed", r"chuckled", r"laughed", r"snorted", r"huffed", r"scoffed",
        r"(?:grin|smile) (?:widened|spread|faltered|faded|tugged)",
    ],
    "breath": [
        r"exhaled", r"inhaled", r"sighed", r"(?:drew|took) a (?:slow |deep |shaky |long )?breath",
        r"let out a (?:slow |long |shaky |soft )?breath", r"breath (?:caught|hitched|left|stuttered)",
        r"swallowed", r"throat (?:tightened|closed|bobbed|moved|worked)", r"cleared (?:his|her) throat", r"gulped",
    ],
    "hands": [
        r"fingers (?:tightened|curled|tapped|drummed|twitched|stilled|loosened)",
        r"(?:hands?|fists?) (?:clenched|curled|tightened|trembled|shook)",
        r"clenched (?:his|her) (?:fists?|hands?|jaw)", r"curled into fists", r"ran a hand", r"rubbed (?:his|her|the)",
        r"tapped", r"drummed", r"fidgeted", r"folded (?:his|her) arms", r"crossed (?:his|her) arms", r"gripped",
        r"wiped (?:at )?(?:his|her)", r"tucked (?:a strand|his|her)", r"pressed (?:his|her) (?:lips|palm|hand|fingers)",
        r"rested (?:his|her) (?:hand|chin|head)",
    ],
    "posture": [
        r"stepped (?:back|closer|forward|aside)", r"took a step", r"leaned (?:back|in|forward|against|towards|toward)",
        r"straightened", r"shifted", r"stiffened", r"froze", r"went still", r"tensed", r"relaxed",
        r"shoulders (?:slumped|tensed|dropped|sagged|stiffened|relaxed)", r"pulled back",
        r"turned (?:away|back|around|towards|toward)", r"stood there", r"sat there", r"settled (?:back|into|against)",
    ],
}
GERUND_KIND = {
    "shaking": "head", "nodding": "head", "shrugging": "head", "tilting": "head", "lowering": "head",
    "smiling": "face", "frowning": "face", "grinning": "face", "squinting": "face", "raising": "face",
    "rolling": "face", "biting": "face", "sighing": "breath", "glancing": "gaze", "looking": "gaze",
    "staring": "gaze", "rubbing": "hands", "tapping": "hands", "wiping": "hands", "scratching": "hands",
    "folding": "hands", "crossing": "hands", "clenching": "hands", "leaning": "posture",
}
GERUND_RE = re.compile(r"\b(" + "|".join(GERUND_KIND) + r")\b", re.I)
COMPILED = [(k, re.compile(p, re.I)) for k, ps in BEAT_PATTERNS.items() for p in ps]
ACTOR_RE = re.compile(r"^[\s,—–-]*(?:[A-Z][a-z’']+(?:\s+[A-Z][a-z’']+)?|He|She|They|I|His|Her|Their)\b")
_verbs = "|".join(v.replace(" ", r"\s+") for v in TAG_VERBS)
TAGUNIT_RE = re.compile(
    r"^[\s,—–-]*(?:(?:[A-Z][a-z’']+|he|she|they|I)\s+(?:\w+ly\s+)?(?:%s)\b|(?:%s)\s+(?:[A-Z][a-z’']+|he|she|they))" % (_verbs, _verbs),
    re.I,
)
ANYTAG_RE = re.compile(r"\b(?:%s)\b" % _verbs, re.I)


def sha1(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def is_break(p):
    s = p.strip()
    return s.startswith("#") or s in ("~", "* * *", "***", "---") or not re.search(r"\w", s)


def para_spans(text):
    return [(m.start(), m.end()) for m in re.finditer(r"[^\n]+(?:\n[^\n]+)*", text) if m.group().strip()]


def split_units(par, a, b, base):
    """Sentence-ish units of a narration chunk (text between quote spans), absolute offsets."""
    chunk = par[a:b]
    cuts, s = [], 0
    for m in re.finditer(r"(?<=[.!?…])\s+", chunk):
        prev = re.findall(r"[A-Za-z]+\.?$", chunk[s:m.start()])
        if prev and prev[0].rstrip(".").lower() in ABBREV:
            continue
        cuts.append((s, m.start()))
        s = m.end()
    cuts.append((s, len(chunk)))
    out = []
    for x, y in cuts:
        seg = chunk[x:y]
        if not seg.strip():
            continue
        lead = len(seg) - len(seg.lstrip())
        out.append((base + a + x + lead, base + a + y - (len(seg) - len(seg.rstrip())), seg.strip()))
    return out


def paragraph_units(par, base):
    out, pos = [], 0
    for qm in QUOTE_RE.finditer(par):
        if qm.start() > pos:
            out += split_units(par, pos, qm.start(), base)
        pos = qm.end()
    if pos < len(par):
        out += split_units(par, pos, len(par), base)
    return out


def norm_key(s):
    s = re.sub(r"\b(?:his|her|their|my|your|its)\b", "_", s.lower())
    s = re.sub(r"^(looked at|glanced at|stared at|watched|looked) (?!away|down|up|back|aside|off|around).*", r"\1", s)
    return " ".join(s.split()[:3])


def detect(unit, in_dialogue_ctx):
    t = unit.strip()
    if len(t.split()) > 18:
        return None
    tag = TAGUNIT_RE.match(t)
    rest = t[tag.end():] if tag else t
    if tag:
        g = GERUND_RE.search(rest)
        if g:
            return {"kinds": [GERUND_KIND[g.group(1).lower()]], "key": g.group(1).lower(), "tagged": True}
        return None
    hits = []
    for kind, rx in COMPILED:
        m = rx.search(rest)
        if m:
            hits.append((m.start(), kind, m.group()))
    if not hits or not ACTOR_RE.match(t):
        return None
    hits.sort()
    kinds = sorted({k for _, k, _ in hits})
    if not in_dialogue_ctx and not (set(kinds) & REACTION_KINDS):
        return None
    if set(kinds) <= {"hands", "posture"} and (not in_dialogue_ctx or len(t.split()) > 10):
        return None
    return {"kinds": kinds, "key": norm_key(hits[0][2]), "tagged": False}


def strip_participle(unit):
    """'“No,” she said, shaking her head.' unit -> 'she said.' (drops the beat, keeps the tag)."""
    m = re.match(r"^(.*?\b(?:%s)\b[^,]*?),\s+(?:\w+ing)\b.*?([.!?…]*)$" % _verbs, unit, re.I)
    return (m.group(1) + (m.group(2) or ".")) if m else None


def analyze(text):
    spans = para_spans(text)
    paras = []
    for i, (s, e) in enumerate(spans):
        p = text[s:e]
        paras.append({"i": i, "s": s, "e": e, "t": p, "q": bool(QUOTE_RE.search(p)), "brk": is_break(p)})
    beats = []
    for p in paras:
        if p["brk"]:
            continue
        nbr_q = any(0 <= j < len(paras) and paras[j]["q"] and not paras[j]["brk"] for j in (p["i"] - 1, p["i"] + 1))
        units = paragraph_units(p["t"], p["s"])
        for ui, (us, ue, ut) in enumerate(units):
            d = detect(ut, p["q"] or nbr_q)
            if not d:
                continue
            role = "attached" if p["q"] else ("standalone" if len(units) == 1 else "inline")
            beats.append({"id": "", "s": us, "e": ue, "text": ut, "kinds": d["kinds"], "key": d["key"],
                          "tagged": d["tagged"], "role": role, "para": p["i"], "unit": ui, "flags": []})
    for n, b in enumerate(beats, 1):
        b["id"] = f"B{n}"

    # --- flags
    by_key = {}
    for b in beats:
        by_key.setdefault(b["key"], []).append(b)
    for key, lst in by_key.items():
        if len(lst) >= 3:
            for b in lst:
                b["flags"].append(f"repeat x{len(lst)}")
        else:
            for x, y in zip(lst, lst[1:]):
                if y["para"] - x["para"] <= 8:
                    y["flags"].append("close-repeat")
    for x, y in zip(beats, beats[1:]):
        adj = (x["para"] == y["para"] and y["unit"] - x["unit"] == 1) or \
              (y["para"] - x["para"] == 1 and x["role"] == "standalone" and y["role"] == "standalone")
        if adj:
            for b in (x, y):
                if "chain" not in b["flags"]:
                    b["flags"].append("chain")
    for i in range(len(beats)):
        win = beats[i:i + 6]
        if len(win) >= 4 and win[-1]["para"] - win[0]["para"] <= 10:
            c = Counter(k for b in win for k in b["kinds"][:1])
            kind, n = c.most_common(1)[0]
            if n >= 4:
                for b in win:
                    if b["kinds"][0] == kind and not any(f.startswith("kind-cluster") for f in b["flags"]):
                        b["flags"].append(f"kind-cluster({kind})")
    # dense exchanges: runs of dialogue / standalone-beat paragraphs where beats ~ lines
    beat_paras = {b["para"] for b in beats if b["role"] == "standalone"}
    run = []
    def close_run(run):
        dl = sum(1 for k in run if paras[k]["q"])
        bs = [b for b in beats if b["para"] in set(run)]
        if dl >= 3 and len(bs) >= 0.7 * dl:
            for b in bs:
                b["flags"].append(f"dense-exchange(paras {run[0] + 1}-{run[-1] + 1}: {len(bs)} beats/{dl} lines)")
    for p in paras + [{"i": -1, "q": False, "brk": True}]:
        if not p["brk"] and (p["q"] or p["i"] in beat_paras):
            run.append(p["i"])
        else:
            if run:
                close_run(run)
            run = []
    return paras, beats


def snippet(s, n=90):
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def ftype(f):
    return f.split(" ")[0].split("(")[0]


def cmd_beats(args):
    text = read(args.file)
    paras, beats = analyze(text)
    wc = max(words(text), 1)
    qlines = [p for p in paras if p["q"] and not p["brk"]]
    with_beat = {b["para"] for b in beats if b["role"] == "attached"}
    standalone = sum(1 for b in beats if b["role"] == "standalone")
    print(f"beats: {len(beats)} ({round(len(beats) * 1000 / wc, 1)}/1k words)   standalone beat paragraphs: {standalone}"
          f"   dialogue lines carrying a beat: {len(with_beat)}/{len(qlines)}")

    groups = {}
    for b in beats:
        groups.setdefault(b["key"], []).append(b)
    rep = sorted([(k, v) for k, v in groups.items() if len(v) >= 3], key=lambda kv: -len(kv[1]))
    print("\nREPEATED STOCK BEATS (keep the best one or two; refine or drop the rest):")
    for k, v in rep[:12] or []:
        print(f"  {k!r} x{len(v)}: " + " ".join(b["id"] for b in v))
    if not rep:
        print("  none")

    dense = {}
    for b in beats:
        for f in b["flags"]:
            if f.startswith("dense-exchange"):
                dense.setdefault(f, []).append(b)
    print("\nDENSE EXCHANGES (a beat after nearly every line - most beats there slow the rhythm):")
    for f, v in dense.items():
        print(f"  {f}: " + " ".join(b["id"] for b in v))
    if not dense:
        print("  none")

    for b in beats:
        b["score"] = len({ftype(f) for f in b["flags"]})
    cand = beats if args.all else [b for b in beats if b["score"] >= args.min_flags]
    cand = sorted(cand, key=lambda b: b["para"])
    print(f"\nCANDIDATES (>= {args.min_flags} distinct flags): {len(cand)} of {len(beats)} beats; the rest are left alone by default\n")
    for b in cand[: args.max]:
        p = paras[b["para"]]
        prev = paras[b["para"] - 1]["t"] if b["para"] > 0 and b["role"] != "inline" else ""
        nxt = paras[b["para"] + 1]["t"] if b["para"] + 1 < len(paras) and b["role"] != "inline" else ""
        print(f"{b['id']:<5} para {b['para'] + 1:<4} [{'/'.join(b['kinds'])}] {b['key']!r}  {'; '.join(b['flags']) or '-'}")
        if prev and not is_break(prev):
            print(f"      prev: {snippet(prev)}")
        print(f"      BEAT: {snippet(p['t'] if b['role'] == 'standalone' else b['text'], 140)}")
        if nxt and not is_break(nxt):
            print(f"      next: {snippet(nxt)}")
    if len(cand) > args.max:
        print(f"... {len(cand) - args.max} more candidates (raise --max)")
    if args.json:
        Path(args.json).write_text(json.dumps({"sha1": sha1(text), "beats": beats}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nwrote all {len(beats)} beats (candidates and not) -> {args.json}")


# ------------------------------------------------------------------ beats-patch

def cmd_beats_patch(args):
    text = read(args.file)
    cands = json.loads(Path(args.cands).read_text(encoding="utf-8-sig"))
    if cands["sha1"] != sha1(text):
        sys.exit("The chapter changed since `beats --json` ran - re-run beats --json on the current text.")
    by_id = {b["id"]: b for b in cands["beats"]}
    decisions = json.loads(Path(args.decisions).read_text(encoding="utf-8-sig"))
    spans = para_spans(text)
    drop_paras, inline, rows, warns = set(), {}, [], []

    for d in decisions:
        b = by_id.get(d["id"])
        act = d.get("action", "").lower()
        if not b:
            warns.append(f"{d['id']}: unknown id"); continue
        if act in ("keep", ""):
            continue
        ps, pe = spans[b["para"]]
        unit_old = text[b["s"]:b["e"]]
        if act in ("trim", "refine"):
            if not d.get("new"):
                warns.append(f"{b['id']}: {act} needs 'new'"); continue
            inline.setdefault(b["para"], []).append((b["s"], b["e"], d["new"]))
        elif act == "drop":
            if b["role"] == "standalone":
                drop_paras.add(b["para"])
            elif b["tagged"]:
                rep = strip_participle(unit_old)
                if not rep:
                    warns.append(f"{b['id']}: can't auto-strip the participle; give action 'trim' with 'new'"); continue
                inline.setdefault(b["para"], []).append((b["s"], b["e"], rep))
            else:
                s, e = b["s"], b["e"]
                if s > ps and text[s - 1] == " ":
                    s -= 1
                elif e < pe and text[e] == " ":
                    e += 1
                inline.setdefault(b["para"], []).append((s, e, ""))
        else:
            warns.append(f"{b['id']}: unknown action {act!r}"); continue
        rows.append((b["id"], act, unit_old, d.get("new", ""), d.get("why", "")))

    for i in drop_paras & set(inline):
        warns.append(f"para {i + 1}: both dropped and edited - resolve")
    for i in drop_paras:
        nb = [paras_t for paras_t in (i - 1, i + 1) if 0 <= paras_t < len(spans)]
        if len(nb) == 2 and all(QUOTE_RE.search(text[spans[k][0]:spans[k][1]]) and
                                not ANYTAG_RE.search(text[spans[k][0]:spans[k][1]]) for k in nb):
            warns.append(f"para {i + 1}: dropping it may blur who is speaking between two untagged lines - check")

    # build paragraph-range groups
    ranges = []
    for i in sorted(set(inline) | drop_paras):
        a = b2 = i
        if i in drop_paras:
            if i > 0: a = i - 1
            elif i + 1 < len(spans): b2 = i + 1
        ranges.append([a, b2])

    def merge(rs):
        rs = sorted(rs); out = []
        for a, b2 in rs:
            if out and a <= out[-1][1]:
                out[-1][1] = max(out[-1][1], b2)
            else:
                out.append([a, b2])
        return out
    ranges = merge(ranges)
    while True:
        changed = False
        for r in ranges:
            while text.count(text[spans[r[0]][0]:spans[r[1]][1]]) != 1 and (r[0] > 0 or r[1] + 1 < len(spans)):
                if r[0] > 0:
                    r[0] -= 1
                elif r[1] + 1 < len(spans):
                    r[1] += 1
                changed = True
        m2 = merge(ranges)
        if m2 != ranges:
            ranges, changed = m2, True
        if not changed:
            break

    patches = []
    for a, b2 in ranges:
        old = text[spans[a][0]:spans[b2][1]]
        sep = text[spans[a][1]:spans[a + 1][0]] if b2 > a else "\n\n"
        kept = []
        for k in range(a, b2 + 1):
            if k in drop_paras:
                continue
            ps, pe = spans[k]
            ptxt = text[ps:pe]
            for s, e, new in sorted(inline.get(k, []), reverse=True):
                ptxt = ptxt[: s - ps] + new + ptxt[e - ps:]
            if re.search(r"”\s+“", ptxt) and not re.search(r"”\s+“", text[ps:pe]):
                warns.append(f"para {k + 1}: edit puts two quoted lines in one paragraph - check speaker change")
            kept.append(ptxt)
        patches.append({"old": old, "new": sep.join(kept)})

    for w in warns:
        print("WARN:", w)
    Path(args.out).write_text(json.dumps(patches, ensure_ascii=False, indent=2), encoding="utf-8")
    c = Counter(r[1] for r in rows)
    print(f"{len(patches)} paragraph patch(es) from {len(rows)} decision(s) ({dict(c)}) -> {args.out}")
    if args.md:
        lines = ["| Beat | Action | Before | After | Why |", "|---|---|---|---|---|"]
        for bid, act, old, new, why in rows:
            lines.append(f"| {bid} | {act} | {snippet(old, 80).replace('|', '/')} | {snippet(new, 80).replace('|', '/') or '(removed)'} | {why.replace('|', '/')} |")
        Path(args.md).write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"proposal table -> {args.md}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("beats")
    p.add_argument("file"); p.add_argument("--json"); p.add_argument("--all", action="store_true")
    p.add_argument("--max", type=int, default=60)
    p.add_argument("--min-flags", type=int, default=2, help="distinct flag types needed to list a beat (default 2)")
    p.set_defaults(func=cmd_beats)
    p = sub.add_parser("beats-patch")
    p.add_argument("file"); p.add_argument("--cands", required=True); p.add_argument("--decisions", required=True)
    p.add_argument("--out", required=True); p.add_argument("--md")
    p.set_defaults(func=cmd_beats_patch)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
