#!/usr/bin/env python3
"""Prepare source text and page images for manual paper localization.

Optionally accepts a JSON crop spec:

{
  "fig1_name.png": {"page": 2, "crop": "500x150+625+385"},
  "table1_original.png": {"page": 2, "crop": "1010x210+105+145"}
}

Page numbers are 1-based. Crop geometry is ImageMagick geometry.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def require(command: str) -> None:
    if shutil.which(command) is None:
        raise SystemExit(f"required command not found: {command}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--assets-dir", type=Path)
    parser.add_argument("--resolution", type=int, default=144)
    parser.add_argument("--crop-spec", type=Path)
    args = parser.parse_args()

    pdf = args.pdf.resolve()
    if not pdf.exists():
        print(f"missing PDF: {pdf}", file=sys.stderr)
        return 2

    for command in ["pdfinfo", "pdftotext", "pdftocairo"]:
        require(command)

    work_dir = args.work_dir.resolve()
    pages_dir = work_dir / "page_images"
    work_dir.mkdir(parents=True, exist_ok=True)
    pages_dir.mkdir(parents=True, exist_ok=True)

    run(["pdfinfo", str(pdf)])
    run(["pdftotext", "-layout", "-enc", "UTF-8", str(pdf), str(work_dir / "source_layout.txt")])
    run(["pdftotext", "-raw", "-enc", "UTF-8", str(pdf), str(work_dir / "source_raw.txt")])
    run(["pdftocairo", "-png", "-r", str(args.resolution), str(pdf), str(pages_dir / "page")])

    if args.crop_spec:
        require("convert")
        if not args.assets_dir:
            raise SystemExit("--assets-dir is required when --crop-spec is used")
        assets_dir = args.assets_dir.resolve()
        assets_dir.mkdir(parents=True, exist_ok=True)
        spec = json.loads(args.crop_spec.read_text(encoding="utf-8"))
        for output_name, item in spec.items():
            page = int(item["page"])
            crop = str(item["crop"])
            page_path = pages_dir / f"page-{page:02d}.png"
            if not page_path.exists():
                raise SystemExit(f"rendered page not found for crop: {page_path}")
            run(["convert", str(page_path), "-crop", crop, "+repage", str(assets_dir / output_name)])

    print(f"work_dir: {work_dir}")
    if args.assets_dir:
        print(f"assets_dir: {args.assets_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
