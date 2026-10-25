"""DSHM 科研工具包的公共小工具（HTTP、CSV、路径、Markdown 表格）。

只用标准库；所有脚本都可独立运行。
相对路径统一按“工作目录”解析（本文件所在目录的上一级 = 工作目录），
这样无论从哪个 cwd 调用都不会把文件写到奇怪的位置。
"""
import csv
import json
import os
import ssl
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("DSH_RESEARCH_ROOT") or ".").resolve()  # 工作目录（可用 DSH_RESEARCH_ROOT 覆盖）


def resolve_path(value: str | os.PathLike | None, default: str | None = None) -> Path:
    """把相对路径按工作目录解析；None 时用 default。"""
    if value is None:
        if default is None:
            raise ValueError("path is required")
        value = default
    p = Path(value).expanduser()
    if not p.is_absolute():
        p = ROOT / p
    return p


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def ssl_context(verify: bool | None = None) -> ssl.SSLContext | None:
    """默认不校验证书（鸿蒙端侧自签证书链会导致 CERTIFICATE_VERIFY_FAILED）。

    需要严格校验时设置环境变量 DSHM_HTTP_VERIFY_SSL=1。
    """
    if verify is None:
        verify = os.environ.get("DSHM_HTTP_VERIFY_SSL", "0") == "1"
    if verify:
        return None
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def http_get(url: str, params: dict | None = None, timeout: int = 40, retries: int = 3,
             headers: dict | None = None, binary: bool = False):
    """GET 一个 URL，返回 str（或 bytes）；失败自动重试 3 次。"""
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    hdrs = {"User-Agent": "dshm-research-tool/1.0 (+HarmonyOS; non-commercial academic use)"}
    if headers:
        hdrs.update(headers)
    last: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
                data = resp.read()
            return data if binary else data.decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001 - 网络错误统一重试
            last = exc
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"请求失败：{url}\n{last}")


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, rows: list[dict], fields: list[str] | None = None) -> None:
    ensure_parent(path)
    if not rows and not fields:
        path.write_text("", encoding="utf-8")
        return
    fields = fields or list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def write_json(path: Path, obj) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def md_table(headers: list[str], rows: list[list]) -> str:
    def cell(v) -> str:
        return str(v).replace("|", "\\|").replace("\n", " ").strip()

    out = ["| " + " | ".join(cell(h) for h in headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for row in rows:
        out.append("| " + " | ".join(cell(v) for v in row) + " |")
    return "\n".join(out)


def fmt_p(p: float) -> str:
    """p 值格式化：保留 3 位有效数字，<0.001 时写 <0.001。"""
    if p is None:
        return "NA"
    if p < 0.001:
        return "<0.001"
    if p < 0.01:
        return f"{p:.4f}"
    return f"{p:.3f}"
