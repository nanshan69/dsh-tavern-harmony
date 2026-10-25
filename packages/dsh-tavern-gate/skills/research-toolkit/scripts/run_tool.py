"""research-toolkit 运行器：用插件的 python 工具（file 模式）跑同目录的工具脚本。

用法（Agent 侧）：
    python(file="/data/storage/el2/base/haps/entry/files/dsh/home/skills/research-toolkit/scripts/run_tool.py",
           args=["md2docx", "输入.md", "--out", "输出.docx"])

不带参数运行会列出全部可用工具。输出路径建议用绝对路径（工具默认以工作目录解析相对路径）。
"""
import os
import runpy
import sys

_argv = list(sys.argv[1:])
_self = ""
if _argv and _argv[0].endswith("run_tool.py"):
    _self = _argv.pop(0)
if not _self:
    _self = globals().get("__file__", "")
TOOLS = os.environ.get("DSH_TOOL_DIR") or (os.path.dirname(os.path.abspath(_self)) if _self else ".")
os.environ["DSH_TOOL_DIR"] = TOOLS
sys.path.insert(0, TOOLS)

if not _argv:
    tools = sorted(f[:-3] for f in os.listdir(TOOLS)
                   if f.endswith(".py") and not f.startswith("_") and f != "run_tool.py")
    print("用法: run_tool.py <工具名> [参数...]")
    print("可用工具: " + ", ".join(tools))
    raise SystemExit(2)

tool, rest = _argv[0], _argv[1:]
script = os.path.join(TOOLS, tool + ".py")
if not os.path.exists(script):
    print("没有这个工具: " + tool)
    raise SystemExit(2)
sys.argv = [tool + ".py"] + rest
runpy.run_path(script, run_name="__main__")
