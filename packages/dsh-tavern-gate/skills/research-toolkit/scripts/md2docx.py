#!/usr/bin/env python3
"""Markdown → DOCX 转换（纯标准库实现，不依赖 python-docx / LibreOffice / pandoc）。

为什么不用 python-docx：本机内嵌 CPython 无法加载 lxml 等 C 扩展，python-docx 装不上。
所以这里直接按 OOXML 拼 XML 并打包成 zip —— 生成的 .docx 可被 Word / WPS / 系统预览打开。

支持：ATX 标题(#~######)、段落、**加粗**、*斜体*、`行内代码`、[链接](url)（只保留文字）、
GFM 表格、无序/有序列表（最多 3 级）、引用块、代码块、分隔线、YAML frontmatter 跳过、
`<!-- pagebreak -->` 分页、页码页脚、可选目录域（Word 打开时按提示更新）、A4 版式、中文字体。
排版（2026-10-21 升级）：正文首行缩进 2 字符 + 两端对齐；表格默认学术三线表（--table-style grid
保留全框线）；--cover 独立封面页（标题/副标题/作者/日期，封面不显示页眉页码）；--header 页眉。

用法：
  python scripts/md2docx.py docs/方案.md
  python scripts/md2docx.py 输入.md --out docs/输出.docx --title "研究方案" --toc
  python scripts/md2docx.py 输入.md --out 预览.docx --cover --title 题目 --subtitle 副题 \
      --author "学位申请人：XXX" --date today --header "研究方案"
不传 --out 时，输出为同目录同名 .docx（覆盖同名旧文件，请先确认）。
"""
import argparse
import datetime as _dt
import os
import re
import sys
import zipfile
from xml.sax.saxutils import escape as _esc

sys.path.insert(0, os.environ.get("DSH_TOOL_DIR") or os.path.dirname(os.path.abspath(globals().get("__file__", "run_tool.py"))))
from _util import ensure_parent, resolve_path  # noqa: E402

W_NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
R_NS = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

# 版式（单位：twip，1 英寸 = 1440）
PAGE_W, PAGE_H = 11906, 16838  # A4
MARGIN = 1440                  # 1 英寸
TEXT_W = PAGE_W - 2 * MARGIN   # 正文可用宽度

