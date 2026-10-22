// 进程内版“服务端模板 worker”。
//
// 上游默认用 child_process.fork() 起一个 disposable 子进程跑 jsdom + EJS 模板；
// 端侧 process.execPath 是 /system/bin/appspawn，被 DSHM 明确禁止 spawn（EACCES），
// 所以这里把 worker 的逻辑搬到宿主进程内执行：
// - 同样的 jsdom 环境与 vendor 引擎
// - RPC 走宿主的 rpc()（带同样的白名单与 session 绑定）
// - 历史读取直接回调，不再走 fd 4 阻塞管道
import { readFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
const lazyRequire = createRequire(import.meta.url)
import { estimateWorldBookTokens } from './worldbook-activation.js'

export function createInProcessTemplateWorker({ sessionId, call, readHistory }) {
  let dom = null
  let session = null
  let disposed = false

  const rpc = (method, args) => {
    if (method === 'countFullTemplateTokens') {
      return Promise.resolve({ tokens: estimateWorldBookTokens(args.text), estimator: 'unicode-estimate' })
    }
    return call(method, args)
  }
  rpc.readHistory = readHistory

  async function initialize(readOnly = false) {
    const jsdom = lazyRequire('jsdom')
    const JSDOM = jsdom.JSDOM
    const VirtualConsole = jsdom.VirtualConsole
    dom = new JSDOM('<!doctype html><div id="extensions_settings"></div>', {
      url: 'https://template.invalid/', runScripts: 'outside-only', pretendToBeVisual: true,
      virtualConsole: new VirtualConsole(),
    })
    const w = dom.window
    Object.assign(w, { structuredClone, TextEncoder, TextDecoder, fetch, AbortController, AbortSignal })
    if (readOnly) {
      const blocked = () => { throw new Error('人物卡更新预览不允许网络请求') }
      w.fetch = blocked
      w.XMLHttpRequest = class { constructor() { blocked() } }
      w.WebSocket = class { constructor() { blocked() } }
      w.navigator.sendBeacon = blocked
    }
    w.toastr = Object.fromEntries(['error', 'warning', 'info', 'success'].map((name) => [name, () => {}]))
    for (const file of ['../vendor/runtime-assets/jquery/jquery.min.js', '../vendor/runtime-assets/lodash/lodash.min.js', '../vendor/st-prompt-template/server-artifact/engine.js']) {
      w.eval(await readFile(new URL(file, import.meta.url), 'utf8'))
    }
    session = await w.DSHTemplate.createServerTemplateSession({
      sessionId,
      rpc,
      settingsHtml: await readFile(new URL('../vendor/st-prompt-template/upstream/settings.html', import.meta.url), 'utf8'),
    })
  }

  return {
    async handle(message) {
      if (disposed) throw new Error('服务端提示词模板运行时已停止')
      if (message.type === 'initialize') {
        await initialize(message.readOnly === true)
        return undefined
      }
      if (session === null) throw new Error('服务端提示词模板尚未初始化')
      if (message.type === 'project') return await session.project(message.operation, message.input)
      if (message.type === 'synchronize') return await session.synchronize()
      throw new Error('Unknown server template operation')
    },
    dispose() {
      disposed = true
      try { dom?.window?.close() } catch { /* jsdom close is best effort */ }
      dom = null
      session = null
    },
  }
}
