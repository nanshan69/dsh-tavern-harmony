import {serveTemplateHistoryPipe} from './template-history-pipe.js'
import { fork } from 'node:child_process'
import { randomUUID, createHash } from 'node:crypto'
import { createRequire } from 'node:module'
import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'
import { redactMvuLoadError } from './mvu-diagnostics.js'
const TEMPLATE_WORKER_THREAD = new URL('./server-template-worker-thread.mjs', import.meta.url)
// 端侧：显示同步（synchronize）在手机上经常整段卡住，会把唯一的模板线程占满 90 秒，
// 前台回合的提示词渲染排在它后面，表现就是"点重新生成要等一分钟"。
// 这里把前台要用的模板调用单独标出来，让它们能直接抢走线程。
const DISPLAY_SYNC_OPERATION = 'synchronize'
const FOREGROUND_OPERATIONS = new Set(['connect', 'initialize', 'input', 'request', 'render', 'worldbook', 'messages', 'command'])
const PREEMPT_DISPLAY_SYNC_AFTER_MS = 2500

const rpcMethods = new Set(['getFullPromptTemplateState', 'saveFullPromptTemplateState',
  'saveFullPromptTemplateSettings', 'saveFullPromptTemplateGlobals', 'countFullTemplateTokens',
  'getFullTemplateWorldbook', 'replaceFullTemplateWorldbook', 'executeTemplateHostCommand'])
const require = createRequire(import.meta.url)
const worker = fileURLToPath(new URL('./server-template-worker.js', import.meta.url))

