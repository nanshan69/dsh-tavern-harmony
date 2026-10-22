# NOTICE — 来源、许可与改动

本仓库是 [flizzywine/dsh-tavern](https://github.com/flizzywine/dsh-tavern) 的
**鸿蒙端侧移植版**（下称「上游」）。它不是上游的分支，不跟踪上游的
installer / 桌面启动器，只把酒馆「搬进」DSHM（HarmonyOS 上的 DSH 客户端）
并在端侧缺能力的地方做了改写。

## 上游版本

| 项 | 值 |
| --- | --- |
| 仓库 | https://github.com/flizzywine/dsh-tavern |
| 版本 | 3.0.1 |
| 清单 revision | `c7d4a118ca8cc0f57917bd054de35b950184381a` |
| 许可 | GNU AGPL-3.0（全文见 `LICENSE`） |

## 哪些是上游原样代码

以下目录/文件来自上游构建产物（或上游源码），**原样保留**，只做了下方列出的改动：

| 路径 | 说明 | 许可 |
| --- | --- | --- |
| `packages/dsh-tavern-host/lib/**` | 酒馆 host 运行时（含 `vendor/` 里的 MVU、ST 模板引擎、宏解析器、`client-assets/`） | AGPL-3.0 |
| `packages/dsh-tavern-host/prompts/**` | 提示词素材（`scene-plan.md` 有追加，见下） | AGPL-3.0 |
| `packages/dsh-tavern-host/packages/dsh-image-gen/**` | 生图模块（上游内嵌的 fork） | MIT（见包内 `LICENSE`） |
| `packages/dsh-tavern-host/packages/dsh-tavern-card-memory/**` | 改卡记忆 | AGPL-3.0 |
| `packages/dsh-tavern-plugin/client.js` | 前端 bundle（预编译产物） | AGPL-3.0 |
| `packages/dsh-tavern-remote/**` | typert 远程信号服务（含 `src/`、构建脚本） | AGPL-3.0 |
| `vendor/dsh-dream-skin/**` | 主题运行时快照（上游注明「随 Tavern 一起分发、不单独发布」）；基于 [RevolutionLA/dsh-dream-skin](https://github.com/RevolutionLA/dsh-dream-skin) 9.23.0 | MIT（见目录内 `LICENSE`） |

`packages/dsh-tavern-gate/**`、`scripts/**`、`docs/**`、根目录文件（含「贴链接安装」的
自举入口 `index.js` / `client.js`）是本移植新增的。

## 自举（1.1.0 起）

仓库根同时是一个**可安装包**（`dsh.bundle.patch` + `dsh.client`）。DSHM 的插件
安装器把整仓装进 `node_modules/dsh-tavern-harmony/` 后，根 `index.js` 在首次启动时：

1. 把 `packages/` 里 5 个包铺到 `<profile>/node_modules/`（同盘复制）
2. 把 `vendor/dsh-dream-skin` 铺过去
3. 把可能被装在包内 `node_modules/` 的依赖链接到 profile 级
4. 渲染 preset、补 home patch、改写 profile 的 `dsh.profile.bundles`
5. 当场加载 `dsh-tavern-gate`，并在 bundles 里移除自举行

它只跑一次，不是运行时插件的一部分；日志在 `$DSH_HOME/tavern-bootstrap.log`。

## 相对上游的改动

完整补丁在 `patches/`，下面是要点。

### host lib（`patches/upstream/0002-tavern-host-lib-dshm.patch`）

端侧没有 `spawn` 权限（`appspawn` 被拒），上游「fork 子进程跑模板引擎」的做法
完全不可用。改动集中在模板执行链路：

- **模板引擎改用 `worker_threads`**：新增 `domain/server-template-worker-thread.mjs`
  与 `domain/server-template-inproc.js`；`server-template-runtime.js` 在
  openharmony/appspawn 下走 `startInProcess()`，用 MessageChannel 传历史。
- 端侧缺 WebAssembly（jitless 构建）→ worker 里给一个永不 resolve 的桩，
  避免初始化直接把 worker 打死。
- 端侧 import 顺序问题 → worker 在 `import()` 完成前缓存消息，避免
  `initialize` 丢失。
- **前台优先**：非 transient 的模板调用会停掉正在跑的 transient 任务并递增
  generation；排队中的后台任务按 `queueKind` 取消，保证「正文生成不被后台
  渲染拖住」。
- **超时/重试**：渲染超时 180s、transient 90s、host 侧 RPC 守卫 30s；
  同步延迟 1500ms、最大退避 15s；生图/世界书过滤超时 5min → 15min。
- **少抢 CPU**：正文回合进行中、候选/生图/结算进行中，都推迟显示同步；
  历史读取加不可变快照缓存（TTL 60s）。
- `tavernSessionSignals` provide 到 `ctx.root`：cordis 服务默认只对子上下文
  可见，`dsh-tavern-remote` 这个启动行是兄弟插件，必须挂到 root 才拿得到。
- 复用门在开机时装的会话补丁（`globalThis.__tavernGateSessionPatch`），不重复包装。

### 前端 bundle（`patches/upstream/0001-tavern-client-dshm.patch`）

- **开关守卫**：factory 开头同步查 `/api/tavern-gate/status`，门没开就空实现返回。
- 候选行动的 `submitTask` 客户端超时 2s → 15s（端侧后台结算繁忙时会超）。
- 侧栏新增「场景生图」页（复用 `SceneImageSettings`）。
- 开机补丁已装时补发 `confirmSessionPatch` 握手。

### 提示词

`prompts/scene-plan.md` = 上游原文 + 「附A 情境观测」+「附B ComfyUI Tag 指南」
（约 +11KB），让端侧的配图规划和生图提示词遵循用户提供的 Tag 写法。
用户若在酒馆设置里改了 `promptOverrides`，会覆盖这里。

### 核心（`patches/core/0001-deepseek-reasoning-replay-strip.patch`）

`@deepseek-ai/dsh-llm-deepseek`：识别为酒馆会话时，不再把历史 assistant
消息里的思维链回放给模型。判定依据是酒馆装配的系统提示词特征
（`【常驻世界书】` / `tavern-system-head` / `小说续写引擎`），普通会话行为不变。
没有这条也能用，只是酒馆长会话会更快碰到上下文上限。

## 未包含的第三方

上游依赖的 `dsh-better-sidebar`、`dsh-dream-skin`、`dsh-web-mobile`、`dsh-pocket`
**不在本仓库内**。本移植依赖前两个（侧栏与主题），安装说明见 `docs/安装.md`；
后两个面向上游的桌面/移动外壳，DSHM 不需要。

## 商标

「DSH」「DeepSeek」等名称归其所有者；「酒馆 / SillyTavern」相关格式与素材
归各自作者。本仓库只做兼容与集成。
