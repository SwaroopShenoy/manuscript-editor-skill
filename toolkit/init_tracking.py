#!/usr/bin/env python3
"""
init_tracking.py - create the _edits/ tracking files for a manuscript
(novelWriter project folder or a folder holding a flat .md manuscript),
from the templates in tracking_template/. Never overwrites existing files.

Usage: python init_tracking.py <target_dir> <project_name>
"""
import sys
from pathlib import Path

TEMPLATE_DIR = Path(__file__).parent / "tracking_template"


def main():
    if len(sys.argv) != 3:
        sys.exit("Usage: python init_tracking.py <target_dir> <project_name>")
    target_dir = Path(sys.argv[1])
    project_name = sys.argv[2]
    if not target_dir.exists():
        sys.exit(f"No such directory: {target_dir}")

    edits_dir = target_dir / "_edits"
    edits_dir.mkdir(exist_ok=True)

    for tmpl in TEMPLATE_DIR.glob("*.md"):
        dest = edits_dir / tmpl.name
        if dest.exists():
            print(f"skip (exists): {dest}")
            continue
        text = tmpl.read_text(encoding="utf-8-sig").replace("{{PROJECT}}", project_name)
        dest.write_text(text, encoding="utf-8")
        print(f"created: {dest}")


if __name__ == "__main__":
    main()
