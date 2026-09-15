#!/usr/bin/env python3
"""
nw_tool.py - safe read/export/edit helper for novelWriter projects and
flat-markdown manuscripts (e.g. the Roadmap Series exports).

Golden rules baked into this script:
  1. Never write to a novelWriter project while it's open in the app
     (checked via the project's nwProject.lock file).
  2. Always back up the file being changed before writing it.
  3. Never fabricate the %%~hash header value as authoritative - novelWriter
     recomputes it on its own next save, so we just keep the file readable
     and let the app self-heal its index on next open.

Usage:
  python nw_tool.py list <project_dir>
  python nw_tool.py export <project_dir> [--out FILE]
  python nw_tool.py get <project_dir> <handle_or_title> [--out FILE]
  python nw_tool.py set <project_dir> <handle> <file_with_new_body>
  python nw_tool.py patch <project_dir> <handle> <patch_file.json> [--dry-run]
  python nw_tool.py lint <project_dir> <handle_or_title>

  python nw_tool.py flat-list <manuscript.md>
  python nw_tool.py flat-get <manuscript.md> <chapter_heading_substring> [--out FILE]
  python nw_tool.py flat-set <manuscript.md> <chapter_heading_substring> <file_with_new_chapter>
  python nw_tool.py flat-patch <manuscript.md> <chapter_heading_substring> <patch_file.json> [--dry-run]
  python nw_tool.py flat-lint <manuscript.md> <chapter_heading_substring>

  python nw_tool.py log-append <file> <text_file>

patch_file.json format (a JSON array, applied in order against the document body):
  [
    {"old": "exact text to find", "new": "replacement text"},
    {"old": "text appearing more than once", "new": "replacement", "count": 3},
    {"old": "text to replace everywhere", "new": "replacement", "replace_all": true}
  ]
Each patch's "old" string must appear exactly once in the body (or exactly "count" times, or
use "replace_all" for every occurrence) at the moment that patch is applied - patches apply
sequentially, so a later patch sees the result of earlier ones. If any patch fails to match,
nothing is written - the whole file's patch set is all-or-nothing. Use --dry-run to validate a
patch file (and see exactly which entry fails, if any) without touching the document.
"""

import argparse
import datetime
import hashlib
import json
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

SKIP_CLASSES = {"TRASH"}
MANUSCRIPT_CLASS = "NOVEL"


# ---------------------------------------------------------------- nwx model

class NwItem:
    def __init__(self, elem):
        self.handle = elem.get("handle")
        self.parent = elem.get("parent")
        self.order = int(elem.get("order", "0"))
        self.type = elem.get("type")
        self.cls = elem.get("class")
        self.layout = elem.get("layout", "")
        name_el = elem.find("name")
        self.name = (name_el.text or "").strip() if name_el is not None else ""
        meta_el = elem.find("meta")
        wc = meta_el.get("wordCount") if meta_el is not None else None
        self.word_count = int(wc) if wc else 0
        self.children = []


def load_items(project_dir: Path):
    nwx_path = project_dir / "nwProject.nwx"
    if not nwx_path.exists():
        sys.exit(f"Not a novelWriter project (missing nwProject.nwx): {project_dir}")
    tree = ET.parse(nwx_path)
    root = tree.getroot()
    content = root.find("content")
    items = {}
    for elem in content.findall("item"):
        it = NwItem(elem)
        items[it.handle] = it
    for it in items.values():
        if it.parent and it.parent in items:
            items[it.parent].children.append(it)
    for it in items.values():
        it.children.sort(key=lambda c: c.order)
    roots = sorted([it for it in items.values() if it.parent in (None, "None")],
                    key=lambda c: c.order)
    return items, roots


def walk_files(roots):
    """Yield FILE items in document order, depth-first."""
    stack = list(reversed(roots))
    while stack:
        it = stack.pop()
        if it.type == "FILE":
            yield it
        stack.extend(reversed(it.children))


def is_lock_present(project_dir: Path) -> bool:
    return (project_dir / "nwProject.lock").exists()