# ---------------------------------------------------------------- 样式
STYLES_XML = XML_DECL + f'''<w:styles {W_NS}>
<w:docDefaults>
  <w:rPrDefault><w:rPr>
    <w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="宋体" w:cs="Times New Roman"/>
    <w:sz w:val="21"/><w:szCs w:val="21"/>
    <w:lang w:val="en-US" w:eastAsia="zh-CN"/>
  </w:rPr></w:rPrDefault>
  <w:pPrDefault><w:pPr><w:spacing w:after="120" w:line="360" w:lineRule="auto"/></w:pPr></w:pPrDefault>
</w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
  <w:pPr><w:jc w:val="center"/><w:spacing w:before="240" w:after="120"/></w:pPr>
  <w:rPr><w:rFonts w:ascii="Times New Roman" w:eastAsia="黑体"/><w:b/><w:sz w:val="36"/><w:szCs w:val="36"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Subtitle"><w:name w:val="Subtitle"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
  <w:pPr><w:jc w:val="center"/><w:spacing w:after="240"/></w:pPr>
  <w:rPr><w:rFonts w:eastAsia="楷体"/><w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
  <w:pPr><w:keepNext/><w:spacing w:before="360" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr>
  <w:rPr><w:rFonts w:ascii="Times New Roman" w:eastAsia="黑体"/><w:b/><w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
  <w:pPr><w:keepNext/><w:spacing w:before="240" w:after="80"/><w:outlineLvl w:val="1"/></w:pPr>
  <w:rPr><w:rFonts w:ascii="Times New Roman" w:eastAsia="黑体"/><w:b/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
  <w:pPr><w:keepNext/><w:spacing w:before="200" w:after="60"/><w:outlineLvl w:val="2"/></w:pPr>
  <w:rPr><w:rFonts w:ascii="Times New Roman" w:eastAsia="黑体"/><w:b/><w:sz w:val="24"/><w:szCs w:val="24"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading4"><w:name w:val="heading 4"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:qFormat/>
  <w:pPr><w:keepNext/><w:spacing w:before="160" w:after="60"/><w:outlineLvl w:val="3"/></w:pPr>
  <w:rPr><w:rFonts w:eastAsia="黑体"/><w:b/><w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:basedOn w:val="Normal"/><w:qFormat/>
  <w:pPr><w:ind w:left="420" w:right="420"/><w:spacing w:after="100"/></w:pPr>
  <w:rPr><w:i/><w:color w:val="404040"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Code"><w:name w:val="Code"/><w:basedOn w:val="Normal"/>
  <w:pPr><w:shd w:val="clear" w:color="auto" w:fill="F2F2F2"/><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr>
  <w:rPr><w:rFonts w:ascii="Courier New" w:hAnsi="Courier New"/><w:sz w:val="18"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="BodyText"><w:name w:val="Body Text"/><w:basedOn w:val="Normal"/><w:qFormat/>
  <w:pPr><w:ind w:firstLineChars="200" w:firstLine="420"/><w:jc w:val="both"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="TableText"><w:name w:val="Table Text"/><w:basedOn w:val="Normal"/><w:qFormat/>
  <w:pPr><w:spacing w:before="40" w:after="40" w:line="260" w:lineRule="auto"/></w:pPr>
  <w:rPr><w:sz w:val="19"/><w:szCs w:val="19"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="CoverTitle"><w:name w:val="Cover Title"/><w:basedOn w:val="Normal"/><w:qFormat/>
  <w:pPr><w:jc w:val="center"/><w:spacing w:before="2400" w:after="480" w:line="440" w:lineRule="auto"/></w:pPr>
  <w:rPr><w:rFonts w:ascii="Times New Roman" w:hAnsi="Times New Roman" w:eastAsia="黑体"/><w:b/><w:sz w:val="44"/><w:szCs w:val="44"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="CoverSub"><w:name w:val="Cover Subtitle"/><w:basedOn w:val="Normal"/><w:qFormat/>
  <w:pPr><w:jc w:val="center"/><w:spacing w:after="240"/></w:pPr>
  <w:rPr><w:rFonts w:eastAsia="楷体"/><w:sz w:val="30"/><w:szCs w:val="30"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="CoverMeta"><w:name w:val="Cover Meta"/><w:basedOn w:val="Normal"/><w:qFormat/>
  <w:pPr><w:jc w:val="center"/><w:spacing w:after="120"/></w:pPr>
  <w:rPr><w:rFonts w:eastAsia="宋体"/><w:sz w:val="28"/><w:szCs w:val="28"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Header"><w:name w:val="header"/><w:basedOn w:val="Normal"/>
  <w:pPr><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="auto"/></w:pBdr>
  <w:spacing w:after="0" w:line="240" w:lineRule="auto"/><w:jc w:val="center"/></w:pPr>
  <w:rPr><w:sz w:val="18"/><w:szCs w:val="18"/></w:rPr></w:style>
<w:style w:type="table" w:styleId="ThreeLine"><w:name w:val="Three Line Table"/><w:tblPr>
  <w:jc w:val="center"/>
  <w:tblBorders><w:top w:val="single" w:sz="12" w:color="000000"/><w:left w:val="nil"/>
  <w:bottom w:val="single" w:sz="12" w:color="000000"/><w:right w:val="nil"/>
  <w:insideH w:val="nil"/><w:insideV w:val="nil"/></w:tblBorders>
</w:tblPr></w:style>
<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/><w:tblPr>
  <w:tblBorders><w:top w:val="single" w:sz="4" w:color="808080"/><w:left w:val="single" w:sz="4" w:color="808080"/>
  <w:bottom w:val="single" w:sz="4" w:color="808080"/><w:right w:val="single" w:sz="4" w:color="808080"/>
  <w:insideH w:val="single" w:sz="4" w:color="808080"/><w:insideV w:val="single" w:sz="4" w:color="808080"/></w:tblBorders>
</w:tblPr></w:style>
</w:styles>'''

