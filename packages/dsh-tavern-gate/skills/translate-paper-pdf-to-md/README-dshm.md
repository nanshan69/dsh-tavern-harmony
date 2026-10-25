# translate-paper-pdf-to-md — DSHM / HarmonyOS 适配说明

这个目录是 [LiuMengxuan04/translate-paper-pdf-to-md](https://github.com/LiuMengxuan04/translate-paper-pdf-to-md)
的 skill，已按 DSHM（鸿蒙 DSH 客户端）环境做了本地化适配并安装到
`<dsh-home>/skills/translate-paper-pdf-to-md`。

## 为什么需要适配

上游 skill 依赖 `pdfinfo` / `pdftotext` / `pdftocairo` / `pdfimages` / ImageMagick `convert`。
鸿蒙端：

- 宿主进程里没有这些命令行工具；
- Alpine guest 是单核虚拟机，装 poppler/imagemagick 很容易把 guest 卡死（实测
  serial.log 出现 RCU stall），不适合当常规依赖；
- `python` 工具跑在宿主进程内，**不能 spawn 子进程**，所以上游脚本里的
  `subprocess.run(...)` 在 DSHM 上必然失败；
- 原生 wheel（PyMuPDF、Pillow、pdfium）加载不了（musl LDSO namespace 限制），
  只能用纯 Python 包。

## 做了什么

| 文件 | 状态 | 说明 |
| --- | --- | --- |
| `SKILL.md` | 上游原文 + 末尾追加 DSHM 段 | 工作流（收集偏好 → 抽取 → 重建 → 翻译 → 校验）不变 |
| `scripts/extract_pdf_assets_dshm.py` | **新增** | 纯标准库 + `pypdf`：文本抽取（layout/plain）、逐页 txt、`meta.json`、位图图表抽取 |
| `scripts/validate_markdown_assets.py` | 改 2 行 | 去掉 `from __future__ import annotations`（DSHM 运行器不接受）、规范化 argv |
| `scripts/extract_pdf_assets.py` | 保留原样 | 仅在装了 poppler 的 PC 上可用 |
| `references/quality-checklist.md` | 原样 | — |

## 依赖安装

```bash
pip3 install pypdf     # 纯 Python，无编译，实测 10 秒装好
```

若工具链升级导致 `pypdf` 丢失，重复上面这一行即可。

## 用法

```bash
python3 <skill>/scripts/extract_pdf_assets_dshm.py paper.pdf \
  --work-dir paper_zh_work \
  --assets-dir paper_zh_assets
python3 <skill>/scripts/validate_markdown_assets.py paper_zh.md
```

产物：

```text
paper_zh_work/
  source_layout.txt       # 保留排版的全文（\f 分页）
  source_raw.txt          # 纯阅读序全文
  pages/page-01.txt ...   # 逐页，便于分块翻译
  meta.json               # 页数/字符数/图片清单/warnings
paper_zh_assets/
  pNN-imgM.png|jpg        # PDF 内嵌位图（JPEG 直出，Flate 解码后重打包 PNG）
```

## 能力边界（实测）

- ✅ 文本抽取：15 页 2.2MB 论文约 **8 秒**，39,585 字符；双栏、图题、公式行号基本可读。
- ✅ 位图图表：直接从 PDF XObject 解码，实测还原出原始插图（`p04-img2.png` 即
  Transformer 多头注意力示意图，无损）。
- ⚠️ 矢量图（TikZ / matplotlib 矢量输出）：**无法渲染**。只能保留图题并在正文注明
  「图见原文」。要补齐需 poppler 渲染页图，而 guest 目前不稳定。
- ⚠️ 没有 PIL，不能裁剪/缩放图片；抽取出的位图本身就是完整图形，通常不需要裁。
- ✅ 校验脚本可用（图片链接、`[n]` 引用数、图/表/公式编号统计）。

## 已验证样例

`Attention Is All You Need`（arXiv 1706.03762，15 页）：

```
pages: 15  chars: 39585  images: 3
work_dir: .../zh_work
assets_dir: .../zh_assets
```

生成中文样例 `Attention_zh_sample.md`（摘要 + §3.2.1），校验输出：

```
image_links: 1
missing_images: 0
figure_numbers_seen: 2
equation_tags_seen: 1
```

## 可选：guest 里装 poppler（渲染矢量图 / 整页位图）

主机进程在手持档不能 `execve`，所以宿主侧只有纯 Python 路径；如果需要把**矢量图**
渲染成图片（TikZ、matplotlib 矢量输出），用 Alpine guest：

```bash
# guest 里一次性安装（实测 35 个包 / 约 60MB，耗时 3–4 分钟）
apk add --no-cache poppler-utils font-dejavu
# 之后
sh render_pages_guest.sh paper.pdf out_dir 120
```

产物：`out_dir/page-01.png …`、`out_dir/source_layout.txt`、`out_dir/pdfimages.txt`。

**路径注意**：guest 只挂载应用沙箱（宿主侧 `/data/storage/el2/base/haps/entry/files`，
guest 里也映射为 `/mnt/share`），**看不到个人盘 `Download/`**。个人盘里的 PDF 要先
用宿主侧 `python` 工具复制进沙箱，渲染完再把图片读回来：

```python
import shutil
shutil.copy("/storage/Users/currentUser/Download/…/paper.pdf",
            "/data/storage/el2/base/haps/entry/files/vm/tmp/paper.pdf")
```

实测记录（本机 DSHM 手持档）：

- `apk add poppler-utils font-dejavu` → 35 个包 / 约 60MB / 3–4 分钟，
  `pdftocairo 25.04.0`、`pdftotext`、`pdfinfo`、`pdfimages` 落在 `/usr/bin/`；
  **装完写进 `vm/rootfs.qcow2`，guest 重启后还在**（实测 qcow2 63MB → 105MB）。
- 渲染质量：`-r 72 -f 1 -l 1` 出 612×792 PNG；`-r 110 -f 3 -l 3`（整页矢量架构图
  + 大位图）出 935×1210 PNG，矢量线条、箭头、公式符号、正文全部正确 —— 这类矢量图
  宿主侧抽不出来，只能靠 poppler。
- 渲染耗时（guest 单核 + 9p 共享目录，实测）：72dpi 文本页 **2 分 42 秒**；
  110dpi 大图页 **6 分 29 秒**。都完成了，只是慢 —— 整页预览偶尔用可以，
  批量渲染不现实，正文/位图图表继续走宿主侧抽取。
- 反过来：`pdftotext`（纯文本）很快，只需要文字时不必渲染。
- 操作提醒：guest 忙时 `bash` 工具的 QGA 通道会丢响应（命令其实跑完了、文件也
  生成了，但工具一直显示在运行）。长命令用
  `setsid ... >/tmp/x.log 2>&1 &`，然后轮询日志/文件，别死等工具返回。

结论：**矢量图/整页预览用 poppler，正文与位图图表优先用宿主侧纯 Python 抽取。**
