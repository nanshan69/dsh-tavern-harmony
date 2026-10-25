// dsh-tavern-gate — host 半边（开关载体）
//
// 职责只有一个：在「运行时」加载/卸载酒馆本体，绝不把它写进启动配置。
// - 启动时：这个文件被执行，只注册两个 HTTP 路由（约 80 行），不加载酒馆
// - 点「打开酒馆」：才 import 酒馆的 host 入口并 ctx.plugin() 挂载
// - 点「关闭酒馆」/ 重启：dispose，酒馆代码从内存消失
// - 不写任何持久状态：重启后一定是关的
import { pathToFileURL, fileURLToPath } from 'node:url'
import { registerHooks } from 'node:module'
import { readdirSync, statSync, existsSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { syncBundledSkills } from './skills-sync.js'

export const name = 'dsh-tavern-gate'
// 只 inject 明确存在的服务；sessionPersistence/sessionQuery 用 ctx.get 可选取，
// 避免服务名不存在时整行 pending。
export const inject = ['webServer']

// 酒馆 host 入口。酒馆没装时这里不存在，toggle 会如实返回“未安装”，不会抛。
const HOST_ENTRY = new URL('./tavern-host-entry.js', import.meta.url).pathname

// ── 核心包解析钩子（启动期安装，先于下面这些第三方包加载）──
// 让 dsh-tavern-host / dsh-better-sidebar / dsh-tavern-remote 里的
// `@deepseek-ai/*` 以核心目录为基准解析，拿到和宿主完全相同的模块实例。
// 路径从本文件位置推导：<home>/profiles/<profile>/node_modules/dsh-tavern-gate/index.js
// 需要时可用 DSH_HOME / DSH_CORES 覆盖。
const PROFILE_DIR = fileURLToPath(new URL('../..', import.meta.url))
const HOME_DIR = process.env.DSH_HOME || resolve(PROFILE_DIR, '../..')
const CORES = process.env.DSH_CORES || resolve(HOME_DIR, '../cores')
const THIRD_PARTY_DIRS = [
  '/node_modules/dsh-tavern-host/',
  '/node_modules/dsh-better-sidebar/',
  '/node_modules/dsh-tavern-remote/',
]
function findCoreDir() {
  let best
  let bestTime = -1
  for (const name of readdirSync(CORES)) {
    const dir = join(CORES, name)
    const marker = join(dir, 'node_modules', '@deepseek-ai', 'dsh-tools', 'package.json')
    if (!existsSync(marker)) continue
    const time = statSync(marker).mtimeMs
    if (time > bestTime) { bestTime = time; best = dir }
  }
  return best
}
function installCoreHook() {
  if (globalThis.__tavernGateCoreHook === true) return
  globalThis.__tavernGateCoreHook = true
  const core = findCoreDir()
  if (core === undefined) {
    console.warn('[tavern-gate] 找不到核心目录，@deepseek-ai 解析可能失败')
    return
  }
  const coreParent = pathToFileURL(join(core, 'package.json')).href
  registerHooks({
    resolve(specifier, context, nextResolve) {
      const parent = context.parentURL ?? ''
      if (specifier.startsWith('@deepseek-ai/') && THIRD_PARTY_DIRS.some((dir) => parent.includes(dir))) {
        return nextResolve(specifier, { ...context, parentURL: coreParent })
      }
      return nextResolve(specifier, context)
    },
  })
  console.log('[tavern-gate] 核心包解析钩子已注册 → ' + core)
}
// 模块求值阶段就装：加载器按行 import，门在 bundles 里排在第三方包前面。
installCoreHook()

// ── 开机健康标记 ──
// 每次启动先写 attemptAt；事件循环健康地活过 1.5 秒才写 okAt。
// 它不是开关的一部分（开关状态只在内存里），只是排障线索：
// doctor.py / 故障排查 会读它判断「上次启动是否被卡住」。
const BOOT_MARKER = join(HOME_DIR, 'tavern-boot.json')
function markBoot() {
  try {
    const fs = process.getBuiltinModule('node:fs')
    let previous = {}
    try { previous = JSON.parse(fs.readFileSync(BOOT_MARKER, 'utf8')) } catch {}
    const attemptAt = Date.now()
    fs.writeFileSync(BOOT_MARKER, JSON.stringify({ attemptAt, okAt: previous.okAt || 0 }))
    setTimeout(() => {
      try { fs.writeFileSync(BOOT_MARKER, JSON.stringify({ attemptAt, okAt: Date.now() })) } catch {}
    }, 1500).unref?.()
  } catch (error) {
    console.warn('[tavern-gate] 写开机标记失败：' + String(error?.message ?? error))
  }
}
markBoot()

// B 方案：开机时只装「会话补丁」，酒馆本体保持关闭。
// 补丁负责正文编辑/回退/重新生成的会话格式兼容，必须在任何会话打开之前装好；
// 酒馆被点开时直接复用这个句柄，不再重复安装。
async function installSessionPatchAtBoot(ctx) {
  try {
    const mod = await import(new URL('../dsh-tavern-host/lib/domain/host-session-patch.js', import.meta.url).href)
    const patch = await mod.installHostSessionPatch({
      persistence: ctx.get('sessionPersistence'),
      query: ctx.get('sessionQuery'),
    })
    globalThis.__tavernGateSessionPatch = patch
    console.log('[tavern-gate] 会话补丁：' + patch.status + (patch.status === 'failed' ? '（' + patch.reason + '）' : ''))
  } catch (error) {
    console.warn('[tavern-gate] 会话补丁安装失败：' + String(error && error.stack || error))
  }
}

// ── 内置技能铺开 ──
// 本包带一个 skills/；安装/升级后由这里铺到 <home>/skills，新设备不用手工装。
// 幂等：内容相同不写盘；不同则先备份到 <home>/skills-backup/<时间戳>/。
function syncSkillsAtBoot() {
  try {
    // 技能放在本包（dsh-tavern-gate/skills）：自举铺包、方式 B 覆盖 packages/* 时
    // 都会一起刷新，所以它是「永远存在且最新」的那一份。旧布局（根包 skills/）作兜底。
    let source = join(PROFILE_DIR, 'node_modules', 'dsh-tavern-gate', 'skills')
    if (!existsSync(source)) source = join(PROFILE_DIR, 'node_modules', 'dsh-tavern-harmony', 'skills')
    if (!existsSync(source)) return
    const report = syncBundledSkills({
      source,
      target: join(HOME_DIR, 'skills'),
      backupRoot: join(HOME_DIR, 'skills-backup'),
      preserve: ['ohos-'],
    })
    if (report.copied > 0 || report.backed > 0) {
      console.log('[tavern-gate] 已同步内置技能：' + JSON.stringify(report))
    }
  } catch (error) {
    console.warn('[tavern-gate] 内置技能同步失败：' + String(error && error.message || error))
  }
}

export async function apply(ctx) {
  syncSkillsAtBoot()
  await installSessionPatchAtBoot(ctx)
  const webServer = ctx.get('webServer')
  if (webServer === undefined) {
    console.warn('[tavern-gate] 没有 webServer 服务，开关不可用')
    return
  }

  const state = { loaded: false, error: '' }
  let fiber

  async function enable() {
    if (fiber !== undefined) return
    try {
      const mod = await import(pathToFileURL(HOST_ENTRY).href)
      fiber = ctx.plugin(mod)
      // 等酒馆的 apply 真正跑完（它会 provide 宿主侧的 tavernSessionSignals，
      // dsh-tavern-remote 这个启动行要靠这个服务才能激活，进而它的前端才会被加载）。
      if (fiber !== undefined && typeof fiber.await === 'function') await fiber.await()
      // 再给依赖它的行一点时间落定，然后前端才刷新，保证刷新时 remote 的 client 已在图里。
      await new Promise((resolve) => setTimeout(resolve, 500))
      state.loaded = true
      state.error = ''
    } catch (error) {
      state.loaded = false
      state.error = String(error && error.message ? error.message : error)
      console.warn('[tavern-gate] 加载酒馆失败：' + state.error)
    }
  }

  async function disable() {
    const current = fiber
    fiber = undefined
    state.loaded = false
    state.error = ''
    if (current !== undefined) {
      try { await current.dispose() } catch (error) {
        console.warn('[tavern-gate] 卸载酒馆失败：' + String(error && error.message ? error.message : error))
      }
    }
  }

  const handler = async (req, res) => {
    const url = new URL(req.url ?? '/', 'http://localhost')
    const send = (code, body) => {
      res.writeHead(code, { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store' })
      res.end(JSON.stringify(body))
    }
    if (url.pathname === '/api/tavern-gate/status') {
      if (req.method !== 'GET') return send(405, { error: 'method' })
      return send(200, { loaded: state.loaded, error: state.error })
    }
    if (url.pathname === '/api/tavern-gate/session-patch-client') {
      if (req.method !== 'GET') return send(405, { error: 'method' })
      const patch = globalThis.__tavernGateSessionPatch
      const source = patch !== undefined && patch.serverReady === true && typeof patch.clientSource === 'string' ? patch.clientSource : ''
      return send(200, { source, status: patch !== undefined ? patch.status : 'missing' })
    }
    if (url.pathname === '/api/tavern-gate/toggle') {
      if (req.method !== 'POST') return send(405, { error: 'method' })
      const on = url.searchParams.get('on') === '1'
      if (on) await enable()
      else await disable()
      return send(200, { loaded: state.loaded, error: state.error })
    }
    return send(404, { error: 'not found' })
  }

  ctx.effect(() => webServer.register({ kind: 'prefix', path: '/api/tavern-gate', handler }), 'tavern-gate: routes')
  // 插件被卸载时把酒馆一起卸掉，避免留下悬空引用。
  ctx.effect(() => () => { void disable() })
}
