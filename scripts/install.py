#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DSHM × DSH Tavern（鸿蒙移植版）安装器。

用法（默认干跑，不写任何文件）：

    python3 scripts/install.py                 # 打印计划
    python3 scripts/install.py --apply         # 真正安装
    python3 scripts/install.py --apply --no-sidebar
    python3 scripts/install.py --apply --no-core-patch

它会做这些事（全部幂等，重复执行安全）：

1. 把 packages/ 下的 5 个包复制到 <profile>/node_modules/
2. 给 dsh-tavern-remote 补上 zod（从 dsh-tavern-host 的依赖里拿）
3. 渲染 dsh-tavern-presets/cordis.patch.yml（把 {{CORE_DIR}} / {{PROFILE_DIR}}
   换成设备上的真实路径）
4. 在 profile 的 dsh.profile.bundles 里登记 6 个 bundle 行（顺序固定）
5. 在 home patch 里补一条 permission 默认值（已存在则不动）
6. 给核心 dsh-llm-deepseek 打「酒馆会话不回放历史思维链」补丁（可用
   --no-core-patch 跳过）

安装完必须**完全退出 DSHM 再打开**（host 只在启动时读 profile 与 bundle）。
重启后酒馆是【关闭】状态，点左下角「酒馆：关」才会加载。
"""
import argparse
import json
import os
import re
import shutil
import sys
import time

PACKAGES = [
    "dsh-tavern-gate",
    "dsh-tavern-host",
    "dsh-tavern-plugin",
    "dsh-tavern-remote",
    "dsh-tavern-presets",
]
BUNDLE_IDS = [
    "dsh-tavern-gate",
    "dsh-better-sidebar",
    "dsh-dream-skin",
    "dsh-tavern-plugin",
    "dsh-tavern-remote",
    "dsh-tavern-presets",
]
OPTIONAL_BUNDLES = {"dsh-better-sidebar", "dsh-dream-skin"}
RECEIPT_NAME = "tavern-harmony-install.json"
IGNORE_DIRS = {".git", "__pycache__", ".virtfs_metadata"}
IGNORE_FILES = (".bak", ".pyc")
SKIP_COPY_DIRS = {"node_modules"}


class Report:
    def __init__(self):
        self.items = []

    def add(self, level, text):
        self.items.append((level, text))
        print(("  " if level == "info" else "") + "[%s] %s" % (level, text), flush=True)

    def counts(self):
        out = {}
        for level, _ in self.items:
            out[level] = out.get(level, 0) + 1
        return out


def project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_args(argv):
    parser = argparse.ArgumentParser(description="安装 DSHM × DSH Tavern（鸿蒙移植版）")
    parser.add_argument("--apply", action="store_true", help="真正写入（默认只打印计划）")
    parser.add_argument("--home", default=os.environ.get("DSH_HOME", ""), help="DSH 数据目录（默认从环境或设备常量推导）")
    parser.add_argument("--profile", default="ondevice", help="profile 名（默认 ondevice）")
    parser.add_argument("--no-sidebar", action="store_true", help="不把 dsh-better-sidebar / dsh-dream-skin 加进 bundles")
    parser.add_argument("--no-core-patch", action="store_true", help="跳过核心 dsh-llm-deepseek 补丁")
    parser.add_argument("--force", action="store_true", help="即使前置检查失败也继续（不推荐）")
    return parser.parse_args(argv)


def resolve_paths(args):
    home = args.home or "/data/storage/el2/base/haps/entry/files/dsh/home"
    home = os.path.abspath(home)
    profile = os.path.join(home, "profiles", args.profile)
    return {
        "root": project_root(),
        "home": home,
        "profile": profile,
        "node_modules": os.path.join(profile, "node_modules"),
        "cores": os.environ.get("DSH_CORES") or os.path.join(os.path.dirname(home), "cores"),
    }


# ── 复制 ────────────────────────────────────────────────────────────────────

def copy_package(src, dst, report):
    if not os.path.isdir(src):
        report.add("fail", "缺包目录：" + src)
        return 0
    count = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and d not in SKIP_COPY_DIRS]
        rel = os.path.relpath(root, src)
        target_root = dst if rel == "." else os.path.join(dst, rel)
        os.makedirs(target_root, exist_ok=True)
        for name in files:
            if any(name.endswith(suffix) for suffix in IGNORE_FILES):
                continue
            shutil.copyfile(os.path.join(root, name), os.path.join(target_root, name))
            count += 1
    return count


def ensure_remote_zod(paths, report):
    remote_zod = os.path.join(paths["node_modules"], "dsh-tavern-remote", "node_modules", "zod")
    if os.path.isdir(remote_zod):
        report.add("ok", "dsh-tavern-remote 自带 zod")
        return
    source = os.path.join(paths["node_modules"], "dsh-tavern-host", "node_modules", "zod")
    if not os.path.isdir(source):
        source = os.path.join(paths["node_modules"], "zod")
    if not os.path.isdir(source):
        report.add("warn", "找不到 zod：dsh-tavern-remote 可能加载失败（先装 dsh-tavern-host 的依赖）")
        return
    shutil.copytree(source, remote_zod)
    report.add("ok", "已从 %s 复制 zod" % os.path.relpath(source, paths["node_modules"]))


# ── preset 渲染 ─────────────────────────────────────────────────────────────

def render_presets(paths, report):
    package = os.path.join(paths["node_modules"], "dsh-tavern-presets")
    template = os.path.join(package, "cordis.patch.yml.tmpl")
    target = os.path.join(package, "cordis.patch.yml")
    if not os.path.isfile(template):
        report.add("fail", "缺 preset 模板：" + template)
        return
    text = open(template, encoding="utf-8").read()
    text = text.replace("{{CORE_DIR}}", paths["cores"]).replace("{{PROFILE_DIR}}", paths["profile"])
    if "{{" in text:
        report.add("fail", "模板里还有没替换的占位符")
        return
    open(target, "w", encoding="utf-8").write(text)
    missing = [p for p in sorted(set(re.findall(r"name: (/[^\s']+)", text))) if not os.path.isfile(p)]
    if missing:
        report.add("warn", "preset 引用了 %d 个不存在的文件（第一条：%s）" % (len(missing), missing[0]))
    else:
        report.add("ok", "preset 已渲染，引用的路径都存在")


# ── profile bundles ────────────────────────────────────────────────────────

def read_bundles(profile_package):
    data = json.load(open(profile_package, encoding="utf-8"))
    bundles = data.get("dsh", {}).get("profile", {}).get("bundles", [])
    if not isinstance(bundles, list):
        raise SystemExit("profile package.json 的 dsh.profile.bundles 不是数组")
    return data, bundles


def plan_bundles(bundles, add_sidebar, available):
    """available: 已经装进 node_modules 的可选 bundle（没装就不登记，否则会 pending）。"""
    wanted = []
    for name in BUNDLE_IDS:
        if name in OPTIONAL_BUNDLES and not (add_sidebar and name in available):
            continue
        wanted.append(name)
    existing = [b for b in bundles if b not in wanted]
    # 插在最后一个 @deepseek-ai/* 之后；没有就放最前面。
    index = 0
    for position, name in enumerate(existing):
        if str(name).startswith("@deepseek-ai/"):
            index = position + 1
    result = existing[:index] + wanted + existing[index:]
    return result, wanted


def write_bundles(profile_package, data, bundles, backup_path):
    shutil.copyfile(profile_package, backup_path)
    data.setdefault("dsh", {}).setdefault("profile", {})["bundles"] = bundles
    with open(profile_package, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


# ── home patch ─────────────────────────────────────────────────────────────

HOME_PATCH_BLOCK = (
    "- id: permission\n"
    "  config:\n"
    "    defaultPreset: workspace-write\n"
)


def ensure_home_patch(paths, report, apply):
    path = os.path.join(paths["home"], "cordis.patch.yml")
    text = open(path, encoding="utf-8").read() if os.path.isfile(path) else ""
    if re.search(r"^- id: permission\s*$", text, re.M):
        report.add("ok", "home patch 已有 permission 行")
        return None
    new_text = text
    if new_text and not new_text.endswith("\n"):
        new_text += "\n"
    new_text += HOME_PATCH_BLOCK
    if apply:
        backup = None
        if os.path.isfile(path):
            backup = path + ".bak-tavern-" + time.strftime("%Y%m%d-%H%M%S")
            shutil.copyfile(path, backup)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8").write(new_text)
        report.add("ok", "home patch 已补 permission.defaultPreset=workspace-write" + ("（备份 %s）" % backup if backup else ""))
    else:
        report.add("plan", "会向 home patch 追加 permission.defaultPreset=workspace-write")
    return new_text


# ── 核心补丁 ────────────────────────────────────────────────────────────────

MARKER = "酒馆会话优化"


def find_core_llm(paths):
    if not os.path.isdir(paths["cores"]):
        return None
    best = None
    best_time = -1
    for name in sorted(os.listdir(paths["cores"])):
        candidate = os.path.join(paths["cores"], name, "node_modules", "@deepseek-ai",
                                 "dsh-llm-deepseek", "lib", "index.js")
        if not os.path.isfile(candidate):
            continue
        stamp = os.path.getmtime(candidate)
        if stamp > best_time:
            best_time, best = stamp, candidate
    return best


def apply_unified_diff(path, diff_text):
    """极简 unified diff 应用器（只支持本仓库的补丁：纯插入/替换，无删除文件）。"""
    lines = open(path, encoding="utf-8").read().splitlines(True)
    result = []
    cursor = 0
    hunks = re.split(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@.*$", diff_text, flags=re.M)
    # re.split 会把 header 切碎：hunks[0] 是前言，之后每 5 个一组
    index = 1
    while index + 4 < len(hunks):
        start = int(hunks[index]) - 1
        body = hunks[index + 4]
        index += 5
        body_lines = body.splitlines(True)
        old = []
        new = []
        for line in body_lines:
            if line.startswith(" "):
                old.append(line[1:])
                new.append(line[1:])
            elif line.startswith("-"):
                old.append(line[1:])
            elif line.startswith("+"):
                new.append(line[1:])
            elif line.startswith("\\"):
                continue
        # 把段落拼回（body 里以文件头开头的行不算内容）
        if cursor > start:
            return None, "补丁区段重叠"
        result.extend(lines[cursor:start])
        window = lines[start:start + len(old)]
        if window != old:
            return None, "第 %d 行的上下文不匹配（可能核心版本不同）" % (start + 1)
        result.extend(new)
        cursor = start + len(old)
    result.extend(lines[cursor:])
    return "".join(result), None


def maybe_patch_core(paths, report, apply):
    target = find_core_llm(paths)
    if target is None:
        report.add("warn", "找不到核心 dsh-llm-deepseek，跳过核心补丁（不影响酒馆功能，只是上下文回放更省）")
        return
    text = open(target, encoding="utf-8").read()
    if MARKER in text:
        report.add("ok", "核心补丁已在（%s）" % os.path.relpath(target, paths["cores"]))
        return
    patch_path = os.path.join(paths["root"], "patches", "core",
                              "0001-deepseek-reasoning-replay-strip.patch")
    if not os.path.isfile(patch_path):
        report.add("warn", "缺核心补丁文件：" + patch_path)
        return
    if not apply:
        report.add("plan", "会给核心 dsh-llm-deepseek/lib/index.js 打补丁")
        return
    patched, error = apply_unified_diff(target, open(patch_path, encoding="utf-8").read())
    if error is not None:
        report.add("warn", "核心补丁没打上：%s（可手动 git apply）" % error)
        return
    backup = target + ".bak-tavern-" + time.strftime("%Y%m%d-%H%M%S")
    shutil.copyfile(target, backup)
    open(target, "w", encoding="utf-8").write(patched)
    report.add("ok", "核心补丁已打上（备份 %s）" % os.path.basename(backup))


# ── 主流程 ─────────────────────────────────────────────────────────────────

def main(argv):
    args = parse_args(argv)
    paths = resolve_paths(args)
    report = Report()
    apply = args.apply

    print("== DSHM × DSH Tavern（鸿蒙移植版）安装器 ==")
    print("仓库　：%s" % paths["root"])
    print("home　：%s" % paths["home"])
    print("profile：%s" % paths["profile"])
    print("cores　：%s" % paths["cores"])
    print("模式　：%s\n" % ("APPLY（会写文件）" if apply else "DRY-RUN（只打印计划）"))

    profile_package = os.path.join(paths["profile"], "package.json")
    if not os.path.isfile(profile_package):
        report.add("fail", "找不到 profile package.json：%s" % profile_package)
        print("\n没有 --apply 时也需要一个已存在 DSHM 安装。")
        return 2

    data, bundles = read_bundles(profile_package)
    report.add("ok", "profile 可读，当前 %d 个 bundle" % len(bundles))

    # 前置检查
    for name in PACKAGES:
        source = os.path.join(paths["root"], "packages", name)
        if not os.path.isdir(source):
            report.add("fail", "缺包目录：" + source)
    host_jsdom = os.path.join(paths["node_modules"], "dsh-tavern-host", "node_modules", "jsdom")
    profile_jsdom = os.path.join(paths["node_modules"], "jsdom")
    if os.path.isdir(host_jsdom) or os.path.isdir(profile_jsdom):
        report.add("ok", "酒馆依赖（jsdom）已就位")
    else:
        report.add("warn", "没找到 jsdom：酒馆 host 的依赖还没装。见 docs/安装.md「依赖」一节。")
    if not args.no_sidebar:
        for name in sorted(OPTIONAL_BUNDLES):
            if not os.path.isdir(os.path.join(paths["node_modules"], name)):
                report.add("warn", "%s 不在 node_modules 里；酒馆侧栏/主题可能不完整（可用 --no-sidebar 跳过）" % name)

    if report.counts().get("fail"):
        print("\n前置检查有失败项，已中止。")
        return 2

    # bundles 计划
    available = {name for name in OPTIONAL_BUNDLES
                 if os.path.isdir(os.path.join(paths["node_modules"], name))}
    next_bundles, wanted = plan_bundles(bundles, not args.no_sidebar, available)
    if next_bundles == bundles:
        report.add("ok", "bundles 已经是最新的")
    else:
        report.add("plan", "bundles：%s" % " → ".join(wanted))

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup_dir = os.path.join(paths["home"], "_tavern-harmony-backup", stamp)

    if apply:
        os.makedirs(backup_dir, exist_ok=True)
        print("\n-- 开始安装（备份到 %s）--" % backup_dir)
        copied = 0
        for name in PACKAGES:
            source = os.path.join(paths["root"], "packages", name)
            target = os.path.join(paths["node_modules"], name)
            count = copy_package(source, target, report)
            copied += count
            report.add("ok", "%s → %d 个文件" % (name, count))
        print("  （共写入 %d 个文件）" % copied)
        ensure_remote_zod(paths, report)
        render_presets(paths, report)
        if next_bundles != bundles:
            write_bundles(profile_package, data, next_bundles,
                          os.path.join(backup_dir, "profile-package.json"))
            report.add("ok", "profile package.json 已更新（备份在 backup 目录）")
        ensure_home_patch(paths, report, apply)
        if not args.no_core_patch:
            maybe_patch_core(paths, report, apply)
        receipt = {
            "installedAt": stamp,
            "version": "1.0.0",
            "home": paths["home"],
            "profile": paths["profile"],
            "bundles": wanted,
            "backup": backup_dir,
            "corePatch": not args.no_core_patch,
        }
        with open(os.path.join(paths["home"], RECEIPT_NAME), "w", encoding="utf-8") as handle:
            json.dump(receipt, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    else:
        print("\n-- 计划 --")
        for name in PACKAGES:
            report.add("plan", "复制 %s → %s" % (name, os.path.join("node_modules", name)))
        report.add("plan", "渲染 dsh-tavern-presets/cordis.patch.yml")
        if next_bundles != bundles:
            report.add("plan", "更新 profile package.json 的 dsh.profile.bundles")
        else:
            report.add("ok", "profile package.json 无需改动")
        ensure_home_patch(paths, report, apply)
        if not args.no_core_patch:
            maybe_patch_core(paths, report, apply)

    counts = report.counts()
    print("\n== 结果：ok %d / warn %d / fail %d ==" % (
        counts.get("ok", 0), counts.get("warn", 0), counts.get("fail", 0)))
    if apply:
        print("""
下一步：
1. 完全退出 DSHM（从多任务里划掉），再打开；
2. 左下角会出现「酒馆：关」，点一下加载酒馆（本次会话内有效）；
3. 重启应用 → 自动回到「关」，不会有任何酒馆代码在跑；
4. 体检：python3 scripts/doctor.py
""")
    else:
        print("\n这是干跑。确认无误后加 --apply 真正安装。")
    return 1 if counts.get("fail") else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
