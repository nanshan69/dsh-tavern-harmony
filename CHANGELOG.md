# 更新日志

## 1.1.3 — 2026-10-25

**装插件顺带把技能带上**：`packages/dsh-tavern-gate/skills/` 里新增 7 个技能，安装或升级后自动铺到
`$DSH_HOME/skills/`，新设备不用再逐个手工装技能。

- 新增 `packages/dsh-tavern-gate/skills/`（7 个技能 / 18 个文件）：
  - `translate-paper-pdf-to-md`：英文文献 PDF → 中文 Markdown（自带 DSHM 版
    纯 Python 抽取脚本，不依赖 poppler / ImageMagick / Pillow）；
  - `academic-humanizer-en` / `academic-humanizer-zh`：学术写作润色；
  - `ohos-pc` / `ohos-plugin-install` / `ohos-python` / `ohos-shell` / `ohos-workspace`
    五篇鸿蒙运行环境说明。
- 新增 `packages/dsh-tavern-gate/skills-sync.js`：内容相同不写盘；内容不同时
  先把旧文件备份到 `$DSH_HOME/skills-backup/<时间戳>/` 再覆盖。只写同名文件，
  **不删除**用户在 `$DSH_HOME/skills/` 下自己放的任何技能。
  `ohos-*.md` 是运行环境事实，目标已存在时一律不覆盖（只补缺失）。
- `dsh-tavern-gate/index.js`：每次启动校验一次（幂等，正常启动零写盘），
  升级方式 B（覆盖 `packages/*`）后重启即带新技能。
- 根 `index.js`（自举入口）：首次安装/重新贴链接时同步一次，链接安装也能带上技能。
- `translate-paper-pdf-to-md` 新增 `scripts/render_pages_guest.sh`：Alpine guest
  装好 `poppler-utils` 后可渲染页面位图，补上「矢量图无法抽取」的场景。

## 1.1.2 — 2026-10-23

**修好「重新生成正文要等一分钟、最后还报错」**：显示同步（`synchronize`）在端侧
从来没跑成功过 —— 模板引擎用 `await WebAssembly.instantiate(...)` 加载 xxhash，
而 jitless 环境把 WebAssembly 打成了**永不落定**的桩，于是每次同步都停在第一个
`await`，撑满 90 秒超时、把唯一的模板线程占死，前台回合只能排在它后面干等。

- `server-artifact/engine.js`：哈希初始化加 300ms 超时 + 纯 JS 128 位哈希兜底，
  兜底结果缓存在 `globalThis`，之后零等待。首次同步实测 2.7 秒完成（此前永远超时）。
- `server-template-runtime.js`：前台模板调用（`request`/`input`/`worldbook`/…）
  不再看 `transient` 标记，直接抢占正在跑的显示同步；排队中的显示同步在前台
  等待时让位。前台任务不再被 90 秒的后台卡顿拖住。
- `server-template-sync.js`：显示同步的失败次数不再跨轮累积，聊天一有新版本
  就重置重试预算，避免连着重生成几次后卡片渲染永久停摆。
- `server-template-worker.js`：注释订正（WebAssembly 桩继续保持“永不落定”，
  改成 reject 反而可能触发未处理拒绝打挂 worker 线程）。

效果：日志里首次出现 `invoke done synchronize`，消息模板/卡片渲染开始生效；
「重新生成正文」不再先等一分钟。

## 1.1.1 — 2026-10-22

- 修复侧栏半透明：dream-skin 壁纸模式会把 `--dsw-alias-bg-base` 压成 0.45 透明，
  侧栏面板用它当底，正文会透上来。现在按实测元素（原生右侧栏
  `P3OORG_panel` 内部的 `_pane_`）把底色换成本地算出的不透明同色。
- 修复单屏/双屏下酒馆左侧面板点不动：DSHM 在面板上盖了一层全屏遮罩
  （fixed、z-index 35、无 class 的空 div），既吃点击又蒙一层灰。现在用
  `clip-path(evenodd)` 按面板矩形给它挖洞 —— 面板内点击归面板，
  面板外点击仍由遮罩接管（点外侧关闭照旧），并清掉遮罩的半透明视觉。
- 与酒馆无关的原生浮层（例如「+」快捷菜单）仍由主题控制，未做改动。

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
