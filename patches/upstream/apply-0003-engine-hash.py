#!/usr/bin/env python3
"""把模板引擎里的 xxhash 初始化改成「有超时 + 纯 JS 兜底」。

上游 `server-artifact/engine.js`（webpack 打包产物，单行 3.2MB）里，xxhash-wasm 是

    ... }((await WebAssembly.instantiate(D)).instance)

也就是在模块工厂里直接 await WebAssembly。DSHM 是 jitless 端：没有 WebAssembly，
`server-template-worker.js` 给了一个**永不落定**的桩（刻意不用 reject，避免未处理
拒绝打挂 worker 线程）。于是显示同步 `synchronize()` 的第一行

    const {h64ToString} = await hashing

永远停在那里：不报错、不退出、CPU 为 0，最后撑满 90 秒超时，把唯一的模板线程占死。
这正是「重新生成正文要等一分钟、最后还报错」的根因。

本脚本做一次精确字符串替换（幂等）：

    旧: const{h64ToString:d}=await e,
    新: const{h64ToString:d}=globalThis.__dshTemplateHash||(... 300ms 超时 + 纯 JS 哈希 ...)

用法：
    python3 apply-0003-engine-hash.py [engine.js 路径]

默认路径相对仓库根：dsh-tavern-host/lib/vendor/st-prompt-template/server-artifact/engine.js
"""
import sys
import pathlib

OLD = "const{h64ToString:d}=await e,"
NEW = "const{h64ToString:d}=" + 'globalThis.__dshTemplateHash||(globalThis.__dshTemplateHash=await Promise.race([e.catch(()=>null),new Promise(r=>setTimeout(()=>r(null),300))]).then(x=>x||{h64ToString:s=>{let a=2166136261,b=2654435769;for(let i=0;i<s.length;i++){const c=s.charCodeAt(i);a=Math.imul(a^c,16777619)>>>0;b=Math.imul(b+c,2246822507)>>>0}return(a>>>0).toString(16).padStart(8,"0")+(b>>>0).toString(16).padStart(8,"0")}}))' + ","

DEFAULT = "dsh-tavern-host/lib/vendor/st-prompt-template/server-artifact/engine.js"


def main(path):
    p = pathlib.Path(path)
    src = p.read_text(encoding="utf-8", errors="surrogateescape")
    if "globalThis.__dshTemplateHash" in src:
        print("已打过补丁，无需重复处理：", p)
        return 0
    count = src.count(OLD)
    if count != 1:
        print("锚点出现", count, "次（应为 1 次），上游产物可能已变，请人工核对：", p)
        return 2
    p.write_text(src.replace(OLD, NEW), encoding="utf-8", errors="surrogateescape")
    print("已打补丁：", p)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else DEFAULT))
