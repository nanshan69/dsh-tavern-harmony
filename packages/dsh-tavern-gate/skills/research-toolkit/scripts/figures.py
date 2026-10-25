#!/usr/bin/env python3
"""科研图表生成（纯标准库，直接输出 SVG；浏览器 / Word / WPS 均可打开或插入）。

子命令：
  forest  森林图（Meta 分析/证据汇总），CSV 列：study, est, lo, hi[, weight]
  bar     柱状图，CSV 列：category, value[, group]
  line    折线图，CSV 列：x  + 一个或多个数值列

示例：
  python scripts/figures.py forest --csv evidence/合并效应.csv --out evidence/forest.svg --ratio
  python scripts/figures.py bar --csv 数据.csv --out 图.svg --title "各组均值"
  python scripts/figures.py line --csv 随访.csv --out 趋势.svg
说明：SVG 可在浏览器打开；若需 PNG/TIFF 投稿图，请在 PC 上用 Inkscape/Illustrator 转换，
      或装 R 用 ggplot2 —— 端侧内嵌 Python 不能装 numpy/matplotlib 等 C 扩展。
"""
import argparse
import math
import os
import sys
from xml.sax.saxutils import escape as _esc

sys.path.insert(0, os.environ.get("DSH_TOOL_DIR") or os.path.dirname(os.path.abspath(globals().get("__file__", "run_tool.py"))))
from _util import ensure_parent, resolve_path  # noqa: E402


def _read_csv(path):
    import csv
    with open(resolve_path(path), newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


class Svg:
    def __init__(self, w, h):
        self.w, self.h = w, h
        self.parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}">',
            f'<rect width="{w}" height="{h}" fill="white"/>',
        ]

    def text(self, x, y, s, size=12, anchor="start", weight="normal", fill="#222", family="'Microsoft YaHei', 'PingFang SC', sans-serif"):
        self.parts.append(
            f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" text-anchor="{anchor}" '
            f'font-weight="{weight}" fill="{fill}" font-family="{family}">{_esc(str(s))}</text>')

    def line(self, x1, y1, x2, y2, stroke="#333", width=1, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                          f'stroke="{stroke}" stroke-width="{width}"{d}/>')

    def rect(self, x, y, w, h, fill="#4C78A8", stroke="none", opacity=1.0):
        self.parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
                          f'fill="{fill}" stroke="{stroke}" opacity="{opacity}"/>')

    def circle(self, x, y, r, fill="#4C78A8"):
        self.parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r:.1f}" fill="{fill}"/>')

    def polygon(self, points, fill="#F58518", opacity=0.85):
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
        self.parts.append(f'<polygon points="{pts}" fill="{fill}" opacity="{opacity}"/>')

    def save(self, path):
        self.parts.append("</svg>")
        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(self.parts))


def _num(row, key):
    try:
        return float(str(row.get(key, "")).strip())
    except (TypeError, ValueError):
        return None


