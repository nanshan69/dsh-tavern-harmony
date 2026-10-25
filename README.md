# DSH Tavern · 鸿蒙移植版（dsh-tavern-harmony）

把 [DSH Tavern](https://github.com/flizzywine/dsh-tavern)（人物卡文字游戏 / SillyTavern
兼容层）完整搬进 **DSHM**（HarmonyOS 上的 DSH 客户端），在设备上自足运行。

> 一句话区别：上游是「给桌面 DSH 装一个 profile」，本仓库是「给鸿蒙 DSH 装一个
> **可选、可关、重启后一定关**的酒馆」。端侧没有子进程、没有 JIT、没有 WebAssembly，
> 所以模板引擎、依赖解析、加载时机都得重写 —— 这些改写都在这里。

---

## 特性

- **默认关闭，重启 100% 关**：酒馆 host 不写进启动配置，只由左下角开关在运行时加载。
  重启应用后不会有酒馆的回合/后台任务/前端逻辑在跑。
- **运行时可开可关**：点一下加载，再点卸载（`fiber.dispose`），不需要重启。
- **关闭状态下会话仍可读**：开机只装一份「只读会话补丁」，让酒馆写出的会话在原生界面
  能正常打开、编辑、回退。
- **端侧自足**：模板引擎跑在 `worker_threads` 里（上游用 fork），不依赖桌面进程模型。
- **前台优先**：正文生成会抢占正在跑的模板渲染；后台结算/候选/生图进行中不抢显示同步。
- **完整玩法**：人物卡、世界书、正则、MVU 变量、场景生图（含 ComfyUI / NovelAI 渠道）、
  改卡工作台、候选行动、后台结算、`/compact` 压缩。
- **中文文档 + 安装器 + 体检脚本**：`scripts/install.py`、`scripts/doctor.py`，
  幂等、干跑默认、自动备份。
- **自带 Agent 技能**：`packages/dsh-tavern-gate/skills/` 会在安装/升级后铺到 `$DSH_HOME/skills/`
  —— 文献翻译、学术润色两套、五篇鸿蒙环境说明，开箱即用（见下面「内置技能」）。

## 架构

```
ArkWeb（浏览器）
├─ dsh-tavern-gate/client.js      左下角「酒馆：开/关」+ 只读补丁注入 + 面板不透明 CSS
└─ dsh-tavern-plugin/client.js    酒馆 UI（约 2MB bundle；门没开时 factory 直接返回空实现）
        │  fetch /api/tavern-gate/{status,toggle,session-patch-client}
        ▼
Host 进程（Node 24 · jitless）
├─ dsh-tavern-gate/index.js        开机只加载这一个文件（~200 行）
│     └─ 点「开」时：import('tavern-host-entry.js') → ctx.plugin()
├─ dsh-tavern-host/index.js        壳：解析钩子 / CJS 兜底 / 加载进度
│     └─ lib/index.js              酒馆 host：会话、卡片、世界书、生图、模板引擎
│           └─ worker_threads      服务端模板引擎（jsdom + ST 模板）
├─ dsh-tavern-remote               typert 远程信号（启动行，等 tavernSessionSignals 出现）
└─ dsh-tavern-presets              tavern / tavern-background 两个 agent preset
```

`dsh-tavern-plugin`（前端 bundle 的加载行）和 `dsh-tavern-remote`（远程信号服务）
必须是独立的包：DSHM 的 `dsh-client-modules` 按「包」扫描前端入口，一个包只能有一个
client 模块；远程服务又必须是启动行、靠 `typert` 走 RPC。这不是可以合并的设计，是
DSH 插件模型本身的约束。

## 目录

| 路径 | 内容 |
| --- | --- |
| `index.js` / `client.js` | 「贴链接安装」的自举入口：首次启动铺开 5 个包并加载开关 |
| `packages/dsh-tavern-gate` | 开关（host 路由 + 前端按钮）。**唯一**在关闭状态下加载的东西 |
| `packages/dsh-tavern-host` | 酒馆 host 运行时（上游 `lib/**` + 移植壳 + 生图模块 + 提示词） |
| `packages/dsh-tavern-plugin` | 前端 bundle 加载行（预编译 `client.js`） |
| `packages/dsh-tavern-remote` | typert 远程信号服务（前端拿 `tavern-state` 更新用） |
| `packages/dsh-tavern-presets` | 两个 agent preset（安装时按设备路径渲染） |
| `vendor/dsh-dream-skin` | 内置的酒馆主题（MIT，不在 registry 稳定版本上） |
| `packages/dsh-tavern-gate/skills/` | 随插件分发的 Agent 技能（安装后铺到 `$DSH_HOME/skills/`） |
| `patches/` | 相对上游的全部改动（核心 / host lib / 前端 bundle） |
| `scripts/install.py` | 安装器（幂等、默认干跑、自动备份） |
| `scripts/uninstall.py` | 卸载器（默认保留数据） |
| `scripts/doctor.py` | 体检（只读） |
| `docs/` | 架构、安装、移植说明、已知限制、故障排查 |

## 安装

### 方式 A：贴链接（推荐，新设备最省事）

1. DSHM → **设置 → 插件** → 「安装插件」，贴：

   ```
   github.com/nanshan69/dsh-tavern-harmony
   ```

2. 等它下载完（约 45MB，取决于网络），提示安装成功。
3. **完全退出 DSHM 再打开**（安装器要求重启才会挂载新插件）。
4. 首次启动会自动「铺开」：把仓库里的 5 个包放进 `node_modules`、登记 bundles、
   渲染 preset、补 home patch，然后直接加载酒馆开关 —— 左下角出现
   「**酒馆：关**」，点一下就进酒馆。
5. 再重启一次即进入普通安装形态（自举行已自动移除）。

依赖（jsdom、better-sidebar 等）写在根 `package.json` 的 `dependencies` 里，
由安装器一并装；主题 `dsh-dream-skin` 随仓库内置（它不在 registry 的稳定版本上）。

### 方式 B：脚本安装（离线 / 自定义路径）

前置：设备上有 Python 3.11+（DSHM 自带 `python3` 垫片，也可以让 Agent 跑）。

```bash
python3 scripts/install.py            # 干跑，确认路径都对
python3 scripts/install.py --apply    # 真正安装
# 完全退出 DSHM 再打开 → 左下角「酒馆：关」→ 点开
python3 scripts/doctor.py             # 体检
```

安装器会：复制 5 个包到 `<profile>/node_modules/`、渲染 preset 的设备路径、
把 6 个 bundle 行登记进 profile、补一条 home patch 的 `permission` 默认值、
给核心打「酒馆会话不回放思维链」补丁（可 `--no-core-patch` 跳过）。
每一步都幂等；写之前会备份到 `$DSH_HOME/_tavern-harmony-backup/`。

卸载：

```bash
python3 scripts/uninstall.py            # 干跑
python3 scripts/uninstall.py --apply    # 摘掉代码与 profile 登记，保留人物卡/聊天
```

## 内置技能

`packages/dsh-tavern-gate/skills/` 会由同目录的 `skills-sync.js` 在每次启动时同步到
`$DSH_HOME/skills/`（幂等：内容相同不写盘；不同则先备份到
`$DSH_HOME/skills-backup/<时间戳>/`，不删用户自己的技能）。

| 技能 | 用途 |
| --- | --- |
| `translate-paper-pdf-to-md` | 英文文献 PDF → 目标语言 Markdown，保留图表/公式/引用；自带 DSHM 纯 Python 抽取脚本 |
| `academic-humanizer-zh` | 中文学术写作去 AI 腔润色（论文/摘要/讨论/基金本子） |
| `academic-humanizer-en` | 英文学术写作与基金申请的清晰度/语气润色 |
| `ohos-python` / `ohos-shell` / `ohos-workspace` / `ohos-pc` / `ohos-plugin-install` | 鸿蒙端运行环境说明（Python、shell、工作区、PC 形态、插件安装通道） |

`ohos-*` 是运行环境事实，随核心版本演进：如果目标文件已存在就**不覆盖**，
仓库里的副本只在缺失时补一份。

文献翻译技能的额外依赖只有 `pypdf`（纯 Python）。设备上让 Agent 执行一次即可：

```python
from pip._internal.cli.main import main
main(["install", "pypdf"])
```

## 开关语义

| 操作 | 结果 |
| --- | --- |
| 新装 / 重启应用 | 关。没有酒馆回合、后台任务、前端逻辑在跑 |
| 点「酒馆：关」 | host 侧 `dispose()`；前端立刻刷新回原界面 |
| 点「酒馆：开」 | 加载 host（约 1–3 秒）→ 刷新 → 酒馆 UI 出现 |
| 停用 bundle | 等价于关闭，且不再有左下角开关 |
| 卸载 | 摘掉 5 个包 + profile 登记；数据保留 |

唯一在「关」时仍加载的酒馆代码是只读会话补丁（一个模块），可用
`DSH_TAVERN_BOOT_PATCH=0` 关掉；关掉后酒馆会话在原生界面会打不开（这是取舍）。

## 依赖

运行时依赖写在根 `package.json` 的 `dependencies` 里，**贴链接安装时由安装器
自动拉取**（`.gitignore` 已排除 `node_modules/`，仓库本身不带）：

```
jsdom@26  marked@16  yaml@2.9  acorn@8.15  chevrotain@11
@jsquash/jpeg  @jsquash/png  @jsquash/webp  mathjs  ws  zod
dsh-better-sidebar@0.28.0      （侧栏，酒馆必需）
```

主题 `dsh-dream-skin` 不在依赖里，仓库带了一份稳定的 9.23.0（`vendor/`），
自举时复制过去。

核心 `@deepseek-ai/*` **不要复制**进 profile：运行时按 `$DSH_HOME/../cores`
解析到宿主那一份，复制会产生第二份实例。

## 已知限制

- 模板引擎在 jitless 设备上是全局瓶颈：正文首字延迟比桌面高，渲染偶发 1–2 秒抖动。
- 生图是异步的：规划 → 提交 → 轮询 → 保存，端到端几十秒到十几分钟（取决于渠道）。
- 酒馆与原生界面共用同一个 Host 进程，CPU 是抢的；移植里用「前台优先 + 延迟后台同步」
  缓解，但设备很忙时仍可能变慢。
- 详细清单见 [`docs/已知限制.md`](docs/已知限制.md)。

## 文档

- [`docs/架构.md`](docs/架构.md) — 组件、生命周期、数据流
- [`docs/安装.md`](docs/安装.md) — 依赖、安装、验证、卸载、升级
- [`docs/移植说明.md`](docs/移植说明.md) — 端侧约束与每一处改写的理由
- [`docs/已知限制.md`](docs/已知限制.md) — 能力边界与取舍
- [`docs/故障排查.md`](docs/故障排查.md) — 日志、体检、常见症状
- [`docs/开发与更新.md`](docs/开发与更新.md) — 跟进上游、重新构建、出补丁

## 版本与来源

| 项 | 值 |
| --- | --- |
| 本移植 | 1.1.3 |
| 上游 | flizzywine/dsh-tavern 3.0.1（`c7d4a118`） |
| 目标 | DSHM 0.2.1-rc.2 / Node 24 · jitless / ArkWeb |
| 许可 | AGPL-3.0-or-later（详见 [`NOTICE.md`](NOTICE.md)） |

本仓库**不是**上游官方项目。上游的作者不接受本移植的 issue；DSHM 相关的问题请
提到本仓库。
