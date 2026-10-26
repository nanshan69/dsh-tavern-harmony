#!/usr/bin/env python3
"""Markdown/DSL → PPTX 生成器（纯标准库，不依赖 python-pptx/LibreOffice）。

为什么自建：本机装不了 python-pptx（依赖 lxml C 扩展）。这里按 OOXML
PresentationML 直接拼 XML 打包，生成 16:9 中文汇报幻灯片。

维护记录：2026-10-22 移除标题左侧方块（TitleMark）；封面/章节页装饰圆
改为完全位于页面内（距边 0.30 英寸），不再越出幻灯片边界。

用法：
  python scripts/pptx.py 汇报.md --out 汇报.pptx
  python scripts/pptx.py 汇报.md --out 汇报.pptx --accent 1F3864 --font "Microsoft YaHei"

Deck DSL（推荐，控制力强）：
  ---
  title: 汇报标题
  subtitle: 副标题
  author: 汇报人
  date: 2026-10-21
  topic: 页脚左侧文字（默认取 title）
  accent: 1F3864
  ---

  [cover]             # 可选；有 frontmatter title 时会自动生成封面，无需写
  [section]           # 章节页
  01
  研究背景与立论

  [content]           # 内容页（默认类型）
  # 本页标题
  - 一级要点
    - 二级要点（前面 2 个空格）
  - **加粗**要点
  普通段落

  [table]
  # 表格页标题
  | 列1 | 列2 |
  |---|---|
  | a | b |

  [metrics]           # 大数字卡片页（进度/样本量）
  # 关键数字
  - 114 | 目标随机例数
  - 70 | 最低可接受例数
  - 18 | 入组窗口（月）

  [statement]         # 金句/结论页
  一句话结论，字号很大
  —— 说明来源（可选）

  图片（content/table 页，2026-10-21 新增）：
  ![图注](相对 .md 所在目录或工作目录的路径.png)
    - 仅 PNG/JPEG；SVG 不支持（PowerPoint 旧版/WPS 兼容差），先在 PC 转 PNG
    - 每页只嵌入第一张；有文字/表格时图片放右侧 38%，否则整页居中等比缩放

  演讲者备注（任意页，2026-10-21 新增）：
  note: 这一页要讲的要点（可写多行，每行一个 note:）

幻灯片之间用单独一行 --- 分隔（frontmatter 之后的 ---）。

已知限制：每页一个表格；表格行数过多会提示拆页（不自动分页）；不支持动画/切换、
图表对象（chart）、SmartArt、超链接；字体需本机已安装（默认微软雅黑，WPS 会替换）。
图片与备注只在模板底包模式下写入（默认就是）；--no-template 时会被忽略并提示。
"""
import argparse
import datetime as _dt
import os
import re
import sys
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as _esc

sys.path.insert(0, os.environ.get("DSH_TOOL_DIR") or os.path.dirname(os.path.abspath(globals().get("__file__", "run_tool.py"))))
from _util import ensure_parent, resolve_path  # noqa: E402

# ---------------------------------------------------------------- 版面常量（EMU）
EMU_IN = 914400
SW, SH = 12192000, 6858000          # 16:9
MARGIN = int(0.62 * EMU_IN)
TITLE_Y = int(0.42 * EMU_IN)
BODY_Y = int(1.50 * EMU_IN)
BODY_H = int(4.75 * EMU_IN)
FOOT_Y = int(6.62 * EMU_IN)

# 默认配色
NAVY = "1F3864"
BLUE = "2E75B6"
LIGHT = "D9E2F3"
GRAY = "6B7280"
DARK = "1F2937"
BG = "F5F7FA"
WHITE = "FFFFFF"
LINE = "E5E7EB"
FONT_DEFAULT = "Microsoft YaHei"

NS = ('xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
      'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
      'xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"')
XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'


# ---------------------------------------------------------------- XML 片段
def _srgb(color: str, alpha: int | None = None) -> str:
    if alpha is None:
        return f'<a:srgbClr val="{color}"/>'
    return f'<a:srgbClr val="{color}"><a:alpha val="{alpha}"/></a:srgbClr>'


def _fill(color: str | None, alpha: int | None = None) -> str:
    if color is None:
        return "<a:noFill/>"
    return f"<a:solidFill>{_srgb(color, alpha)}</a:solidFill>"


def _line(color: str | None, width: int = 12700) -> str:
    if color is None:
        return "<a:ln><a:noFill/></a:ln>"
    return (f'<a:ln w="{width}" cap="flat" cmpd="sng" algn="ctr">'
            f"<a:solidFill>{_srgb(color)}</a:solidFill><a:prstDash val=\"solid\"/></a:ln>")


def _runs(text: str, size: int, color: str = DARK, bold: bool = False, font: str | None = None) -> str:
    """解析 **加粗**、`代码`，生成 run 序列。"""
    font = font or FONT_DEFAULT
    out = []
    for part in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", text):
        if not part:
            continue
        b = bold
        if part.startswith("**") and part.endswith("**"):
            part, b = part[2:-2], True
        elif part.startswith("`") and part.endswith("`"):
            part = part[1:-1]
        rpr = (f'<a:rPr lang="zh-CN" altLang="en-US" sz="{size}" b="{1 if b else 0}" dirty="0">'
               f"<a:solidFill>{_srgb(color)}</a:solidFill>"
               f'<a:latin typeface="{font}"/><a:ea typeface="{font}"/></a:rPr>')
        out.append(f'<a:r>{rpr}<a:t xml:space="preserve">{_esc(part)}</a:t></a:r>')
    return "".join(out) if out else (
        f'<a:r><a:rPr lang="zh-CN" sz="{size}" dirty="0"><a:solidFill>{_srgb(color)}</a:solidFill></a:rPr>'
        f"<a:t></a:t></a:r>")


def _para(text: str = "", size: int = 1800, color: str = DARK, bold: bool = False,
          bullet: str | None = None, level: int = 0, align: str | None = None,
          space_before: int = 0, space_after: int = 0, line_pct: int = 120000,
          font: str | None = None) -> str:
    """生成段落。bullet: None/'square'/'dash'/'dot'/'num'。level 0-2。"""
    algn = f' algn="{align}"' if align else ""
    if bullet is None:
        ppr = (f'<a:pPr marL="0" indent="0"{algn}>'
               f'<a:lnSpc><a:spcPct val="{line_pct}"/></a:lnSpc>'
               f'<a:spcBef><a:spcPts val="{space_before}"/></a:spcBef>'
               f'<a:spcAft><a:spcPts val="{space_after}"/></a:spcAft>'
               f'<a:buNone/></a:pPr>')
    else:
        base = {0: 342900, 1: 800100, 2: 1257300}[min(level, 2)]
        indent = -342900 if level == 0 else -285750
        char = {"square": "▪", "dash": "–", "dot": "·"}.get(bullet, "▪")
        bu_size = {"square": 70000, "dash": 90000, "dot": 100000}.get(bullet, 80000)
        if bullet == "num":
            bu = '<a:buAutoNum type="arabicPeriod"/>'
        else:
            bu = f'<a:buFont typeface="Arial"/><a:buChar char="{char}"/>'
        ppr = (f'<a:pPr marL="{base}" indent="{indent}"{algn}>'
               f'<a:lnSpc><a:spcPct val="{line_pct}"/></a:lnSpc>'
               f'<a:spcBef><a:spcPts val="{space_before}"/></a:spcBef>'
               f'<a:spcAft><a:spcPts val="{space_after}"/></a:spcAft>'
               f'<a:buClr>{_srgb(BLUE if level == 0 else GRAY)}</a:buClr>'
               f'<a:buSzPct val="{bu_size}"/>{bu}</a:pPr>')
    return f"<a:p>{ppr}{_runs(text, size, color, bold, font)}</a:p>"