def forest(rows, out, title="森林图", xlabel="效应量", ratio=False, pooled=False, width=900):
    studies = []
    for r in rows:
        est, lo, hi = _num(r, "est"), _num(r, "lo"), _num(r, "hi")
        if est is None or lo is None or hi is None:
            continue
        if lo > hi:  # 上下限写反时自动交换
            lo, hi = hi, lo
        studies.append({"name": (r.get("study") or "").strip(), "est": est, "lo": lo, "hi": hi,
                        "w": _num(r, "weight") or 1.0})
    if not studies:
        raise SystemExit("[错误] CSV 里没有可用的 study/est/lo/hi 行")
    if ratio and not all(s["est"] > 0 and s["lo"] > 0 for s in studies):
        print("[提示] --ratio 需要所有 est/lo > 0；存在非正值，已改用线性坐标、无效线=0")
        ratio = False
    if pooled and any(s["hi"] - s["lo"] <= 0 for s in studies):
        print("[提示] 有研究 CI 宽度为 0，无法逆方差加权，已取消合并菱形")
        pooled = False
    tf = math.log if (ratio and all(s["est"] > 0 and s["lo"] > 0 for s in studies)) else (lambda v: v)
    vals = [tf(s["lo"]) for s in studies] + [tf(s["hi"]) for s in studies]
    null = tf(1.0) if ratio else 0.0
    lo_x, hi_x = min(vals + [null]), max(vals + [null])
    pad = (hi_x - lo_x) * 0.08 or 0.1
    lo_x, hi_x = lo_x - pad, hi_x + pad

    left, right = 235, 150
    top, row_h, bottom = 70, 26, 80
    n = len(studies) + (1 if pooled else 0)
    height = top + row_h * n + bottom
    plot_l, plot_r = left, width - right
    plot_t, plot_b = top, top + row_h * n

    def tpos(v):
        """已变换空间（log/恒等之后）的取值 → 像素 x。"""
        return plot_l + (v - lo_x) / (hi_x - lo_x) * (plot_r - plot_l)

    def xpos(v):
        """原始效应量取值 → 像素 x（内部自动变换）。"""
        return tpos(tf(v))

    def ypos(i):
        return plot_t + row_h * (i + 1) - row_h / 2

    s = Svg(width, height)
    s.text(width / 2, 30, title, size=16, anchor="middle", weight="bold")
    s.text(left, 52, "研究", size=12, weight="bold")
    s.text(plot_r + 10, 52, "效应量 (95%CI)", size=12, weight="bold")

    # 轴线与刻度
    for i in range(6):
        v = lo_x + (hi_x - lo_x) * i / 5
        real = math.exp(v) if (ratio and all(s["est"] > 0 and s["lo"] > 0 for s in studies)) else v
        x = plot_l + (v - lo_x) / (hi_x - lo_x) * (plot_r - plot_l)
        s.line(x, plot_b, x, plot_b + 5, stroke="#666")
        label = f"{real:.2f}" if ratio else f"{real:.2f}"
        s.text(x, plot_b + 20, label, size=10, anchor="middle", fill="#555")
    s.line(plot_l, plot_b, plot_r, plot_b, stroke="#333", width=1)
    nx = tpos(null)  # null 已是变换空间的值，不能再变换一次（对数坐标下 log(0) 会崩）
    s.line(nx, plot_t - 8, nx, plot_b, stroke="#888", width=1, dash="4,4")

    max_w = max(s_["w"] for s_ in studies)
    for i, st in enumerate(studies):
        y = ypos(i)
        s.text(left - 8, y + 4, st["name"][:34], size=11, anchor="end")
        x1, x2 = xpos(st["lo"]), xpos(st["hi"])
        s.line(x1, y, x2, y, stroke="#333", width=1.2)
        for xx in (x1, x2):
            s.line(xx, y - 4, xx, y + 4, stroke="#333", width=1.2)
        size = 4 + 7 * math.sqrt(max(st["w"], 0.01) / max_w)
        s.rect(xpos(st["est"]) - size / 2, y - size / 2, size, size, fill="#4C78A8")
        s.text(plot_r + 10, y + 4, f"{st['est']:.2f} ({st['lo']:.2f}, {st['hi']:.2f})", size=11)

    if pooled:
        se = [(st["hi"] - st["lo"]) / (2 * 1.96) for st in studies]
        if ratio and all(st["est"] > 0 for st in studies):
            se = [(tf(st["hi"]) - tf(st["lo"])) / (2 * 1.96) for st in studies]
            wts = [1 / (s_ ** 2) for s_ in se]
            bel = sum(w * tf(st["est"]) for w, st in zip(wts, studies)) / sum(wts)
            bse = math.sqrt(1 / sum(wts))
            b_lo, b_hi = math.exp(bel - 1.96 * bse), math.exp(bel + 1.96 * bse)
            b_est = math.exp(bel)
        else:
            wts = [1 / (s_ ** 2) for s_ in se]
            b_est = sum(w * st["est"] for w, st in zip(wts, studies)) / sum(wts)
            bse = math.sqrt(1 / sum(wts))
            b_lo, b_hi = b_est - 1.96 * bse, b_est + 1.96 * bse
        y = ypos(len(studies))
        s.line(left, y, plot_r, y, stroke="#ccc", width=1, dash="2,2")
        s.text(left - 8, y + 4, "合并效应", size=12, anchor="end", weight="bold")
        bl, br = xpos(b_lo), xpos(b_hi)
        s.polygon([(xpos(b_est), y - 8), (br, y), (xpos(b_est), y + 8), (bl, y)])
        s.text(plot_r + 10, y + 4, f"{b_est:.2f} ({b_lo:.2f}, {b_hi:.2f})", size=11, weight="bold")
    s.text((plot_l + plot_r) / 2, height - 18, xlabel, size=12, anchor="middle")
    s.save(out)