def numbering_xml(ol_count: int = 0) -> str:
    """生成 numbering.xml。

    ol_count = 有序列表的**块数**：每个块一个独立 <w:num>（共用同一 abstractNum），
    这样 Word/WPS 里每个有序列表都从 1 重新计数；共用一个 numId 会让全文档连号
    （曾导致 4.1 列到 5、4.2 接着 6、6.2 再接着往下）。
    """
    nums = ['<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>']
    for k in range(max(ol_count, 1)):
        nums.append(f'<w:num w:numId="{2 + k}"><w:abstractNumId w:val="1"/>'
                    '<w:lvlOverride w:ilvl="0"><w:startOverride w:val="1"/></w:lvlOverride>'
                    '<w:lvlOverride w:ilvl="1"><w:startOverride w:val="1"/></w:lvlOverride>'
                    '<w:lvlOverride w:ilvl="2"><w:startOverride w:val="1"/></w:lvlOverride>'
                    "</w:num>")
    return XML_DECL + f'''<w:numbering {W_NS}>
<w:abstractNum w:abstractNumId="0"><w:multiLevelType w:val="hybridMultilevel"/>
  <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="•"/><w:lvlJc w:val="left"/>
    <w:pPr><w:ind w:left="420" w:hanging="420"/></w:pPr></w:lvl>
  <w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="◦"/><w:lvlJc w:val="left"/>
    <w:pPr><w:ind w:left="840" w:hanging="420"/></w:pPr></w:lvl>
  <w:lvl w:ilvl="2"><w:start w:val="1"/><w:numFmt w:val="bullet"/><w:lvlText w:val="▪"/><w:lvlJc w:val="left"/>
    <w:pPr><w:ind w:left="1260" w:hanging="420"/></w:pPr></w:lvl>
</w:abstractNum>
<w:abstractNum w:abstractNumId="1"><w:multiLevelType w:val="hybridMultilevel"/>
  <w:lvl w:ilvl="0"><w:start w:val="1"/><w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/><w:lvlJc w:val="left"/>
    <w:pPr><w:ind w:left="420" w:hanging="420"/></w:pPr></w:lvl>
  <w:lvl w:ilvl="1"><w:start w:val="1"/><w:numFmt w:val="lowerLetter"/><w:lvlText w:val="%2)"/><w:lvlJc w:val="left"/>
    <w:pPr><w:ind w:left="840" w:hanging="420"/></w:pPr></w:lvl>
  <w:lvl w:ilvl="2"><w:start w:val="1"/><w:numFmt w:val="lowerRoman"/><w:lvlText w:val="%3."/><w:lvlJc w:val="left"/>
    <w:pPr><w:ind w:left="1260" w:hanging="420"/></w:pPr></w:lvl>
</w:abstractNum>
{chr(10).join(nums)}
</w:numbering>'''


NUMBERING_XML = numbering_xml(1)  # 兼容旧引用；实际按有序列表块数动态生成

SETTINGS_XML = XML_DECL + f'''<w:settings {W_NS}>
<w:zoom w:percent="100"/><w:defaultTabStop w:val="420"/>
<w:updateFields w:val="true"/>
<w:compat><w:compatSetting w:name="compatibilityMode" w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat>
</w:settings>'''

FOOTER_XML = XML_DECL + f'''<w:ftr {W_NS} {R_NS}>
<w:p><w:pPr><w:jc w:val="center"/></w:pPr>
<w:r><w:fldChar w:fldCharType="begin"/></w:r>
<w:r><w:instrText xml:space="preserve"> PAGE </w:instrText></w:r>
<w:r><w:fldChar w:fldCharType="separate"/></w:r>
<w:r><w:t>1</w:t></w:r>
<w:r><w:fldChar w:fldCharType="end"/></w:r>
</w:p></w:ftr>'''


# ---------------------------------------------------------------- 行内解析
_INLINE = re.compile(
    r"(\*\*[^*]+\*\*|__[^_]+__|`[^`]+`|\*[^*]+\*|_[^_]+_|\[[^\]]+\]\([^)]+\)|~~[^~]+~~)")


def inline_runs(text: str) -> list[tuple[str, dict]]:
    """把一行 Markdown 拆成 (文字, 格式) 片段。"""
    runs: list[tuple[str, dict]] = []
    pos = 0
    for m in _INLINE.finditer(text):
        if m.start() > pos:
            runs.append((text[pos:m.start()], {}))
        token = m.group(0)
        fmt: dict = {}
        if token.startswith("**") and token.endswith("**"):
            content, fmt = token[2:-2], {"b": True}
        elif token.startswith("__") and token.endswith("__"):
            content, fmt = token[2:-2], {"b": True}
        elif token.startswith("`") and token.endswith("`"):
            content, fmt = token[1:-1], {"code": True}
        elif token.startswith("~~") and token.endswith("~~"):
            content, fmt = token[2:-2], {"strike": True}
        elif token.startswith("[") and "](" in token:
            content = token[1:token.index("]")]
            fmt = {"link": token[token.index("](") + 2:-1]}
        else:
            content, fmt = token[1:-1], {"i": True}
        runs.append((content, fmt))
        pos = m.end()
    if pos < len(text):
        runs.append((text[pos:], {}))
    return [r for r in runs if r[0]]


def runs_xml(text: str, base_bold: bool = False) -> str:
    out = []
    for content, fmt in inline_runs(text):
        props = []
        if fmt.get("b") or base_bold:
            props.append("<w:b/>")
        if fmt.get("i"):
            props.append("<w:i/>")
        if fmt.get("strike"):
            props.append("<w:strike/>")
        if fmt.get("code"):
            props.append('<w:rFonts w:ascii="Courier New" w:hAnsi="Courier New"/>')
        rpr = f"<w:rPr>{''.join(props)}</w:rPr>" if props else ""
        out.append(f'<w:r>{rpr}<w:t xml:space="preserve">{_esc(content)}</w:t></w:r>')
    return "".join(out)


