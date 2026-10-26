# dsh-tavern-gate

DSHM（DSH on HarmonyOS）的酒馆开关：**酒馆本体默认不加载**，点左下角按钮才在运行时挂载，关掉即从内存消失。

版本 0.2.0。这个包不只是个开关，它还承担三件启动期必须完成的事。

## 它做什么

### 1. 酒馆的运行时开关（本体）

`apply()` 只注册 3 条 HTTP 路由（约 80 行），不加载酒馆代码。点「打开酒馆」时才 `import` 酒馆的 host 入口并 `ctx.plugin()` 挂载；关闭或重启则 `dispose`。

**不写任何持久状态** —— 重启后一定是关的。这样酒馆的任何问题都不会拖垮启动。

| 路由 | 方法 | 作用 |
|---|---|---|
| `/api/tavern-gate/status` | GET | 当前是否已加载 + 错误信息 |
| `/api/tavern-gate/toggle?on=1` | POST | 开 / 关 |
| `/api/tavern-gate/session-patch-client` | GET | 会话补丁的前端源码 |

### 2. 核心包解析钩子（关键，容易被忽略）

`installCoreHook()` 在**模块求值阶段**（不是 `apply` 里）注册 `module.registerHooks`，把
`dsh-tavern-host` / `dsh-better-sidebar` / `dsh-tavern-remote` 里的 `@deepseek-ai/*` 解析到核心目录。

**为什么必须**：这些第三方包如果拿到和宿主**不同的** cordis / schemastery 实例，服务注入会全部失效（`ctx.get` 返回 undefined、provider 认不出同一对象）。钩子让它们共享同一份模块实例。

因此本包在 profile 的 `dsh.profile.bundles` 里**必须排在上述第三方包之前**。

核心目录自动探测：扫 `<home>/../cores/*`，取含 `@deepseek-ai/dsh-tools/package.json` 且 mtime 最新的那个。可用 `DSH_HOME` / `DSH_CORES` 覆盖。

### 3. 会话补丁（开机即装）

`installSessionPatchAtBoot()` 在启动时装好「正文编辑 / 回退 / 重新生成」的会话格式兼容层。必须在**任何会话打开之前**装好，所以放在开机阶段而不是开关里。酒馆被点开时复用这个句柄。

### 4. 内置技能铺开

`syncSkillsAtBoot()` 把包内 `skills/` 铺到 `<home>/skills`：

- 目标不存在 → 写入
- 内容相同 → 不写盘（正常启动零 IO）
- 内容不同 → 旧文件先备份到 `<home>/skills-backup/<时间戳>/` 再覆盖
- `preserve: ['ohos-']` → 不覆盖 `ohos-` 前缀的技能
- 不删除用户自己放的其他技能

备份目录刻意放在 `skills/` 之外，否则会被技能加载器当成一个技能目录。

## 安装

DSHM「设置 → 插件」里贴本仓库地址即可。安装器读 `package.json` 的 `dsh.bundle.patch`，把 `cordis.patch.yml` 登记为 profile 层。

也可以手动在 profile 的 `cordis.patch.yml` 加：

```yaml
- insert:
    - id: tavern-gate
      name: dsh-tavern-gate
```

并确保 `dsh.profile.bundles` 里有 `dsh-tavern-gate`，且排在 `dsh-better-sidebar` / `dsh-tavern-remote` 之前。

## 排障

开机标记写在 `<home>/tavern-boot.json`：

- `attemptAt` — 每次启动先写
- `okAt` — 事件循环健康地活过 1.5 秒才写

`okAt < attemptAt` 说明上次启动被卡住。这不是开关状态的一部分，纯粹是排障线索。

## 文件

| 文件 | 作用 |
|---|---|
| `index.js` | host 半边：开关 + 核心包钩子 + 会话补丁 + 技能同步 |
| `client.js` | 浏览器半边：左下角「酒馆：开 / 关」按钮 |
| `skills-sync.js` | 技能铺开（幂等 + 备份） |
| `tavern-host-entry.js` | 门后面真正的酒馆 host 入口，转发到 `dsh-tavern-host` |
| `cordis.patch.yml` | bundle 层，登记 `tavern-gate` 条目 |
| `skills/` | 随包分发的技能 |

## 变更

- **0.2.0** — 从「最小验证版」升级为实际在用的完整版：核心包解析钩子、会话补丁、技能同步、3 条开关路由。
- **0.1.1** — 最小版：空 host 半边 + 一个只写 localStorage 的假开关，用于验证 bundle 安装链路。

## License

AGPL-3.0-or-later（与 dsh-tavern-harmony 一致）