def bar(rows, out, title="柱状图", width=760, height=460):
    cats, vals, groups = [], [], []
    for r in rows:
        c = (r.get("category") or "").strip()
        v = _num(r, "value")
        if not c or v is None:
            continue
        cats.append(c)
        vals.append(v)
        groups.append((r.get("group") or "").strip())
    if not vals:
        raise SystemExit("[错误] CSV 需要 category,value 两列")
    # 保持 CSV 中的出现顺序（时点/剂量有自然顺序，按字母排序会打乱）
    uniq = list(dict.fromkeys(cats))
    gs = list(dict.fromkeys(groups)) if any(groups) else [""]
    left, right, top, bottom = 70, 30, 60, 90
    plot_l, plot_r = left, width - right
    plot_t, plot_b = top, height - bottom
    vmax = max(vals + [0])
    vmin = min(vals + [0])
    span = (vmax - vmin) or 1.0
    vmax += span * 0.1
    vmin = min(0.0, vmin)

    def ypos(v):
        return plot_b - (v - vmin) / (vmax - vmin) * (plot_b - plot_t)

    s = Svg(width, height)
    s.text(width / 2, 28, title, size=16, anchor="middle", weight="bold")
    # y 轴刻度
    for i in range(6):
        v = vmin + (vmax - vmin) * i / 5
        y = ypos(v)
        s.line(plot_l, y, plot_r, y, stroke="#eee")
        s.text(plot_l - 8, y + 4, f"{v:.2f}", size=10, anchor="end", fill="#555")
    s.line(plot_l, plot_b, plot_r, plot_b, stroke="#333")
    s.line(plot_l, plot_t, plot_l, plot_b, stroke="#333")
    band = (plot_r - plot_l) / max(len(uniq), 1)
    colors = ["#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2", "#B279A2"]
    bw = band * 0.7 / len(gs)
    idx = {c: i for i, c in enumerate(uniq)}
    for row_c, row_v, row_g in zip(cats, vals, groups):
        gi = gs.index(row_g)
        x = plot_l + band * idx[row_c] + band * 0.15 + gi * bw
        y = ypos(row_v)
        top_y = min(y, ypos(0))
        s.rect(x, top_y, bw * 0.92, abs(ypos(0) - y), fill=colors[gi % len(colors)])
        s.text(x + bw * 0.46, top_y - 5, f"{row_v:g}", size=9, anchor="middle")
    for c in uniq:
        s.text(plot_l + band * idx[c] + band / 2, plot_b + 22, c[:12], size=11, anchor="middle")
    if gs != [""]:
        for gi, g in enumerate(gs):
            s.rect(plot_l + gi * 110, height - 40, 12, 12, fill=colors[gi % len(colors)])
            s.text(plot_l + 18 + gi * 110, height - 29, g, size=11)
    s.save(out)


