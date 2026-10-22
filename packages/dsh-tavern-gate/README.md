# dsh-tavern-gate

酒馆的**门**：约 200 行的 host 插件，负责「默认关闭 + 运行时加载」。
它本身不含任何酒馆逻辑，可以单独安装、单独停用。

## 它做什么

| 时机 | 行为 |
| --- | --- |
| DSHM 启动 | 只加载本文件：注册 `/api/tavern-gate/*` 路由 + 装一份「只读会话补丁」 |
| 点「酒馆：开」 | `import('./tavern-host-entry.js')` → `ctx.plugin()` 挂载 `dsh-tavern-host` |
| 点「酒馆：关」 | `fiber.dispose()`，酒馆代码从内存里消失（不写任何持久状态） |
| 重启应用 | 一定是关的：开关状态只存在内存里 |

「只读会话补丁」是关闭状态下唯一会加载的酒馆代码
（`dsh-tavern-host/lib/domain/host-session-patch.js`）。它只替换
`SessionEventStream` 的读取方法，让酒馆写出的会话在原生界面也能打开；
不加载酒馆 UI、回合逻辑或后台任务。需要完全干净启动时设
`DSH_TAVERN_BOOT_PATCH=0`。

## HTTP 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/tavern-gate/status` | `{ loaded, error }` |
| POST | `/api/tavern-gate/toggle?on=1` / `?on=0` | 加载 / 卸载酒馆 |
| GET | `/api/tavern-gate/session-patch-client` | 前端补丁源码（客户端 eval 用） |

## 为什么不在启动配置里

端侧的启动配置由 DSHM 每次启动重写，「重启后 100% 关闭」无法用
「启动行 + 开关字段」表达：任何写进启动配置的酒馆行都会在下次启动时被加载。
把加载动作推迟到一次 HTTP 请求里，是这台设备上唯一可靠的做法。

## 环境变量

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `DSH_HOME` | 从本文件位置推导 | 数据目录；日志、开机标记写在这里 |
| `DSH_CORES` | `$DSH_HOME/../cores` | 核心包目录（解析 `@deepseek-ai/*` 用） |
| `DSH_TAVERN_BOOT_PATCH` | 未设置（= 安装） | 设为 `0` 跳过开机会话补丁 |

## 依赖

- `dsh-tavern-host`（同仓库 package；`tavern-host-entry.js` 转出它）
- `dsh-better-sidebar`、`dsh-dream-skin`（酒馆前端用，可选但推荐）
- 核心 `@deepseek-ai/*` 不复制，运行时按 `DSH_CORES` 解析到宿主那一份

## 许可

AGPL-3.0-or-later。上游：<https://github.com/flizzywine/dsh-tavern>。
