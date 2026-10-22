# dsh-tavern-presets

登记两个 agent preset（以及它们的子插件行）：

| preset id | 说明 |
| --- | --- |
| `tavern` | 酒馆模式：persona + 卡片工作台工具 + Skill + 压缩 |
| `tavern-background` | 后台结算用的最小 preset：只有 Skill、联网搜索、压缩 |

**注意**：preset 里的每个子插件行都必须用**设备上的绝对路径**指向
核心目录（`@deepseek-ai/*`）和酒馆包，才能和宿主共用同一份模块实例。
所以仓库里只放模板 `cordis.patch.yml.tmpl`，安装器会把
`{{CORE_DIR}}`、`{{PROFILE_DIR}}` 替换成实际路径后生成
`cordis.patch.yml`。

占位符：

| 占位符 | 安装后的值 |
| --- | --- |
| `{{CORE_DIR}}` | `$DSH_HOME/../cores/<当前核心版本>` |
| `{{PROFILE_DIR}}` | `$DSH_HOME/profiles/ondevice` |

## 压缩配置

两个 preset 都把 `compaction-basic` 的 `thresholdRatio` 设成 `0.5`。
端侧模板引擎 CPU 很贵，上下文越大，每一轮的模板渲染越慢；默认的
`0.8` 在 1M 窗口的模型上几乎不会触发（要 ~80 万 token），会话会一直拖着。
`0.5` 更早压缩，代价是摘要调用会多几次。可按需在设置里改。

## 许可

AGPL-3.0-or-later。上游：<https://github.com/flizzywine/dsh-tavern>。
