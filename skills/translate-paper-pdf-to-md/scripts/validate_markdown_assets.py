#!/usr/bin/env python3
"""Validate image links and basic structure in a localized Markdown paper."""

import argparse
import os
import re
import sys
from pathlib import Path


IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
REF_RE = re.compile(r"^\[[0-9]+\]")


def main() -> int:
    # DSHM's in-process runner passes [prog, <script>, *args] and has no
    # __file__; strip the script path so argparse sees only real arguments.
    if len(sys.argv) > 1:
        try:
            _self = os.path.abspath(__file__)
        except NameError:
            _self = None
        first = sys.argv[1]
        if _self and os.path.abspath(first) == _self:
            del sys.argv[1]
        elif _self is None and first.endswith(".py") and os.path.isfile(first):
            del sys.argv[1]
    parser = argparse.ArgumentParser()
    parser.add_argument("markdown", type=Path)
    args = parser.parse_args()

    md_path = args.markdown.resolve()
    if not md_path.exists():
        print(f"missing markdown: {md_path}", file=sys.stderr)
        return 2

    text = md_path.read_text(encoding="utf-8")
    links = IMAGE_RE.findall(text)
    missing: list[str] = []
    for link in links:
        if "://" in link:
            continue
        target = (md_path.parent / link).resolve()
        if not target.exists():
            missing.append(link)

    refs = [line for line in text.splitlines() if REF_RE.match(line)]
    figures = sorted(set(re.findall(r"图\s*([0-9]+)", text)))
    tables = sorted(set(re.findall(r"表\s*([0-9]+)", text)))
    equations = sorted(set(re.findall(r"\\tag\{([^}]+)\}", text)))

    print(f"markdown: {md_path}")
    print(f"image_links: {len(links)}")
    print(f"missing_images: {len(missing)}")
    for link in missing:
        print(f"  - {link}")
    print(f"reference_entries: {len(refs)}")
    print(f"figure_numbers_seen: {', '.join(figures) if figures else '(none)'}")
    print(f"table_numbers_seen: {', '.join(tables) if tables else '(none)'}")
    print(f"equation_tags_seen: {', '.join(equations) if equations else '(none)'}")

    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())

