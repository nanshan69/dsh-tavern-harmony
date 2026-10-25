---
name: research-stats-plan
description: 样本量/效能计算与统计分析计划（SAP）通用方法：分析集、主要分析、缺失与伴发事件、多重性、模型假设、报告规范，配套纯 Python stats_tools 用法与结果解读纪律。算样本量、写统计章节、做初步分析、看统计结果时读。
---
# 样本量与统计分析计划（SAP）

工具：`research-toolkit` 技能的 `scripts/run_tool.py` + `stats_tools.py`（纯 Python，
不依赖 numpy/scipy/R）。

## 1. 样本量

- 两组连续变量（含基线校正 ANCOVA）：
  `n/组 = 2(z_{1−α/2}+z_{1−β})² σ²(1−ρ²) / Δ²`

  Δ = 临床有意义的最小差值（不是文献预期效应）；σ = 标准差；ρ = 基线-随访相关系数
  （0.5 是常用但偏乐观的设定，需数据或文献支持）；α、power、脱落率要写清。
- 命令：`stats_tools samplesize --design ancova --delta 1.0 --sd 2.0 --rho 0.5 --dropout 0.15`
  → 可评估 n/组、随机 n/组、总 N。
- 效能表 / MDE / CI 半宽：`stats_tools power --n-per-group 48 --delta 1.0 --sd 2.0 --rho 0.5`。
- 报告：写清所有假设与出处，并给「入组目标 / 最低可接受 / 时间窗」；
  按最终 N 分层解读（确证 / 优效+估计 / 先导），规则预先写死。

## 2. SAP 骨架（写方案或独立 SAP）

1. **分析集**：ITT/全分析集（随机后全部，按随机分组分析）；PP（完成主要终点、
   无重大偏离、依从达标）作敏感性；安全性集（至少接受 1 次干预）。
2. **主要分析**：明确因变量、自变量、协变量（基线值、分层因素）、效应量
   （调整后均数差 / GMR / OR）+ 95%CI + p（双侧 α）。
3. **伴发事件（estimand，ICH E9(R1)）**：每类伴发事件（补救治疗、转手术、停药、
   启动其他治疗）写明策略（treatment-policy / hypothetical / composite /
   while-on-treatment），并配敏感性分析。
4. **缺失数据**：主分析用可用数据 + 明确缺失假设；敏感性用多重插补（含辅助变量）、
   worst-case、tipping point。报告各组缺失例数与原因。
5. **多重性**：主要终点单一则直接检验；多个关键次要终点按层级顺序（固定序列），
   只有前一个显著才继续；其余为支持性/探索性，只报效应量与 CI。
6. **亚组**：预先声明（年龄、基线严重度、合并用药等），只作探索，报交互项 p，
   不宣称组间疗效差异。
7. **模型假设**：残差正态性/方差齐性；违背后用 bootstrap/稳健 SE（PC 端 R/Stata）。
8. **报告规范**：CONSORT/STROBE/SPIRIT + ICH E9(R1)；数值精度：均数/差值 1–2 位小数，
   p 3 位（<0.001），CI 与效应量同精度。

## 3. 常用命令

- 两组比较（Welch t + Mann-Whitney）：`stats_tools compare --csv data.csv --var y --group arm`
- 协变量校正：`stats_tools ancova --csv data.csv --y y --group arm --covariates y0,age`
- 描述统计：`stats_tools desc --csv data.csv --cols age,y0,y --group arm`
- 相关：`stats_tools corr --csv data.csv --x y0 --y y`
- 限制：只支持数值协变量与哑变量分组，不做交互/随机效应。

## 4. 结果解读纪律

- 报「调整后组间差 + 95%CI」，不要只报 p；p≥0.05 不等于无效（看 CI 是否排除
  临床重要差值）。
- 不把 SMD 当 MD；统计显著 ≠ 临床意义（对照 MCID）。
- 不因 N 小就改主要终点或分析集；分层解读规则事先写死。
- 期中分析只做可行性，不提前揭盲、不单独下疗效结论。
- 数据锁定后再解盲；统计师盲态分析（分组编码）。
- 分析代码、数据文件、日期写进 SAP 附件，保证可复现。

## 5. 本机限制与替代

| 需要 | 本机 | 替代 |
| --- | --- | --- |
| 描述/两组比较/ANCOVA/相关 | `stats_tools.py`（纯 Python OLS） | — |
| 重复测量/混合模型 | ✗ | R lme4/nlme、SPSS MIXED |
| 多重插补 | ✗（仅描述性） | R mice、SPSS |
| 生存分析 | ✗ | R survival |
| Meta 分析 | 森林图示意（`figures.py`） | R metafor、RevMan |
| 绘图 | SVG（`figures.py`） | R ggplot2、GraphPad |