def para_xml(text: str = "", style: str | None = None, *, bold: bool = False,
             align: str | None = None, num_id: int | None = None, ilvl: int = 0,
             keep_next: bool = False, border_bottom: bool = False,
             indent_left: int | None = None, runs: str | None = None) -> str:
    ppr = []
    if style:
        ppr.append(f'<w:pStyle w:val="{style}"/>')
    if keep_next:
        ppr.append("<w:keepNext/>")
    if num_id is not None:
        ppr.append(f'<w:numPr><w:ilvl w:val="{ilvl}"/><w:numId w:val="{num_id}"/></w:numPr>')
    # 子元素顺序须符合 OOXML schema：numPr → pBdr → ind → jc（Word 对乱序较严格）
    if border_bottom:
        ppr.append('<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="999999"/></w:pBdr>')
    if indent_left:
        ppr.append(f'<w:ind w:left="{indent_left}"/>')
    if align:
        ppr.append(f'<w:jc w:val="{align}"/>')
    ppr_xml = f"<w:pPr>{''.join(ppr)}</w:pPr>" if ppr else ""
    body = runs if runs is not None else runs_xml(text, bold)
    return f"<w:p>{ppr_xml}{body}</w:p>"


# ---------------------------------------------------------------- 表格
def split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    cells, cur, i = [], "", 0
    while i < len(line):
        ch = line[i]
        if ch == "\\" and i + 1 < len(line) and line[i + 1] == "|":
            cur += "|"
            i += 2
            continue
        if ch == "|":
            cells.append(cur.strip())
            cur = ""
        else:
            cur += ch
        i += 1
    cells.append(cur.strip())
    return cells


def is_sep_row(cells: list[str]) -> bool:
    # GFM：分隔单元格至少 1 个 '-'（如 :-:）
    return bool(cells) and any(c.strip() for c in cells) and \
        all(re.fullmatch(r":?-+:?", c.strip()) for c in cells if c.strip())


def _disp_len(s: str) -> int:
    """显示宽度：中文/全角按 2，其余按 1（用于列宽估算）。"""
    import unicodedata
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)


def table_xml(header: list[str], rows: list[list[str]], col_aligns: list[str],
              style: str = "three-line") -> str:
    """style: three-line（学术三线表，默认）| grid（全框线 + 表头底色）。"""
    ncol = max([len(header)] + [len(r) for r in rows]) if (header or rows) else 0
    if ncol == 0:
        return ""
    weights = []
    for c in range(ncol):
        lengths = [_disp_len(header[c]) if c < len(header) else 0]
        lengths += [_disp_len(r[c]) if c < len(r) else 0 for r in rows]
        weights.append(max(6, min(80, max(lengths))))
    total = sum(weights)
    widths = [max(800, int(TEXT_W * w / total)) for w in weights]
    scale = TEXT_W / sum(widths)  # 最小宽度抬高后回缩到版心宽度内
    if scale < 1:
        widths = [int(w * scale) for w in widths]
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
    three = style != "grid"
    rule = '<w:bottom w:val="single" w:sz="6" w:space="0" w:color="000000"/>'

    def cell_xml(text: str, width: int, bold: bool, align: str | None, is_header: bool) -> str:
        tcpr = [f'<w:tcW w:w="{width}" w:type="dxa"/>']
        if is_header and three:
            tcpr.append(f"<w:tcBorders>{rule}</w:tcBorders>")  # 表头下细线（栏目线）
        elif is_header:
            tcpr.append('<w:shd w:val="clear" w:color="auto" w:fill="D9E2F3"/>')
        tcpr.append('<w:vAlign w:val="center"/>')
        body = para_xml("", style="TableText", bold=bold,
                        align=align or ("center" if is_header and three else None),
                        runs=runs_xml(text, bold))
        return f"<w:tc><w:tcPr>{''.join(tcpr)}</w:tcPr>{body}</w:tc>"

    tstyle = "ThreeLine" if three else "TableGrid"
    out = [f'<w:tbl><w:tblPr><w:tblStyle w:val="{tstyle}"/><w:tblW w:w="{sum(widths)}" w:type="dxa"/>'
           + ('<w:jc w:val="center"/>' if three else "")
           + '<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="1" w:lastColumn="0" w:noHBand="0" w:noVBand="1"/></w:tblPr>',
           f"<w:tblGrid>{grid}</w:tblGrid>"]
    if header:
        cells = [cell_xml(header[c] if c < len(header) else "", widths[c], True,
                          col_aligns[c] if c < len(col_aligns) else None, True) for c in range(ncol)]
        out.append(f'<w:tr><w:trPr><w:tblHeader/></w:trPr>{"".join(cells)}</w:tr>')
    for r in rows:
        if all(not c.strip() for c in r):
            continue
        cells = [cell_xml(r[c] if c < len(r) else "", widths[c], False,
                          col_aligns[c] if c < len(col_aligns) else None, False) for c in range(ncol)]
        out.append(f'<w:tr>{"".join(cells)}</w:tr>')
    out.append("</w:tbl>")
    out.append(para_xml(""))  # 表后空一行，防止表格粘连
    return "".join(out)


