#!/usr/bin/env python3
"""PDF 文本提取与检索（依赖 pypdf，纯 Python 包，可用 scripts/deps.py install 安装）。

用法：
  python scripts/pdf_tools.py text fulltext/inbox/xxx.pdf            # 输出到同目录同名 .txt
  python scripts/pdf_tools.py text xxx.pdf --outdir fulltext             # 输出到指定目录
  python scripts/pdf_tools.py batch fulltext/待下载PDF --outdir fulltext
  python scripts/pdf_tools.py info  xxx.pdf
  python scripts/pdf_tools.py search xxx.pdf --pattern "photobiomodulation"
"""
import argparse
import os
import re
import sys

sys.path.insert(0, os.environ.get("DSH_TOOL_DIR") or os.path.dirname(os.path.abspath(globals().get("__file__", "run_tool.py"))))
from _util import ensure_parent, resolve_path  # noqa: E402


def _pypdf():
    try:
        import pypdf  # noqa: WPS433
        return pypdf
    except ImportError:
        print("[缺少依赖] pypdf 未安装。先运行：\n"
              "  python scripts/deps.py install\n"
              "（需要联网；装到内嵌 CPython 的 site-packages）", file=sys.stderr)
        raise SystemExit(3)


def extract_text(path, page_range: str | None = None) -> str:
    pypdf = _pypdf()
    reader = pypdf.PdfReader(str(path))
    pages = range(len(reader.pages))
    if page_range:
        m = re.match(r"(\d+)\s*[-–]\s*(\d+)", page_range)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            pages = range(max(0, a - 1), min(len(reader.pages), b))
    out = []
    for i in pages:
        try:
            txt = reader.pages[i].extract_text() or ""
        except Exception as exc:  # noqa: BLE001
            txt = f"[第 {i + 1} 页提取失败：{exc}]"
        out.append(f"\n\n===== 第 {i + 1} 页 =====\n{txt.strip()}")
    meta = reader.metadata or {}
    head = []
    if meta.get("/Title"):
        head.append(f"# 标题: {meta.get('/Title')}")
    if meta.get("/Author"):
        head.append(f"# 作者: {meta.get('/Author')}")
    if meta.get("/CreationDate"):
        head.append(f"# 创建日期: {meta.get('/CreationDate')}")
    return "\n".join(head) + "\n" + "".join(out)


def do_one(pdf, outdir, page_range) -> str:
    text = extract_text(pdf, page_range)
    outdir = resolve_path(outdir) if outdir else pdf.parent
    outdir.mkdir(parents=True, exist_ok=True)
    out = outdir / (pdf.stem + ".txt")
    out.write_text(text, encoding="utf-8")
    return str(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="PDF 文本提取与检索")
    ap.add_argument("cmd", choices=["text", "batch", "info", "search"])
    ap.add_argument("file")
    ap.add_argument("--outdir")
    ap.add_argument("--pages", help="页码范围，如 1-3")
    ap.add_argument("--pattern")
    args = ap.parse_args(argv)
    src = resolve_path(args.file)

    if args.cmd == "batch":
        if not src.is_dir():
            print(f"[错误] 不是目录：{src}", file=sys.stderr)
            return 1
        pdfs = sorted(p for p in src.iterdir() if p.suffix.lower() == ".pdf")
        if not pdfs:
            print(f"[提示] {src} 下没有 PDF")
            return 0
        for p in pdfs:
            try:
                out = do_one(p, args.outdir, args.pages)
                print(f"[完成] {p.name} → {out}")
            except Exception as exc:  # noqa: BLE001
                print(f"[失败] {p.name}: {exc}")
        return 0
    if not src.is_file():
        print(f"[错误] 找不到文件：{src}", file=sys.stderr)
        return 1
    if args.cmd == "text":
        out = do_one(src, args.outdir, args.pages)
        print(f"[完成] {src.name} → {out}")
    elif args.cmd == "info":
        pypdf = _pypdf()
        reader = pypdf.PdfReader(str(src))
        meta = reader.metadata or {}
        print(f"文件：{src.name}\n页数：{len(reader.pages)}")
        for k, v in meta.items():
            print(f"{k}: {v}")
    else:
        if not args.pattern:
            print("search 需要 --pattern", file=sys.stderr)
            return 2
        text = extract_text(src, args.pages)
        rx = re.compile(args.pattern, re.IGNORECASE)
        hits = [m for m in rx.finditer(text)]
        print(f"[检索] 命中 {len(hits)} 处")
        for m in hits[:40]:
            lo, hi = max(0, m.start() - 120), min(len(text), m.end() + 120)
            print("-" * 60)
            print(text[lo:hi].replace("\n", " "))
    return 0


if __name__ == "__main__":
    sys.exit(main())
