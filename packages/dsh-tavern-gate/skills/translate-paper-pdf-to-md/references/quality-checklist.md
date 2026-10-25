# Quality Checklist

Use this before handing off a localized paper.

## Completeness

- The output has the same major sections as the source.
- Abstract, introduction, method/design, implementation, evaluation, discussion, related work, summary/conclusion, acknowledgments, and references are present when they exist in the source.
- Every figure number in the source appears in the output.
- Every table number in the source appears in the output.
- Every numbered equation in the source appears in the output with the same number.
- Citation numbers remain in square brackets and still match the bibliography.
- The bibliography has the same number of entries as the source.

## Asset Integrity

- All Markdown image links resolve on disk.
- Crops are legible and not missing axes, legends, labels, or table rows.
- Figure/table captions are localized even if the image itself keeps English labels.
- Wide tables include either a faithful crop or a carefully rebuilt table.

## Translation Quality

- Terminology is consistent across the paper.
- The translation profile requested from the user is reflected in wording, tone, and terminology.
- Technical nouns are translated by meaning, not by generic dictionary output.
- Sentences read as academic prose in the target language.
- Variables, algorithms, model names, system names, datasets, and URLs are preserved.
- No machine-translation artifacts remain, such as “抽象的” for a paper abstract heading.

## Reproducibility

- Keep extracted text and rendered pages in a work directory if the user may want further edits.
- Keep asset filenames stable and descriptive.
- Document any deliberate choice to leave labels in original language.
