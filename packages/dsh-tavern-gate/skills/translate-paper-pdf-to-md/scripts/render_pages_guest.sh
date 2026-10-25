#!/bin/sh
# render_pages_guest.sh — 在 DSHM 的 Alpine guest 里把 PDF 渲染成页面位图。
#
# 前提：guest 里装好 poppler（一次性）：
#     apk add --no-cache poppler-utils font-dejavu
# 作用：给「矢量图无法从 PDF 内嵌对象里抽出来」的场景兜底 —— 整页渲染成
#      PNG 后，可以从页面上裁出图/表（有 ImageMagick 就用 convert；没有就整页留档）。
#
# 用法（在 Agent 的 bash 工具里跑）。注意 guest 只挂载**应用沙箱**
# （/data/storage/el2/base/haps/entry/files，guest 里也能用 /mnt/share），
# 看不到个人盘 Download/：个人盘里的 PDF 要先用宿主侧 python 工具复制进沙箱。
#     sh render_pages_guest.sh paper.pdf out_dir [dpi]
#
# 产物：out_dir/page-01.png …、out_dir/source_layout.txt、out_dir/pdfimages.txt
set -e

PDF="$1"
OUT="$2"
DPI="${3:-144}"

if [ -z "$PDF" ] || [ -z "$OUT" ]; then
  echo "usage: sh render_pages_guest.sh <pdf> <out-dir> [dpi]" >&2
  exit 2
fi
if [ ! -f "$PDF" ]; then
  echo "missing PDF: $PDF" >&2
  exit 2
fi
for cmd in pdftocairo pdftotext pdfimages; do
  command -v "$cmd" >/dev/null 2>&1 || {
    echo "required command not found: $cmd (run: apk add --no-cache poppler-utils font-dejavu)" >&2
    exit 3
  }
done

mkdir -p "$OUT"
# -r 渲染分辨率；-png 输出 PNG（无损，便于后续裁剪/阅读）
pdftocairo -png -r "$DPI" "$PDF" "$OUT/page"
pdftotext -layout -enc UTF-8 "$PDF" "$OUT/source_layout.txt"
pdfimages -list "$PDF" > "$OUT/pdfimages.txt" 2>&1 || true
ls -l "$OUT" | sed -n '1,20p'
