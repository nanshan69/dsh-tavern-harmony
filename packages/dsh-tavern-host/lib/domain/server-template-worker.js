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
  // 端侧 jitless：全局没有 WebAssembly。模板引擎只用它加载 xxhash-wasm 做缓存哈希，
  // 加载失败本就有纯 JS 兜底；这里给一个“总是失败”的桩，让它走 catch 分支，
  // 而不是抛 ReferenceError 把 worker 线程打挂。
  if (typeof w.WebAssembly === 'undefined') {
    // 返回“永挂起”的 Promise：引擎的 await 停在原地，xxhash 保持 null，
    // 它自带的纯 JS 哈希兜底会被使用；不产生 rejection，避免 unhandled 打挂线程。
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
