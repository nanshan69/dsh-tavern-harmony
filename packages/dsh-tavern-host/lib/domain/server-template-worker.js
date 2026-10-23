import {createTemplateHistoryPipeClient} from './template-history-pipe.js'
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
const lazyRequire = createRequire(import.meta.url)
const jsdomModule = () => lazyRequire('jsdom')

import { estimateWorldBookTokens } from './worldbook-activation.js'

// Templates live in this disposable process, never in the service's JS realm.
// jsdom supplies browser APIs; it is not the process isolation boundary.
let session, dom, sequence = 0
const pending = new Map()
const send = message => { if (process.connected) process.send(message) }
const rpc = (method, args) => {
  // Upstream schedules token statistics after returning its operation receipt.
  // This pure estimate needs no session lease: calculate it here, using the
  // same estimator as the host, without admitting expired state-changing RPCs.
  if (method === 'countFullTemplateTokens') return Promise.resolve({ tokens: estimateWorldBookTokens(args.text), estimator: 'unicode-estimate' })
  return new Promise((resolve, reject) => {
    const id = ++sequence
    pending.set(id, { resolve, reject })
    send({ type: 'rpc', id, method, args })
  })
}
rpc.readHistory = globalThis.__dshTavernHistoryReader ?? createTemplateHistoryPipeClient()
async function initialize(sessionId, readOnly = false) {
  const L = globalThis.__dshTavernWorkerLog || (() => {})
  L('init: start')
  dom = new (jsdomModule().JSDOM)('<!doctype html><div id="extensions_settings"></div>', {
    url: 'https://template.invalid/', runScripts: 'outside-only', pretendToBeVisual: true,
    virtualConsole: new (jsdomModule().VirtualConsole)()
  })
  L('init: jsdom constructed')
  const w = dom.window
  // 端侧 jitless：jsdom 窗口里没有 WebAssembly。引擎只拿它加载 xxhash-wasm 做显示缓存哈希。
  // 这里**故意**返回永不落定的 Promise（不会产生 unhandled rejection 把 worker 线程打挂）；
  // 显示同步那一侧的 await 在 engine.js 里加了 300ms 超时 + 纯 JS 哈希兜底，
  // 所以不会再出现"每条同步都卡满 90 秒"。
  if (typeof w.WebAssembly === 'undefined') {
    const unavailable = () => new Promise(() => {})
    w.WebAssembly = { instantiate: unavailable, compile: unavailable, validate: () => false }
  }
  Object.assign(w, { structuredClone, TextEncoder, TextDecoder, fetch, AbortController, AbortSignal })
  if (readOnly) {
    const blocked = () => { throw new Error('人物卡更新预览不允许网络请求') }
    w.fetch = blocked
    w.XMLHttpRequest = class { constructor() { blocked() } }
    w.WebSocket = class { constructor() { blocked() } }
    w.navigator.sendBeacon = blocked
  }
  w.toastr = Object.fromEntries(['error', 'warning', 'info', 'success'].map(name => [name, () => {}]))
  for (const file of ['../vendor/runtime-assets/jquery/jquery.min.js', '../vendor/runtime-assets/lodash/lodash.min.js', '../vendor/st-prompt-template/server-artifact/engine.js']) {
    const startedAt = Date.now()
    L('init: read ' + file)
    const source = await readFile(new URL(file, import.meta.url), 'utf8')
    L('init: read done ' + source.length + 'B in ' + (Date.now() - startedAt) + 'ms')
    w.eval(source)
    L('init: eval done in ' + (Date.now() - startedAt) + 'ms')
  }
  L('init: createServerTemplateSession')
  session = await w.DSHTemplate.createServerTemplateSession({ sessionId, rpc,
    settingsHtml: await readFile(new URL('../vendor/st-prompt-template/upstream/settings.html', import.meta.url), 'utf8') })
  L('init: session ready')
}
process.on('message', async message => {
  if (message.type === 'rpc-result') {
    const item = pending.get(message.id)
    if (!item) return
    pending.delete(message.id)
    message.error ? item.reject(new Error(message.error)) : item.resolve(message.result)
    return
  }
  try {
    let result
    if (message.type === 'initialize') await initialize(message.sessionId, message.readOnly)
    else if (message.type === 'project') result = await session.project(message.operation, message.input)
    else if (message.type === 'synchronize') result = await session.synchronize()
    else throw new Error('Unknown server template operation')
    send({ type: 'result', id: message.id, result })
  } catch (error) { send({ type: 'result', id: message.id, error: String(error.message || error) }) }
})
process.on('disconnect', () => process.exit(0))
