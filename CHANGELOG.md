# 更新日志

## 1.1.0 — 2026-10-22

**「贴链接安装」**：仓库根变成一个可安装包，新设备在「设置 → 插件」里贴
`github.com/nanshan69/dsh-tavern-harmony` 即可。

- 根 `index.js` 是自举入口：首次启动把 5 个包铺到 `<profile>/node_modules/`、
  复制内置主题、渲染 preset、登记 bundles、移除自举行，并当场加载开关。
- 根 `package.json` 声明运行时依赖，安装器一并拉取（jsdom、better-sidebar 等）。
- 内置 `dsh-dream-skin` 9.23.0（上游随 Tavern 分发的运行时快照，MIT）。
- 根 `client.js`：自举那次启动也能看到「酒馆：关」按钮，不用多等一轮重启。
- 脚本安装（`scripts/install.py`）保留，作为离线/自定义路径的兜底。

## 1.0.0 — 2026-10-22

首个可用的鸿蒙移植版本（上游 `flizzywine/dsh-tavern` 3.0.1 / `c7d4a118`，
目标 DSHM `0.2.1-rc.2`、Node 24 · jitless、ArkWeb）。

### 开关与加载

- 默认关闭：酒馆 host 不进启动配置，重启后不会有任何酒馆逻辑在跑。
- 运行时开 / 关：左下角一个按钮，关闭走 `fiber.dispose()`，不写持久状态。
- 关闭状态下保留「只读会话补丁」，酒馆写出的会话在原生界面仍可打开、编辑、回退。
- 前端 bundle 自带闸门：门没开时整个模块空实现返回（不执行任何酒馆逻辑）。

### 端侧适配

- 服务端模板引擎从 `fork` 改为 `worker_threads`（端侧禁止 spawn）。
- WebAssembly 桩、消息缓冲、`resolve.paths` 兜底，解决端侧 Node 构建的缺失 API。
- `@deepseek-ai/*` 运行时解析回核心目录，不复制第二份实例。
- 前台优先：正文回合抢占模板渲染；后台忙时推迟显示同步；排队任务按类别取消。
- 超时体系：渲染 180s / transient 90s / RPC 30s / 生图与过滤 15min / 前端候选 15s。
- 会话补丁拆成「host 侧安装 + 前端源码分发」，关闭状态也能读酒馆会话。

### 玩法

- 人物卡、世界书、正则、MVU 变量、候选行动、后台结算、改卡工作台、场景生图
  （NovelAI / ComfyUI 等渠道）、`/compact` 压缩全部可用。
- 场景生图超时 5min → 15min；图已生成但保存被取消时会自动补保存。
- 配图规划提示词追加「情境观测」与「ComfyUI Tag 指南」。

### 工程

- 5 个包的插件包布局（gate / host / plugin / remote / presets）。
- `scripts/install.py`：幂等安装、默认干跑、自动备份、核心补丁应用。
- `scripts/uninstall.py`：默认保留数据，可选还原核心文件。
- `scripts/doctor.py`：七组只读体检。
- `patches/`：核心、host lib、前端 bundle 的全部改动都可 `git apply` 复核。

### 已知问题

- 首字延迟 5–20 秒（jitless 下模板渲染本身贵），长会话更明显。
- 折叠屏 / 手机窄屏的侧栏与候选卡偏挤；面板不透明靠 gate 注入的 CSS 兜底。
- 依赖（约 300MB）不随仓库分发，首次安装需自行准备。
