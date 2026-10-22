# dsh-tavern-host

酒馆的宿主侧本体。体积 99% 来自上游构建产物（`lib/**`），本包只多了一个
**端侧移植壳** `index.js`。

```
dsh-tavern-host/
├── index.js                 移植壳（解析钩子、CJS 兜底、jsdom 探针、加载超时）
├── lib/                     上游 host 运行时（vendored，已打移植补丁）
│   ├── index.js             酒馆 host 主入口（380KB）
│   ├── domain/              会话、卡片、世界书、生图、模板引擎
│   ├── vendor/              MVU、ST 模板引擎、宏解析器、前端资源
│   ├── client-assets/       tavern.css
│   └── client.js            上游前端 bundle 副本（不参与本移植运行，保留以便对照）
├── prompts/                 提示词（scene-plan.md 有追加，见 NOTICE）
└── packages/
    ├── dsh-image-gen/       生图模块（MIT，上游内嵌 fork）
    └── dsh-tavern-card-memory/
```

## 加载方式

**不要**把这个包加进启动 bundles。它由 `dsh-tavern-gate` 在用户点「打开酒馆」时
动态 `import()` 并 `ctx.plugin()` 挂载；`tavern-host-entry.js`（在 gate 包里）
负责把本包的 `name / inject / apply` 转出去。

## 壳做了什么

1. `registerHooks`：本包内的 `@deepseek-ai/*` 解析到宿主核心目录（不复制实例）。
2. `Module._resolveFilename` 兜底：端侧缺 `resolve.paths`，jsdom 依赖树会整片失败。
3. `createRequire('jsdom')` 探针：失败只告警，不阻断启动。
4. `import('./lib/index.js')` 加 90 秒超时，过程写 `$DSH_HOME/tavern-load.log`。
5. 设置 `DSH_HOME`（端侧 Host 不一定导出它）。

路径全部从 `import.meta.url` 推导：`<home>/profiles/<profile>/node_modules/dsh-tavern-host/`。
可用 `DSH_HOME` / `DSH_CORES` 覆盖。

## 依赖

`package.json` 里列了运行时要的包（jsdom、marked、yaml、acorn、chevrotain、
@jsquash/*、mathjs、ws、zod）。**不随仓库分发**，装法见 `docs/安装.md`。
依赖可以放在本包自己的 `node_modules/`，也可以放在 profile 的 `node_modules/`
（Node 会向上查找）。

## 许可

AGPL-3.0-or-later（`packages/dsh-image-gen` 为 MIT，见包内 LICENSE）。
上游：<https://github.com/flizzywine/dsh-tavern>。
