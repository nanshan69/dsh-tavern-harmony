---
name: research-toolkit
description: 本机科研文档工具链（纯 Python，无 pandoc/LibreOffice）：Markdown→DOCX（封面/页眉/目录/三线表）、Markdown/DSL→PPTX、DOCX/PDF 读取与检索、CSV↔XLSX、SVG 图表、样本量与统计核对、PubMed 检索。需要生成/修改 Word 或 PPT、读 PDF、做 Excel、画图、跑统计、查文献，或工具报错时读。
---
# 科研文档工具链（research-toolkit）

HarmonyOS + DSHM 内嵌 CPython 上自建的一套纯 Python 工具。**不要**试图装
python-docx / pandas / matplotlib（C 扩展会被沙箱拒绝），也不要装来路不明的原生模块。

## 0. 怎么跑

脚本在本技能目录的 `scripts/` 下，用 Agent 的 `python` 工具 + 本目录运行器执行
（`file` 模式只能进沙箱路径，所以必须走这个运行器）：

```python
python(file="/data/storage/el2/base/haps/entry/files/dsh/home/skills/research-toolkit/scripts/run_tool.py",
       args=["md2docx", "输入.md", "--out", "输出.docx"])
```

- 不带参数运行会列出全部可用工具。
- `python` 工具的 cwd 是 `/`，**输入/输出路径一律用绝对路径**最稳；
  相对路径会按工作目录解析（可用环境变量 `DSH_RESEARCH_ROOT` 指定根）。
- 工具共用 `_util.py`；运行器已经把 `scripts/` 加进 `sys.path`，不要单独复制脚本。

## 1. 工具清单

| 工具 | 用途 | 常用 args |
|---|---|---|
| `md2docx.py` | Markdown→DOCX：封面/页眉/页码/目录域、三线表、首行缩进两端对齐、A4 中文 | `["md2docx","输入.md","--out","输出.docx","--cover","--title","标题","--header","页眉","--toc"]` |
| `pptx.py` | Markdown/DSL→PPTX（模板底包，16:9；封面/章节/内容/表格/数字卡/结论页、图片、备注） | `["pptx","汇报.md","--out","汇报.pptx"]` |
| `docx_tools.py` | 读 DOCX：转文本/Markdown、标题结构、全文检索 | `["docx_tools","extract","a.docx","--format","md"]`、`["docx_tools","outline","a.docx"]`、`["docx_tools","search","a.docx","--pattern","样本量"]` |
| `pdf_tools.py` | PDF 提文本/检索/批量转 txt（pypdf） | `["pdf_tools","batch","inbox","--outdir","fulltext"]`、`["pdf_tools","search","a.pdf","--pattern","..."]` |
| `xlsx_tools.py` | CSV→XLSX（冻结首行首列、中文列宽、换行）、XLSX→CSV/Markdown | `["xlsx_tools","csv2xlsx","a.csv","--out","a.xlsx"]` |
| `figures.py` | SVG 图表：森林图/柱状/折线 | `["figures","forest","--csv","effects.csv","--out","forest.svg","--pooled"]` |
| `stats_tools.py` | 样本量/效能/描述/两组比较/ANCOVA/相关（纯 Python OLS） | 见 `research-stats-plan` 技能 |
| `pubmed.py` | PubMed / Europe PMC / ClinicalTrials.gov 检索、OA 全文、核对、生成引文 | 见 `research-pubmed-search` 技能 |
| `deps.py` | 依赖检查/安装（openpyxl、pypdf） | `["deps","check"]`、`["deps","install"]` |

## 2. md2docx 要点

- **Markdown 是源稿**，docx 只是交付物；不要反过来手改 docx。
- 支持：`#` 标题、段落、粗体/斜体/代码、GFM 表格、列表、引用块、代码块、`---`
  分隔线、`<!-- pagebreak -->` 分页（frontmatter 会跳过）。
- 排版：正文首行缩进 2 字符 + 两端对齐（`--no-indent` 关闭）；表格默认学术三线表；
  `--cover` 独立封面（需 `--title`，可加 `--subtitle/--author/--date`，`--date today`）；
  `--header` 页眉；`--toc` 目录单独一页，需在 Word/WPS 里右键「更新域」才显示。
- 标题层级：唯一且最前的 `#` 当文档题目（不进目录），`##`=章、`###`=节；
  默认 `--number-headings fill` 只给缺号标题补号，已有编号不动。
- 不支持：图片嵌入、脚注、合并单元格/嵌套表格、自动编号标题、奇偶页页眉。
- 生成后可用 `docx_tools extract` 复核内容。

## 3. pptx 要点

- 底包 `scripts/_pptx_template.pptx`（官方 master/layout/theme 原样），不要删。
- DSL：frontmatter（title/subtitle/author/date/topic/accent）→ 封面；页间单独一行
  `---`；页类型 `[section]` `[content]` `[table]` `[metrics]` `[statement]`。
- 图片：`![图注](图.png)`，仅 PNG/JPEG，每页 1 张；SVG 需先转 PNG。
- 备注：任意页 `note: ...`；表格每页 1 个，超出版心只提示、不自动拆页。
- 不支持动画/切换/原生图表/SmartArt/超链接/合并单元格。

## 4. 依赖与故障排查

- `deps check` 看依赖；缺就 `deps install`（联网装到内嵌 CPython site-packages；
  **卸载/重装应用后要重装一次**）。
- `ModuleNotFoundError: openpyxl/pypdf` → `deps install`。
- `script path outside allowed roots`（python 工具 file 模式）→ 必须用本技能的
  `run_tool.py`，不要直接 file= 别的路径。
- 改了脚本但行为没变：`python` 工具是常驻进程，被 import 的模块有缓存 →
  重启会话或重新导入。
- 不要用 `bash` 跑 `python3`（手持档 guest 里没有 Python），Python 一律走 `python` 工具。
