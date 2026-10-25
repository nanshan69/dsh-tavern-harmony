#!/usr/bin/env python3
"""DSHM variant of extract_pdf_assets.py - pure Python, no poppler, no PIL.

HarmonyOS / DSHM has no ``pdfinfo``, ``pdftotext``, ``pdftocairo`` or
ImageMagick, and native wheels (PyMuPDF, Pillow) cannot load.  This script
reproduces the same work skeleton with only the standard library plus
``pypdf`` (``pip3 install pypdf``):

  <work-dir>/source_layout.txt      # text with layout/whitespace preserved
  <work-dir>/source_raw.txt         # plain reading-order text per page
  <work-dir>/pages/page-NN.txt      # one file per page (chunked translation)
  <work-dir>/meta.json              # pages, title, per-page stats, image index
  <assets-dir>/pNN-imgM.png|.jpg    # raster images harvested from the PDF

Differences from upstream:

* No page rasterisation.  Vector figures (TikZ, matplotlib SVG output) cannot
  be turned into images here, they are only reported in ``meta.json`` under
  ``warnings``.  Raster figures (JPEG / Flate embedded images, the usual case
  for scans, photos and publisher-rasterised figures) are extracted directly.
* No ImageMagick cropping.  Extracted images are already the figure itself, so
  cropping is normally unnecessary.

Usage::

    python3 extract_pdf_assets_dshm.py paper.pdf \
        --work-dir paper_zh_work --assets-dir paper_zh_assets
"""

import argparse
import hashlib
import json
import os
import struct
import sys
import zlib
from pathlib import Path

try:
    from pypdf import PdfReader
    from pypdf.generic import IndirectObject
except ImportError:  # pragma: no cover
    print("pypdf missing: run `pip3 install pypdf`", file=sys.stderr)
    raise SystemExit(3)

MIN_W, MIN_H = 80, 60
MIN_AREA = 12000

# ---------------------------------------------------------------- png writer


def _png(width: int, height: int, rgb: bytes) -> bytes:
    """Wrap raw 8-bit DeviceRGB sample rows (3 bytes/pixel) into a PNG file."""
    stride = width * 3
    if len(rgb) < stride * height:
        raise ValueError("short RGB buffer: %d < %d" % (len(rgb), stride * height))
    rows = bytearray()
    for y in range(height):
        rows.append(0)  # filter type 0 (None)
        rows += rgb[y * stride:(y + 1) * stride]
    out = bytearray(b"\x89PNG\r\n\x1a\n")

    def chunk(tag: bytes, payload: bytes) -> None:
        out.extend(struct.pack(">I", len(payload)))
        out.extend(tag)
        out.extend(payload)
        out.extend(struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))

    chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    chunk(b"IDAT", zlib.compress(bytes(rows), 6))
    chunk(b"IEND", b"")
    return bytes(out)


def _flate(data: bytes) -> bytes:
    try:
        return zlib.decompress(data)
    except zlib.error:
        d = zlib.decompressobj()
        return d.decompress(data)


def _expand_bits(data: bytes, width: int, height: int, bpc: int) -> bytes:
    """Expand 1/2/4/8/16-bit samples to one byte per sample."""
    if bpc == 8:
        return data
    if bpc == 16:
        return bytes(data[0::2])  # keep high byte, good enough for figures
    if bpc not in (1, 2, 4):
        raise ValueError("unsupported bits per component: %d" % bpc)
    per_byte = 8 // bpc
    mask = (1 << bpc) - 1
    total = width * height
    out = bytearray(total)
    i = 0
    for byte in data:
        for k in range(per_byte):
            if i >= total:
                return bytes(out)
            shift = 8 - bpc * (k + 1)
            out[i] = (byte >> shift) & mask
            i += 1
    return bytes(out)