def _shape(sid: int, name: str, x: int, y: int, w: int, h: int, txbody: str,
           fill: str | None = None, alpha: int | None = None,
           line_color: str | None = None, geom: str = "rect",
           line_w: int = 12700) -> str:
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="{_esc(name)}"/>'
        f'<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr/></p:nvSpPr>'
        f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>'
        f'<a:prstGeom prst="{geom}"><a:avLst/></a:prstGeom>{_fill(fill, alpha)}'
        f"{_line(line_color, line_w)}</p:spPr>"
        + (f'<p:txBody><a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" anchor="t">'
           f'<a:noAutofit/></a:bodyPr><a:lstStyle/>{txbody}</p:txBody>' if txbody else "")
        + "</p:sp>")


def _textbox(sid: int, name: str, x: int, y: int, w: int, h: int, paras: str,
             anchor: str = "t") -> str:
    return (
        f'<p:sp><p:nvSpPr><p:cNvPr id="{sid}" name="{_esc(name)}"/>'
        f'<p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
        f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></p:spPr>'
        f'<p:txBody><a:bodyPr wrap="square" lIns="0" tIns="0" rIns="0" bIns="0" anchor="{anchor}">'
        '<a:noAutofit/></a:bodyPr><a:lstStyle/>' + paras + "</p:txBody></p:sp>")


def _table_tc(text: str, size: int, header: bool, col_w: int, font: str,
              align: str = "l") -> str:
    color = WHITE if header else DARK
    fill = f'<a:solidFill>{_srgb(NAVY if header else WHITE)}</a:solidFill>'
    b = " b=\"1\"" if header else ""
    border = "".join(
        f'<a:ln{l} w="6350" cap="flat" cmpd="sng" algn="ctr"><a:solidFill>{_srgb("D9D9D9")}</a:solidFill>'
        f'<a:prstDash val="solid"/></a:ln{l}>' for l in ("L", "R", "T", "B"))
    return (
        f'<a:tc><a:txBody><a:bodyPr/><a:lstStyle/><a:p><a:pPr algn="{align}">'
        f'<a:buNone/></a:pPr>{_runs(text, size, color, bool(b), font)}</a:p></a:txBody>'
        f'<a:tcPr marL="91440" marR="91440" marT="45720" marB="45720" anchor="ctr">'
        f"{border}{fill}</a:tcPr></a:tc>")


def _disp_len(s: str) -> int:
    """显示宽度：中文/全角按 2，其余按 1。"""
    import unicodedata
    s = re.sub(r"\*\*|`", "", s)
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)


def table_col_widths(rows: list[list[str]], total_w: int, min_frac: float = 0.08) -> list[int]:
    """按各列最长显示宽度分配列宽（压缩极端长列，保证每列 ≥ min_frac 总宽）。"""
    ncol = max(len(r) for r in rows)
    weights = []
    for c in range(ncol):
        lens = [_disp_len(r[c]) if c < len(r) else 0 for r in rows]
        # 取最长与 P75 的平均，避免一个超长单元格把整列撑满
        srt = sorted(lens)
        p75 = srt[int(0.75 * (len(srt) - 1))]
        weights.append(max(4, min(60, (max(lens) + p75) / 2)))
    total = sum(weights)
    raw = [w / total for w in weights]
    floor = min(min_frac, 1 / ncol)
    raw = [max(floor, f) for f in raw]
    s = sum(raw)
    widths = [int(total_w * f / s) for f in raw]
    widths[-1] += total_w - sum(widths)  # 消除取整误差，使总宽 = 表宽
    return widths


def table_font_size(rows: list[list[str]]) -> int:
    """行列越多字号越小（12→10pt），防止溢出版心。"""
    nrow, ncol = len(rows), max(len(r) for r in rows)
    longest = max((_disp_len(c) for r in rows for c in r), default=0)
    if nrow > 9 or ncol > 6 or longest > 60:
        return 1000
    if nrow > 6 or ncol > 4 or longest > 36:
        return 1100
    return 1200


def _table_frame(sid: int, x: int, y: int, w: int, h: int, rows: list[list[str]],
                 font: str, size: int | None = None) -> str:
    ncol = max(len(r) for r in rows)
    size = size or table_font_size(rows)
    widths = table_col_widths(rows, w)
    grid = "".join(f'<a:gridCol w="{cw}"/>' for cw in widths)
    trs = []
    for i, row in enumerate(rows):
        header = i == 0
        cells = "".join(_table_tc((row[c] if c < len(row) else ""), size, header, widths[c], font)
                        for c in range(ncol))
        rh = int(0.42 * EMU_IN) if header else int(0.36 * EMU_IN)
        trs.append(f'<a:tr h="{rh}">{cells}</a:tr>')
    tbl = (f'<a:tbl><a:tblPr firstRow="1" bandRow="1">'
           '<a:tableStyleId>{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}</a:tableStyleId></a:tblPr>'
           f"<a:tblGrid>{grid}</a:tblGrid>{''.join(trs)}</a:tbl>")
    return (
        f'<p:graphicFrame><p:nvGraphicFramePr><p:cNvPr id="{sid}" name="Table {sid}"/>'
        '<p:cNvGraphicFramePr><a:graphicFrameLocks noGrp="1"/></p:cNvGraphicFramePr><p:nvPr/>'
        f'</p:nvGraphicFramePr><p:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></p:xfrm>'
        '<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/table">'
        f"{tbl}</a:graphicData></a:graphic></p:graphicFrame>")


def _cover_title_size(title: str) -> int:
    n = _disp_len(title)
    return 4000 if n <= 32 else 3400 if n <= 48 else 2800 if n <= 72 else 2400


def _sp_tree(children: str) -> str:
    return ('<p:spTree><p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
            '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
            '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
            + children + "</p:spTree>")


