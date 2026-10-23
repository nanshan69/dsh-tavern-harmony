# patches/

这里是本移植相对上游（`flizzywine/dsh-tavern` 3.0.1 / `c7d4a118`）的**全部改动**，
可直接 `git apply` 到上游源码/产物上复现。

| 文件 | 作用对象 | 大小 |
| --- | --- | --- |
| `core/0001-deepseek-reasoning-replay-strip.patch` | 核心 `@deepseek-ai/dsh-llm-deepseek/lib/index.js` | ~3KB |
| `upstream/0001-tavern-client-dshm.patch` | 上游 `tavern-plugin/lib/client.js`（前端 bundle） | ~3KB |
| `upstream/0002-tavern-host-lib-dshm.patch` | 上游 `tavern-plugin/lib/**`（host 运行时，含 3 个新文件） | ~49KB |
| `upstream/0003-display-sync-hang.patch` | 在 `0002` 之上追加：显示同步卡死的修复（3 个 host 文件） | ~6KB |
| `upstream/apply-0003-engine-hash.py` | 模板引擎产物 `engine.js`（单行 3.2MB，用脚本做精确替换） | ~2KB |

## 用法

```bash
# 在装有上游源码/产物的目录里
git apply --check patches/upstream/0002-tavern-host-lib-dshm.patch
git apply         patches/upstream/0002-tavern-host-lib-dshm.patch
```

`0003` 要打在**已经打过 `0002`** 的文件上（它改的是移植后的 host 运行时）：

```bash
git apply patches/upstream/0003-display-sync-hang.patch
# 模板引擎是单行 3.2MB 的产物，用脚本改（幂等，锚点唯一才动手）
python3 patches/upstream/apply-0003-engine-hash.py \
    dsh-tavern-host/lib/vendor/st-prompt-template/server-artifact/engine.js
```

核心补丁同理，路径前缀是 `node_modules/@deepseek-ai/dsh-llm-deepseek/lib/index.js`，
所以在 `$DSH_HOME/../cores/<版本>/` 下执行：

```bash
cd "$(ls -d "$DSH_HOME"/../cores/*/ | tail -1)"
git apply --check /path/to/patches/core/0001-deepseek-reasoning-replay-strip.patch
```

`scripts/install.py` 内置了一个极简 unified diff 应用器（只处理本仓库的补丁：
上下文匹配 + 只插入/替换，不删文件），失败时会保留原文件并提示手动 `git apply`。

## 注意

- 补丁是按 **上游 3.0.1 + DSH 0.2.1-rc.2** 的产物生成的。上游换版本后上下文大概率
  对不上：`git apply` 会拒绝，这是预期行为（不要 `--3way` 硬打）。
- 仓库里 vendored 的 `lib/**` 已经是打过补丁的版本，这些补丁主要用于**复核**和
  **升级上游时重新移植**。
- 升级流程见 `docs/开发与更新.md`。
