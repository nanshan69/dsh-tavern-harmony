// dsh-tavern-harmony —— 「贴链接就能装」的自举入口（host 半边）
//
// 这个文件是仓库根包的主入口。DSHM 的插件安装器把本仓库当**一个包**装进
// <profile>/node_modules/dsh-tavern-harmony/，并登记 cordis.patch.yml 里的
// 那一行（id: tavern-harmony-bootstrap）。首次启动时本文件执行：
//
//   1. 把仓库里 vendored 的 5 个包铺到 <profile>/node_modules/（同盘复制，秒级）
//   2. 如果依赖被装到了本包自己的 node_modules 里，把它们链接/复制到 profile 级
//   3. 渲染 dsh-tavern-presets/cordis.patch.yml（把占位符换成设备真实路径）
//   4. 更新 profile package.json 的 dsh.profile.bundles：去掉自己，登记 6 行
//   5. 补 home patch 的 permission 默认值
//   6. 当场加载 dsh-tavern-gate —— 本次启动就能用「酒馆：关」按钮
//
// 之后本行不再存在，一切按普通安装的路径加载。幂等：已铺开时只加载门。
import { existsSync, mkdirSync, cpSync, readFileSync, writeFileSync, symlinkSync,
         readdirSync, appendFileSync, copyFileSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { join, resolve } from 'node:path'

export const name = 'tavern-harmony-bootstrap'
// 只依赖 webServer：门自己会等它需要的服务。
export const inject = ['webServer']

// <home>/profiles/<profile>/node_modules/dsh-tavern-harmony/index.js
const PKG_ROOT = fileURLToPath(new URL('.', import.meta.url))
const PROFILE_DIR = fileURLToPath(new URL('../..', import.meta.url))
const HOME_DIR = process.env.DSH_HOME || resolve(PROFILE_DIR, '../..')
const CORES_DIR = process.env.DSH_CORES || resolve(HOME_DIR, '../cores')
const NM = join(PROFILE_DIR, 'node_modules')
const LOG = join(HOME_DIR, 'tavern-bootstrap.log')
const MARKER = join(HOME_DIR, 'tavern-harmony-boot.json')

const PACKAGES = ['dsh-tavern-gate', 'dsh-tavern-host', 'dsh-tavern-plugin',
                  'dsh-tavern-remote', 'dsh-tavern-presets']
const SELF = 'dsh-tavern-harmony'
const OWN_ROWS = [SELF, ...PACKAGES]
const OPTIONAL = ['dsh-better-sidebar', 'dsh-dream-skin']

const SKIP = (src) => {
  const base = src.split('/').pop() ?? ''
  return base === 'node_modules' || base === '.git' || base === '__pycache__'
    || base === '.virtfs_metadata' || base.includes('.bak')
}

function log(line) {
  try { appendFileSync(LOG, new Date().toISOString() + ' ' + line + '\n') } catch {}
}

function readJson(path) { return JSON.parse(readFileSync(path, 'utf8')) }

function writeJson(path, data) {
  writeFileSync(path, JSON.stringify(data, null, 2) + '\n')
}

function backup(path, dir) {
  try {
    mkdirSync(dir, { recursive: true })
    copyFileSync(path, join(dir, path.split('/').pop()))
  } catch { /* 备份失败不阻断 */ }
}

/** 依赖可能被安装器放在本包自己的 node_modules 下；profile 级的解析链看不到，
 *  所以逐个链接到 profile 级（失败则复制）。已存在的不动。 */
function linkDepsUp() {
  const nested = join(PKG_ROOT, 'node_modules')
  if (!existsSync(nested)) return 0
  let linked = 0
  for (const name of readdirSync(nested)) {
    if (name.startsWith('.')) continue
    const source = join(nested, name)
    if (name.startsWith('@')) {
      for (const inner of readdirSync(source)) {
        const from = join(source, inner)
        const to = join(NM, name, inner)
        if (existsSync(to)) continue
        mkdirSync(join(NM, name), { recursive: true })
        try { symlinkSync(from, to, 'dir') } catch { cpSync(from, to, { recursive: true }) }
        linked += 1
      }
      continue
    }
    const to = join(NM, name)
    if (existsSync(to)) continue
    try { symlinkSync(source, to, 'dir') } catch { cpSync(source, to, { recursive: true }) }
    linked += 1
  }
  return linked
}

function planBundles(bundles) {
  // 我们自己管的那几行都先摘掉再按固定顺序插回：Optional 也必须摘，
  // 否则会在原位置留一份、新位置又加一份，变成重复行。
  const rest = bundles.filter((row) => !OWN_ROWS.includes(row) && !OPTIONAL.includes(row))
  let index = 0
  rest.forEach((row, position) => { if (String(row).startsWith('@deepseek-ai/')) index = position + 1 })
  const wanted = ['dsh-tavern-gate']
  for (const name of OPTIONAL) if (existsSync(join(NM, name))) wanted.push(name)
  wanted.push('dsh-tavern-plugin', 'dsh-tavern-remote', 'dsh-tavern-presets')
  return { next: [...rest.slice(0, index), ...wanted, ...rest.slice(index)], wanted }
}

function renderPresets() {
  const dir = join(NM, 'dsh-tavern-presets')
  const template = join(dir, 'cordis.patch.yml.tmpl')
  if (!existsSync(template)) return 'missing'
  let text = readFileSync(template, 'utf8')
  text = text.replaceAll('{{CORE_DIR}}', CORES_DIR).replaceAll('{{PROFILE_DIR}}', PROFILE_DIR)
  writeFileSync(join(dir, 'cordis.patch.yml'), text)
  return 'ok'
}

function ensureHomePatch() {
  const path = join(HOME_DIR, 'cordis.patch.yml')
  const text = existsSync(path) ? readFileSync(path, 'utf8') : ''
  if (/^- id: permission\s*$/m.test(text)) return 'exists'
  const block = '- id: permission\n  config:\n    defaultPreset: workspace-write\n'
  writeFileSync(path, (text && !text.endsWith('\n') ? text + '\n' : text) + block)
  return 'added'
}

async function loadGate(ctx) {
  const entry = join(NM, 'dsh-tavern-gate', 'index.js')
  if (!existsSync(entry)) {
    log('gate 不存在，跳过加载：' + entry)
    return
  }
  try {
    const mod = await import(pathToFileURL(entry).href)
    const fiber = ctx.plugin(mod)
    globalThis.__tavernHarmonyBootstrapFiber = fiber
    log('gate 已加载')
  } catch (error) {
    log('gate 加载失败：' + String(error && error.stack || error))
    console.warn('[tavern-harmony] 门加载失败：' + String(error && error.message || error))
  }
}

export async function apply(ctx) {
  try {
    const profilePackage = join(PROFILE_DIR, 'package.json')
    if (!existsSync(profilePackage)) {
      console.warn('[tavern-harmony] 找不到 profile package.json：' + profilePackage)
      return
    }
    const data = readJson(profilePackage)
    const bundles = data?.dsh?.profile?.bundles ?? []
    const already = existsSync(join(NM, 'dsh-tavern-gate')) && existsSync(MARKER)
    const gateRow = bundles.includes('dsh-tavern-gate')

    if (already && gateRow) {
      // 已经是普通安装的形态：本行理论上早该被移除了。
      return
    }

    if (!already) {
      log('--- bootstrap start ---')
      let copied = 0
      for (const name of PACKAGES) {
        const source = join(PKG_ROOT, 'packages', name)
        if (!existsSync(source)) { console.warn('[tavern-harmony] 缺包：' + source); continue }
        cpSync(source, join(NM, name), { recursive: true, force: true, filter: (src) => !SKIP(src) })
        copied += 1
      }
      // 内置主题（不在 registry 上，vendored）
      const skin = join(PKG_ROOT, 'vendor', 'dsh-dream-skin')
      if (existsSync(skin) && !existsSync(join(NM, 'dsh-dream-skin'))) {
        cpSync(skin, join(NM, 'dsh-dream-skin'), { recursive: true, force: true, filter: (src) => !SKIP(src) })
      }
      log('已铺开 %d 个包' % copied)

      const linked = linkDepsUp()
      if (linked > 0) log('已把 %d 个依赖链接到 profile 级' % linked)

      log('preset 渲染：' + renderPresets())
      log('home patch：' + ensureHomePatch())
    }

    // profile 登记
    const { next, wanted } = planBundles(bundles)
    const changed = JSON.stringify(next) !== JSON.stringify(bundles)
    if (changed) {
      backup(profilePackage, join(HOME_DIR, '_tavern-harmony-backup', 'bootstrap-' + Date.now()))
      data.dsh = data.dsh ?? {}
      data.dsh.profile = data.dsh.profile ?? {}
      data.dsh.profile.bundles = next
      writeJson(profilePackage, data)
      log('bundles 已更新：' + wanted.join(', '))
    }

    if (!already) {
      writeJson(MARKER, { at: Date.now(), packages: PACKAGES, bundles: wanted })
      log('--- bootstrap done ---')
      console.log('[tavern-harmony] 组件已铺开，本次启动即可使用「酒馆：关」；下次启动按普通安装加载')
    }

    // 本次启动就能用：直接挂门（如果门不是独立行）
    if (!gateRow) await loadGate(ctx)
  } catch (error) {
    log('BOOTSTRAP FAILED: ' + String(error && error.stack || error))
    console.error('[tavern-harmony] 自举失败：' + String(error && error.message || error))
  }
}
