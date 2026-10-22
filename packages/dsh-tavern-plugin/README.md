# dsh-tavern-plugin

只做一件事：让酒馆**前端 bundle** 有一个加载行。

`client.js`（约 2MB）是上游 `tavern-plugin/lib/client.js` 的预编译产物，
本仓库对它的改动只有 4 处（见 `patches/upstream/0001-tavern-client-dshm.patch`）：

1. **开关守卫**：factory 开头同步问 `/api/tavern-gate/status`，门没开就直接
   `apply = () => {}` 返回 —— 酒馆关闭时前端一行逻辑都不执行。
2. 候选行动 `submitTask` 的客户端超时 2s → **15s**（端侧后台结算繁忙时会超）。
3. 侧栏新增「场景生图」标签页（渲染已有的 `SceneImageSettings`）。
4. 开机补丁已装时，补发 `confirmSessionPatch` 握手，避免编辑/回退被判未就绪。

`index.js` 是空实现（`apply() {}`）。真正的 host 逻辑在 `dsh-tavern-host` 里，
由 `dsh-tavern-gate` 在运行时加载。分成两个包是上游的结构：前端 bundle 需要
自己的一行才能进入 `dsh-client-modules` 的扫描表。

## 重新构建

`client.js` 由上游 `node bin/build-tavern-client.mjs` 生成。要重新构建：

1. 取上游仓库对应提交（见根目录 `NOTICE.md`）
2. `node bin/build-tavern-client.mjs`
3. 按 `patches/upstream/0001-tavern-client-dshm.patch` 打上本移植的 4 处改动

## 依赖

- `dsh-tavern-gate`：必须一起装（前端守卫问的就是它）
- `dsh-better-sidebar`：侧栏标签页宿主，酒馆强依赖

## 许可

AGPL-3.0-or-later。上游：<https://github.com/flizzywine/dsh-tavern>。