def require_closed(project_dir: Path):
    if is_lock_present(project_dir):
        sys.exit(
            f"REFUSING TO WRITE: {project_dir} appears to be open in novelWriter "
            f"(nwProject.lock present). Close the project in the app first."
        )


def strip_header(text: str):
    """Split a .nwd file into (header_lines, body). Header lines start with %%~."""
    lines = text.split("\n")
    i = 0
    while i < len(lines) and lines[i].startswith("%%~"):
        i += 1
    header = lines[:i]
    body = "\n".join(lines[i:])
    return header, body


def backup_file(src: Path, edits_dir: Path):
    edits_dir.mkdir(parents=True, exist_ok=True)
    backups = edits_dir / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backups / f"{stamp}__{src.name}"
    shutil.copy2(src, dest)
    return dest


def write_nwd_body(nwd: Path, header: list, new_body: str, edits_dir: Path):
    """Back up nwd, then write new_body under it with hash/date refreshed in the header.
    Shared by cmd_set and cmd_patch so both stay in sync."""
    backup_path = backup_file(nwd, edits_dir)
    new_header = []
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for line in header:
        if line.startswith("%%~hash:"):
            new_hash = hashlib.sha1(new_body.encode("utf-8")).hexdigest()
            new_header.append(f"%%~hash: {new_hash}")
        elif line.startswith("%%~date:"):
            created = line.split(":", 1)[1].strip().split("/")[0].strip()
            new_header.append(f"%%~date: {created}/{now}")
        else:
            new_header.append(line)
    new_text = "\n".join(new_header) + "\n" + new_body
    nwd.write_text(new_text, encoding="utf-8", newline="\n")
    return backup_path


def apply_patches(body: str, patches: list):
    """Apply a list of {old, new, count?, replace_all?} patches to body, in order.
    Each patch is checked against the *current* text (i.e. after prior patches applied),
    matching how a sequence of manual find/replace edits behaves. Returns (new_body, errors).
    On any failure, stops at the first bad patch and returns (None, [error]) - nothing is
    partially applied, so callers can safely skip writing when errors is non-empty."""
    text = body
    for idx, p in enumerate(patches):
        if "old" not in p or "new" not in p:
            return None, [f"patch {idx}: missing required 'old' or 'new' key"]
        old, new = p["old"], p["new"]
        replace_all = bool(p.get("replace_all", False))
        found = text.count(old)
        if replace_all:
            if found == 0:
                return None, [f"patch {idx}: old string not found: {old!r}"]
            text = text.replace(old, new)
        else:
            expected = p.get("count", 1)
            if found != expected:
                return None, [
                    f"patch {idx}: expected {expected} occurrence(s), found {found}: {old!r}"
                ]
            text = text.replace(old, new, expected)
    return text, []


LINT_CHECKS = [
    ("straight-apostrophe", re.compile(r"[A-Za-z]'[A-Za-z]")),
    ("straight-double-quote", re.compile(r'"')),
    ("triple-dot-ellipsis", re.compile(r"\.\.\.")),
    ("double-space", re.compile(r"  ")),
    ("doubled-word", re.compile(r"\b(\w+)\s+\1\b", re.IGNORECASE)),
]


def lint_body(body: str):
    """Return a list of (line_no, col, label, line_text) for common contamination/typo
    patterns this project has repeatedly hit (straight quotes pasted in from elsewhere,
    triple-dot ellipses instead of the curly '...' char, doubled words, etc). This mirrors
    the ad hoc Grep pass that used to be run by hand on every chapter."""
    hits = []
    for line_no, line in enumerate(body.split("\n"), start=1):
        for label, pattern in LINT_CHECKS:
            for m in pattern.finditer(line):
                hits.append((line_no, m.start() + 1, label, line.strip()[:120]))
    return hits


def print_lint_hits(hits, label: str):
    if not hits:
        print(f"No lint hits in {label}")
        return
    print(f"--- {len(hits)} lint hit(s) in {label} ---")
    for line_no, col, tag, text in hits:
        print(f"{line_no}:{col}  {tag}  {text}")


# --------------------------------------------------------------- commands

