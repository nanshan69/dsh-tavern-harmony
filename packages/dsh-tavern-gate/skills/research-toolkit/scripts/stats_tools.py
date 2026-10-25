#!/usr/bin/env python3
"""统计与样本量小工具（纯 Python，不依赖 numpy/scipy/R）。

设计用于临床研究方案：
  · 样本量：ANCOVA 校正基线的两样本比较（方案第 7 节公式）、两样本、配对
  · 效能/最小可检出差值(MDE)/95%CI 半宽，可复算方案表 7.3
  · 描述统计、组间比较（t / Mann-Whitney）、ANCOVA（OLS）、相关
  复杂模型（重复测量、多重插补、混合模型、生存分析）仍建议回 PC 用 R/SPSS 做。

用法示例：
  python scripts/stats_tools.py samplesize --design ancova --delta 1.0 --sd 2.0 --rho 0.5 --dropout 0.15
  python scripts/stats_tools.py table --n-list 70,80,90,100,114 --delta 1.0 --sd 2.0 --rho 0.5
  python scripts/stats_tools.py desc --csv 数据.csv --cols age,nrs
  python scripts/stats_tools.py compare --csv 数据.csv --var nrs --group arm
  python scripts/stats_tools.py ancova --csv 数据.csv --y nrs4 --group arm --covariates nrs_base,age
  python scripts/stats_tools.py corr --csv 数据.csv --x nrs_base --y nrs4
"""
import argparse
import csv
import math
import os
import sys

sys.path.insert(0, os.environ.get("DSH_TOOL_DIR") or os.path.dirname(os.path.abspath(globals().get("__file__", "run_tool.py"))))
from _util import fmt_p, md_table, resolve_path  # noqa: E402

ND = __import__("statistics").NormalDist()
_EPS = 1e-12


# ---------------------------------------------------------------- 分布函数
def betacf(a: float, b: float, x: float) -> float:
    """不完全 Beta 函数的连分式（Numerical Recipes）。"""
    MAXIT, EPS, FPMIN = 300, 3e-14, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < EPS:
            return h
    raise ArithmeticError("betacf 不收敛")


def betai(a: float, b: float, x: float) -> float:
    """正则化不完全 Beta 函数 I_x(a,b)。"""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    ln_bt = (math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
             + a * math.log(x) + b * math.log(1.0 - x))
    bt = math.exp(ln_bt)
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * betacf(a, b, x) / a
    return 1.0 - bt * betacf(b, a, 1.0 - x) / b


def t_cdf(t: float, df: float) -> float:
    if df <= 0:
        raise ValueError("df 必须 > 0")
    if t == 0:
        return 0.5
    x = df / (df + t * t)
    p = 0.5 * betai(df / 2.0, 0.5, x)
    return 1.0 - p if t > 0 else p


def t_p_two_sided(t: float, df: float) -> float:
    return 2.0 * (1.0 - t_cdf(abs(t), df))


def t_ppf(p: float, df: float) -> float:
    """t 分布分位数（二分法，够用且稳定）。"""
    if not 0 < p < 1:
        raise ValueError("p 必须在 (0,1)")
    lo, hi = -200.0, 200.0
    for _ in range(200):
        mid = (lo + hi) / 2
        if t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def gammainc_lower_reg(a: float, x: float) -> float:
    """正则化下不完全 Gamma 函数 P(a,x)（用于卡方/F 分布）。"""
    if x < 0 or a <= 0:
        return 0.0
    if x == 0:
        return 0.0
    if x < a + 1.0:
        ap, s, delta = a, 1.0 / a, 1.0 / a
        for _ in range(1000):
            ap += 1.0
            delta *= x / ap
            s += delta
            if abs(delta) < abs(s) * 3e-14:
                break
        return s * math.exp(-x + a * math.log(x) - math.lgamma(a))
    # 连分式算 Q(a,x) 再取补
    b = x + 1.0 - a
    c = 1e300
    d = 1.0 / b
    h = d
    for i in range(1, 1000):
        an = -i * (i - a)
        b += 2.0
        d = an * d + b
        if abs(d) < 1e-300:
            d = 1e-300
        c = b + an / c
        if abs(c) < 1e-300:
            c = 1e-300
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-14:
            break
    q = math.exp(-x + a * math.log(x) - math.lgamma(a)) * h
    return 1.0 - q