# ---------------------------------------------------------------- 单页构建
class Deck:
    def __init__(self, meta: dict):
        self.meta = meta
        self.title = meta.get("title", "汇报")
        self.topic = meta.get("topic") or self.title
        self.accent = (meta.get("accent") or NAVY).lstrip("#").upper()
        self.font = meta.get("font") or FONT_DEFAULT
        self.slides: list[str] = []
        self._slide_index = 0

    # -- 公共装饰
    def _footer(self, sid: int, dark: bool = False) -> str:
        if dark:
            return ""
        return (
            _textbox(sid, "FooterTopic", MARGIN, FOOT_Y, int(6.5 * EMU_IN), int(0.3 * EMU_IN),
                     _para(self.topic, 900, GRAY, line_pct=100000))
            + _textbox(sid + 1, "FooterPage", int(9.6 * EMU_IN), FOOT_Y, int(3.1 * EMU_IN),
                       int(0.3 * EMU_IN),
                       _para(f"{self._slide_index:02d} / {len(self._meta_total or []) or ''}".strip(),
                             900, GRAY, align="r", line_pct=100000))
        )

    def _page_label(self) -> str:
        total = len(getattr(self, "_meta_total", None) or [])
        return f"{self._slide_index:02d} / {total:02d}" if total else f"{self._slide_index:02d}"

    def _frame(self, children: str, dark: bool = False) -> str:
        self._slide_index += 1
        if not dark:
            children += (f'<p:sp><p:nvSpPr><p:cNvPr id="90" name="FooterLine"/>'
                         '<p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
                         f'<p:spPr><a:xfrm><a:off x="{MARGIN}" y="{FOOT_Y - int(0.12 * EMU_IN)}"/>'
                         f'<a:ext cx="{SW - 2 * MARGIN}" cy="9525"/></a:xfrm>'
                         '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
                         f"{_fill(LINE)}<a:ln><a:noFill/></a:ln></p:spPr>"
                         '<p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody></p:sp>')
            children += (f'<p:sp><p:nvSpPr><p:cNvPr id="91" name="FooterText"/>'
                         '<p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
                         f'<p:spPr><a:xfrm><a:off x="{MARGIN}" y="{FOOT_Y}"/>'
                         f'<a:ext cx="{int(6.5 * EMU_IN)}" cy="{int(0.3 * EMU_IN)}"/></a:xfrm>'
                         '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></p:spPr>'
                         '<p:txBody><a:bodyPr lIns="0" tIns="0" rIns="0" bIns="0"><a:noAutofit/></a:bodyPr>'
                         f'<a:lstStyle/>{_para(self.topic, 900, GRAY, line_pct=100000)}</p:txBody></p:sp>')
            children += (f'<p:sp><p:nvSpPr><p:cNvPr id="92" name="FooterPage"/>'
                         '<p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
                         f'<p:spPr><a:xfrm><a:off x="{int(9.9 * EMU_IN)}" y="{FOOT_Y}"/>'
                         f'<a:ext cx="{int(2.8 * EMU_IN)}" cy="{int(0.3 * EMU_IN)}"/></a:xfrm>'
                         '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/><a:ln><a:noFill/></a:ln></p:spPr>'
                         '<p:txBody><a:bodyPr lIns="0" tIns="0" rIns="0" bIns="0"><a:noAutofit/></a:bodyPr>'
                         f'<a:lstStyle/>{_para(self._page_label(), 900, GRAY, align="r", line_pct=100000)}'
                         "</p:txBody></p:sp>")
        return (XML_DECL + f"<p:sld {NS}><p:cSld>{_sp_tree(children)}</p:cSld>"
                "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>")

    # -- 页面类型
    def cover(self) -> str:
        m = self.meta
        kids = [
            f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="Bg"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{SW}" cy="{SH}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>{_fill(NAVY)}'
            '<a:ln><a:noFill/></a:ln></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody></p:sp>',
            # 装饰圆：完全位于页面内（右上/右下），不越出幻灯片边界
            _shape(3, "Circle1", SW - int(5.4 * EMU_IN) - int(0.30 * EMU_IN), int(0.30 * EMU_IN),
                   int(5.4 * EMU_IN), int(5.4 * EMU_IN), "", fill=BLUE, alpha=14000,
                   line_color=None, geom="ellipse"),
            _shape(4, "Circle2", SW - int(3.6 * EMU_IN) - int(0.30 * EMU_IN),
                   SH - int(3.6 * EMU_IN) - int(0.30 * EMU_IN), int(3.6 * EMU_IN),
                   int(3.6 * EMU_IN), "", fill=WHITE, alpha=6000, line_color=None, geom="ellipse"),
            _shape(5, "AccentBar", int(0.85 * EMU_IN), int(1.25 * EMU_IN), int(0.09 * EMU_IN),
                   int(0.62 * EMU_IN), "", fill=self.accent),
            _textbox(6, "Kicker", int(1.08 * EMU_IN), int(1.18 * EMU_IN), int(8 * EMU_IN),
                     int(0.4 * EMU_IN), _para(m.get("kicker", "临床研究"), 1200,
                                              LIGHT, line_pct=100000)),
            # 标题字号随长度自适应（中文长题目 40pt 会挤出 3 行）；底部对齐，紧贴副标题
            _textbox(7, "Title", int(0.85 * EMU_IN), int(1.75 * EMU_IN), int(10.6 * EMU_IN),
                     int(2.2 * EMU_IN), _para(m.get("title", ""), _cover_title_size(m.get("title", "")),
                                              WHITE, bold=True, line_pct=110000), anchor="b"),
            _textbox(8, "Subtitle", int(0.85 * EMU_IN), int(4.05 * EMU_IN), int(10.2 * EMU_IN),
                     int(0.9 * EMU_IN), _para(m.get("subtitle", ""), 1900, LIGHT, line_pct=115000)),
            _shape(9, "Divider", int(0.88 * EMU_IN), int(5.05 * EMU_IN), int(1.1 * EMU_IN),
                   int(0.05 * EMU_IN), "", fill=self.accent),
            _textbox(10, "Author", int(0.88 * EMU_IN), int(5.3 * EMU_IN), int(10.5 * EMU_IN),
                     int(0.9 * EMU_IN),
                     _para(m.get("author", ""), 1300, LIGHT, line_pct=110000)
                     + _para(m.get("date", ""), 1200, "AEB8CE", line_pct=110000)),
        ]
        self._slide_index += 1
        return XML_DECL + f"<p:sld {NS}><p:cSld>{_sp_tree(''.join(kids))}</p:cSld>" \
            "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>"

    def section(self, number: str, title: str, sub: str = "") -> str:
        kids = [
            f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="Bg"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{SW}" cy="{SH}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>{_fill(NAVY)}'
            '<a:ln><a:noFill/></a:ln></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody></p:sp>',
            _shape(3, "LeftBar", int(MARGIN), int(1.9 * EMU_IN), int(0.10 * EMU_IN),
                   int(3.0 * EMU_IN), "", fill=self.accent),
            # 装饰圆：完全位于页面内（右上角），不越出幻灯片边界
            _shape(7, "Ring", SW - int(5.2 * EMU_IN) - int(0.30 * EMU_IN), int(0.30 * EMU_IN),
                   int(5.2 * EMU_IN), int(5.2 * EMU_IN), "", fill=BLUE, alpha=10000,
                   line_color=None, geom="ellipse"),
            # 章节号：大号、主色提亮，与标题垂直居中对齐
            _textbox(4, "Num", int(MARGIN + int(0.35 * EMU_IN)), int(1.9 * EMU_IN),
                     int(2.3 * EMU_IN), int(3.0 * EMU_IN),
                     _para(number, 7200, "8FAADC", bold=True, line_pct=100000), anchor="ctr"),
            _textbox(5, "SectionTitle", int(MARGIN + int(2.8 * EMU_IN)), int(1.9 * EMU_IN),
                     int(8.4 * EMU_IN), int(1.75 * EMU_IN),
                     _para(title, 3200 if _disp_len(title) <= 28 else 2600, WHITE, bold=True,
                           line_pct=110000), anchor="b"),
            _shape(8, "SectionRule", int(MARGIN + int(2.8 * EMU_IN)), int(3.8 * EMU_IN),
                   int(0.9 * EMU_IN), int(0.05 * EMU_IN), "", fill=self.accent if self.accent != NAVY else BLUE),
            _textbox(6, "SectionSub", int(MARGIN + int(2.8 * EMU_IN)), int(4.0 * EMU_IN),
                     int(8.2 * EMU_IN), int(0.9 * EMU_IN), _para(sub, 1500, LIGHT, line_pct=120000)),
            _textbox(9, "SectionTopic", MARGIN, FOOT_Y, int(8 * EMU_IN), int(0.3 * EMU_IN),
                     _para(self.topic, 900, "8FA3C4", line_pct=100000)),
        ]
        self._slide_index += 1
        return XML_DECL + f"<p:sld {NS}><p:cSld>{_sp_tree(''.join(kids))}</p:cSld>" \
            "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sld>"

    def content(self, title: str, body_xml: str, extras: str = "",
                body_w: int | None = None, body_h: int | None = None) -> str:
        kids = [
            _textbox(3, "Title", MARGIN, int(0.45 * EMU_IN),
                     SW - 2 * MARGIN, int(0.7 * EMU_IN),
                     _para(title, 2400, NAVY, bold=True, line_pct=100000)),
            f'<p:sp><p:nvSpPr><p:cNvPr id="4" name="Rule"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{MARGIN}" y="{int(1.22 * EMU_IN)}"/>'
            f'<a:ext cx="{SW - 2 * MARGIN}" cy="9525"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
            f"{_fill(LINE)}<a:ln><a:noFill/></a:ln></p:spPr>"
            '<p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody></p:sp>',
            _textbox(5, "Body", MARGIN, BODY_Y, body_w or (SW - 2 * MARGIN), body_h or BODY_H, body_xml)
            if body_xml else "",
            extras,  # 表格/图片等独立图形：必须是 spTree 的直接子元素，不能塞进文本框
        ]
        return self._frame("".join(kids))

    def statement(self, text: str, attribution: str = "") -> str:
        kids = [
            f'<p:sp><p:nvSpPr><p:cNvPr id="2" name="Bg"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{SW}" cy="{SH}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>{_fill(BG)}'
            '<a:ln><a:noFill/></a:ln></p:spPr><p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody></p:sp>',
            _shape(3, "QuoteBar", int(1.05 * EMU_IN), int(1.55 * EMU_IN), int(0.12 * EMU_IN),
                   int(2.6 * EMU_IN), "", fill=self.accent),
            _textbox(4, "Statement", int(1.5 * EMU_IN), int(1.55 * EMU_IN), int(10.4 * EMU_IN),
                     int(3.0 * EMU_IN), _para(text, 2800, NAVY, bold=True, line_pct=120000)),
            _textbox(5, "Attribution", int(1.5 * EMU_IN), int(5.1 * EMU_IN), int(10.4 * EMU_IN),
                     int(0.5 * EMU_IN), _para(attribution, 1300, GRAY, line_pct=100000)),
        ]
        return self._frame("".join(kids))

    def metrics(self, title: str, items: list[tuple[str, str]]) -> str:
        n = min(max(len(items), 1), 4)
        gap = int(0.25 * EMU_IN)
        card_w = (SW - 2 * MARGIN - gap * (n - 1)) // n
        card_h = int(2.35 * EMU_IN)
        y = int(2.15 * EMU_IN)
        kids = [
            _textbox(3, "Title", MARGIN, int(0.45 * EMU_IN),
                     SW - 2 * MARGIN, int(0.7 * EMU_IN),
                     _para(title, 2400, NAVY, bold=True, line_pct=100000)),
            f'<p:sp><p:nvSpPr><p:cNvPr id="4" name="Rule"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
            f'<p:spPr><a:xfrm><a:off x="{MARGIN}" y="{int(1.22 * EMU_IN)}"/>'
            f'<a:ext cx="{SW - 2 * MARGIN}" cy="9525"/></a:xfrm>'
            '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
            f"{_fill(LINE)}<a:ln><a:noFill/></a:ln></p:spPr>"
            '<p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody></p:sp>',
        ]
        for i, (num, label) in enumerate(items[:n]):
            x = MARGIN + i * (card_w + gap)
            kids.append(_shape(10 + i, f"Card{i}", x, y, card_w, card_h, "", fill="FFFFFF",
                               line_color="E2E8F0"))
            kids.append(_shape(20 + i, f"CardBar{i}", x, y, card_w, int(0.07 * EMU_IN), "", fill=self.accent))
            kids.append(_textbox(30 + i, f"Num{i}", x + int(0.28 * EMU_IN), y + int(0.35 * EMU_IN),
                                 card_w - int(0.5 * EMU_IN), int(0.9 * EMU_IN),
                                 _para(num, 4000, self.accent, bold=True, line_pct=100000)))
            kids.append(_textbox(40 + i, f"Label{i}", x + int(0.28 * EMU_IN),
                                 y + int(1.35 * EMU_IN), card_w - int(0.5 * EMU_IN),
                                 int(0.8 * EMU_IN), _para(label, 1300, GRAY, line_pct=110000)))
        return self._frame("".join(kids))