def cmd_list(args):
    project_dir = Path(args.project_dir)
    items, roots = load_items(project_dir)
    for it in walk_files(roots):
        flag = " [TRASH]" if it.cls in SKIP_CLASSES else ""
        print(f"{it.handle}  {it.cls:<10} {it.layout:<9} {it.word_count:>6}w  {it.name}{flag}")


def cmd_export(args):
    project_dir = Path(args.project_dir)
    items, roots = load_items(project_dir)
    out_lines = []
    for it in walk_files(roots):
        if it.cls != MANUSCRIPT_CLASS or it.cls in SKIP_CLASSES:
            continue
        nwd = project_dir / "content" / f"{it.handle}.nwd"
        if not nwd.exists():
            continue
        text = nwd.read_text(encoding="utf-8-sig")
        _, body = strip_header(text)
        out_lines.append(body.strip())
    result = "\n\n\n".join(out_lines) + "\n"
    if args.out:
        Path(args.out).write_text(result, encoding="utf-8")
        print(f"Wrote {len(result)} chars to {args.out}")
    else:
        sys.stdout.write(result)


def find_item(project_dir: Path, handle_or_title: str):
    items, roots = load_items(project_dir)
    if handle_or_title in items:
        return items[handle_or_title]
    matches = [it for it in items.values() if it.type == "FILE" and handle_or_title.lower() in it.name.lower()]
    if not matches:
        sys.exit(f"No document matches handle/title: {handle_or_title}")
    if len(matches) > 1:
        names = ", ".join(f"{m.handle}:{m.name}" for m in matches)
        sys.exit(f"Ambiguous title, matches: {names}")
    return matches[0]


def cmd_get(args):
    project_dir = Path(args.project_dir)
    it = find_item(project_dir, args.handle_or_title)
    nwd = project_dir / "content" / f"{it.handle}.nwd"
    text = nwd.read_text(encoding="utf-8-sig")
    header, body = strip_header(text)
    if args.out:
        Path(args.out).write_text(body, encoding="utf-8")
        print(f"[{it.handle}] {it.name} -> {args.out}")
    else:
        sys.stdout.write(body)


def cmd_set(args):
    project_dir = Path(args.project_dir)
    require_closed(project_dir)
    items, _ = load_items(project_dir)
    if args.handle not in items:
        sys.exit(f"Unknown handle: {args.handle}")
    it = items[args.handle]
    nwd = project_dir / "content" / f"{it.handle}.nwd"
    if not nwd.exists():
        sys.exit(f"Missing document file: {nwd}")

    old_text = nwd.read_text(encoding="utf-8-sig")
    header, _old_body = strip_header(old_text)
    new_body = Path(args.file).read_text(encoding="utf-8-sig")

    edits_dir = project_dir / "_edits"
    backup_path = write_nwd_body(nwd, header, new_body, edits_dir)
    print(f"Updated [{it.handle}] {it.name}")
    print(f"Backup saved: {backup_path}")
    print("Reminder: open the project in novelWriter and let it re-index before editing there.")