def chi2_cdf(x: float, df: float) -> float:
    return gammainc_lower_reg(df / 2.0, x / 2.0)


def chi2_p(x: float, df: float) -> float:
    return 1.0 - chi2_cdf(x, df)


# ---------------------------------------------------------------- 样本量/效能
DESIGNS = ("ancova", "two-sample", "paired")


def _check(design: str, delta: float, sd: float, rho: float) -> None:
    if design not in DESIGNS:
        raise ValueError(f"design 必须是 {DESIGNS}")
    if delta <= 0 or sd <= 0:
        raise ValueError("delta 和 sd 必须为正数")
    if design == "ancova" and not (-1 < rho < 1):
        raise ValueError("rho 必须在 (-1,1)")


def sd_effective(design: str, sd: float, rho: float) -> float:
    if design == "ancova":
        return sd * math.sqrt(max(0.0, 1.0 - rho * rho))
    return sd


def n_per_group(design: str, delta: float, sd: float, rho: float = 0.0,
                alpha: float = 0.05, power: float = 0.8, sides: int = 2,
                t_correct: bool = False) -> float:
    """返回每组“可评估例数”，可为小数（向上取整由调用方处理）。"""
    _check(design, delta, sd, rho)
    za = ND.inv_cdf(1.0 - alpha / sides)
    zb = ND.inv_cdf(power)
    if design == "paired":
        # 配对设计：sd 传的是“差值标准差”
        return ((za + zb) * sd / delta) ** 2
    se = sd_effective(design, sd, rho)
    n = 2.0 * ((za + zb) * se / delta) ** 2
    if not t_correct:
        return n
    for _ in range(100):  # t 分布校正（迭代到稳定）
        df = 2.0 * max(1.0, n) - 2.0
        n_new = 2.0 * ((t_ppf(1.0 - alpha / sides, df) + t_ppf(power, df)) * se / delta) ** 2
        if abs(n_new - n) < 1e-6:
            n = n_new
            break
        n = n_new
    return n


def power_for_n(design: str, n_eval_per_group: float, delta: float, sd: float,
                rho: float = 0.0, alpha: float = 0.05, sides: int = 2) -> float:
    """给定每组可评估例数，计算效能（正态近似，与方案文档口径一致）。"""
    _check(design, delta, sd, rho)
    za = ND.inv_cdf(1.0 - alpha / sides)
    if design == "paired":
        z = delta * math.sqrt(n_eval_per_group) / sd
    else:
        se = sd_effective(design, sd, rho)
        z = delta * math.sqrt(n_eval_per_group / 2.0) / se
    return ND.cdf(z - za)


def mde_for_n(design: str, n_eval_per_group: float, sd: float, rho: float = 0.0,
              alpha: float = 0.05, power: float = 0.8, sides: int = 2) -> float:
    """给定每组可评估例数，计算 80% 效能下的最小可检出差值。"""
    za = ND.inv_cdf(1.0 - alpha / sides)
    zb = ND.inv_cdf(power)
    if design == "paired":
        return (za + zb) * sd / math.sqrt(n_eval_per_group)
    return (za + zb) * sd_effective(design, sd, rho) * math.sqrt(2.0 / n_eval_per_group)


def ci_half_width(design: str, n_eval_per_group: float, sd: float, rho: float = 0.0,
                  alpha: float = 0.05) -> float:
    """95%CI 半宽（t 分位近似）。"""
    if design == "paired":
        df = n_eval_per_group - 1
        se = sd / math.sqrt(n_eval_per_group)
    else:
        df = 2 * n_eval_per_group - 2
        se = sd_effective(design, sd, rho) * math.sqrt(2.0 / n_eval_per_group)
    return t_ppf(1 - alpha / 2, max(1, df)) * se


