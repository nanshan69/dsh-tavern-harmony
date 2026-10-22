# dsh-tavern-remote

把酒馆宿主侧的 `tavernSessionSignals` 通过 DSH 的 **typert** 远程服务暴露给前端：
`follow(sessionIds)` 是流，`control(method, args)` 也是流。前端靠它拿
`tavern-state` 更新（候选任务、场景生图、后台结算的进度）。

## 为什么必须是独立的启动行

- `typert` 只在启动期注册远程服务；运行时加载的插件行拿不到这个时机。
- 所以它必须出现在 profile 的 `dsh.profile.bundles` 里，作为启动行存在。
- 它 `static inject = ['typert']`，但 `tavernSessionSignals` 是**运行时**才由
  `dsh-tavern-host` provide 的 —— 服务出现前这行是 pending，出现后自动激活，
  前端随之加载。这就是「点开酒馆要等半秒再刷新」的原因。

## 本移植的改动（相对上游）

只有 `lib/index.js` 的几十字节：两处服务访问从属性读取改成 `ctx.get(...)`。
上游是 `this.ctx.tavernSessionSignals.follow(...)`，本移植里服务被 provide 到
`ctx.root`，兄弟行通过属性读不到，必须用 `get`：

```js
follow(sessionIds, signal) {
  return (this.ctx.get ? this.ctx.get('tavernSessionSignals') : this.ctx.tavernSessionSignals)
    .follow(sessionIds, signal)
}
```

`lib/client.js`（153KB，前端模块）与上游完全一致，未改。

## 构建

上游用 tsdown + tsc（`pnpm build`）。仓库里带的是**构建产物**，改 `src/` 后需要在
电脑上重新构建，再把 `lib/` 拷回来：

```bash
pnpm install
pnpm build
```

## 依赖

- `zod`（安装器会从 `dsh-tavern-host` 的依赖里复制过来）
- peer：`@deepseek-ai/cordis`、`@deepseek-ai/dsh-api-gateway`、`@deepseek-ai/dsh-typert-protocol`
  （都解析到宿主的核心实例，不要复制）

## 许可

AGPL-3.0-or-later。上游：<https://github.com/flizzywine/dsh-tavern>。