def _colorspace_info(cs, res=None) -> tuple[str, int, bytes | None]:
    """Return (kind, ncomponents, palette) for an image colour space."""
    if cs is None:
        return "gray", 1, None
    if isinstance(cs, IndirectObject):
        cs = cs.get_object()
    if isinstance(cs, list) and cs:
        head = cs[0]
        if isinstance(head, IndirectObject):
            head = head.get_object()
        if head == "/Indexed":
            base = cs[1]
            if isinstance(base, IndirectObject):
                base = base.get_object()
            _, nbase, _ = _colorspace_info(base, res)
            lookup = cs[3]
            if isinstance(lookup, IndirectObject):
                lookup = lookup.get_object()
            if hasattr(lookup, "get_data"):
                lookup = lookup.get_data()
            elif isinstance(lookup, str):
                lookup = lookup.encode("latin-1")
            return "indexed", nbase, bytes(lookup)
        if head == "/ICCBased":
            stream = cs[1].get_object()
            return "rgb", int(stream.get("/N", 3)), None
        cs = head
    name = str(cs)
    if name in ("/DeviceRGB", "/CalRGB"):
        return "rgb", 3, None
    if name in ("/DeviceGray", "/CalGray"):
        return "gray", 1, None
    if name == "/DeviceCMYK":
        return "cmyk", 4, None
    return "rgb", 3, None