def cmd_patch(args):
    project_dir = Path(args.project_dir)
    require_closed(project_dir)
    items, _ = load_items(project_dir)
    if args.handle not in items:
        sys.exit(f"Unknown handle: {args.handle}")
    it = items[args.handle]
    nwd = project_dir / "content" / f"{it.handle}.nwd"
    if not nwd.exists():
        sys.exit(f"Missing document file: {nwd}")

    old_text = nwd.read_text(encoding="utf-8-sig")
    header, body = strip_header(old_text)

    try:
        patches = json.loads(Path(args.patch_file).read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        sys.exit(f"Invalid JSON in {args.patch_file}: {e}")
    if not isinstance(patches, list) or not patches:
        sys.exit("Patch file must be a non-empty JSON array of {old, new} objects")

    new_body, errors = apply_patches(body, patches)
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(f"Patch failed - 0 of {len(patches)} applied, nothing written.")

    if args.dry_run:
        print(f"Dry run OK: all {len(patches)} patch(es) match cleanly against [{it.handle}] {it.name}")
        return

    edits_dir = project_dir / "_edits"
    backup_path = write_nwd_body(nwd, header, new_body, edits_dir)
    print(f"Applied {len(patches)} patch(es) to [{it.handle}] {it.name}")
    print(f"Backup saved: {backup_path}")
    print("Reminder: open the project in novelWriter and let it re-index before editing there.")


def cmd_lint(args):
    project_dir = Path(args.project_dir)
    it = find_item(project_dir, args.handle_or_title)
    nwd = project_dir / "content" / f"{it.handle}.nwd"
    text = nwd.read_text(encoding="utf-8-sig")
    _, body = strip_header(text)
    print_lint_hits(lint_body(body), f"[{it.handle}] {it.name}")


# ----------------------------------------------------------- flat-md mode

CHAPTER_RE = re.compile(r"^#\s+(.*)$")


def flat_chapters(path: Path):
    """Return list of (title, start_line, end_line) for each top-level '# ' heading."""
    lines = path.read_text(encoding="utf-8-sig").split("\n")
    marks = [(i, m.group(1).strip()) for i, line in enumerate(lines) if (m := CHAPTER_RE.match(line))]
    chapters = []
    for idx, (line_no, title) in enumerate(marks):
        end = marks[idx + 1][0] if idx + 1 < len(marks) else len(lines)
        chapters.append((title, line_no, end))
    return lines, chapters


def cmd_flat_list(args):
    _, chapters = flat_chapters(Path(args.manuscript))
    for title, start, end in chapters:
        print(f"line {start+1:>6}  {title}")


def find_chapter(chapters, needle: str):
    matches = [c for c in chapters if needle.lower() in c[0].lower()]
    if not matches:
        sys.exit(f"No chapter heading matches: {needle}")
    if len(matches) > 1:
        sys.exit("Ambiguous match: " + ", ".join(c[0] for c in matches))
    return matches[0]


def cmd_flat_get(args):
    lines, chapters = flat_chapters(Path(args.manuscript))
    title, start, end = find_chapter(chapters, args.heading)
    body = "\n".join(lines[start:end]).strip() + "\n"
    if args.out:
        Path(args.out).write_text(body, encoding="utf-8")
        print(f"{title} -> {args.out}")
    else:
        sys.stdout.write(body)


def cmd_flat_set(args):
    manuscript = Path(args.manuscript)
    lines, chapters = flat_chapters(manuscript)
    title, start, end = find_chapter(chapters, args.heading)
    new_chunk = Path(args.file).read_text(encoding="utf-8-sig").rstrip("\n")

    edits_dir = manuscript.parent / "_edits"
    backup_path = backup_file(manuscript, edits_dir)

    new_lines = lines[:start] + new_chunk.split("\n") + lines[end:]
    manuscript.write_text("\n".join(new_lines), encoding="utf-8", newline="\n")
    print(f"Updated chapter: {title}")
    print(f"Backup saved: {backup_path}")


def cmd_flat_patch(args):
    manuscript = Path(args.manuscript)
    lines, chapters = flat_chapters(manuscript)
    title, start, end = find_chapter(chapters, args.heading)
    body = "\n".join(lines[start:end]).strip() + "\n"

    try:
        patches = json.loads(Path(args.patch_file).read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as e:
        sys.exit(f"Invalid JSON in {args.patch_file}: {e}")
    if not isinstance(patches, list) or not patches:
        sys.exit("Patch file must be a non-empty JSON array of {old, new} objects")

    new_body, errors = apply_patches(body, patches)
    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(f"Patch failed - 0 of {len(patches)} applied, nothing written.")

    if args.dry_run:
        print(f"Dry run OK: all {len(patches)} patch(es) match cleanly against chapter: {title}")
        return

    edits_dir = manuscript.parent / "_edits"
    backup_path = backup_file(manuscript, edits_dir)

    new_chunk = new_body.rstrip("\n")
    new_lines = lines[:start] + new_chunk.split("\n") + lines[end:]
    manuscript.write_text("\n".join(new_lines), encoding="utf-8", newline="\n")
    print(f"Applied {len(patches)} patch(es) to chapter: {title}")
    print(f"Backup saved: {backup_path}")


def cmd_flat_lint(args):
    lines, chapters = flat_chapters(Path(args.manuscript))
    title, start, end = find_chapter(chapters, args.heading)
    body = "\n".join(lines[start:end])
    print_lint_hits(lint_body(body), f"chapter: {title}")


# -------------------------------------------------------------- log-append

def cmd_log_append(args):
    """Append text to a tracking file (e.g. _edits/edit_log.md) without reading the whole
    file into context first - safe because it's a pure append, never touches existing content,
    so there's nothing to match/diff against and nothing existing can be clobbered."""
    target = Path(args.file)
    if not target.exists():
        sys.exit(f"File does not exist: {target}")
    addition = Path(args.text_file).read_text(encoding="utf-8-sig")
    if not addition.strip():
        sys.exit(f"Nothing to append - {args.text_file} is empty")

    current = target.read_text(encoding="utf-8-sig")
    if current and not current.endswith("\n"):
        current += "\n"
    if not addition.endswith("\n"):
        addition += "\n"
    target.write_text(current + addition, encoding="utf-8", newline="\n")
    print(f"Appended {len(addition.splitlines())} line(s) to {target}")


# --------------------------------------------------------------------- cli

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("list", help="List documents in a novelWriter project, in order")
    p.add_argument("project_dir")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("export", help="Export the ordered NOVEL manuscript to one clean text file")
    p.add_argument("project_dir")
    p.add_argument("--out")
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("get", help="Extract one document's clean body (no header) for editing")
    p.add_argument("project_dir")
    p.add_argument("handle_or_title")
    p.add_argument("--out")
    p.set_defaults(func=cmd_get)

    p = sub.add_parser("set", help="Write an edited body back into a document (project must be closed)")
    p.add_argument("project_dir")
    p.add_argument("handle")
    p.add_argument("file")
    p.set_defaults(func=cmd_set)

    p = sub.add_parser("patch", help="Apply a list of exact old->new text replacements to a document in one pass (project must be closed)")
    p.add_argument("project_dir")
    p.add_argument("handle")
    p.add_argument("patch_file", help="JSON file: array of {old, new, count?, replace_all?}")
    p.add_argument("--dry-run", action="store_true", help="Validate the patches match without writing")
    p.set_defaults(func=cmd_patch)

    p = sub.add_parser("lint", help="Flag common contamination/typo patterns (straight quotes, triple-dot ellipses, doubled words) in a document")
    p.add_argument("project_dir")
    p.add_argument("handle_or_title")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("log-append", help="Append text to a tracking file (e.g. edit_log.md) without reading it first")
    p.add_argument("file")
    p.add_argument("text_file", help="File whose contents get appended")
    p.set_defaults(func=cmd_log_append)

    p = sub.add_parser("flat-list", help="List '# ' chapter headings in a flat markdown manuscript")
    p.add_argument("manuscript")
    p.set_defaults(func=cmd_flat_list)

    p = sub.add_parser("flat-get", help="Extract one chapter from a flat markdown manuscript")
    p.add_argument("manuscript")
    p.add_argument("heading")
    p.add_argument("--out")
    p.set_defaults(func=cmd_flat_get)

    p = sub.add_parser("flat-set", help="Replace one chapter in a flat markdown manuscript")
    p.add_argument("manuscript")
    p.add_argument("heading")
    p.add_argument("file")
    p.set_defaults(func=cmd_flat_set)

    p = sub.add_parser("flat-patch", help="Apply a list of exact old->new text replacements to one chapter in one pass")
    p.add_argument("manuscript")
    p.add_argument("heading")
    p.add_argument("patch_file", help="JSON file: array of {old, new, count?, replace_all?}")
    p.add_argument("--dry-run", action="store_true", help="Validate the patches match without writing")
    p.set_defaults(func=cmd_flat_patch)

    p = sub.add_parser("flat-lint", help="Flag common contamination/typo patterns in one chapter of a flat markdown manuscript")
    p.add_argument("manuscript")
    p.add_argument("heading")
    p.set_defaults(func=cmd_flat_lint)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