# ---------------------------------------------------------------- 数据读取
def load_csv(path: str) -> list[dict]:
    target = resolve_path(path)
    if not target.is_file():
        raise SystemExit(f"[错误] 找不到 CSV：{target}")
    with open(target, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        raise SystemExit(f"[错误] CSV 为空：{target}")
    return rows


def _f(v):
    try:
        return float(str(v).strip())
    except (TypeError, ValueError):
        return None


def _col(rows, name, allow_text=False):
    vals = []
    for r in rows:
        raw = r.get(name)
        if allow_text:
            vals.append(str(raw).strip() if raw is not None else "")
        else:
            x = _f(raw)
            if x is None:
                raise SystemExit(f"[错误] 列 {name} 存在非数值：{raw!r}")
            vals.append(x)
    return vals


# ---------------------------------------------------------------- 子命令实现
def cmd_samplesize(args) -> int:
    n_raw = n_per_group(args.design, args.delta, args.sd, args.rho, args.alpha,
                        args.power, args.sides, args.t_correct)
    n_eval = math.ceil(n_raw)
    n_random = math.ceil(n_eval / (1 - args.dropout)) if args.dropout > 0 else n_eval
    print(f"设计：{args.design}；Δ={args.delta}，SD={args.sd}，ρ={args.rho}，"
          f"α={args.alpha}（{'双侧' if args.sides == 2 else '单侧'}），power={args.power}，脱落率={args.dropout:.0%}")
    print(f"每组可评估例数：{n_raw:.2f} → 取整 {n_eval}")
    print(f"每组随机例数：{n_random}；总随机例数 N = {2 * n_random}")
    print(f"（可评估总数 ≈ {2 * n_eval}）")
    return 0


def cmd_power(args) -> int:
    n = args.n_per_group
    if n is None:
        if args.n_total is None:
            print("需要 --n-per-group 或 --n-total", file=sys.stderr)
            return 2
        n = args.n_total * (1 - args.dropout) / 2
    p = power_for_n(args.design, n, args.delta, args.sd, args.rho, args.alpha, args.sides)
    mde = mde_for_n(args.design, n, args.sd, args.rho, args.alpha, 0.8, args.sides)
    hw = ci_half_width(args.design, n, args.sd, args.rho, args.alpha)
    print(f"每组可评估 n={n:.1f}；效能（Δ={args.delta}）= {p:.1%}")
    print(f"80% 效能可检出 Δ = {mde:.2f}；95%CI 半宽 ≈ {hw:.2f}")
    return 0


def cmd_table(args) -> int:
    ns = [int(x) for x in args.n_list.split(",") if x.strip()]
    d2 = args.delta2 if args.delta2 else 1.2
    rows = []
    for N in ns:
        evaluable = round(N * (1 - args.dropout))
        n = evaluable / 2.0

        def pw(rho, sd):
            return power_for_n("ancova", n, args.delta, sd, rho, args.alpha)

        rows.append([
            N, evaluable, f"{pw(0.5, 2.0):.0%}", f"{pw(0.3, 2.0):.0%}",
            f"{pw(0.5, 2.5):.0%}", f"{power_for_n('ancova', n, d2, 2.0, 0.5, args.alpha):.0%}",
            f"{mde_for_n('ancova', n, 2.0, 0.5, args.alpha):.2f}",
            f"{ci_half_width('ancova', n, 2.0, 0.5, args.alpha):.2f}",
        ])
    print(f"# 效能与精度随 N 的变化（正态近似，脱落 {args.dropout:.0%}，α={args.alpha} 双侧）\n")
    print(md_table(["随机例数 N", "可评估例数",
                    "效能(ρ=0.5,SD=2.0)", "效能(ρ=0.3)",
                    "效能(SD=2.5)", f"效能(Δ={d2})",
                    "80%效能可检出Δ", "95%CI半宽"], rows))
    print(f"\n注：效能为 Δ={args.delta}、SD=2.0、ρ=0.5（除注明列外）时的近似值，与方案表 7.3 同口径；"
          "CI 半宽按 t 分位计算，比方案表中的 z 近似略宽（约 0.01），属正常。")
    return 0


def cmd_desc(args) -> int:
    rows = load_csv(args.csv)
    cols = [c.strip() for c in args.cols.split(",") if c.strip()]
    groups = None
    if args.group:
        groups = sorted({r.get(args.group, "") for r in rows})
    table_rows = []
    for col in cols:
        for g in groups or [None]:
            subset = rows if g is None else [r for r in rows if r.get(args.group) == g]
            vals = [v for v in (_f(r.get(col)) for r in subset) if v is not None]
            if not vals:
                continue
            n = len(vals)
            mean = sum(vals) / n
            sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (n - 1)) if n > 1 else 0.0
            s = sorted(vals)
            med = s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2
            q1 = s[int(0.25 * (n - 1))]
            q3 = s[int(0.75 * (n - 1))]
            table_rows.append([col, g or "总体", n, f"{mean:.2f}", f"{sd:.2f}",
                               f"{med:.2f}", f"{q1:.2f}–{q3:.2f}", f"{min(vals):.2f}–{max(vals):.2f}"])
    print(md_table(["变量", "组", "n", "均值", "SD", "中位数", "Q1–Q3", "范围"], table_rows))
    return 0