# ---------------------------------------------------------------- Markdown → body
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
UL_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
OL_RE = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
FENCE_RE = re.compile(r"^\s*```")

# 标题里手写的编号：0 / 4.1 / 13.2.1 / 6.1a（允许尾随 . 、 ．与单个字母后缀，如 6.1a）
NUM_HEAD_RE = re.compile(r"^(\d+(?:\.\d+)*[a-zA-Z]?)\s*[.、．:：]?\s+(\S.*)$")


def _tail_num(num: str) -> int:
    """取编号最后一段的数字部分：13.2→2，6.1a→1，7→7。"""
    seg = num.split(".")[-1]
    m = re.match(r"\d+", seg)
    return int(m.group(0)) if m else 0

# 不参与自动编号的章：附录、修订说明、致谢等
NO_NUM_HEAD_RE = re.compile(r"^(附录|附表|附件|附表|致谢|参考文献|修订说明|[vV]\d)")


def _scan_headings(lines: list[str]) -> list[tuple[int, str]]:
    """按文档顺序取出 (md 层级, 标题文本)，跳过代码块内的 #。"""
    out: list[tuple[int, str]] = []
    in_code = False
    for line in lines:
        if FENCE_RE.match(line):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = HEADING_RE.match(line.strip())
        if m:
            out.append((len(m.group(1)), m.group(2).strip()))
    return out


def plan_headings(heads: list[tuple[int, str]]) -> tuple[bool, list[str], list[str]]:
    """决定文档大标题是否下沉，并给缺号标题补号。

    返回 (shift, 每个标题的最终文本, 提示列表)。
    shift=True 表示唯一的 `#` 是文档题目 → 用 Title 样式（不进目录），其余层级上移一级，
    这样 Word 目录/导航窗格里“章=一级、节=二级”，序号才对得上。
    """
    notes: list[str] = []
    lv1 = [i for i, (lv, _) in enumerate(heads) if lv == 1]
    shift = len(lv1) == 1 and lv1[0] == 0 and len(heads) > 3
    if shift:
        notes.append("文档大标题用 Title 样式（不进目录），其下层级上移一级")
    base = 2 if shift else 1                      # 章的 md 层级
    texts = [t for _, t in heads]
    counters: dict[int, str | None] = {}          # 层级 → 本级当前编号
    kids: dict[int, int] = {}                     # 层级 → 已出现的小节数
    seen: dict[str, int] = {}
    for idx, (level, text) in enumerate(heads):
        m = NUM_HEAD_RE.match(text)
        explicit, rest = (m.group(1), m.group(2)) if m else (None, text)
        for deeper in [k for k in list(counters) if k > level]:
            counters.pop(deeper, None)
            kids.pop(deeper, None)
        if level < base:                           # 比章还高的层级（没有时）不编号
            counters[level] = None
            continue
        if level == base:
            # 章：显式编号优先；无编号且不是附录/修订说明时补一个
            if explicit:
                counters[level] = explicit
                num = explicit
            elif NO_NUM_HEAD_RE.match(text):
                counters[level] = None
                num = None
                notes.append(f"不编号（附录/说明类）：{text[:24]}")
            else:
                prev = kids.get(level, 0) + 1
                kids[level] = prev
                num = str(prev)
                counters[level] = num
                texts[idx] = f"{num} {text}"
                notes.append(f"补章号 {num}：{text[:24]}")
            kids[level] = max(kids.get(level, 0), _tail_num(num)) if num else kids.get(level, 0)
        else:
            parent = next((counters[k] for k in sorted(counters, reverse=True)
                           if k < level and counters[k]), None)
            if explicit:
                counters[level] = explicit
                n = _tail_num(explicit)
                kids[level] = max(kids.get(level, 0), n)
                if seen.get(explicit):
                    notes.append(f"编号重复：{explicit} 出现第 {seen[explicit] + 1} 次（未自动改，请核对正文交叉引用）")
                seen[explicit] = seen.get(explicit, 0) + 1
            elif parent:
                kids[level] = kids.get(level, 0) + 1
                num = f"{parent}.{kids[level]}"
                counters[level] = num
                texts[idx] = f"{num} {rest}"
                notes.append(f"补小节号 {num}：{text[:24]}")
            else:
                counters[level] = None
                notes.append(f"上级章无号，未补号：{text[:24]}")
    return shift, texts, notes


