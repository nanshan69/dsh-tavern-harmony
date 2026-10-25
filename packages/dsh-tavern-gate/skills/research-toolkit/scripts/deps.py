#!/usr/bin/env python3
"""依赖检查与安装（openpyxl、pypdf 均为纯 Python 包，本机内嵌 CPython 可用）。

装到内嵌 CPython 的 site-packages（/data/storage/el2/base/haps/entry/files/toolchain/...）。
注意：这是应用数据目录，卸载/重装应用后需重新执行一次 install。

用法：
  python scripts/deps.py check      # 查看依赖是否可用
  python scripts/deps.py install    # 联网安装（PyPI；失败会自动换清华镜像再试）
"""
import argparse
import importlib
import sys

PACKAGES = [("openpyxl", "读写 .xlsx"), ("pypdf", "PDF 文本提取")]
MIRRORS = [
    [],  # 默认 PyPI
    ["-i", "https://pypi.tuna.tsinghua.edu.cn/simple",
     "--trusted-host", "pypi.tuna.tsinghua.edu.cn",
     "--trusted-host", "files.pythonhosted.org", "--trusted-host", "pypi.org"],
]


def check(verbose=True) -> bool:
    ok = True
    for name, desc in PACKAGES:
        try:
            mod = importlib.import_module(name)
            ver = getattr(mod, "__version__", "?")
            if verbose:
                print(f"[可用] {name:10s} {ver:10s} {desc}")
        except ImportError:
            ok = False
            if verbose:
                print(f"[缺失] {name:10s} {'':10s} {desc}  → 运行: python scripts/deps.py install")
    return ok


def install() -> int:
    from pip._internal.cli.main import main as pipmain
    base = ["install", "--disable-pip-version-check", "--no-cache-dir",
            "--trusted-host", "pypi.org", "--trusted-host", "files.pythonhosted.org",
            *[p for name, _ in PACKAGES for p in (name,)]]
    for extra in MIRRORS:
        rc = pipmain(base + extra)
        if rc == 0:
            break
    print()
    if check():
        print("[完成] 依赖已就绪。")
        return 0
    print("[失败] 依赖仍不可用：请检查网络，或把报错贴给 Agent。")
    return 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="科研工具依赖检查/安装")
    ap.add_argument("cmd", choices=["check", "install"])
    args = ap.parse_args(argv)
    return 0 if (check() if args.cmd == "check" else install() == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
