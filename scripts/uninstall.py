#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""卸载 DSHM × DSH Tavern（鸿蒙移植版）。

    python3 scripts/uninstall.py              # 只打印会做什么
    python3 scripts/uninstall.py --apply      # 真正卸载
    python3 scripts/uninstall.py --apply --purge-data   # 连酒馆数据一起删

默认保留酒馆数据（人物卡、聊天、场景图），只摘掉代码与 profile 登记。
"""
import argparse
import glob
import json
import os
import shutil
import sys
import time

PACKAGES = ["dsh-tavern-gate", "dsh-tavern-host", "dsh-tavern-plugin",
            "dsh-tavern-remote", "dsh-tavern-presets"]
TAVERN_BUNDLES = ["dsh-tavern-gate", "dsh-tavern-plugin", "dsh-tavern-remote",
                  "dsh-tavern-presets"]
# 这两个是第三方主题/侧栏，可能被你自己单独使用；默认不动它们。
THEME_BUNDLES = ["dsh-better-sidebar", "dsh-dream-skin"]
DEFAULT_HOME = "/data/storage/el2/base/haps/entry/files/dsh/home"


def parse_args(argv):
    parser = argparse.ArgumentParser(description="卸载 DSHM × DSH Tavern")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--home", default=os.environ.get("DSH_HOME", DEFAULT_HOME))
    parser.add_argument("--profile", default="ondevice")
    parser.add_argument("--purge-data", action="store_true", help="连 profile-data/tavern 一起删")
    parser.add_argument("--with-sidebar", action="store_true",
                        help="同时停用 dsh-better-sidebar / dsh-dream-skin（默认保留，它们可能被你单独使用）")
    parser.add_argument("--revert-core-patch", action="store_true", help="从 .bak-tavern-* 还原核心文件")
    return parser.parse_args(argv)


def main(argv):
    args = parse_args(argv)
    home = os.path.abspath(args.home)
    profile = os.path.join(home, "profiles", args.profile)
    node_modules = os.path.join(profile, "node_modules")
    stamp = time.strftime("%Y%m%d-%H%M%S")

    print("== 卸载 DSHM × DSH Tavern ==")
    print("profile：%s" % profile)
    print("模式　：%s\n" % ("APPLY" if args.apply else "DRY-RUN"))

    package = os.path.join(profile, "package.json")
    if not os.path.isfile(package):
        print("找不到 %s，无法继续。" % package)
        return 2

    data = json.load(open(package, encoding="utf-8"))
    bundles = data.get("dsh", {}).get("profile", {}).get("bundles", [])
    drop = set(TAVERN_BUNDLES)
    if args.with_sidebar:
        drop |= set(THEME_BUNDLES)
    remaining = [name for name in bundles if name not in drop]
    removed = [name for name in bundles if name in drop]
    print("会从 bundles 移除：%s" % (", ".join(removed) if removed else "（无）"))
    print("会删除的包：%s" % ", ".join(PACKAGES))
    kept_theme = [name for name in bundles if name in THEME_BUNDLES and name not in drop]
    if kept_theme:
        print("保留（可能你自己在用）：%s　　要一起停用加 --with-sidebar" % ", ".join(kept_theme))

    if args.purge_data:
        print("会删除酒馆数据：%s" % os.path.join(home, "profile-data", "tavern"))
    else:
        print("酒馆数据保留：%s" % os.path.join(home, "profile-data", "tavern"))

    if not args.apply:
        print("\n这是干跑。加 --apply 真正卸载。")
        return 0

    backup_dir = os.path.join(home, "_tavern-harmony-backup", "uninstall-" + stamp)
    os.makedirs(backup_dir, exist_ok=True)
    shutil.copyfile(package, os.path.join(backup_dir, "profile-package.json"))

    data.setdefault("dsh", {}).setdefault("profile", {})["bundles"] = remaining
    with open(package, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print("\n[1/4] profile package.json 已更新（备份 %s）" % backup_dir)

    for name in PACKAGES:
        path = os.path.join(node_modules, name)
        if os.path.isdir(path):
            shutil.rmtree(path)
            print("[2/4] 删除 %s" % name)

    receipt = os.path.join(home, "tavern-harmony-install.json")
    if os.path.isfile(receipt):
        shutil.move(receipt, os.path.join(backup_dir, "tavern-harmony-install.json"))
        print("[3/4] 安装回执已移到备份目录")

    if args.purge_data:
        target = os.path.join(home, "profile-data", "tavern")
        if os.path.isdir(target):
            shutil.move(target, os.path.join(backup_dir, "tavern-data"))
            print("[4/4] 酒馆数据已移入备份（%s）" % backup_dir)
    else:
        print("[4/4] 酒馆数据未动")

    if args.revert_core_patch:
        cores = os.environ.get("DSH_CORES") or os.path.join(os.path.dirname(home), "cores")
        for pattern in ("*/node_modules/@deepseek-ai/dsh-llm-deepseek/lib/index.js.bak-tavern-*",):
            for backup in sorted(glob.glob(os.path.join(cores, pattern))):
                target = backup.split(".bak-tavern-")[0]
                shutil.copyfile(backup, target)
                print("    已还原核心文件：%s" % target)

    print("""
卸载完成。请**完全退出 DSHM 再打开**。
注意：dsh-better-sidebar / dsh-dream-skin 是本移植之外的主题与侧栏插件，
如果它们不是你自己装的，可以一并删除；数据目录（人物卡、聊天）默认保留。
""")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