# ---------------------------------------------------------------- Markdown → 页面
def _parse_frontmatter(lines: list[str]) -> tuple[dict, list[str]]:
    meta: dict = {}
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() in ("---", "..."):
                for raw in lines[1:i]:
                    if ":" in raw and not raw.lstrip().startswith("#"):
                        k, v = raw.split(":", 1)
                        meta[k.strip()] = v.strip().strip('"').strip("'")
                return meta, lines[i + 1:]
    return meta, lines


MARKER_RE = re.compile(r"^\[(cover|section|content|table|metrics|statement)\]\s*$", re.I)


def _split_slides(lines: list[str]) -> list[list[str]]:
    """幻灯片边界：单独一行 ---，或 [cover]/[section]/[content]/[table]/[metrics]/[statement] 标记行。"""
    slides, cur = [], []
    for line in lines:
        if line.strip() == "---":
            slides.append(cur)
            cur = []
        elif MARKER_RE.match(line.strip()) and any(x.strip() for x in cur):
            slides.append(cur)
            cur = [line]
        else:
            cur.append(line)
    slides.append(cur)
    return [s for s in slides if any(x.strip() for x in s)]


def _parse_table(lines: list[str], i: int) -> tuple[list[list[str]], int]:
    def cells(line: str) -> list[str]:
        line = line.strip()
        if line.startswith("|"):
            line = line[1:]
        if line.endswith("|"):
            line = line[:-1]
        return [c.strip() for c in line.split("|")]
    header = cells(lines[i])
    i += 1
    if i < len(lines) and re.fullmatch(r"[|:\-\s]+", lines[i].strip()):
        i += 1
    rows = [header]
    while i < len(lines) and lines[i].strip().startswith("|"):
        rows.append(cells(lines[i]))
        i += 1
    return rows, i


