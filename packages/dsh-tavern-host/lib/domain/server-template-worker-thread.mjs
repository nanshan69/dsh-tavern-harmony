// 端侧“模板 worker”线程入口。
//
// 上游用 child_process.fork() 跑 jsdom 模板；端侧 execPath 是 appspawn，spawn 被拒。
// 进程内执行会阻塞宿主事件循环（卡住所有 HTTP，导致“一直重新加载”、关不掉酒馆），
// 所以改成 worker_threads：模板在独立线程里跑，宿主事件循环不受影响。
//
// - process.send / process.on('message') 映射到 parentPort
// - 历史读取（原来是 fd 4 阻塞管道）改成 MessagePort 同步收发，
//   保持 engine 侧“同步调用”的语义
import { parentPort, workerData, receiveMessageOnPort } from 'node:worker_threads'

import { appendFileSync } from 'node:fs'
const __logPath = (process.env.DSH_HOME || '/data/storage/el2/base/haps/entry/files/dsh/home') + '/tavern-worker.log'
const __log = (message) => { try { appendFileSync(__logPath, new Date().toISOString() + ' ' + message + '\n') } catch { /* best effort */ } }
__log('bootstrap start; has workerData=' + (workerData !== undefined) + ' port=' + (workerData && workerData.port !== undefined))
globalThis.__dshTavernWorkerLog = __log

const port = workerData.port
const pause = new Int32Array(new SharedArrayBuffer(4))

process.send = (message) => parentPort.postMessage(message)
process.connected = true

globalThis.__dshTavernHistoryReader = (args) => {
  const startedAt = Date.now()
  port.postMessage({ type: 'history', args })
  for (;;) {
    const received = receiveMessageOnPort(port)
    if (received !== undefined) {
      const message = received.message
      __log('history done in ' + (Date.now() - startedAt) + 'ms')
      if (message && message.error) throw new Error(message.error)
      return message.result
    }
    if (Date.now() - startedAt > 6000) {
      __log('history TIMEOUT after ' + (Date.now() - startedAt) + 'ms')
      throw new Error('模板历史读取超时（宿主 6 秒未响应）')
    }
    Atomics.wait(pause, 0, 0, 2)
  }
}

// worker 模块还没导入完成时先缓存消息：initialize 通常在创建线程后立刻到达，
// 如果此时 process 上还没有 listener，直接 emit 会把消息丢掉（表现为初始化永远不开始）。
const __pending = []
let __ready = false
parentPort.on('message', (message) => {
  __log('in ' + (message && message.type))
  if (__ready) process.emit('message', message)
  else __pending.push(message)
})

// 与主线程相同的 CJS 解析兜底：DSHM 的 ResolutionRouter 在 profile 下的 CJS 包
// require 别的包时会因为缺少 createRequire(...).resolve.paths 抛错。
try {
  const moduleBuiltin = process.getBuiltinModule('node:module')
  const original = moduleBuiltin._resolveFilename
  moduleBuiltin._resolveFilename = function resolveFilename(request, parent, isMain, options) {
    try {
      return original.call(this, request, parent, isMain, options)
    } catch (error) {
      const filename = parent && parent.filename
      if (typeof filename === 'string' && filename.includes('/dsh-tavern-host/')) {
        try {
          const path = process.getBuiltinModule('node:path')
          const found = moduleBuiltin._findPath(request, moduleBuiltin._nodeModulePaths(path.dirname(filename)), isMain)
          if (found) return found
        } catch { /* 落回原始错误 */ }
      }
      throw error
    }
  }
} catch { /* worker 解析兜底失败不阻断启动 */ }

try {
  await import('./server-template-worker.js')
  __log('worker module imported')
} catch (error) {
  __log('worker import failed: ' + String(error && error.stack || error))
  throw error
}
__ready = true
for (const message of __pending.splice(0)) process.emit('message', message)
__log('pending flushed: ' + __pending.length)
