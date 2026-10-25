---
name: translate-paper-pdf-to-md
description: Translate English academic PDF papers into polished target-language Markdown documents while preserving figures, tables, equations, citations, document structure, and domain-specific terminology. Use when Codex is asked to turn an English research PDF into a localized .md paper, extract visual assets, rebuild editable content, ask for field/style translation preferences before translating, or avoid low-quality machine-translated PDF output.
---

# Translate Paper PDF to Markdown

## Output Contract

Produce a new editable Markdown document plus an assets directory:

- Main file: `<paper-stem>_<lang>.md` or a user-provided name.
- Assets: `<paper-stem>_<lang>_assets/`.
- Work files: `<paper-stem>_<lang>_work/` for extracted text, rendered pages, and temporary crops.

Do not treat an auto-translated PDF as the final deliverable. Machine translation tools may be used only as rough context; the final document must be rewritten as a coherent localized paper with preserved academic structure.

## Workflow

1. **Collect translation preferences**
   - Before doing substantive translation, ask the user for missing preferences unless they already provided them.
   - Keep the intake short. Ask for:
     - Target language or locale.
     - Paper domain or subfield, e.g. systems, ML, biology, economics, materials science.
     - Intended reader and tone, e.g. faithful academic translation, smoother explanatory translation, teaching notes, publication-ready prose.
     - Terminology preference, e.g. preserve English key terms with first-use explanations, translate all established terms, or follow a supplied glossary.
     - Figure/table handling preference, e.g. preserve original image labels, translate captions only, or recreate editable figures when possible.
   - If the user wants the work to begin immediately and some preferences are missing, make conservative assumptions and state them in a short “translation profile” at the top of the work notes or final answer.

2. **Inspect the source**
   - Run `pdfinfo` and `file` on the PDF.
   - Extract text twice when possible:
     - `pdftotext -layout -enc UTF-8 <pdf> source_layout.txt`
     - `pdftotext -raw -enc UTF-8 <pdf> source_raw.txt`
   - Render page images with `pdftocairo -png -r 144 <pdf> page`.
   - Check whether figures are vector or raster with `pdfimages -list`.

3. **Plan the rebuilt document**
   - Keep the original section hierarchy, figure/table numbers, equation numbers, citations, acknowledgments, and references.
   - Rebuild normal tables as Markdown tables when practical.
   - Rebuild equations in LaTeX, preserving equation numbers with `\tag{n}` when the paper uses them.
   - Crop original figures from rendered page images when replotting is not needed.
   - For very wide or dense tables, include an original crop and, if useful, a simplified Markdown table.

4. **Translate and localize**
   - Translate sentence by sentence, but write fluent target-language academic prose.
   - Preserve technical meaning over literal word order.
   - Build a task-local terminology profile from the user's field, supplied glossary, paper context, and established usage in that domain.
   - Preserve names of systems, algorithms, datasets, conferences, software packages, and citations unless there is an established target-language rendering.
   - Keep references in the original language unless the user explicitly requests translated bibliography entries.
   - For key terms with multiple plausible translations, choose once and stay consistent; optionally include the English term on first use.

5. **Build figures and tables**
   - Use the rendered pages as the visual source of truth.
   - Crop each figure/table into the assets directory with `convert` or the helper script.
   - Name assets predictably, e.g. `fig1_slo_violation.png`, `table7_original.png`.
   - Add a localized caption under every visual asset.
   - If a figure contains English labels, keep the image as-is and translate the caption/body explanation. Recreate the plot only when the user asks or raw data is available.

6. **Validate**
   - Run `scripts/validate_markdown_assets.py <main.md>` to check image links.
   - Confirm all figures/tables/equations from the source appear in the output.
   - Confirm references are complete and citation numbers still match.
   - Read a representative section aloud mentally for translation quality; fix literal or awkward wording.
   - Use `references/quality-checklist.md` for a final pass.

## Helper Scripts

- `scripts/extract_pdf_assets.py`: create a work directory, extract layout/raw text, render pages, and optionally apply crop specifications.
- `scripts/validate_markdown_assets.py`: verify Markdown image links, count references, and report missing assets.

Prefer these scripts for repeatable setup and validation, then do the translation and document reconstruction manually with editorial judgment.

## Style Rules

- Match the requested translation profile. If no profile is provided, prefer faithful academic prose over loose paraphrase.
- Keep acronyms on first use, e.g. “中文术语（English Term, ACRONYM）” when useful for the target audience.
- Keep equation variables unchanged.
- Keep citation brackets unchanged, e.g. `[28]`.
- Avoid adding commentary that is not in the paper except a short “整理说明” if useful.
- If the source text extraction is noisy, use page images and local context to reconstruct meaning rather than copying OCR artifacts.


## DSHM / HarmonyOS notes

This install also targets DSHM (HarmonyOS DSH client), where poppler and
ImageMagick are unavailable and native wheels (PyMuPDF, Pillow) cannot load.

- Use `scripts/extract_pdf_assets_dshm.py` (pure stdlib + `pypdf`) instead of
  `scripts/extract_pdf_assets.py`. It produces the same work-directory layout
  (`source_layout.txt`, `source_raw.txt`, `pages/page-NN.txt`, `meta.json`)
  and harvests embedded raster figures into the assets directory.
- No page rasterisation: vector figures (TikZ, matplotlib vector output)
  cannot be rendered. Keep their captions and tell the reader to consult the
  source PDF for those figures.
- No ImageMagick cropping is needed: harvested images are whole figures.
- Scripts are run through the agent `python` tool. That in-process runner
  passes `[prog, <script>, *args]` and does not define `__file__`; the scripts
  in this install normalise the argument list. Do not put a `from __future__`
  import first in a script if it must run there.
- Deliver the final `.md` plus `_assets/` into the user-visible workspace
  (Download / workspace directory) so the user can open the result.
- See `README-dshm.md` for install steps, measured timings and limits.
- Invocation from the agent: use the `python` tool in file mode, e.g. `file=<skill>/scripts/extract_pdf_assets_dshm.py`, `args=["paper.pdf", "--work-dir", "paper_zh_work", "--assets-dir", "paper_zh_assets"]`. Do not call these scripts through the `bash` tool (Alpine guest has no python3).
- One-time dependency: \`pypdf\` (pure Python). If it is missing, run this through
  the agent \`python\` tool:
  \`from pip._internal.cli.main import main; main(["install", "pypdf"])\`.
- Optional page rasterisation: when the Alpine guest has poppler installed
  (\`apk add --no-cache poppler-utils font-dejavu\`), run
  \`scripts/render_pages_guest.sh <pdf> <out-dir> [dpi]\` through the \`bash\` tool.
  It writes \`page-NN.png\` plus \`source_layout.txt\`, which covers vector figures
  that cannot be harvested from the PDF. The guest is a 1-vCPU VM: render only
  the pages you actually need (\`pdftocairo -f N -l N ...\`).