def cmd_compare(args) -> int:
    rows = load_csv(args.csv)
    levels = sorted({str(r.get(args.group, "")).strip() for r in rows})
    if len(levels) != 2:
        print(f"[错误] --group 目前只支持两组，实际为 {levels}", file=sys.stderr)
        return 2
    a = [v for r in rows if str(r.get(args.group, "")).strip() == levels[0]
         for v in [_f(r.get(args.var))] if v is not None]
    b = [v for r in rows if str(r.get(args.group, "")).strip() == levels[1]
         for v in [_f(r.get(args.var))] if v is not None]
    if len(a) < 2 or len(b) < 2:
        print("[错误] 每组至少需要 2 个观测", file=sys.stderr)
        return 2

    def mean(x):
        return sum(x) / len(x)

    def var(x):
        m = mean(x)
        return sum((v - m) ** 2 for v in x) / (len(x) - 1)

    diff = mean(b) - mean(a)
    se = math.sqrt(var(a) / len(a) + var(b) / len(b))
    df = (var(a) / len(a) + var(b) / len(b)) ** 2 / (
        (var(a) / len(a)) ** 2 / (len(a) - 1) + (var(b) / len(b)) ** 2 / (len(b) - 1))
    t = diff / se if se > 0 else 0.0
    p = t_p_two_sided(t, df) if se > 0 else 1.0
    tc = t_ppf(0.975, df)
    # Mann-Whitney U（正态近似 + 结校正）
    allv = [(v, 0) for v in a] + [(v, 1) for v in b]
    allv.sort()
    ranks = {}
    i = 0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        avg = (i + j) / 2 + 1
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    r1 = sum(ranks[k] for k, (v, g) in enumerate(allv) if g == 0)
    u1 = r1 - len(a) * (len(a) + 1) / 2
    u = min(u1, len(a) * len(b) - u1)
    mu = len(a) * len(b) / 2
    # 结校正
    tie = 0
    i = 0
    while i < len(allv):
        j = i
        while j + 1 < len(allv) and allv[j + 1][0] == allv[i][0]:
            j += 1
        tie += (j - i + 1) ** 3 - (j - i + 1)
        i = j + 1
    n = len(allv)
    sigma = math.sqrt(len(a) * len(b) / 12 * ((n + 1) - tie / (n * (n - 1))))
    z = (u - mu) / sigma if sigma > 0 else 0.0
    p_mw = 2 * (1 - ND.cdf(abs(z))) if sigma > 0 else 1.0
    print(f"# 组间比较：{args.var} by {args.group}\n")
    print(md_table(["组", "n", "均值", "SD"], [
        [levels[0], len(a), f"{mean(a):.3f}", f"{math.sqrt(var(a)):.3f}"],
        [levels[1], len(b), f"{mean(b):.3f}", f"{math.sqrt(var(b)):.3f}"]]))
    print(f"\n**Welch t 检验**：均数差（{levels[1]} − {levels[0]}）= {diff:.3f}，"
          f"95%CI {diff - tc * se:.3f} ~ {diff + tc * se:.3f}，t({df:.1f}) = {t:.3f}，p = {fmt_p(p)}")
    print(f"**Mann-Whitney U**：U = {u:.1f}，z = {z:.3f}，p = {fmt_p(p_mw)}")
    return 0


