function object(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value : {}
}

function text(value) {
  return typeof value === 'string' ? value.trim() : ''
}

export function normalizeBackgroundModel(value) {
  if (value === null || value === undefined) return null
  const input = object(value)
  const provider = text(input.provider)
  const model = text(input.model)
  if (provider === '' || model === '') return null
  const reasoningEffort = text(input.reasoningEffort)
  return { provider, model, ...(reasoningEffort ? { reasoningEffort } : {}) }
}

export function configuredChatBackgroundModel(chat, settings) {
  const game = object(chat)
  const config = object(settings)
  // A global change supersedes every older game selection. A later per-game
  // choice remains in effect until the next global model/effort change.
  if (config.backgroundModelRevision && game.backgroundModelRevision !== config.backgroundModelRevision) {
    return normalizeBackgroundModel(config.backgroundModel)
  }
  return normalizeBackgroundModel(game.backgroundModelSelection)
}

export function resolveChatBackgroundModel(chat, fallback, settings) {
  const configured = configuredChatBackgroundModel(chat, settings)
  const route = normalizeBackgroundModel(configured || fallback)
  // 端侧优化：后台任务（候选项/结算等）没有单独配置模型时会继承前台模型，
  // 前台用户常把思考强度开到 High/Max，导致候选项和结算也想很久。
  // 继承 DeepSeek 模型时把思考强度降到 low（显式配置的后台模型保持原样）。
  if (configured === null && route !== null && route.reasoningEffort !== undefined &&
      (route.reasoningEffort === 'high' || route.reasoningEffort === 'max') &&
      /deepseek/i.test(route.model)) {
    return { ...route, reasoningEffort: 'low' }
  }
  return route
}

export async function readBackgroundModelReasoning(llm, selection) {
  const route = normalizeBackgroundModel(selection)
  if (!route) throw new Error('后台模型配置无效')
  // Older hosts can still select models, but cannot advertise reasoning levels.
  if (typeof llm.resolveModelInfo !== 'function') return null
  const info = await llm.resolveModelInfo(route.provider, route.model)
  return info.reasoning || null
}