def convert_markdown(md: str, toc: bool = False, table_style: str = "three-line",
                     indent: bool = True, number_headings: str = "fill",
                     heading_shift: bool = True,
                     ol_continuous_headings: list[str] | None = None) -> tuple[str, int, int, list[str], int]:
    """ol_continuous_headings：这些关键词命中的一级标题章内，有序列表跨小节连续编号
    （参考文献正文常写"文献 22"这种全局序号）。其余处的有序列表每块从 1 重新计数。"""
    continuous_keys = [k for k in (ol_continuous_headings if ol_continuous_headings is not None
                                   else ["参考文献"]) if k]
    lines = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    # 跳过 YAML frontmatter
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() in ("---", "..."):
                lines = lines[i + 1:]
                break
    body: list[str] = []
    # 标题层级与编号：先整体规划，再逐行写入
    notes: list[str] = []
    shift = False
    head_texts: list[str] = []
    if heading_shift or number_headings != "off":
        heads = _scan_headings(lines)
        shift, head_texts, notes = plan_headings(heads)
        if not heading_shift:
            shift = False
        if number_headings == "off":
            head_texts = [t for _, t in heads]
            notes = []
    head_no = 0
    if toc:
        body.append(para_xml("目  录", style="Title"))
        body.append(para_xml(runs='<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                             '<w:r><w:instrText xml:space="preserve"> TOC \\o "1-3" \\h \\z \\u </w:instrText></w:r>'
                             '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
                             '<w:r><w:t>（在 Word 中右键“更新域”生成目录）</w:t></w:r>'
                             '<w:r><w:fldChar w:fldCharType="end"/></w:r>'))
        body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')  # 目录单独一页
    i, n_tables, n_para = 0, 0, 0
    in_code = False
    code_buf: list[str] = []
    in_list_region = False      # 当前是否处在同一个列表块内（块内共享一个有序编号实例）
    ol_started = False
    ol_blocks = 0
    cur_ol_num = 2
    cur_h1 = ""
    chapter_ol_num = None       # 「参考文献」这类章内跨小节连续编号用的 numId
    chapter_level = 2 if shift else 1
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # 非列表内容（标题/正文/表格/引用/分隔线）结束当前列表块；空行不结束
        if stripped and not (UL_RE.match(line) or OL_RE.match(line)):
            in_list_region, ol_started = False, False
        if FENCE_RE.match(line):
            if in_code:
                for cl in code_buf:
                    body.append(para_xml("", style="Code", runs=f'<w:r><w:t xml:space="preserve">{_esc(cl)}</w:t></w:r>'))
                code_buf = []
                in_code = False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue
        if not stripped:
            i += 1
            continue
        if stripped.lower() in ("<!-- pagebreak -->", "<!--pagebreak-->"):
            body.append('<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
            i += 1
            continue
        if stripped.startswith("<!--"):
            i += 1
            continue
        m = HEADING_RE.match(stripped)
        if m:
            level = len(m.group(1))
            text = head_texts[head_no] if head_no < len(head_texts) else m.group(2).strip()
            head_no += 1
            if shift and level == 1:
                style = "Title"            # 文档大标题：不进目录、不参与章编号
            else:
                style = f"Heading{min(max(1, level - (1 if shift else 0)), 4)}"
            body.append(para_xml(text, style=style))
            if level == chapter_level:       # 进入新的一章：重置跨节连续编号
                cur_h1 = text
                chapter_ol_num = None
            n_para += 1
            i += 1
            continue
        # 表格：当前行含 |，下一行是分隔行
        if "|" in stripped and i + 1 < len(lines) and "|" in lines[i + 1] and is_sep_row(split_row(lines[i + 1])):
            header = split_row(stripped)
            sep = split_row(lines[i + 1])
            aligns = []
            for c in sep:
                c = c.strip()
                aligns.append("center" if c.startswith(":") and c.endswith(":") else
                              "right" if c.endswith(":") else None)
            rows: list[list[str]] = []
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                rows.append(split_row(lines[j]))
                j += 1
            body.append(table_xml(header, rows, aligns, style=table_style))
            n_tables += 1
            i = j
            continue
        m = UL_RE.match(line)
        if m:
            level = min(len(m.group(1)) // 2, 2)
            in_list_region = True
            body.append(para_xml(m.group(2).strip(), num_id=1, ilvl=level))
            i += 1
            continue
        m = OL_RE.match(line)
        if m:
            level = min(len(m.group(1)) // 2, 2)
            continuous = any(k in cur_h1 for k in continuous_keys)
            if continuous:
                # 参考文献类：本章所有小节共用一个编号实例，全章连续
                if chapter_ol_num is None:
                    ol_blocks += 1
                    chapter_ol_num = 1 + ol_blocks
                num_id = chapter_ol_num
            else:
                if not ol_started:      # 每个列表块一个独立 numId → Word 里从 1 重新计数
                    ol_blocks += 1
                    cur_ol_num = 1 + ol_blocks
                    ol_started = True
                num_id = cur_ol_num
            in_list_region = True
            body.append(para_xml(m.group(2).strip(), num_id=num_id, ilvl=level))
            i += 1
            continue
        if stripped.startswith(">"):
            body.append(para_xml(stripped.lstrip("> ").strip(), style="Quote"))
            i += 1
            continue
        if re.fullmatch(r"[-*_]{3,}", stripped):
            body.append(para_xml("", border_bottom=True))
            i += 1
            continue
        # 正文：首行缩进 2 字符 + 两端对齐（BodyText 样式）；--no-indent 时用 Normal
        body.append(para_xml(stripped, style="BodyText" if indent else None))
        n_para += 1
        i += 1
    if in_code:  # 未闭合代码块：按代码收尾
        for cl in code_buf:
            body.append(para_xml("", style="Code", runs=f'<w:r><w:t xml:space="preserve">{_esc(cl)}</w:t></w:r>'))
    return "".join(body), n_tables, n_para, notes, ol_blocks


# ---------------------------------------------------------------- 打包
def build_docx(md: str, out_path, *, title: str | None = None, subtitle: str | None = None,
               author: str = "", toc: bool = False, page_numbers: bool = True,
               cover: bool = False, date: str = "", header: str | None = None,
               table_style: str = "three-line", indent: bool = True,
               number_headings: str = "fill", heading_shift: bool = True,
               ol_continuous_headings: list[str] | None = None) -> dict:
    body_xml, n_tables, n_para, notes, ol_blocks = convert_markdown(
        md, toc=toc, table_style=table_style, indent=indent,
        number_headings=number_headings, heading_shift=heading_shift,
        ol_continuous_headings=ol_continuous_headings)
    page = (f'<w:pgSz w:w="{PAGE_W}" w:h="{PAGE_H}"/>'
            f'<w:pgMar w:top="{MARGIN}" w:right="{MARGIN}" w:bottom="{MARGIN}" w:left="{MARGIN}" '
            'w:header="851" w:footer="992" w:gutter="0"/>'
            '<w:cols w:space="425"/><w:docGrid w:type="lines" w:linePitch="312"/>')
    refs = ""
    if header:
        refs += '<w:headerReference w:type="default" r:id="rId5"/>'
    if page_numbers:
        refs += '<w:footerReference w:type="default" r:id="rId3"/>'
    cover_xml = ""
    if cover:
        # 封面单独成节：不挂页眉页脚；正文节页码从 1 起
        cover_xml = (para_xml(title or "", style="CoverTitle")
                     + (para_xml(subtitle, style="CoverSub") if subtitle else "")
                     + '<w:p><w:pPr><w:spacing w:before="3600"/></w:pPr></w:p>'
                     + (para_xml(author, style="CoverMeta") if author else "")
                     + (para_xml(date, style="CoverMeta") if date else "")
                     + f'<w:p><w:pPr><w:sectPr>{page}</w:sectPr></w:pPr></w:p>')
    elif title:
        body_xml = para_xml(title, style="Title") + \
            (para_xml(subtitle, style="Subtitle") if subtitle else "") + body_xml
    pgnum = '<w:pgNumType w:start="1"/>' if cover else ""
    sect = f'<w:sectPr>{refs}{page.replace("<w:cols", pgnum + "<w:cols", 1)}</w:sectPr>'
    document = XML_DECL + f'<w:document {W_NS} {R_NS}><w:body>{cover_xml}{body_xml}{sect}</w:body></w:document>'

    rels_doc = ['<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>',
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>']
    if page_numbers:
        rels_doc.append('<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" Target="footer1.xml"/>')
    if header:
        rels_doc.append('<Relationship Id="rId5" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" Target="header1.xml"/>')
    rels_doc.append('<Relationship Id="rId4" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/settings" Target="settings.xml"/>')
    document_rels = XML_DECL + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(rels_doc) + '</Relationships>'

    now = _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    core = XML_DECL + (
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f'<dc:title>{_esc(title or "")}</dc:title><dc:creator>{_esc(author)}</dc:creator>'
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
        f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>')
    app = XML_DECL + ('<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
                      'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
                      '<Application>DSHM md2docx</Application></Properties>')

    overrides = ['<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>',
                 '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>',
                 '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>',
                 '<Override PartName="/word/settings.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.settings+xml"/>',
                 '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
                 '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>']
    if page_numbers:
        overrides.append('<Override PartName="/word/footer1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>')
    if header:
        overrides.append('<Override PartName="/word/header1.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>')
    content_types = XML_DECL + ('<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                                '<Default Extension="xml" ContentType="application/xml"/>' + "".join(overrides) + '</Types>')
    package_rels = XML_DECL + ('<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                               '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
                               '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
                               '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
                               '</Relationships>')

    ensure_parent(out_path)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", content_types)
        z.writestr("_rels/.rels", package_rels)
        z.writestr("docProps/core.xml", core)
        z.writestr("docProps/app.xml", app)
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", STYLES_XML)
        z.writestr("word/numbering.xml", numbering_xml(ol_blocks))
        z.writestr("word/settings.xml", SETTINGS_XML)
        z.writestr("word/_rels/document.xml.rels", document_rels)
        if page_numbers:
            z.writestr("word/footer1.xml", FOOTER_XML)
        if header:
            z.writestr("word/header1.xml", XML_DECL + f'<w:hdr {W_NS} {R_NS}>'
                       + para_xml("", style="Header", runs=runs_xml(header)) + "</w:hdr>")

    # 自检：所有 XML 部件必须可解析
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(out_path) as z:
        bad = z.testzip()
        for name in z.namelist():
            if name.endswith(".xml") or name.endswith(".rels"):
                ET.fromstring(z.read(name))
    return {"path": out_path, "tables": n_tables, "paragraphs": n_para, "bad_zip": bad,
            "notes": notes}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Markdown → DOCX（纯标准库）")
    ap.add_argument("input", help="输入 Markdown 文件（相对工作目录或绝对路径）")
    ap.add_argument("--out", help="输出 .docx（默认同目录同名 .docx）")
    ap.add_argument("--title", help="追加一个居中的大标题")
    ap.add_argument("--subtitle")
    ap.add_argument("--author", default="")
    ap.add_argument("--toc", action="store_true", help="插入目录域（Word 打开后需“更新域”）")
    ap.add_argument("--no-page-numbers", action="store_true")
    ap.add_argument("--cover", action="store_true",
                    help="生成独立封面页（用 --title/--subtitle/--author/--date；封面无页眉页码，正文页码从 1 起）")
    ap.add_argument("--date", default="", help="封面日期（如 2026年10月；传 today 用当天）")
    ap.add_argument("--header", help="页眉文字（居中 + 下横线；封面页不显示）")
    ap.add_argument("--table-style", choices=["three-line", "grid"], default="three-line",
                    help="表格样式：three-line 学术三线表（默认）| grid 全框线")
    ap.add_argument("--no-indent", action="store_true", help="正文不做首行缩进/两端对齐（旧版样式）")
    ap.add_argument("--number-headings", choices=["fill", "off"], default="fill",
                    help="标题编号：fill=为缺号标题按层级补号并重新计数（默认）| off=原样")
    ap.add_argument("--no-heading-shift", action="store_true",
                    help="不把唯一的 # 文档大标题下沉为 Title（默认下沉，使章=一级标题、节=二级，目录序号才连续）")
    ap.add_argument("--ol-continuous", action="append", metavar="章节关键词",
                    help="该关键词命中的章内，有序列表跨小节连续编号（默认 参考文献；可多次指定，"
                         "传空串则全部每块重启）")
    args = ap.parse_args(argv)
    if args.cover and not args.title:
        print("[错误] --cover 需要同时给 --title", file=sys.stderr)
        return 2
    if args.date == "today":
        args.date = _dt.date.today().strftime("%Y年%m月%d日")
    src = resolve_path(args.input)
    if not src.is_file():
        print(f"[错误] 找不到输入文件：{src}", file=sys.stderr)
        return 1
    out = resolve_path(args.out) if args.out else src.with_suffix(".docx")
    md = src.read_text(encoding="utf-8")
    info = build_docx(md, out, title=args.title, subtitle=args.subtitle, author=args.author,
                      toc=args.toc, page_numbers=not args.no_page_numbers,
                      cover=args.cover, date=args.date, header=args.header,
                      table_style=args.table_style, indent=not args.no_indent,
                      number_headings=args.number_headings,
                      heading_shift=not args.no_heading_shift,
                      ol_continuous_headings=(args.ol_continuous if args.ol_continuous is not None
                                              else ["参考文献"]))
    size = out.stat().st_size
    print(f"[完成] {src.name} → {out}")
    print(f"       段落 {info['paragraphs']} 个，表格 {info['tables']} 个，文件 {size/1024:.1f} KB，自检通过")
    for n in info.get("notes", []):
        print(f"[标题] {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