/** Service-owned sessions. No browser leases, heartbeat, or replay of started work. */
export function createServerTemplateRuntime({ rpc, store, timeoutMs = 180000, // 端侧：jsdom(pretendToBeVisual) 空闲时也占 CPU，会话数要少、空闲要尽快回收。
  // 否则多个空闲模板线程会把设备 CPU 吃满，表现为模板渲染从 1 秒变成 2 分钟。
  idleMs = 60000, maxSessions = 4, readOnly = false, maxOldSpaceMb, onDiagnostic }) {
  const heapMb = Number(maxOldSpaceMb ?? process.env.DSH_TAVERN_TEMPLATE_HEAP_MB ?? 1024)
  if (!Number.isInteger(heapMb) || heapMb < 128 || heapMb > 4096) throw new RangeError('DSH_TAVERN_TEMPLATE_HEAP_MB 必须是 128 到 4096 之间的整数（MB）')
  const sessions = new Map(), tails = new Map(), generations = new Map(), jobs = new Map()
  const queueKind = new Map()
  // 每个会话还有多少个前台模板调用在等线程；排队中的显示同步看见它就放弃。
  const foregroundWaiting = new Map()
  const capacityWaiters = new Set()
  const wakeCapacity = () => { for (const wake of capacityWaiters) wake() }
  let disposed = false
  const journalPath = id => 'template-work/' + createHash('sha256').update(id).digest('hex') + '.json'
  const save = (id, job, failure = false) => store && (failure || !job.transient) ? store.writeJson(journalPath(id), job) : Promise.resolve()
  // 端侧没有可 spawn 的 node 可执行文件（execPath 是 appspawn，被 DSHM 拒绝），
  // 模板 worker 改为在宿主进程内执行。
  // 端侧：platform=openharmony，或者 execPath 是 appspawn（无法 spawn）
  const IN_PROCESS = process.platform === 'openharmony' || /appspawn/i.test(String(process.execPath || ''))
  async function startInProcess(sessionId, generation) {
    const { Worker, MessageChannel } = process.getBuiltinModule('node:worker_threads')
    const { port1, port2 } = new MessageChannel()
    let thread
    try {
      thread = new Worker(TEMPLATE_WORKER_THREAD, { workerData: { port: port2 }, transferList: [port2],
        // 对齐上游子进程的 --max-old-space-size：模板爆内存时只杀线程，不拖垮宿主。
        resourceLimits: { maxOldGenerationSizeMb: heapMb, maxYoungGenerationSizeMb: 32 } })
      console.log('[dsh-tavern-template] worker 线程已创建')
    } catch (error) {
      console.error('[dsh-tavern-template] worker 线程创建失败：' + String(error && error.stack || error))
      throw error
    }
    thread.on('online', () => console.log('[dsh-tavern-template] worker online'))
    thread.on('error', error => console.error('[dsh-tavern-template] worker error: ' + String(error && error.stack || error)))
    const record = { thread, sessionId, pending: new Map(), busy: true, ready: false, closed: false, usedAt: Date.now(), writes: Promise.resolve() }
    sessions.set(sessionId, record)
    // 模板线程同步读历史：宿主异步取数后从 port 回给线程。
    port1.on('message', async message => {
      if (record.closed || message === null || typeof message !== 'object' || message.type !== 'history') return
      const startedAt = Date.now()
      try {
        const result = await Promise.race([
          rpc('getPromptTemplateHistory', { sessionId, token: message.args?.token, messageId: message.args?.messageId }),
          new Promise((_, reject) => setTimeout(() => reject(new Error('模板历史读取在宿主侧超时（7 秒）')), 7000)),
        ])
        console.log('[dsh-tavern-template] history read in ' + (Date.now() - startedAt) + 'ms')
        port1.postMessage({ result })
      } catch (error) {
        console.log('[dsh-tavern-template] history read failed in ' + (Date.now() - startedAt) + 'ms: ' + String(error && error.message || error))
        port1.postMessage({ error: String(error && error.message || error) })
      }
    })
    port1.start?.()
    thread.on('message', message => {
      if (record.closed || message === null || typeof message !== 'object') return
      if (message.type === 'result') {
        const item = record.pending.get(message.id)
        if (!item) return
        record.pending.delete(message.id); clearTimeout(item.timer)
        message.error ? item.reject(new Error(message.error)) : item.resolve(message.result)
      } else if (message.type === 'rpc') {
        const startedAt = Date.now()
        const operation = record.writes.then(async () => {
          if (record.closed || !record.busy || !rpcMethods.has(message.method)) throw new Error('Unsupported or expired template RPC')
          // 防止模板引擎等宿主的 RPC 永远不返回：超时后回错误，别让 worker 线程挂死。
          const result = await Promise.race([
            rpc(message.method, { ...message.args, sessionId }),
            new Promise((_, reject) => setTimeout(() => reject(new Error('模板 RPC 超时（30 秒未返回）：' + message.method)), 30000)),
          ])
          const spent = Date.now() - startedAt
          if (spent > 3000) console.log('[dsh-tavern-template] slow rpc ' + message.method + ' in ' + spent + 'ms')
          return result
        })
        record.writes = operation.catch(() => {})
        operation.then(result => { if (!record.closed) thread.postMessage({ type: 'rpc-result', id: message.id, result }) },
          error => {
            const spent = Date.now() - startedAt
            if (spent > 3000) console.log('[dsh-tavern-template] rpc failed ' + message.method + ' in ' + spent + 'ms: ' + String(error && error.message || error))
            if (!record.closed) thread.postMessage({ type: 'rpc-result', id: message.id, error: String(error && error.message || error) })
          })
      }
    })
    thread.on('error', error => stop(record, error))
    thread.on('exit', code => {
      if (record.closed) return
      stop(record, Object.assign(new Error('服务端提示词模板线程退出 (' + code + ')，任务未重试'), { code: 'FULL_TEMPLATE_WORKER_EXIT' }))
    })
    record.initialization = request(record, { type: 'initialize', sessionId, readOnly }).then(() => { record.ready = true })
    return record
  }
  function stop(record, error) {
    if (error === undefined) {
      // 默认错误只有 dispose / 容量驱逐会走到；记录来源，避免再次出现“执行已停止”却不知道谁停的。
      console.warn('[dsh-tavern-template] stop without error, caller: ' + String(new Error().stack).split('\n').slice(1, 4).join(' | '))
      error = new Error('服务端提示词模板执行已停止')
    }
    if (sessions.get(record.sessionId) === record) sessions.delete(record.sessionId)
    record.closed = true
    clearTimeout(record.idle)
    for (const item of record.pending.values()) { clearTimeout(item.timer); item.reject(error) }
    record.pending.clear()
    if (record.thread !== undefined) { try { record.thread.terminate() } catch { /* best effort */ } } else record.child.kill('SIGKILL')
    wakeCapacity()
  }
  function request(record, message, overrideTimeoutMs) {
    if (record.closed) return Promise.reject(new Error('服务端提示词模板进程已退出'))
    return new Promise((resolve, reject) => {
      const id = randomUUID()
      const timer = setTimeout(() => stop(record, Object.assign(new Error('服务端提示词模板执行超时，已停止执行；已开始的模板不会自动重试'), { code: 'FULL_TEMPLATE_EXECUTION_TIMEOUT' })), overrideTimeoutMs || timeoutMs)
      record.pending.set(id, { resolve, reject, timer })
      if (record.thread !== undefined) record.thread.postMessage({ ...message, id })
      else record.child.send({ ...message, id }, error => { if (error) stop(record, error) })
    })
  }
  async function start(sessionId, generation) {
    while (sessions.size >= maxSessions) {
      if (disposed || generation !== generations.get(sessionId)) throw new Error('提示词模板任务已取消')
      const idle = [...sessions.values()].filter(item => !item.busy).sort((a, b) => a.usedAt - b.usedAt)[0]
      if (idle) stop(idle)
      else await new Promise((resolve, reject) => {
        const wake = () => { clearTimeout(timer); capacityWaiters.delete(wake); resolve() }
        const timer = setTimeout(() => { capacityWaiters.delete(wake); reject(new Error('服务端模板执行队列繁忙，等待超时')) }, timeoutMs)
        capacityWaiters.add(wake)
      })
    }
    if (disposed || generation !== generations.get(sessionId)) throw new Error('提示词模板任务已取消')
    if (IN_PROCESS) return startInProcess(sessionId, generation)
    // Do not inherit API keys, NODE_OPTIONS or arbitrary launch flags. File access
    // is limited to executable dependencies and plugin code, never profile data.
    const modules = dirname(dirname(require.resolve('jsdom/package.json')))
    const plugin = fileURLToPath(new URL('../../', import.meta.url))
    // Node 24 removed the experimental alias; older hosts still need it.
    const permissionFlag = process.allowedNodeEnvironmentFlags.has('--permission') ? '--permission' : '--experimental-permission'
    const child = fork(worker, [], { env: { NODE_ENV: 'production', ...(process.env.SystemRoot ? { SystemRoot: process.env.SystemRoot } : {}) },
      execArgv: [permissionFlag, '--allow-fs-read=' + plugin, '--allow-fs-read=' + modules, '--max-old-space-size=' + heapMb],
      stdio: ['ignore', 'ignore', 'pipe', 'ipc', 'pipe'], serialization: 'advanced', windowsHide: true })
    const record = { child, sessionId, pending: new Map(), busy: true, ready: false, closed: false, stderr: '', usedAt: Date.now(), writes: Promise.resolve() }
    sessions.set(sessionId, record)
    serveTemplateHistoryPipe(child.stdio[4], async args => {
      if(record.closed || !record.busy)throw Error('Expired template history read')
      return rpc('getPromptTemplateHistory',{sessionId,token:args.token,messageId:args.messageId})
    })
    child.on('error', error => stop(record, error))
    // Retain only a bounded stderr tail. Wait for stdio to close so V8's fatal
    // message is available; SIGABRT alone does not establish an OOM diagnosis.
    child.stderr.setEncoding('utf8')
    child.stderr.on('data', chunk => { record.stderr = (record.stderr + chunk).slice(-16384) })
    child.on('close', (code, signal) => {
      if (record.closed) return
      const outOfMemory = /FATAL ERROR:[^\r\n]*(?:heap out of memory|Reached heap limit|Ineffective mark-compacts near heap limit)/i.test(record.stderr)
      const diagnostic = { phase: record.ready ? 'execution' : 'initialization', exitCode: code, signal,
        heapMb, outOfMemory, stderr: redactMvuLoadError(record.stderr, 16384).slice(-8192) }
      const message = outOfMemory
        ? `服务端提示词模板内存不足（V8 老生代上限 ${heapMb} MB，${signal || code}），任务未重试`
        : `服务端提示词模板进程退出 (${signal || code})，任务未重试`
      const error = Object.assign(new Error(message), {
        code: outOfMemory ? 'FULL_TEMPLATE_OUT_OF_MEMORY' : 'FULL_TEMPLATE_WORKER_EXIT', workerDiagnostic: diagnostic
      })
      try { onDiagnostic?.(diagnostic) } catch { /* Logging cannot prevent task rejection. */ }
      stop(record, error)
    })
    child.on('message', async message => {
      if (record.closed) return
      if (message.type === 'result') {
        const item = record.pending.get(message.id)
        if (!item) return
        record.pending.delete(message.id); clearTimeout(item.timer)
        message.error ? item.reject(new Error(message.error)) : item.resolve(message.result)
      } else if (message.type === 'rpc') {
        // Bind ownership here, not to the arguments supplied by template code.
        const operation = record.writes.then(async () => {
          if (record.closed || !record.busy || !rpcMethods.has(message.method)) throw new Error('Unsupported or expired template RPC')
          return rpc(message.method, { ...message.args, sessionId })
        })
        record.writes = operation.catch(() => {})
        try {
          const result = await operation
          if (!record.closed) child.send({ type: 'rpc-result', id: message.id, result }, () => {})
        } catch (error) {
          if (!record.closed) child.send({ type: 'rpc-result', id: message.id, error: String(error.message || error) }, () => {})
        }
      }
    })
    record.initialization = request(record, { type: 'initialize', sessionId, readOnly }).then(() => { record.ready = true })
    return record
  }
  async function invoke(sessionId, operation, input, transient = false) {
    const __startedAt = Date.now()
    console.log('[dsh-tavern-template] invoke start ' + operation + (transient ? ' (transient)' : ''))
    try {
      const __result = await invokeInner(sessionId, operation, input, transient)
      console.log('[dsh-tavern-template] invoke done ' + operation + ' in ' + (Date.now() - __startedAt) + 'ms')
      return __result
    } catch (error) {
      console.log('[dsh-tavern-template] invoke failed ' + operation + ' in ' + (Date.now() - __startedAt) + 'ms: ' + String(error && error.message || error))
      throw error
    }
  }
  async function invokeInner(sessionId, operation, input, transient = false) {
    if (disposed || !sessionId) throw new Error('服务端提示词模板会话不可用')
    // 记录队列里排的是不是纯后台任务：前台任务进来时把排队中的后台任务一起作废。
    if (!transient) {
      if (queueKind.get(sessionId) === true) {
        console.log('[dsh-tavern-template] cancel queued background jobs for foreground ' + operation)
        generations.set(sessionId, randomUUID())
      }
      queueKind.set(sessionId, false)
    } else if (queueKind.get(sessionId) !== false) {
      queueKind.set(sessionId, true)
    }
    // 前台请求（回合的提示词渲染）优先：后台显示同步经常在端侧跑几分钟，
    // 如果让它占着会话队列，用户就要等很久才看到模型开始生成。
    // 做法：前台任务到来时直接停掉正在跑的后台任务，用新 worker 立即服务前台。
    const foreground = !transient || FOREGROUND_OPERATIONS.has(operation)
    if (foreground) {
      const running = sessions.get(sessionId)
      const runningFor = running !== undefined && running.currentStartedAt !== undefined ? Date.now() - running.currentStartedAt : 0
      // 显示同步只画消息外观，丢掉可以按退避重排，所以前台一等就让它让位，
      // 不用等满 90 秒超时——那 90 秒里前台什么都干不了。
      if (running !== undefined && running.closed !== true && running.currentOperation === DISPLAY_SYNC_OPERATION && runningFor > PREEMPT_DISPLAY_SYNC_AFTER_MS) {
        console.log('[dsh-tavern-template] preempt display sync (' + runningFor + 'ms) for foreground ' + operation)
        stop(running, new Error('显示同步让位前台请求（稍后重试）'))
      }
    }
    if (!transient) {
      const running = sessions.get(sessionId)
      const runningFor = running !== undefined && running.currentStartedAt !== undefined ? Date.now() - running.currentStartedAt : 0
      // 只抢占已经跑了一会儿的后台作业；刚起步的（多半 1~2 秒就完）不要打断，减少无用重试。
      if (running !== undefined && running.currentTransient === true && running.closed !== true && runningFor > 2500) {
        console.log('[dsh-tavern-template] preempt background ' + String(running.currentOperation || '') + ' (' + runningFor + 'ms) for foreground ' + operation)
        // 同时作废已排队的后台任务（generation 变化会让它们快速退出，而不是继续排队）。
        generations.set(sessionId, randomUUID())
        stop(running, new Error('后台模板任务被前台请求打断'))
      }
    }
    // Match the former JSON transport: host-only callbacks (notably random)
    // stay in the caller; randomSeed/randomRef carry deterministic evaluation.
    input = JSON.parse(JSON.stringify(input))
    if (foreground) foregroundWaiting.set(sessionId, (foregroundWaiting.get(sessionId) || 0) + 1)
    const generation = generations.get(sessionId)
    const releaseForeground = () => {
      if (!foreground) return
      const left = (foregroundWaiting.get(sessionId) || 0) - 1
      if (left > 0) foregroundWaiting.set(sessionId, left)
      else foregroundWaiting.delete(sessionId)
    }
    const pending = (tails.get(sessionId) || Promise.resolve()).catch(() => {}).then(async () => {
      if (disposed || generation !== generations.get(sessionId)) throw new Error('提示词模板任务已取消')
      // 前台还在等线程时，排在前面的显示同步直接放弃（调度方会按退避重排），
      // 否则它一跑又是 90 秒，前台等于没抢到。
      if (operation === DISPLAY_SYNC_OPERATION && (foregroundWaiting.get(sessionId) || 0) > 0) {
        console.log('[dsh-tavern-template] skip queued display sync while foreground waits')
        throw new Error('提示词模板任务已取消')
      }
      const job = { id: randomUUID(), operation, phase: 'executing', createdAt: Date.now(), transient }
      jobs.set(sessionId, job)
      let record
      try {
        await save(sessionId, job)
        if (disposed || generation !== generations.get(sessionId)) throw new Error('提示词模板任务已取消')
        record = sessions.get(sessionId) || await start(sessionId, generation)
        record.busy = true; clearTimeout(record.idle)
        record.currentTransient = transient === true
        record.currentOperation = operation
        record.currentStartedAt = Date.now()
        await record.initialization
        const result = operation === 'connect' ? undefined
          : await request(record, operation === 'synchronize' ? { type: 'synchronize' } : { type: 'project', operation, input }, transient ? 90000 : undefined)
        if (disposed || generation !== generations.get(sessionId)) throw new Error('提示词模板任务已取消')
        job.phase = 'completed'; job.completedAt = Date.now()
        await save(sessionId, job)
        return result
      } catch (error) {
        job.phase = 'interrupted'; job.error = String(error.message || error)
        if (error.workerDiagnostic) job.workerDiagnostic = error.workerDiagnostic
        // Display jobs skip routine journals, but their crashes need evidence too.
        try { await save(sessionId, job, true) }
        finally { if (record) { stop(record, error); await record.writes } }
        throw error
      } finally {
        if (record && !record.closed) {
          record.busy = false; record.currentTransient = false; record.currentOperation = ''; record.usedAt = Date.now()
          record.idle = setTimeout(() => stop(record), idleMs); record.idle.unref?.()
          wakeCapacity()
        }
        jobs.delete(sessionId)
      }
    })
    tails.set(sessionId, pending)
    try { return await pending } finally {
      releaseForeground()
      if (tails.get(sessionId) === pending) { tails.delete(sessionId); queueKind.delete(sessionId) }
    }
  }
  return {
    forSession: sessionId => ({
      historyContext: 'session',
      connect: () => invoke(sessionId, 'connect', {}, true),
      renderInput: (text, context = {}) => invoke(sessionId, 'input', { text, context }),
      prepareWorldbook: (entries, context = {}) => invoke(sessionId, 'worldbook', { entries, context }),
      prepareWorldbookProjection: (entries, context = {}) => invoke(sessionId, 'worldbook', { entries, context }, true),
      command: text => invoke(sessionId, 'command', { text }),
      render: (template, context = {}) => invoke(sessionId, 'render', { template, context }),
      renderProjection: (template, context = {}) => invoke(sessionId, 'render', { template, context }, true),
      renderProjections: (items, context = {}) => invoke(sessionId, 'renderMany', { items, context }, true),
      renderMessages: (messages, context = {}) => invoke(sessionId, 'messages', { messages, context }),
      projectRequest: request => invoke(sessionId, 'request', { request }),
      projectRequestProjection: request => invoke(sessionId, 'request', { request }, true),
      initializeVariables: (entries, context = {}) => invoke(sessionId, 'initialize', { entries, context })
    }),
    synchronize: sessionId => invoke(sessionId, 'synchronize', {}, true),
    inspect: async sessionId => {
      const record = sessions.get(sessionId)
      return { executor: 'node', heapMb, present: Boolean(record), ready: Boolean(record?.ready), busy: Boolean(record?.busy),
        phase: record?.busy ? 'executing' : 'idle', heartbeat: null, task: jobs.get(sessionId) || (store && await store.readJson(journalPath(sessionId))) || null }
    },
    cancel(sessionId) { generations.set(sessionId, randomUUID()); const record = sessions.get(sessionId); if (record) stop(record, new Error('提示词模板任务已手动取消')); wakeCapacity() },
    dispose() { disposed = true; for (const record of sessions.values()) stop(record); wakeCapacity() }
  }
}