def _mat_inv(mat: list[list[float]]) -> list[list[float]]:
    n = len(mat)
    aug = [row[:] + [1.0 if i == j else 0.0 for j in range(n)] for i, row in enumerate(mat)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(aug[r][col]))
        if abs(aug[pivot][col]) < _EPS:
            raise ArithmeticError("设计矩阵奇异（存在共线/常量列）")
        aug[col], aug[pivot] = aug[pivot], aug[col]
        pv = aug[col][col]
        aug[col] = [x / pv for x in aug[col]]
        for r in range(n):
            if r != col and aug[r][col] != 0:
                factor = aug[r][col]
                aug[r] = [x - factor * y for x, y in zip(aug[r], aug[col])]
    return [row[n:] for row in aug]


def cmd_ancova(args) -> int:
    rows = load_csv(args.csv)
    y = _col(rows, args.y)
    levels = sorted({str(r.get(args.group, "")).strip() for r in rows})
    if len(levels) < 2:
        print("[错误] 分组列至少要有两个水平", file=sys.stderr)
        return 2
    covs = [c.strip() for c in (args.covariates or "").split(",") if c.strip()]
    cov_data = [_col(rows, c) for c in covs]
    X, names = [], ["(截距)"]
    for i in range(len(rows)):
        row = [1.0]
        for j, lev in enumerate(levels[1:], 1):
            row.append(1.0 if str(rows[i].get(args.group, "")).strip() == lev else 0.0)
            if i == 0:
                names.append(f"组别={lev}（对照={levels[0]}）")
        for c, cd in zip(covs, cov_data):
            row.append(cd[i])
        X.append(row)
    names += covs
    n, p = len(X), len(X[0])
    if n <= p + 1:
        print(f"[错误] 样本量不足以拟合 {p} 个参数（n={n}）", file=sys.stderr)
        return 2
    XtX = [[sum(X[i][a] * X[i][b] for i in range(n)) for b in range(p)] for a in range(p)]
    Xty = [sum(X[i][a] * y[i] for i in range(n)) for a in range(p)]
    inv = _mat_inv(XtX)
    beta = [sum(inv[a][b] * Xty[b] for b in range(p)) for a in range(p)]
    resid = [y[i] - sum(X[i][a] * beta[a] for a in range(p)) for i in range(n)]
    rss = sum(r * r for r in resid)
    df = n - p
    sigma2 = rss / df
    ybar = sum(y) / n
    tss = sum((v - ybar) ** 2 for v in y)
    r2 = 1 - rss / tss if tss > 0 else float("nan")
    tc = t_ppf(0.975, df)
    print(f"# ANCOVA：{args.y} ~ {' + '.join(names[1:])}")
    print(f"n = {n}，R² = {r2:.3f}，残差 SD = {math.sqrt(sigma2):.3f}\n")
    table_rows = []
    for a in range(p):
        se = math.sqrt(sigma2 * inv[a][a])
        t = beta[a] / se if se > 0 else 0.0
        pval = t_p_two_sided(t, df)
        table_rows.append([names[a], f"{beta[a]:.3f}", f"{se:.3f}", f"{t:.3f}", fmt_p(pval),
                           f"{beta[a] - tc * se:.3f} ~ {beta[a] + tc * se:.3f}"])
    print(md_table(["项", "系数", "SE", "t", "p", "95%CI"], table_rows))
    print("\n提示：组别系数 = 校正协变量后的组间均数差（后一水平 − 对照水平）。")
    return 0


