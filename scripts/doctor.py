#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""体检：确认 DSHM × DSH Tavern 的每一块都在位。

    python3 scripts/doctor.py
    python3 scripts/doctor.py --home /path/to/dsh/home

只读，不修改任何文件。
"""
import argparse
import json
import os
import re
import sys
import urllib.request

PACKAGES = ["dsh-tavern-gate", "dsh-tavern-host", "dsh-tavern-plugin",
            "dsh-tavern-remote", "dsh-tavern-presets"]
BUNDLES = ["dsh-tavern-gate", "dsh-tavern-plugin", "dsh-tavern-remote", "dsh-tavern-presets"]
HOST_DEPS = ["jsdom", "marked", "yaml", "acorn", "chevrotain", "mathjs"]


class Doctor:
    def __init__(self):
        self.errors = 0
        self.warnings = 0

    def ok(self, text):
        print("  \033[32m✔\033[0m " + text)

    def warn(self, text):
        self.warnings += 1
        print("  \033[33m▲\033[0m " + text)

    def fail(self, text):
        self.errors += 1
        print("  \033[31m✘\033[0m " + text)

    def section(self, title):
        print("\n" + title)


def resolve_home(value):
    return os.path.abspath(value or os.environ.get("DSH_HOME")
                           or "/data/storage/el2/base/haps/entry/files/dsh/home")


def read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def check_bundles(doctor, profile):
    package = os.path.join(profile, "package.json")
    if not os.path.isfile(package):
        doctor.fail("profile package.json 不存在：" + package)
        return
    try:
        data = read_json(package)
        bundles = data["dsh"]["profile"]["bundles"]
    except Exception as error:  # noqa: BLE001
        doctor.fail("profile package.json 读不出 bundles：%r" % (error,))
        return
    missing = [name for name in BUNDLES if name not in bundles]
    if missing:
        doctor.fail("bundles 缺少：" + ", ".join(missing))
    else:
        positions = [bundles.index(name) for name in BUNDLES]
        if positions == sorted(positions):
            doctor.ok("bundles 已登记且顺序正确（%d 个）" % len(BUNDLES))
        else:
            doctor.warn("bundles 顺序不理想：%s" % positions)
    for name in ("dsh-better-sidebar", "dsh-dream-skin"):
        if name in bundles:
            doctor.ok("%s 已启用" % name)
        else:
            doctor.warn("%s 未启用：酒馆的侧栏 / 主题会缺一块" % name)


def check_packages(doctor, node_modules):
    for name in PACKAGES:
        path = os.path.join(node_modules, name)
        if not os.path.isdir(path):
            doctor.fail("缺包：" + path)
            continue
        manifest = os.path.join(path, "package.json")
        version = "?"
        if os.path.isfile(manifest):
            try:
                version = read_json(manifest).get("version", "?")
            except Exception:  # noqa: BLE001
                version = "损坏"
        files = sum(len(fs) for _, _, fs in os.walk(path))
        doctor.ok("%-22s %-14s %d 个文件" % (name, version, files))


def find_host(node_modules):
    return os.path.join(node_modules, "dsh-tavern-host")


def check_deps(doctor, node_modules):
    host_dir = find_host(node_modules)
    search = [os.path.join(host_dir, "node_modules"), node_modules]
    for dep in HOST_DEPS:
        found = next((os.path.join(base, dep) for base in search if os.path.isdir(os.path.join(base, dep))), None)
        if found:
            doctor.ok("依赖 %-12s → %s" % (dep, os.path.relpath(found, node_modules)))
        else:
            doctor.warn("依赖 %s 没找到（模板引擎/解析会退化）" % dep)
    remote_zod = os.path.join(node_modules, "dsh-tavern-remote", "node_modules", "zod")
    if os.path.isdir(remote_zod) or os.path.isdir(os.path.join(node_modules, "zod")):
        doctor.ok("依赖 zod（dsh-tavern-remote）")
    else:
        doctor.fail("dsh-tavern-remote 缺 zod：远程信号会加载失败")


def check_presets(doctor, node_modules, profile, home):
    path = os.path.join(node_modules, "dsh-tavern-presets", "cordis.patch.yml")
    if not os.path.isfile(path):
        doctor.fail("preset 还没渲染：" + path)
        return
    text = open(path, encoding="utf-8").read()
    if "{{" in text:
        doctor.fail("preset 里还有模板占位符")
        return
    missing = [p for p in sorted(set(re.findall(r"name: (/[^\s']+)", text))) if not os.path.isfile(p)]
    if missing:
        doctor.fail("preset 引用了不存在的文件：%s" % missing[0])
    else:
        doctor.ok("preset 已渲染，引用路径全部存在")
    cores = os.environ.get("DSH_CORES") or os.path.join(os.path.dirname(home), "cores")
    if cores in text and profile in text:
        doctor.ok("preset 用的是本机核心目录与 profile 路径")
    else:
        doctor.warn("preset 里的路径看起来不是本机路径（cores=%s）" % cores)


def check_core_patch(doctor, home):
    cores = os.environ.get("DSH_CORES") or os.path.join(os.path.dirname(home), "cores")
    if not os.path.isdir(cores):
        doctor.warn("找不到核心目录 %s" % cores)
        return
    found = False
    for name in sorted(os.listdir(cores)):
        candidate = os.path.join(cores, name, "node_modules", "@deepseek-ai",
                                 "dsh-llm-deepseek", "lib", "index.js")
        if not os.path.isfile(candidate):
            continue
        if "酒馆会话优化" in open(candidate, encoding="utf-8", errors="replace").read():
            doctor.ok("核心补丁在位（%s）" % name)
            found = True
    if not found:
        doctor.warn("核心补丁不在：酒馆会话会回放历史思维链（更费上下文，功能不受影响）")


def check_gate(doctor):
    url = "http://127.0.0.1:3120/api/tavern-gate/status"
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        state = "开" if payload.get("loaded") else "关"
        doctor.ok("门在运行：酒馆=%s%s" % (state, ("，错误：" + payload["error"]) if payload.get("error") else ""))
    except Exception as error:  # noqa: BLE001
        doctor.warn("连不上门（%s）：DSHM 没开，或门没装上" % type(error).__name__)


def check_logs(doctor, home):
    marker = os.path.join(home, "tavern-boot.json")
    if os.path.isfile(marker):
        try:
            data = read_json(marker)
            if data.get("okAt"):
                doctor.ok("上次启动事件循环健康（okAt=%s）" % data["okAt"])
            else:
                doctor.warn("上次启动没有写 okAt：可能启动被卡住过")
        except Exception:  # noqa: BLE001
            doctor.warn("开机标记读不出来")
    else:
        doctor.warn("还没有开机标记（安装后没重启过？）")
    for name in ("tavern-load.log", "tavern-worker.log"):
        path = os.path.join(home, name)
        if os.path.isfile(path):
            doctor.ok("%s %.1fKB" % (name, os.path.getsize(path) / 1024))
        else:
            doctor.ok("%s 还没生成（正常）" % name)


def check_data(doctor, home):
    data = os.path.join(home, "profile-data", "tavern")
    if not os.path.isdir(data):
        doctor.warn("还没有酒馆数据目录（第一次打开酒馆时创建）")
        return
    total = 0
    for root, _, files in os.walk(data):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    sessions = os.path.join(data, "sessions.json")
    chats = os.path.join(data, "chats")
    doctor.ok("酒馆数据 %.1fMB%s%s" % (
        total / 1e6,
        "，sessions.json 在" if os.path.isfile(sessions) else "",
        "，%d 个 chat" % len(os.listdir(chats)) if os.path.isdir(chats) else ""))


def main(argv):
    parser = argparse.ArgumentParser(description="DSHM × DSH Tavern 体检")
    parser.add_argument("--home", default="")
    parser.add_argument("--profile", default="ondevice")
    args = parser.parse_args(argv)

    home = resolve_home(args.home)
    profile = os.path.join(home, "profiles", args.profile)
    node_modules = os.path.join(profile, "node_modules")
    print("== DSHM × DSH Tavern 体检 ==")
    print("home　：%s" % home)
    print("profile：%s" % profile)

    doctor = Doctor()
    if not os.path.isdir(profile):
        print("\n找不到 profile，停止。")
        return 2

    doctor.section("① 包文件")
    check_packages(doctor, node_modules)
    doctor.section("② profile 登记")
    check_bundles(doctor, profile)
    doctor.section("③ 依赖")
    check_deps(doctor, node_modules)
    doctor.section("④ preset")
    check_presets(doctor, node_modules, profile, home)
    doctor.section("⑤ 核心补丁")
    check_core_patch(doctor, home)
    doctor.section("⑥ 运行时")
    check_gate(doctor)
    check_logs(doctor, home)
    doctor.section("⑦ 数据")
    check_data(doctor, home)

    print("\n== %s（错误 %d / 警告 %d）==" % (
        "全部通过" if not doctor.errors else "有问题", doctor.errors, doctor.warnings))
    return 1 if doctor.errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
