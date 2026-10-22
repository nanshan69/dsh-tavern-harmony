// dsh-tavern-host —— 端侧移植壳（由 dsh-tavern-gate 在运行时加载）
//
// 顺序很重要：
// 1. 注册 ESM 解析钩子：把 tavern 里所有 `@deepseek-ai/*` 的 import
//    以「核心目录」为基准解析，指回宿主正在用的那一份（不复制、不产生第二份实例）
// 2. 补一个 DSH_HOME
// 3. 动态 import 真正的 lib/index.js，并记录加载进度（卡住时能看出卡在哪个文件）
import { registerHooks } from 'node:module'
import { pathToFileURL, fileURLToPath } from 'node:url'
import { readdirSync, statSync, existsSync, appendFileSync } from 'node:fs'
import { join, resolve } from 'node:path'

export const name = 'dsh-tavern'
export const inject = [
  'fs', 'llm', 'webServer', 'tools', 'skills', 'agentDefaultModel',
  'sandboxPolicy', 'shell', 'agentPresets', 'settings', 'tokenMeter',
]

// 路径从本文件位置推导：<home>/profiles/<profile>/node_modules/dsh-tavern-host/index.js
const PROFILE_DIR = fileURLToPath(new URL('../..', import.meta.url))
const DSH_HOME = process.env.DSH_HOME || resolve(PROFILE_DIR, '../..')
const CORES = process.env.DSH_CORES || resolve(DSH_HOME, '../cores')
const PROGRESS = join(DSH_HOME, 'tavern-load.log')

function log(line) {
  try { appendFileSync(PROGRESS, new Date().toISOString() + ' ' + line + '\n') } catch {}
}

console.log('[dsh-tavern-host] module evaluated')

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

function installHook() {
  if (globalThis.__dshTavernHostHook === true) return
  globalThis.__dshTavernHostHook = true
  const core = findCoreDir()
  if (core === undefined) {
    console.warn('[dsh-tavern-host] 找不到核心目录，@deepseek-ai 解析可能失败')
    return
  }
  const coreParent = pathToFileURL(join(core, 'package.json')).href
  registerHooks({
    resolve(specifier, context, nextResolve) {
      const parent = context.parentURL ?? ''
      if (specifier.startsWith('@deepseek-ai/') && parent.includes('/node_modules/dsh-tavern-host/')) {
        return nextResolve(specifier, { ...context, parentURL: coreParent })
      }
      return nextResolve(specifier, context)
    },
    load(url, context, nextLoad) {
      if (url.includes('/dsh-tavern-host/')) log('load ' + url.split('/dsh-tavern-host/')[1])
      return nextLoad(url, context)
    },
  })
  console.log('[dsh-tavern-host] 核心包解析钩子已注册 → ' + core)
}

// DSHM 的 ResolutionRouter 在“profile 里的 CJS 包 require 另一个包”时，
// 会调用 createRequire(parent).resolve.paths —— 端侧 Node 构建里这个 API 缺失，
// 直接抛 TypeError，导致 jsdom 这类 CJS 依赖树整个加载失败。
// 这里给 _resolveFilename 加一层兜底：DSH 那层失败时，用 Node 自己的 _findPath 重新找。
function installCjsResolutionFallback() {
  const moduleBuiltin = process.getBuiltinModule('node:module')
  if (moduleBuiltin.__dshTavernCjsFallback === true) return
  moduleBuiltin.__dshTavernCjsFallback = true
  const original = moduleBuiltin._resolveFilename
  if (typeof original !== 'function') return
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
  console.log('[dsh-tavern-host] CJS 解析兜底已安装')
}

export async function apply(ctx) {
  console.log('[dsh-tavern-host] apply start')
  log('--- apply start ---')
  installHook()
  installCjsResolutionFallback()
  // 探针：确认真实 jsdom 能在端侧 CJS 加载路径上装起来（模板引擎依赖它）。
  try {
    const { createRequire } = process.getBuiltinModule('node:module')
    const jsdom = createRequire(import.meta.url)('jsdom')
    log('jsdom require ok: JSDOM=' + typeof jsdom.JSDOM)
    console.log('[dsh-tavern-host] jsdom 加载成功：JSDOM=' + typeof jsdom.JSDOM)
  } catch (error) {
    log('jsdom require failed: ' + String(error?.stack ?? error))
    console.error('[dsh-tavern-host] jsdom 加载失败：' + String(error?.message ?? error))
  }
  if (process.env.DSH_HOME === undefined || process.env.DSH_HOME === '') process.env.DSH_HOME = DSH_HOME

  const started = Date.now()
  let mod
  try {
    mod = await Promise.race([
      import('./lib/index.js'),
      new Promise((_, reject) => setTimeout(() => reject(new Error('import timeout after 90s')), 90000)),
    ])
  } catch (error) {
    log('IMPORT FAILED after ' + (Date.now() - started) + 'ms: ' + String(error?.stack ?? error))
    console.error('[dsh-tavern-host] lib/index.js 导入失败：' + String(error?.stack ?? error))
    return
  }
  log('imported in ' + (Date.now() - started) + 'ms')
  console.log('[dsh-tavern-host] lib/index.js 已导入，交给酒馆 apply')
  try {
    const result = await mod.apply(ctx)
    log('apply resolved')
    console.log('[dsh-tavern-host] 酒馆 apply 已完成')
    return result
  } catch (error) {
    log('APPLY FAILED: ' + String(error?.stack ?? error))
    console.error('[dsh-tavern-host] 酒馆 apply 失败：' + String(error?.stack ?? error))
  }
}