def cmd_corr(args) -> int:
    rows = load_csv(args.csv)
    xs = _col(rows, args.x)
    ys = _col(rows, args.y)
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    r = sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else 0.0
    t = r * math.sqrt((n - 2) / (1 - r * r)) if abs(r) < 1 else float("inf")
    p = t_p_two_sided(t, n - 2) if abs(r) < 1 else 0.0
    # Fisher z 的 95%CI
    if abs(r) < 1:
        z = 0.5 * math.log((1 + r) / (1 - r))
        se = 1 / math.sqrt(n - 3) if n > 3 else float("nan")
        lo, hi = math.tanh(z - 1.96 * se), math.tanh(z + 1.96 * se)
        ci = f"{lo:.3f} ~ {hi:.3f}"
    else:
        ci = "NA"
    # Spearman
    def ranks(v):
        order = sorted(range(n), key=lambda i: v[i])
        rk = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                rk[order[k]] = avg
            i = j + 1
        return rk
    rx, ry = ranks(xs), ranks(ys)
    mrx, mry = sum(rx) / n, sum(ry) / n
    sxy2 = sum((a - mrx) * (b - mry) for a, b in zip(rx, ry))
    sxx2 = sum((a - mrx) ** 2 for a in rx)
    syy2 = sum((b - mry) ** 2 for b in ry)
    rho = sxy2 / math.sqrt(sxx2 * syy2) if sxx2 > 0 and syy2 > 0 else 0.0
    print(f"# 相关分析：{args.x} vs {args.y}（n={n}）\n")
    print(f"Pearson r = {r:.3f}，95%CI {ci}，p = {fmt_p(p)}")
    print(f"Spearman ρ = {rho:.3f}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="统计与样本量小工具（纯 Python）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_design_args(p):
        p.add_argument("--design", default="ancova", choices=DESIGNS)
        p.add_argument("--delta", type=float, default=1.0, help="目标差值 Δ")
        p.add_argument("--sd", type=float, default=2.0, help="标准差 SD")
        p.add_argument("--rho", type=float, default=0.5, help="基线-终点相关系数 ρ（ANCOVA 用）")
        p.add_argument("--alpha", type=float, default=0.05)
        p.add_argument("--sides", type=int, default=2, choices=[1, 2])
        p.add_argument("--dropout", type=float, default=0.15)

    s = sub.add_parser("samplesize", help="计算样本量")
    add_design_args(s)
    s.add_argument("--power", type=float, default=0.8)
    s.add_argument("--t-correct", action="store_true", help="用 t 分布迭代校正（更保守）")
    s.set_defaults(func=cmd_samplesize)

    p = sub.add_parser("power", help="计算效能/MDE/CI 半宽")
    add_design_args(p)
    p.add_argument("--n-per-group", type=float)
    p.add_argument("--n-total", type=float)
    p.set_defaults(func=cmd_power)

    t = sub.add_parser("table", help="复算方案表 7.3 的效能表")
    t.add_argument("--n-list", default="70,80,90,100,114")
    t.add_argument("--delta", type=float, default=1.0)
    t.add_argument("--delta2", type=float, default=None, help="额外一列的 Δ（默认 1.2）")
    t.add_argument("--alpha", type=float, default=0.05)
    t.add_argument("--dropout", type=float, default=0.15)
    t.set_defaults(func=cmd_table)

    d = sub.add_parser("desc", help="描述统计")
    d.add_argument("--csv", required=True)
    d.add_argument("--cols", required=True)
    d.add_argument("--group")
    d.set_defaults(func=cmd_desc)

    c = sub.add_parser("compare", help="两组比较（Welch t / Mann-Whitney）")
    c.add_argument("--csv", required=True)
    c.add_argument("--var", required=True)
    c.add_argument("--group", required=True)
    c.set_defaults(func=cmd_compare)

    a = sub.add_parser("ancova", help="ANCOVA（OLS 校正协变量）")
    a.add_argument("--csv", required=True)
    a.add_argument("--y", required=True)
    a.add_argument("--group", required=True)
    a.add_argument("--covariates", default="")
    a.set_defaults(func=cmd_ancova)

    r = sub.add_parser("corr", help="Pearson/Spearman 相关")
    r.add_argument("--csv", required=True)
    r.add_argument("--x", required=True)
    r.add_argument("--y", required=True)
    r.set_defaults(func=cmd_corr)

    args = ap.parse_args(argv)
    try:
        return args.func(args)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"[错误] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
