---
name: research-pubmed-search
description: 医学文献检索与全文获取的标准流程：PICO 拆解、PubMed/Europe PMC/ClinicalTrials.gov 检索式构造、PRISMA-S 留痕、标题摘要与全文筛选、OA 全文获取、引文核对与 Vancouver 参考文献生成。需要检索文献、查某篇文献、核对引文、写检索方法学时读。
---
# 文献检索与全文获取

工具用法见 `research-toolkit` 技能（`scripts/run_tool.py` + `pubmed.py` / `pdf_tools.py`）。

## 1. 先把问题写成 PICO

| 项 | 内容 |
| --- | --- |
| P 人群 | 疾病/人群、诊断标准、年龄性别等 |
| I 干预 | 具体干预与参数（剂量/疗程/方式） |
| C 对照 | 安慰/假干预/常规治疗/无干预 |
| O 结局 | 主要与次要结局、测量工具、时点 |
| S 研究类型 | RCT / 观察性 / 系统综述 / 动物 / 体外 |

PICO 写进检索记录，后续所有检索式从它派生。

## 2. 检索式构造（PubMed）

- 字段标签：`[tiab]`（题名摘要）、`[MeSH]`、`[pt]`（文献类型）、`[ti]`。
- 同义词用 OR 扩全，概念间用 AND；`NOT` 慎用（容易误排）。
- 模板：

```
("term A"[tiab] OR "term A alias"[tiab] OR "MeSH heading"[MeSH])
AND
("outcome 1"[tiab] OR "outcome 2"[tiab])
AND
(randomized controlled trial[pt] OR controlled clinical trial[pt])
```

- `pubmed search --query "..." --years 2015-2026 --retmax 50`；`--sort pub_date` 按时间倒序。
- 每个结局/每种设计可单独检索后合并（提高召回）。

## 3. 留痕（写方法学直接引用，PRISMA-S）

每次检索必须记录：日期、数据库、平台/接口、检索式原文、命中数、取回数、筛选结果分布。
工具会把题录写到 `literature/检索结果_<时间>.csv/.json`（含检索式与计数）；
手工维护 `literature/检索记录.md`（日期/检索式/命中/分类/关键发现）。
更新检索也要留记录，不要覆盖旧记录。

## 4. 筛选（标题摘要 → 全文）

- 导出 CSV 做筛选表：`pmid,title,year,journal,decision(纳入/排除/待定),reason,notes`。
- 排除原因用固定词表（人群不符/非人体/无对照/结局无关/重复/全文不可得…），
  便于画 PRISMA 流程图。
- 可 `xlsx_tools csv2xlsx` 转 Excel 人工筛，或用 subagent 批量初筛
  （字段纪律见 `research-evidence-extraction`）。
- 最终纳入数、排除数、各原因计数要能对上 PRISMA 2020 流程。

## 5. 全文获取

- OA 优先：`pubmed oa --pmid <PMID> --outdir fulltext`（Europe PMC fullTextXML，
  存 `<PMID>_<年>.txt`）。
- 失败再走 PubMed 页面 → PMC 全文 / 期刊官网 / 图书馆。
- 用户下载的 PDF 放 `inbox/`，然后 `pdf_tools batch inbox --outdir fulltext`。
- PDF 提不出文本（扫描件）：如实报「无文本层，需 OCR」，**不得猜内容**。

## 6. 引文核对与参考文献

- 核对：`pubmed verify --file 稿件.md`（有问题的条目必须人工处理；未收录≠无效，
  中文 DOI 常未收录，需到 doi.org 或期刊网核对）。
- 生成：`pubmed cite --pmids 123,456 --out 参考文献_Vancouver.md`。
- 规则：只引查得到的；不确定标「需核对」；**禁止编造文献**。

## 7. 注册库与引用追踪

- ClinicalTrials.gov：`pubmed ctgov --query "..."`；ChiCTR 需网页检索并记录日期与结果。
  检索结果写进方案「竞争试验/研究空白」部分。
- 滚雪球：关键系统综述 → 查其纳入研究列表（补漏）与引文追踪；关键结论以原文为准。
