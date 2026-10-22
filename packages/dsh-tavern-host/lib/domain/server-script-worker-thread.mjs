// 端侧“卡脚本运行时”线程入口。
//
// 上游用 child_process.fork() 跑 headless 卡脚本（jsdom + vm.SourceTextModule）；
// 端侧 execPath 是 appspawn，spawn 被拒。这里改成 worker_threads，
// 保持与子进程版相同的 IPC 协议：fetch 请求/应答、signal 转发、log。
import { parentPort, workerData } from 'node:worker_threads'

import { appendFileSync } from 'node:fs'
const __logPath = (process.env.DSH_HOME || '/data/storage/el2/base/haps/entry/files/dsh/home') + '/tavern-script-worker.log'
const __log = (message) => { try { appendFileSync(__logPath, new Date().toISOString() + ' ' + message + '\n') } catch { /* best effort */ } }
__log('script worker bootstrap; execArgv=' + JSON.stringify(process.execArgv))

process.send = (message) => { try { parentPort.postMessage(message) } catch { /* channel closed */ } }
process.connected = true

// worker 模块导入完成前先缓存消息，避免 start 早到被丢掉。
const pending = []
let ready = false
parentPort.on('message', (message) => {
  if (ready) process.emit('message', message)
  else pending.push(message)
})

// 与主线程相同的 CJS 解析兜底（DSHM 的 ResolutionRouter 缺陷）。
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
} catch { /* 解析兜底失败不阻断 */ }

try {
  await import('./server-script-worker.js')
  __log('script worker module imported; vm.SourceTextModule=' + (typeof process.getBuiltinModule('node:vm').SourceTextModule))
} catch (error) {
  __log('script worker import failed: ' + String(error && error.stack || error))
  throw error
}
ready = true
for (const message of pending.splice(0)) process.emit('message', message)
__log('script worker ready, flushed ' + pending.length)