def line(rows, out, title="折线图", width=780, height=460):
    if not rows:
        raise SystemExit("[错误] CSV 为空")
    xcol = "x" if "x" in rows[0] else list(rows[0].keys())[0]
    xs = [(r.get(xcol) or "").strip() for r in rows]
    series = [k for k in rows[0].keys() if k != xcol]
    data = {}
    for k in series:
        data[k] = [_num(r, k) for r in rows]
    allv = [v for vs in data.values() for v in vs if v is not None]
    if not allv:
        raise SystemExit("[错误] 没有数值列")
    left, right, top, bottom = 70, 150, 60, 70
    plot_l, plot_r = left, width - right
    plot_t, plot_b = top, height - bottom
    vmax, vmin = max(allv), min(allv)
    span = (vmax - vmin) or 1.0
    vmax += span * 0.08
    vmin -= span * 0.08

    def xpos(i):
        return plot_l + (i / max(len(xs) - 1, 1)) * (plot_r - plot_l)

    def ypos(v):
        return plot_b - (v - vmin) / (vmax - vmin) * (plot_b - plot_t)

    s = Svg(width, height)
    s.text(width / 2, 28, title, size=16, anchor="middle", weight="bold")
    for i in range(6):
        v = vmin + (vmax - vmin) * i / 5
        y = ypos(v)
        s.line(plot_l, y, plot_r, y, stroke="#eee")
        s.text(plot_l - 8, y + 4, f"{v:.2f}", size=10, anchor="end", fill="#555")
    s.line(plot_l, plot_b, plot_r, plot_b, stroke="#333")
    s.line(plot_l, plot_t, plot_l, plot_b, stroke="#333")
    for i, x in enumerate(xs):
        s.text(xpos(i), plot_b + 20, x[:10], size=10, anchor="middle")
    colors = ["#4C78A8", "#F58518", "#54A24B", "#E45756", "#72B7B2", "#B279A2"]
    for si, k in enumerate(series):
        pts = [(xpos(i), ypos(v)) for i, v in enumerate(data[k]) if v is not None]
        if len(pts) > 1:
            s.parts.append('<polyline fill="none" stroke="%s" stroke-width="2" points="%s"/>'
                           % (colors[si % len(colors)],
                              " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)))
        for x, y in pts:
            s.circle(x, y, 3, fill=colors[si % len(colors)])
        s.rect(plot_r + 12, plot_t + si * 22, 12, 12, fill=colors[si % len(colors)])
        s.text(plot_r + 30, plot_t + 11 + si * 22, k, size=11)
    s.save(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="生成 SVG 科研图表（纯标准库）")
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("forest", help="森林图")
    f.add_argument("--csv", required=True)
    f.add_argument("--out", required=True)
    f.add_argument("--title", default="森林图")
    f.add_argument("--xlabel", default="效应量")
    f.add_argument("--ratio", action="store_true", help="比值型效应量（对数坐标，无效线=1）")
    f.add_argument("--pooled", action="store_true", help="加合并效应菱形（逆方差法）")
    f.add_argument("--width", type=int, default=900)
    b = sub.add_parser("bar", help="柱状图")
    b.add_argument("--csv", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--title", default="柱状图")
    b.add_argument("--width", type=int, default=760)
    b.add_argument("--height", type=int, default=460)
    l = sub.add_parser("line", help="折线图")
    l.add_argument("--csv", required=True)
    l.add_argument("--out", required=True)
    l.add_argument("--title", default="折线图")
    l.add_argument("--width", type=int, default=780)
    l.add_argument("--height", type=int, default=460)
    args = ap.parse_args(argv)
    rows = _read_csv(args.csv)
    out = resolve_path(args.out)
    ensure_parent(out)
    if args.cmd == "forest":
        forest(rows, out, args.title, args.xlabel, args.ratio, args.pooled, args.width)
    elif args.cmd == "bar":
        bar(rows, out, args.title, args.width, args.height)
    else:
        line(rows, out, args.title, args.width, args.height)
    print(f"[完成] {args.cmd} → {out}（SVG；浏览器/Word/WPS 可打开）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
