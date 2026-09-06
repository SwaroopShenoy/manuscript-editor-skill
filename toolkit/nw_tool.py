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

  python nw_tool.py flat-list <manuscript.md>
  python nw_tool.py flat-get <manuscript.md> <chapter_heading_substring> [--out FILE]
  python nw_tool.py flat-set <manuscript.md> <chapter_heading_substring> <file_with_new_chapter>
"""

import argparse
import datetime
import hashlib
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
        text = nwd.read_text(encoding="utf-8")
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
    text = nwd.read_text(encoding="utf-8")
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

    old_text = nwd.read_text(encoding="utf-8")
    header, _old_body = strip_header(old_text)
    new_body = Path(args.file).read_text(encoding="utf-8")

    edits_dir = project_dir / "_edits"
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
    print(f"Updated [{it.handle}] {it.name}")
    print(f"Backup saved: {backup_path}")
    print("Reminder: open the project in novelWriter and let it re-index before editing there.")


# ----------------------------------------------------------- flat-md mode

CHAPTER_RE = re.compile(r"^#\s+(.*)$")


def flat_chapters(path: Path):
    """Return list of (title, start_line, end_line) for each top-level '# ' heading."""
    lines = path.read_text(encoding="utf-8").split("\n")
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
    new_chunk = Path(args.file).read_text(encoding="utf-8").rstrip("\n")

    edits_dir = manuscript.parent / "_edits"
    backup_path = backup_file(manuscript, edits_dir)

    new_lines = lines[:start] + new_chunk.split("\n") + lines[end:]
    manuscript.write_text("\n".join(new_lines), encoding="utf-8", newline="\n")
    print(f"Updated chapter: {title}")
    print(f"Backup saved: {backup_path}")


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

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