def _to_rgb(raw: bytes, kind: str, ncomp: int) -> bytes:
    """Normalise samples to 8-bit DeviceRGB (3 bytes per pixel)."""
    if kind == "rgb" and ncomp == 3:
        return raw
    if kind == "gray" and ncomp == 1:
        out = bytearray(len(raw) * 3)
        out[0::3] = raw
        out[1::3] = raw
        out[2::3] = raw
        return bytes(out)
    if kind == "cmyk" and ncomp == 4:
        out = bytearray(len(raw) // 4 * 3)
        for i in range(0, len(raw) - 3, 4):
            c, m, y, k = raw[i], raw[i + 1], raw[i + 2], raw[i + 3]
            o = i // 4 * 3
            out[o] = (255 - c) * (255 - k) // 255
            out[o + 1] = (255 - m) * (255 - k) // 255
            out[o + 2] = (255 - y) * (255 - k) // 255
        return bytes(out)
    raise ValueError("cannot convert %s/%d to RGB" % (kind, ncomp))


def _image_bytes(obj) -> tuple[str, bytes]:
    """Return (extension, file bytes) for one image XObject."""
    filters = obj.get("/Filter")
    if isinstance(filters, IndirectObject):
        filters = filters.get_object()
    if not isinstance(filters, list):
        filters = [filters] if filters is not None else []
    filters = [str(f.get_object() if isinstance(f, IndirectObject) else f) for f in filters]

    if "/DCTDecode" in filters:
        data = obj._data  # raw JPEG stream
        if isinstance(data, str):
            data = data.encode("latin-1")
        return "jpg", data
    if "/JPXDecode" in filters:
        data = obj._data
        if isinstance(data, str):
            data = data.encode("latin-1")
        return "jp2", data
    if filters not in ([], ["/FlateDecode"]):
        raise ValueError("unsupported filter chain: %s" % filters)

    width = int(obj["/Width"])
    height = int(obj["/Height"])
    bpc = int(obj.get("/BitsPerComponent", 8))
    kind, ncomp, palette = _colorspace_info(obj.get("/ColorSpace"))

    # pypdf already applies FlateDecode in get_data(); fall back to raw deflate
    # only if the object refuses to decode.
    try:
        raw = obj.get_data()
    except Exception:
        payload = obj._data
        if isinstance(payload, str):
            payload = payload.encode("latin-1")
        raw = _flate(payload)
    if len(raw) < width * height * max(ncomp, 1) and filters == ["/FlateDecode"]:
        raise ValueError("short Flate stream (%d bytes for %dx%d/%d)"
                         % (len(raw), width, height, ncomp))
    raw = _expand_bits(raw, width, height, bpc)
    if kind == "indexed" and palette is not None:
        stride = width * ncomp
        out = bytearray(width * height * 3)
        for y in range(height):
            row = raw[y * stride:(y + 1) * stride]
            for x in range(width):
                idx = row[x * ncomp] if ncomp > 1 else row[x]
                p = idx * 3
                triple = palette[p:p + 3]
                o = (y * width + x) * 3
                out[o:o + 3] = triple + b"\x00" * (3 - len(triple))
        return "png", _png(width, height, bytes(out))

    rgb = _to_rgb(raw, kind, ncomp)
    return "png", _png(width, height, rgb)


# ------------------------------------------------------------------- extract


def harvest_images(page, page_no: int, assets_dir: Path, seen: dict,
                   warnings: list[str]) -> list[dict]:
    out: list[dict] = []
    resources = page.get("/Resources")
    if resources is None:
        return out
    resources = resources.get_object()
    xobjects = resources.get("/XObject")
    if xobjects is None:
        return out
    xobjects = xobjects.get_object()
    index = 0
    for name in xobjects:
        try:
            obj = xobjects[name].get_object()
        except Exception:
            continue
        if str(obj.get("/Subtype")) != "/Image":
            continue
        try:
            width = int(obj.get("/Width", 0))
            height = int(obj.get("/Height", 0))
        except Exception:
            continue
        if width < MIN_W or height < MIN_H or width * height < MIN_AREA:
            warnings.append("page %d %s: skipped small image %dx%d" % (page_no, name, width, height))
            continue
        try:
            ext, data = _image_bytes(obj)
        except Exception as exc:  # pragma: no cover - defensive
            warnings.append("page %d %s: cannot decode (%s); vector or exotic image"
                            % (page_no, name, exc))
            continue
        digest = hashlib.sha1(data).hexdigest()
        if digest in seen:
            continue
        seen[digest] = True
        index += 1
        fname = "p%02d-img%d.%s" % (page_no, index, ext)
        (assets_dir / fname).write_bytes(data)
        out.append({"file": fname, "page": page_no, "name": str(name),
                    "width": width, "height": height, "bytes": len(data)})
    return out


def main() -> int:
    # DSHM's in-process python runner exposes argv as [prog, <script>, *args]
    # and does not define __file__; a real `python3 script.py ...` passes only
    # the user arguments.  Normalise both so argparse sees the user's args.
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
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pdf", type=Path)
    ap.add_argument("--work-dir", type=Path, required=True)
    ap.add_argument("--assets-dir", type=Path)
    ap.add_argument("--max-pages", type=int, default=0, help="0 = all")
    args = ap.parse_args()

    pdf = args.pdf
    if not pdf.exists():
        print("missing PDF: %s" % pdf, file=sys.stderr)
        return 2
    work = args.work_dir
    assets = args.assets_dir or (work.parent / (pdf.stem + "_assets"))
    (work / "pages").mkdir(parents=True, exist_ok=True)
    assets.mkdir(parents=True, exist_ok=True)

    reader = PdfReader(str(pdf))
    pages = list(reader.pages)
    if args.max_pages:
        pages = pages[:args.max_pages]
    meta = reader.metadata or {}
    title = (str(meta.get("/Title") or "").strip()) or pdf.stem

    warnings: list[str] = []
    plain_pages: list[str] = []
    layout_pages: list[str] = []
    images: list[dict] = []
    seen: dict = {}
    stats = []
    for i, page in enumerate(pages, 1):
        try:
            plain = page.extract_text() or ""
        except Exception as exc:
            plain = ""
            warnings.append("page %d: text extraction failed (%s)" % (i, exc))
        try:
            layout = page.extract_text(extraction_mode="layout") or ""
        except Exception as exc:
            layout = plain
            warnings.append("page %d: layout extraction failed (%s)" % (i, exc))
        plain_pages.append(plain)
        layout_pages.append(layout)
        (work / "pages" / ("page-%02d.txt" % i)).write_text(
            "# page %d\n\n%s\n" % (i, layout), encoding="utf-8")
        found = harvest_images(page, i, assets, seen, warnings)
        images.extend(found)
        stats.append({"page": i, "chars_plain": len(plain), "chars_layout": len(layout),
                      "images": len(found)})

    (work / "source_raw.txt").write_text("\f".join(plain_pages), encoding="utf-8")
    (work / "source_layout.txt").write_text("\f".join(layout_pages), encoding="utf-8")

    total = sum(s["chars_plain"] for s in stats)
    if not images:
        warnings.append("no raster images found: figures are probably vector "
                        "(TikZ/SVG); DSHM cannot rasterise them without poppler")
    meta_out = {
        "source_pdf": str(pdf),
        "title_guess": title,
        "pages": len(pages),
        "chars_total": total,
        "chars_total_layout": sum(s["chars_layout"] for s in stats),
        "chars_per_page": stats,
        "images": images,
        "warnings": warnings,
        "engine": "pypdf %s (no poppler/PIL)" % getattr(__import__("pypdf"), "__version__", "?"),
    }
    (work / "meta.json").write_text(json.dumps(meta_out, ensure_ascii=False, indent=2),
                                    encoding="utf-8")
    print("work_dir: %s" % work)
    print("assets_dir: %s" % assets)
    print("pages: %d  chars: %d  images: %d" % (len(pages), total, len(images)))
    for w in warnings[:12]:
        print("  ! %s" % w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
