#!/usr/bin/env python3
"""读取/检索 .docx（纯标准库：zipfile + ElementTree 解析 OOXML）。

用法：
  python scripts/docx_tools.py extract docs/方案.docx          # 转纯文本
  python scripts/docx_tools.py extract 输入.docx --format md --out 导出.md                  # 转 Markdown
  python scripts/docx_tools.py outline 输入.docx                                            # 只看标题结构
  python scripts/docx_tools.py search  输入.docx --pattern "样本量" --context 1             # 检索段落
  python scripts/docx_tools.py stats   输入.docx                                            # 字数/段落/表格统计
"""
import argparse
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.environ.get("DSH_TOOL_DIR") or os.path.dirname(os.path.abspath(globals().get("__file__", "run_tool.py"))))
from _util import ensure_parent, resolve_path  # noqa: E402

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
NS = {"w": W[1:-1]}


def _p_text(p) -> str:
    parts = []
    for t in p.iter(W + "t"):
        if t.text:
            parts.append(t.text)
    for br in p.iter(W + "br"):
        if br.get(W + "type") == "page":
            parts.append("\n[[分页]]\n")
    return "".join(parts)


def _p_style(p) -> str:
    st = p.find(f".//{W}pStyle")
    return st.get(W + "val") if st is not None else ""


def _p_is_list(p) -> tuple[bool, int]:
    num = p.find(f".//{W}numPr")
    if num is None:
        return False, 0
    ilvl = num.find(f"{W}ilvl")
    return True, int(ilvl.get(W + "val", "0")) if ilvl is not None else 0


def _p_align(p) -> str:
    jc = p.find(f".//{W}jc")
    return jc.get(W + "val") if jc is not None else ""


def _table_rows(tbl) -> list[list[str]]:
    rows = []
    for tr in tbl.findall(f"{W}tr"):
        cells = []
        for tc in tr.findall(f"{W}tc"):
            cells.append("\n".join(_p_text(p).strip() for p in tc.findall(f"{W}p")).strip())
        rows.append(cells)
    return rows


def iter_blocks(path):
    """按文档顺序产出 (类型, 内容)；类型为 'p' 或 'table'。"""
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    body = root.find(f"{W}body")
    if body is None:
        return
    for child in body:
        if child.tag == f"{W}p":
            yield "p", child
        elif child.tag == f"{W}tbl":
            yield "table", child


def to_markdown(path) -> str:
    out: list[str] = []
    for kind, node in iter_blocks(path):
        if kind == "table":
            rows = _table_rows(node)
            if not rows:
                continue
            out.append("")
            out.append("| " + " | ".join(c.replace("|", "\\|") for c in rows[0]) + " |")
            out.append("|" + "|".join(["---"] * len(rows[0])) + "|")
            for r in rows[1:]:
                out.append("| " + " | ".join(c.replace("|", "\\|") for c in r) + " |")
            out.append("")
            continue
        text = _p_text(node).strip()
        style = _p_style(node)
        if not text:
            if style.startswith("Heading"):
                continue
            out.append("")
            continue
        m = re.match(r"(?:Heading|heading)\s*(\d)", style)
        if m:
            out.append("#" * int(m.group(1)) + " " + text)
        elif style == "Title":
            out.append("# " + text)
        elif style == "Quote":
            out.append("> " + text)
        elif style == "Code":
            out.append("    " + text)
        else:
            is_list, ilvl = _p_is_list(node)
            if is_list:
                out.append("  " * ilvl + "- " + text)
            else:
                out.append(text)
    md = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"


def to_text(path) -> str:
    out: list[str] = []
    for kind, node in iter_blocks(path):
        if kind == "table":
            for r in _table_rows(node):
                out.append("\t".join(r))
            out.append("")
        else:
            text = _p_text(node).strip()
            if text:
                out.append(text)
    return "\n".join(out).strip() + "\n"


def outline(path) -> list[tuple[int, str]]:
    items = []
    for kind, node in iter_blocks(path):
        if kind != "p":
            continue
        text = _p_text(node).strip()
        style = _p_style(node)
        m = re.match(r"(?:Heading|heading)\s*(\d)", style)
        if m and text:
            items.append((int(m.group(1)), text))
    return items


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="读取/检索 .docx（纯标准库）")
    ap.add_argument("cmd", choices=["extract", "outline", "search", "stats"])
    ap.add_argument("file")
    ap.add_argument("--format", default="md", choices=["md", "txt"])
    ap.add_argument("--out")
    ap.add_argument("--pattern")
    ap.add_argument("--context", type=int, default=1)
    args = ap.parse_args(argv)
    src = resolve_path(args.file)
    if not src.is_file():
        print(f"[错误] 找不到文件：{src}", file=sys.stderr)
        return 1

    if args.cmd == "extract":
        text = to_markdown(src) if args.format == "md" else to_text(src)
        if args.out:
            out = resolve_path(args.out)
            ensure_parent(out)
            out.write_text(text, encoding="utf-8")
            print(f"[完成] {src.name} → {out}（{len(text)} 字符）")
        else:
            print(text)
    elif args.cmd == "outline":
        items = outline(src)
        print(f"# {src.name} 标题结构（{len(items)} 个标题）")
        for level, text in items:
            print("  " * (level - 1) + ("#" * level) + f" {text}")
    elif args.cmd == "search":
        if not args.pattern:
            print("search 需要 --pattern", file=sys.stderr)
            return 2
        paras = [(_p_text(n) or "").strip() for k, n in iter_blocks(src) if k == "p"]
        paras = [p for p in paras if p]
        rx = re.compile(args.pattern)
        hits = [i for i, p in enumerate(paras) if rx.search(p)]
        print(f"[检索] 命中 {len(hits)} 段（模式：{args.pattern}）")
        for i in hits[:50]:
            lo, hi = max(0, i - args.context), min(len(paras), i + args.context + 1)
            print("-" * 60)
            for j in range(lo, hi):
                mark = ">>" if j == i else "  "
                print(f"{mark} {paras[j][:300]}")
    else:
        paras = [p for k, n in iter_blocks(src) if k == "p" for p in [(_p_text(n) or "").strip()] if p]
        tables = [n for k, n in iter_blocks(src) if k == "table"]
        chars = sum(len(p) for p in paras)
        cjk = sum(len(re.findall(r"[\u4e00-\u9fff]", p)) for p in paras)
        print(f"文件：{src.name}")
        print(f"段落：{len(paras)}；表格：{len(tables)}；字符：{chars}（其中汉字 {cjk}）")
        print(f"估算字数：约 {cjk + len(re.findall(r'[A-Za-z]+', ' '.join(paras)))} 字（不含标点/表格）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