def _body_elements(lines: list[str]) -> tuple[list[str], list[list[list[str]]]]:
    """返回 (段落 XML 列表, 表格列表)。"""
    paras: list[str] = []
    tables: list[list[list[str]]] = []
    i = 0
    while i < len(lines):
        raw = lines[i]
        s = raw.strip()
        if not s:
            i += 1
            continue
        if s.startswith("|") and i + 1 < len(lines) and re.fullmatch(r"[|:\-\s]+", lines[i + 1].strip()):
            rows, i = _parse_table(lines, i)
            tables.append(rows)
            continue
        if s.startswith(">"):
            paras.append(_para(s.lstrip("> ").strip(), 1700, NAVY, bold=True, line_pct=125000,
                               space_before=600, space_after=400))
            i += 1
            continue
        m = re.match(r"^(\s*)[-*+]\s+(.*)$", raw)
        if m:
            level = min(len(m.group(1)) // 2, 2)
            paras.append(_para(m.group(2), 1800 if level == 0 else 1600,
                               DARK if level == 0 else "374151",
                               bullet=["square", "dash", "dot"][level], level=level,
                               space_before=300, space_after=120))
            i += 1
            continue
        m = re.match(r"^(\s*)\d+[.)]\s+(.*)$", raw)
        if m:
            level = min(len(m.group(1)) // 2, 2)
            paras.append(_para(m.group(2), 1800, DARK, bullet="num", level=level,
                               space_before=300, space_after=120))
            i += 1
            continue
        paras.append(_para(s, 1600, DARK, line_pct=125000, space_after=300))
        i += 1
    return paras, tables


def _title_and_body(slide: list[str]) -> tuple[str, list[str]]:
    title = ""
    body: list[str] = []
    for idx, line in enumerate(slide):
        s = line.strip()
        if not s:
            continue
        if re.match(r"^#{1,3}\s+", s):
            title = re.sub(r"^#{1,3}\s+", "", s).strip()
            body = slide[idx + 1:]
            break
        if not title:
            title = s
            body = slide[idx + 1:]
            break
    return title, body


IMG_RE = re.compile(r"^\s*!\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)\s*$")
NOTE_RE = re.compile(r"^\s*(?:note|notes|备注)\s*[:：]\s?(.*)$", re.I)


def _image_size(data: bytes) -> tuple[int, int] | None:
    """读取 PNG/JPEG 像素尺寸（纯标准库）；不支持的格式返回 None。"""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                i += 2
                continue
            seg = int.from_bytes(data[i + 2:i + 4], "big")
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                return int.from_bytes(data[i + 7:i + 9], "big"), int.from_bytes(data[i + 5:i + 7], "big")
            i += 2 + seg
    return None


def _pic(sid: int, rid: str, name: str, x: int, y: int, w: int, h: int) -> str:
    return (f'<p:pic><p:nvPicPr><p:cNvPr id="{sid}" name="{_esc(name)}" descr="{_esc(name)}"/>'
            '<p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
            f'<p:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>'
            f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{w}" cy="{h}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>{_line("E5E7EB", 6350)}</p:spPr></p:pic>')


def _fit(iw: int, ih: int, box_w: int, box_h: int) -> tuple[int, int]:
    scale = min(box_w / iw, box_h / ih)
    return int(iw * scale), int(ih * scale)


def _strip_notes(lines: list[str]) -> tuple[list[str], list[str]]:
    keep, notes = [], []
    for line in lines:
        m = NOTE_RE.match(line)
        if m:
            notes.append(m.group(1).strip())
        else:
            keep.append(line)
    return keep, notes


def build_deck(md: str, base_dir=None, warnings: list[str] | None = None
               ) -> tuple[dict, list[str], list[dict]]:
    """返回 (meta, 幻灯片 XML 列表, 每页附加信息 [{'notes': [...], 'images': [(rid, bytes, ext)]}])。"""
    warnings = warnings if warnings is not None else []
    lines = md.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    meta, lines = _parse_frontmatter(lines)
    deck = Deck(meta)
    slides = _split_slides(lines)
    out: list[str] = []
    extras: list[dict] = []
    # 封面：有 frontmatter title 且第一屏不是显式 [cover] 时自动加封面
    first_type = ""
    for s in slides:
        for line in s:
            if line.strip().startswith("["):
                first_type = line.strip()
                break
            if line.strip():
                break
        break
    if meta.get("title") and first_type != "[cover]":
        out.append(deck.cover())
        extras.append({"notes": [], "images": []})
    total = len(out) + len(slides)
    deck._meta_total = [None] * total  # type: ignore[attr-defined]

    for slide in slides:
        lines_s, notes = _strip_notes(list(slide))
        info = {"notes": notes, "images": []}
        extras.append(info)
        # 图片：每页取第一张 ![说明](路径)（PNG/JPEG），其余忽略并告警
        img_lines = [i for i, x in enumerate(lines_s) if IMG_RE.match(x)]
        img_xml_args = None
        for k, li in enumerate(img_lines):
            m = IMG_RE.match(lines_s[li])
            if k == 0:
                path = m.group(2)
                p = path if os.path.isabs(path) else os.path.join(str(base_dir or "."), path)
                if not os.path.isfile(p):
                    p2 = str(resolve_path(path))
                    p = p2 if os.path.isfile(p2) else p
                try:
                    data = open(p, "rb").read()
                except OSError:
                    warnings.append(f"图片不存在，已跳过：{path}")
                    data = b""
                size = _image_size(data) if data else None
                if data and size is None:
                    warnings.append(f"仅支持 PNG/JPEG（SVG 请先在 PC 转 PNG），已跳过：{path}")
                if size:
                    ext = "png" if data[:4] == b"\x89PNG" else "jpeg"
                    info["images"].append(("rId2", data, ext))
                    img_xml_args = (m.group(1) or os.path.basename(path), size)
            else:
                warnings.append(f"每页只嵌入第一张图片，已忽略：{m.group(2)}")
        lines_s = [x for i, x in enumerate(lines_s) if i not in img_lines]
        stype = "content"
        idx = 0
        for idx, line in enumerate(lines_s):
            if not line.strip():
                continue
            s = line.strip()
            if s.startswith("[") and s.endswith("]"):
                stype = s[1:-1].strip().lower()
                lines_s = lines_s[idx + 1:]
            break
        if stype == "cover":
            out.append(deck.cover())
        elif stype == "section":
            nonempty = [x.strip() for x in lines_s if x.strip()]
            num = "01"
            title = "章节"
            sub_idx = 1
            if nonempty:
                m = re.match(r"^(\d{1,2})\s*[|、.．\s]\s*(.+)$", nonempty[0])
                if m:
                    num, title = m.group(1), m.group(2)
                    sub_idx = 1          # 「01 标题」同行 → 下一行才是副标题
                else:
                    num = nonempty[0][:2]
                    title = nonempty[1] if len(nonempty) > 1 else "章节"
                    sub_idx = 2          # 章节号单独一行 → 标题占第 2 行
            sub = nonempty[sub_idx] if len(nonempty) > sub_idx else ""
            # 「note:」行已被 _strip_notes 抽走，不会被误当副标题
            out.append(deck.section(num, title, sub))
        elif stype == "statement":
            nonempty = [x.strip() for x in lines_s if x.strip()]
            text = nonempty[0] if nonempty else ""
            attr = nonempty[1] if len(nonempty) > 1 else ""
            out.append(deck.statement(text, attr))
        elif stype == "metrics":
            title, body = _title_and_body(lines_s)
            items = []
            for line in body:
                m = re.match(r"^\s*[-*+]\s*(.+?)\s*\|\s*(.+)$", line)
                if m:
                    items.append((m.group(1).strip(), m.group(2).strip()))
            out.append(deck.metrics(title or "关键数字", items))
        else:  # content / table
            title, body = _title_and_body(lines_s)
            paras, tables = _body_elements(body)
            if len(tables) > 1:
                warnings.append(f"「{title}」页有 {len(tables)} 个表格，只渲染第一个")
            full_w = SW - 2 * MARGIN
            text_w, text_h = full_w, BODY_H
            shapes = ""
            if tables:
                rows = tables[0]
                # 表格放在正文段落下方；段落按每段约 0.5 英寸估高
                text_h = min(int(len(paras) * 0.5 * EMU_IN), int(1.6 * EMU_IN)) if paras else 0
                ty = BODY_Y + (text_h + int(0.15 * EMU_IN) if paras else 0)
                avail = BODY_Y + BODY_H - ty
                h = int(0.42 * EMU_IN) + int(0.36 * EMU_IN) * (len(rows) - 1)
                if h > avail:
                    warnings.append(f"「{title}」表格 {len(rows)} 行，估计高度超出版心，建议拆页")
                tw = full_w if not img_xml_args else int(full_w * 0.58)
                shapes += _table_frame(10, MARGIN, ty, tw, min(h, avail), rows, deck.font)
                if img_xml_args:
                    text_w = tw
            if img_xml_args:
                caption, (iw, ih) = img_xml_args
                if paras or tables:
                    box_x = MARGIN + int(full_w * 0.62)
                    box_w = full_w - int(full_w * 0.62)
                    if not tables:
                        text_w = int(full_w * 0.58)
                else:
                    box_x, box_w = MARGIN, full_w
                box_h = BODY_H - int(0.35 * EMU_IN)
                w, h = _fit(iw, ih, box_w, box_h)
                x = box_x + (box_w - w) // 2
                shapes += _pic(60, "rId2", caption, x, BODY_Y, w, h)
                if caption:
                    shapes += _textbox(61, "Caption", box_x, BODY_Y + h + int(0.08 * EMU_IN), box_w,
                                       int(0.3 * EMU_IN), _para(caption, 1100, GRAY, align="ctr",
                                                                line_pct=100000))
            content = "".join(paras)
            if not content and not shapes:
                content = _para("（本页暂无内容）", 1600, GRAY)
            out.append(deck.content(title or ("表格" if stype == "table" else ""), content,
                                    extras=shapes, body_w=text_w, body_h=text_h or None))
            continue
        if img_xml_args:
            warnings.append(f"[{stype}] 页不支持图片，已忽略（请放在 content/table 页）")
            info["images"].clear()
    return meta, out, extras


# ---------------------------------------------------------------- 静态部件
def _content_types(n_slides: int) -> str:
    overrides = [
        ('/ppt/presentation.xml', 'application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml'),
        ('/ppt/presProps.xml', 'application/vnd.openxmlformats-officedocument.presentationml.presProps+xml'),
        ('/ppt/viewProps.xml', 'application/vnd.openxmlformats-officedocument.presentationml.viewProps+xml'),
        ('/ppt/tableStyles.xml', 'application/vnd.openxmlformats-officedocument.presentationml.tableStyles+xml'),
        ('/ppt/theme/theme1.xml', 'application/vnd.openxmlformats-officedocument.theme+xml'),
        ('/ppt/slideMasters/slideMaster1.xml', 'application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml'),
        ('/ppt/slideLayouts/slideLayout1.xml', 'application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml'),
        ('/docProps/core.xml', 'application/vnd.openxmlformats-package.core-properties+xml'),
        ('/docProps/app.xml', 'application/vnd.openxmlformats-officedocument.extended-properties+xml'),
    ]
    for i in range(1, n_slides + 1):
        overrides.append((f'/ppt/slides/slide{i}.xml',
                          'application/vnd.openxmlformats-officedocument.presentationml.slide+xml'))
    body = "".join(f'<Override PartName="{p}" ContentType="{c}"/>' for p, c in overrides)
    return (XML_DECL + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>' + body + "</Types>")


def _theme_xml() -> str:
    colors = [("dk1", "000000"), ("lt1", "FFFFFF"), ("dk2", NAVY), ("lt2", "F3F4F6"),
              ("accent1", NAVY), ("accent2", BLUE), ("accent3", "70AD47"),
              ("accent4", "FFC000"), ("accent5", "C00000"), ("accent6", "7030A0"),
              ("hlink", BLUE), ("folHlink", "7F7F7F")]
    clr = "".join(f'<a:{k}><a:srgbClr val="{v}"/></a:{k}>' for k, v in colors)
    fill = "<a:solidFill><a:schemeClr val=\"phClr\"/></a:solidFill>"
    ln = ('<a:ln w="6350" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
          '<a:prstDash val="solid"/></a:ln>')
    eff = '<a:effectStyle><a:effectLst/></a:effectStyle>'
    return (XML_DECL + '<a:theme xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" name="DSHM">'
            '<a:themeElements>'
            f'<a:clrScheme name="DSHM">{clr}</a:clrScheme>'
            f'<a:fontScheme name="DSHM"><a:majorFont><a:latin typeface="{FONT_DEFAULT}"/>'
            f'<a:ea typeface="{FONT_DEFAULT}"/><a:cs typeface=""/></a:majorFont>'
            f'<a:minorFont><a:latin typeface="{FONT_DEFAULT}"/><a:ea typeface="{FONT_DEFAULT}"/>'
            '<a:cs typeface=""/></a:minorFont></a:fontScheme>'
            '<a:fmtScheme name="DSHM">'
            f"<a:fillStyleLst>{fill}{fill}{fill}</a:fillStyleLst>"
            f"<a:lnStyleLst>{ln}{ln}{ln}</a:lnStyleLst>"
            f"<a:effectStyleLst>{eff}{eff}{eff}</a:effectStyleLst>"
            f"<a:bgFillStyleLst>{fill}{fill}{fill}</a:bgFillStyleLst>"
            "</a:fmtScheme></a:themeElements></a:theme>")


def _master_xml() -> str:
    return (XML_DECL + f"<p:sldMaster {NS}><p:cSld>"
            f'<p:bg><p:bgPr>{_fill(WHITE)}<a:effectLst/></p:bgPr></p:bg>'
            + _sp_tree("") +
            "</p:cSld>"
            '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" '
            'accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" '
            'hlink="hlink" folHlink="folHlink"/>'
            '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
            "<p:txStyles><p:titleStyle><a:lvl1pPr><a:defRPr sz=\"2400\"/></a:lvl1pPr></p:titleStyle>"
            "<p:bodyStyle><a:lvl1pPr><a:defRPr sz=\"1800\"/></a:lvl1pPr></p:bodyStyle>"
            "<p:otherStyle><a:lvl1pPr><a:defRPr sz=\"1800\"/></a:lvl1pPr></p:otherStyle></p:txStyles>"
            "</p:sldMaster>")


def _layout_xml() -> str:
    return (XML_DECL + f'<p:sldLayout {NS} type="blank" preserve="1"><p:cSld name="Blank">'
            + _sp_tree("") + "</p:cSld><p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:sldLayout>")


def _presentation_xml(n: int) -> str:
    ids = "".join(f'<p:sldId id="{255 + i}" r:id="rId{i + 1}"/>' for i in range(1, n + 1))
    return (XML_DECL + f'<p:presentation {NS} saveSubsetFonts="1">'
            '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
            f"<p:sldIdLst>{ids}</p:sldIdLst>"
            f'<p:sldSz cx="{SW}" cy="{SH}"/><p:notesSz cx="6858000" cy="9144000"/>'
            '<p:defaultTextStyle><a:defPPr><a:defRPr lang="zh-CN"/></a:defPPr></p:defaultTextStyle>'
            "</p:presentation>")


def _presentation_rels(n: int) -> str:
    items = [('rId1', 'slideMasters/slideMaster1.xml',
              'http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster')]
    for i in range(1, n + 1):
        items.append((f"rId{i + 1}", f"slides/slide{i}.xml",
                      'http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide'))
    base = n + 2
    items += [
        (f"rId{base}", "presProps.xml", 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/presProps'),
        (f"rId{base + 1}", "viewProps.xml", 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/viewProps'),
        (f"rId{base + 2}", "theme/theme1.xml", 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme'),
        (f"rId{base + 3}", "tableStyles.xml", 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/tableStyles'),
    ]
    body = "".join(f'<Relationship Id="{i}" Type="{t}" Target="{target}"/>' for i, target, t in items)
    return (XML_DECL + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            + body + "</Relationships>")


def _package_rels() -> str:
    return (XML_DECL + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>'
            "</Relationships>")


def _core_xml(meta: dict) -> str:
    now = _dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    return (XML_DECL + '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{_esc(meta.get("title", ""))}</dc:title>'
            f'<dc:creator>{_esc(meta.get("author", ""))}</dc:creator>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>')


def _validate(path) -> None:
    """校验 zip、XML、rel 目标、content-types 覆盖。"""
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        assert z.testzip() is None, "zip 损坏"
        for name in names:
            if name.endswith((".xml", ".rels")):
                ET.fromstring(z.read(name))
        # rel 目标必须存在
        for name in [n for n in names if n.endswith(".rels")]:
            base = os.path.dirname(os.path.dirname(name))
            root = ET.fromstring(z.read(name))
            for rel in root:
                target = rel.get("Target")
                if not target or target.startswith("http"):
                    continue
                resolved = os.path.normpath(os.path.join(base, target)).replace("\\", "/")
                if resolved not in names:
                    raise AssertionError(f"{name} 指向不存在的部件: {resolved}")
        # content-types 覆盖
        ct = ET.fromstring(z.read("[Content_Types].xml"))
        defaults = {d.get("Extension").lower() for d in ct if d.tag.endswith("Default")}
        overrides = {o.get("PartName").lstrip("/") for o in ct if o.tag.endswith("Override")}
        for name in names:
            if name == "[Content_Types].xml" or name.endswith(".rels"):
                continue
            ext = name.rsplit(".", 1)[-1].lower()
            if name not in overrides and ext not in defaults:
                raise AssertionError(f"部件缺少 Content-Type: {name}")


P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
for _p, _u in (("a", A_NS), ("r", R_NS), ("p", P_NS), ("", REL_NS)):
    ET.register_namespace(_p, _u)


def _xml_bytes(el) -> bytes:
    return (XML_DECL + ET.tostring(el, encoding="unicode")).encode("utf-8")


def _pick_blank_layout(entries: dict) -> str:
    names = sorted(n for n in entries if re.fullmatch(r"ppt/slideLayouts/slideLayout\d+\.xml", n))
    for n in names:
        try:
            root = ET.fromstring(entries[n])
            if root.get("type") == "blank":
                return n.rsplit("/", 1)[-1]
        except Exception:
            continue
    return names[0].rsplit("/", 1)[-1] if names else "slideLayout1.xml"


REL_T = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/"
CT_PML = "application/vnd.openxmlformats-officedocument.presentationml."
NOTES_W, NOTES_H = 6858000, 9144000


def _notes_master_xml() -> str:
    """最小可用的备注母版：幻灯片缩略图占位 + 备注正文占位。"""
    ph = ('<p:sp><p:nvSpPr><p:cNvPr id="2" name="Slide Image Placeholder 1"/>'
          '<p:cNvSpPr><a:spLocks noGrp="1" noRot="1" noChangeAspect="1"/></p:cNvSpPr>'
          '<p:nvPr><p:ph type="sldImg" idx="2"/></p:nvPr></p:nvSpPr>'
          '<p:spPr><a:xfrm><a:off x="381000" y="685800"/><a:ext cx="6096000" cy="3429000"/></a:xfrm>'
          '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom><a:noFill/>'
          '<a:ln w="12700"><a:solidFill><a:prstClr val="black"/></a:solidFill></a:ln></p:spPr></p:sp>'
          '<p:sp><p:nvSpPr><p:cNvPr id="3" name="Notes Placeholder 2"/>'
          '<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="body" sz="quarter" idx="3"/></p:nvPr></p:nvSpPr>'
          '<p:spPr><a:xfrm><a:off x="685800" y="4400550"/><a:ext cx="5486400" cy="3600450"/></a:xfrm>'
          '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
          '<p:txBody><a:bodyPr vert="horz" lIns="91440" tIns="45720" rIns="91440" bIns="45720" rtlCol="0"/>'
          '<a:lstStyle/><a:p><a:pPr lvl="0"/><a:r><a:rPr lang="zh-CN"/><a:t>备注</a:t></a:r></a:p></p:txBody></p:sp>')
    return (XML_DECL + f"<p:notesMaster {NS}><p:cSld>"
            '<p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg>'
            + _sp_tree(ph) + "</p:cSld>"
            '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" '
            'accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
            '<p:notesStyle><a:lvl1pPr marL="0" algn="l" defTabSz="914400" rtl="0" eaLnBrk="1" latinLnBrk="0" hangingPunct="1">'
            '<a:defRPr sz="1200" kern="1200"><a:solidFill><a:schemeClr val="tx1"/></a:solidFill>'
            '<a:latin typeface="+mn-lt"/><a:ea typeface="+mn-ea"/><a:cs typeface="+mn-cs"/></a:defRPr></a:lvl1pPr>'
            "</p:notesStyle></p:notesMaster>")


def _notes_slide_xml(notes: list[str], font: str) -> str:
    paras = "".join(
        f'<a:p><a:r><a:rPr lang="zh-CN" altLang="en-US" sz="1200" dirty="0">'
        f'<a:latin typeface="{font}"/><a:ea typeface="{font}"/></a:rPr>'
        f'<a:t xml:space="preserve">{_esc(t)}</a:t></a:r></a:p>' for t in notes) or "<a:p/>"
    kids = ('<p:sp><p:nvSpPr><p:cNvPr id="2" name="Slide Image Placeholder 1"/>'
            '<p:cNvSpPr><a:spLocks noGrp="1" noRot="1" noChangeAspect="1"/></p:cNvSpPr>'
            '<p:nvPr><p:ph type="sldImg"/></p:nvPr></p:nvSpPr><p:spPr/></p:sp>'
            '<p:sp><p:nvSpPr><p:cNvPr id="3" name="Notes Placeholder 2"/>'
            '<p:cNvSpPr><a:spLocks noGrp="1"/></p:cNvSpPr><p:nvPr><p:ph type="body" idx="1"/></p:nvPr></p:nvSpPr>'
            f'<p:spPr/><p:txBody><a:bodyPr/><a:lstStyle/>{paras}</p:txBody></p:sp>')
    return (XML_DECL + f"<p:notes {NS}><p:cSld>{_sp_tree(kids)}</p:cSld>"
            "<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr></p:notes>")


def _attach_media_and_notes(entries: dict, pres, rels, ct, extras: list[dict], font: str,
                            layout: str, next_id: int) -> int:
    """给每页写 slide rels；按需加入图片（ppt/media）与演讲者备注（notesMaster + notesSlide）。

    entries 中的 slide XML 必须已写入；pres/rels/ct 为 ElementTree 根节点，就地修改。返回新的 next_id。
    """
    has_notes = any(e["notes"] for e in extras)
    has_png = any(img[2] == "png" for e in extras for img in e["images"])
    has_jpg = any(img[2] == "jpeg" for e in extras for img in e["images"])
    defaults = {d.get("Extension").lower() for d in ct if d.tag.endswith("Default")}
    for ext, mime, need in (("png", "image/png", has_png), ("jpeg", "image/jpeg", has_jpg)):
        if need and ext not in defaults:
            d = ET.Element(f"{{{CT_NS}}}Default")
            d.set("Extension", ext)
            d.set("ContentType", mime)
            ct.insert(0, d)

    def override(part: str, ctype: str) -> None:
        if part not in {o.get("PartName") for o in ct if o.tag.endswith("Override")}:
            ov = ET.SubElement(ct, f"{{{CT_NS}}}Override")
            ov.set("PartName", part)
            ov.set("ContentType", ctype)

    if has_notes and "ppt/notesMasters/notesMaster1.xml" not in entries:
        theme_src = entries.get("ppt/theme/theme1.xml")
        theme_n = 1
        while f"ppt/theme/theme{theme_n}.xml" in entries:
            theme_n += 1
        entries[f"ppt/theme/theme{theme_n}.xml"] = theme_src or _theme_xml().encode("utf-8")
        override(f"/ppt/theme/theme{theme_n}.xml", "application/vnd.openxmlformats-officedocument.theme+xml")
        entries["ppt/notesMasters/notesMaster1.xml"] = _notes_master_xml().encode("utf-8")
        entries["ppt/notesMasters/_rels/notesMaster1.xml.rels"] = (
            XML_DECL + f'<Relationships xmlns="{REL_NS}"><Relationship Id="rId1" Type="{REL_T}theme" '
            f'Target="../theme/theme{theme_n}.xml"/></Relationships>').encode("utf-8")
        override("/ppt/notesMasters/notesMaster1.xml", CT_PML + "notesMaster+xml")
        rid = f"rId{next_id}"
        next_id += 1
        rel = ET.SubElement(rels, f"{{{REL_NS}}}Relationship")
        rel.set("Id", rid)
        rel.set("Type", REL_T + "notesMaster")
        rel.set("Target", "notesMasters/notesMaster1.xml")
        lst = ET.Element(f"{{{P_NS}}}notesMasterIdLst")
        nm = ET.SubElement(lst, f"{{{P_NS}}}notesMasterId")
        nm.set(f"{{{R_NS}}}id", rid)
        children = list(pres)
        anchor = next((i for i, c in enumerate(children) if c.tag == f"{{{P_NS}}}sldMasterIdLst"), -1)
        pres.insert(anchor + 1, lst)

    media_n = 0
    for i, info in enumerate(extras, 1):
        rel_items = [f'<Relationship Id="rId1" Type="{REL_T}slideLayout" Target="../slideLayouts/{layout}"/>']
        for rid, data, ext in info["images"]:
            media_n += 1
            name = f"image{media_n}.{'png' if ext == 'png' else 'jpeg'}"
            entries[f"ppt/media/{name}"] = data
            rel_items.append(f'<Relationship Id="{rid}" Type="{REL_T}image" Target="../media/{name}"/>')
        if info["notes"]:
            entries[f"ppt/notesSlides/notesSlide{i}.xml"] = _notes_slide_xml(info["notes"], font).encode("utf-8")
            entries[f"ppt/notesSlides/_rels/notesSlide{i}.xml.rels"] = (
                XML_DECL + f'<Relationships xmlns="{REL_NS}">'
                f'<Relationship Id="rId1" Type="{REL_T}notesMaster" Target="../notesMasters/notesMaster1.xml"/>'
                f'<Relationship Id="rId2" Type="{REL_T}slide" Target="../slides/slide{i}.xml"/>'
                "</Relationships>").encode("utf-8")
            override(f"/ppt/notesSlides/notesSlide{i}.xml", CT_PML + "notesSlide+xml")
            rel_items.append(f'<Relationship Id="rId9" Type="{REL_T}notesSlide" '
                             f'Target="../notesSlides/notesSlide{i}.xml"/>')
        entries[f"ppt/slides/_rels/slide{i}.xml.rels"] = (
            XML_DECL + f'<Relationships xmlns="{REL_NS}">' + "".join(rel_items) + "</Relationships>"
        ).encode("utf-8")
    return next_id


def build_from_template(md: str, out_path, template_path, base_dir=None,
                        warnings: list[str] | None = None) -> dict:
    """以真实 PPTX（如 python-pptx 的 default.pptx）为底包，只替换幻灯片。

    好处：theme / slideMaster / slideLayout / presProps / viewProps / tableStyles
    等静态部件都是官方模板原样，兼容性最稳；我们只负责生成 slide XML。
    """
    meta, slides, extras = build_deck(md, base_dir, warnings)
    with zipfile.ZipFile(template_path) as z:
        entries = {n: z.read(n) for n in z.namelist()}
    if "ppt/presentation.xml" not in entries:
        raise ValueError("模板缺少 ppt/presentation.xml")
    pres = ET.fromstring(entries["ppt/presentation.xml"])
    for el in pres.findall(f"{{{P_NS}}}sldIdLst"):
        pres.remove(el)
    rels = ET.fromstring(entries["ppt/_rels/presentation.xml.rels"])
    used = [int(r.get("Id")[3:]) for r in rels if (r.get("Id") or "").startswith("rId")]
    next_id = max(used, default=0) + 1
    sld_lst = ET.Element(f"{{{P_NS}}}sldIdLst")
    for i in range(1, len(slides) + 1):
        sid = ET.SubElement(sld_lst, f"{{{P_NS}}}sldId")
        sid.set("id", str(255 + i))
        sid.set(f"{{{R_NS}}}id", f"rId{next_id}")
        rel = ET.SubElement(rels, f"{{{REL_NS}}}Relationship")
        rel.set("Id", f"rId{next_id}")
        rel.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide")
        rel.set("Target", f"slides/slide{i}.xml")
        next_id += 1
    # 统一为 16:9 画布（模板默认可能是 4:3，不统一会导致右侧内容被裁掉）
    sld_sz = pres.find(f"{{{P_NS}}}sldSz")
    if sld_sz is not None:
        sld_sz.set("cx", str(SW))
        sld_sz.set("cy", str(SH))
        sld_sz.set("type", "screen16x9")
    # 插入位置：sldMasterIdLst 之后，sldSz 之前
    if sld_sz is not None:
        pres.insert(list(pres).index(sld_sz), sld_lst)
    else:
        pres.append(sld_lst)
    # 顺手修正模板 app.xml 里的页数与版式元数据（只是元数据，不影响渲染）
    app = entries.get("docProps/app.xml")
    if app:
        text = app.decode("utf-8", "replace")
        text = text.replace("<Slides>0</Slides>", f"<Slides>{len(slides)}</Slides>")
        text = text.replace("On-screen Show (4:3)", "Widescreen")
        entries["docProps/app.xml"] = text.encode("utf-8")
    ct = ET.fromstring(entries["[Content_Types].xml"])
    existing = {o.get("PartName") for o in ct if o.tag.endswith("Override")}
    for i in range(1, len(slides) + 1):
        part = f"/ppt/slides/slide{i}.xml"
        if part not in existing:
            ov = ET.SubElement(ct, f"{{{CT_NS}}}Override")
            ov.set("PartName", part)
            ov.set("ContentType", "application/vnd.openxmlformats-officedocument.presentationml.slide+xml")

    layout = _pick_blank_layout(entries)
    for i, slide_xml in enumerate(slides, 1):
        entries[f"ppt/slides/slide{i}.xml"] = slide_xml.encode("utf-8")
    _attach_media_and_notes(entries, pres, rels, ct, extras, meta.get("font") or FONT_DEFAULT,
                            layout, next_id)
    entries["ppt/presentation.xml"] = _xml_bytes(pres)
    entries["ppt/_rels/presentation.xml.rels"] = _xml_bytes(rels)
    entries["[Content_Types].xml"] = _xml_bytes(ct)
    ensure_parent(out_path)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in entries.items():
            z.writestr(name, data)
    _validate(out_path)
    return {"slides": len(slides), "meta": meta, "size": os.path.getsize(out_path), "template": True,
            "notes": sum(1 for e in extras if e["notes"]),
            "images": sum(len(e["images"]) for e in extras)}


def build_pptx(md: str, out_path, template_path=None, base_dir=None,
               warnings: list[str] | None = None) -> dict:
    if template_path is not None and os.path.isfile(template_path):
        return build_from_template(md, out_path, template_path, base_dir, warnings)
    # 纯生成模式（兼容性风险较高，仅作后备）：不支持图片与备注
    meta, slides, extras = build_deck(md, base_dir, warnings)
    if any(e["notes"] or e["images"] for e in extras) and warnings is not None:
        warnings.append("纯生成模式不写图片与备注；需要时请使用模板底包（默认）")
    slides = [re.sub(r"<p:pic>.*?</p:pic>", "", s, flags=re.S) for s in slides]
    n = len(slides)
    parts = {
        "[Content_Types].xml": _content_types(n),
        "_rels/.rels": _package_rels(),
        "docProps/core.xml": _core_xml(meta),
        "docProps/app.xml": XML_DECL + '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
                                       'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
                                       "<Application>DSHM pptx</Application></Properties>",
        "ppt/presentation.xml": _presentation_xml(n),
        "ppt/_rels/presentation.xml.rels": _presentation_rels(n),
        "ppt/presProps.xml": XML_DECL + f"<p:presentationPr {NS}/>",
        "ppt/viewProps.xml": XML_DECL + f"<p:viewPr {NS}/>",
        "ppt/tableStyles.xml": XML_DECL + '<a:tblStyleLst xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
                                          'def="{5C22544A-7EE6-4342-B048-85BDC9FD1C3A}"/>',
        "ppt/theme/theme1.xml": _theme_xml(),
        "ppt/slideMasters/slideMaster1.xml": _master_xml(),
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": XML_DECL + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>'
            "</Relationships>",
        "ppt/slideLayouts/slideLayout1.xml": _layout_xml(),
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels": XML_DECL + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>'
            "</Relationships>",
    }
    for i, slide in enumerate(slides, 1):
        parts[f"ppt/slides/slide{i}.xml"] = slide
        parts[f"ppt/slides/_rels/slide{i}.xml.rels"] = (
            XML_DECL + '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" '
            'Target="../slideLayouts/slideLayout1.xml"/></Relationships>')
    ensure_parent(out_path)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in parts.items():
            z.writestr(name, data)
    _validate(out_path)
    return {"slides": n, "meta": meta, "size": os.path.getsize(out_path)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Markdown/DSL → PPTX（纯标准库）")
    ap.add_argument("input", help="输入 .md（DSL 见文件头注释）")
    ap.add_argument("--out", help="输出 .pptx（默认同名 .pptx）")
    ap.add_argument("--accent", help="主色（十六进制，如 1F3864）")
    ap.add_argument("--font", help="字体（默认 Microsoft YaHei）")
    ap.add_argument("--template", help="底包 .pptx（默认 _pptx_template.pptx，存在则用；--no-template 可禁用）")
    ap.add_argument("--no-template", action="store_true", help="不用底包，纯生成（兼容性风险较高）")
    args = ap.parse_args(argv)
    src = resolve_path(args.input)
    if not src.is_file():
        print(f"[错误] 找不到输入文件：{src}", file=sys.stderr)
        return 1
    md = src.read_text(encoding="utf-8")
    if args.accent or args.font:
        # 在 frontmatter 之外注入覆盖
        lines = md.split("\n")
        extra = []
        if args.accent:
            extra.append(f"accent: {args.accent}")
        if args.font:
            extra.append(f"font: {args.font}")
        if lines and lines[0].strip() == "---":
            for i in range(1, len(lines)):
                if lines[i].strip() in ("---", "..."):
                    lines = lines[:i] + extra + lines[i:]
                    break
        else:
            lines = ["---"] + extra + ["---", ""] + lines
        md = "\n".join(lines)
    out = resolve_path(args.out) if args.out else src.with_suffix(".pptx")
    template = None
    if not args.no_template:
        # 底包路径一律走 resolve_path 归一成 Path；直接 os.path.join 得到的是 str，
        # 下一行 template.is_file() 会 AttributeError（2026-10-26 修）。
        template = resolve_path(
            args.template
            or os.path.join(os.environ.get("DSH_TOOL_DIR") or ".", "_pptx_template.pptx")
        )
        if not template.is_file():
            print(f"[提示] 未找到底包 {template}，改用纯生成模式（兼容性风险较高）")
            template = None
    warnings: list[str] = []
    info = build_pptx(md, out, str(template) if template else None, base_dir=str(src.parent),
                      warnings=warnings)
    print(f"[完成] {src.name} → {out}")
    mode = "模板底包" if info.get("template") else "纯生成"
    print(f"       共 {info['slides']} 页，{info['size'] / 1024:.1f} KB，{mode}，"
          f"图片 {info.get('images', 0)} 张，备注 {info.get('notes', 0)} 页，结构自检通过"
          f"（zip/XML/关系/content-types）")
    for w in warnings:
        print(f"[提示] {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
