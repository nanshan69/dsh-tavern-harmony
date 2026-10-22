import { existsSync } from 'node:fs'
import { mkdir, readdir, readFile, rename, rm, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { readZipEntries } from './zip-entries.js'
import { scanUserPlugins, STATUS_FILE, userPluginPaths } from './user-plugins.js'
import { pluginDataFile } from './plugin-data-store.js'

// 应用内安装插件：粘贴 GitHub 地址或上传 zip，放进 <data>/plugins/<文件夹>；
// 之后的加载仍由 plugins/ 目录同步负责（宿主侧几秒内加载，浏览器侧刷新后出现）。
export const SOURCE_FILE = '.tavern-source.json'
const CARD_MARKER = '.dsh-card.json'
const SKIP = new Set(['.git', '.github', 'node_modules/.cache'])

const fail = message => { throw Object.assign(new Error(message), { code: 'TAVERN_PLUGIN_INSTALL' }) }

/** owner/repo、https://github.com/owner/repo(.git)、…/tree/<分支或标签> → { owner, repo, ref } */
export function parseGithubSource(input) {
  const raw = String(input || '').trim().replace(/\/+$/, '').replace(/\.git$/i, '')
  const short = /^([\w.-]+)\/([\w.-]+)$/.exec(raw)
  if (short) return { owner: short[1], repo: short[2], ref: null }
  let url
  try { url = new URL(raw) } catch { fail('请粘贴 GitHub 仓库地址，例如 https://github.com/作者/仓库') }
  if (url.protocol !== 'https:' || !/^(www\.)?github\.com$/i.test(url.hostname)) fail('只支持 https://github.com/ 上的仓库地址；其他来源请下载 zip 后上传')
  const parts = url.pathname.split('/').filter(Boolean)
  if (parts.length < 2) fail('地址里缺少作者或仓库名')
  const ref = parts[2] === 'tree' && parts.length > 3 ? decodeURIComponent(parts.slice(3).join('/')) : null
  return { owner: parts[0], repo: parts[1], ref }
}

async function fetchOk(fetchImpl, url, accept) {
  let response
  try { response = await fetchImpl(url, { headers: { Accept: accept, 'User-Agent': 'dsh-tavern' }, redirect: 'follow' }) }
  catch (error) { fail('连不上 GitHub（' + (error?.cause?.code || error?.message || error) + '）。网络不通时，可以在仓库页面下载 ZIP 后上传') }
  return response
}

/** 有 Release 用最新 Release，否则用默认分支；地址里写了分支或标签就用它。 */
export async function downloadGithubPlugin(source, { fetchImpl = fetch } = {}) {
  const base = `https://api.github.com/repos/${source.owner}/${source.repo}`
  let ref = source.ref, label = source.ref ? source.ref : '默认分支'
  if (!ref) {
    const latest = await fetchOk(fetchImpl, base + '/releases/latest', 'application/vnd.github+json')
    if (latest.ok) { const release = await latest.json(); ref = release.tag_name; label = 'Release ' + release.tag_name }
    else if (latest.status !== 404) fail('读取仓库发布信息失败（HTTP ' + latest.status + (latest.status === 403 ? '，可能是 GitHub 访问次数受限，稍后再试或上传 ZIP' : '') + '）')
  }
  const archive = await fetchOk(fetchImpl, base + '/zipball' + (ref ? '/' + encodeURIComponent(ref) : ''), 'application/vnd.github+json')
  if (archive.status === 404) fail('找不到仓库 ' + source.owner + '/' + source.repo + (source.ref ? ' 的 ' + source.ref : '') + '，请检查地址，或确认仓库是公开的')
  if (!archive.ok) fail('下载插件失败（HTTP ' + archive.status + '）')
  return { bytes: Buffer.from(await archive.arrayBuffer()), ref: ref || 'HEAD', label }
}

function hostEntryOf(pkg) {
  const exportsField = pkg.exports
  return typeof exportsField === 'string' ? exportsField
    : typeof exportsField?.['.'] === 'string' ? exportsField['.']
      : exportsField?.['.']?.import || exportsField?.['.']?.default || (typeof pkg.main === 'string' ? pkg.main : '')
}

/** zip 里找到插件根（最浅的 package.json），检查能不能当 Tavern 插件装。 */
export function readPluginArchive(bytes) {
  const entries = readZipEntries(bytes, { label: '插件 ZIP' })
  const manifests = [...entries.keys()].filter(name => /(^|\/)package\.json$/.test(name) && !name.includes('node_modules/'))
    .sort((left, right) => left.split('/').length - right.split('/').length)
  if (!manifests.length) fail('压缩包里没有 package.json，不是 Tavern 插件')
  const root = manifests[0].slice(0, -'package.json'.length)
  let pkg
  try { pkg = JSON.parse(entries.get(manifests[0]).toString('utf8')) } catch (error) { fail('package.json 无法解析：' + error.message) }
  const files = new Map()
  for (const [name, data] of entries) {
    if (!name.startsWith(root) || name.endsWith('/')) continue
    const relative = name.slice(root.length)
    if (!relative || relative.split('/').some(part => part === '..' || part === '') || path.isAbsolute(relative)) continue
    if ([...SKIP].some(prefix => relative === prefix || relative.startsWith(prefix + '/'))) continue
    files.set(relative, data)
  }
  const main = hostEntryOf(pkg)
  if (!main) fail('package.json 没有写宿主入口（exports "." 或 main），不是 Tavern 插件')
  if (!files.has(path.posix.normalize(main.replace(/^\.\//, '')))) fail('找不到宿主入口 ' + main)
  const dependencies = Object.keys(pkg.dependencies || {})
  const bundled = [...files.keys()].some(name => name.startsWith('node_modules/'))
  if (dependencies.length && !bundled) fail('这个插件依赖 npm 包（' + dependencies.slice(0, 5).join('、') + (dependencies.length > 5 ? ' 等' : '') + '），暂不支持一键安装。请联系作者把依赖打包进插件，或按作者的说明手动安装')
  return { pkg, files }
}

function folderFor(pkg, fallback) {
  const name = String(pkg.name || fallback || '').replace(/^@[^/]+\//, '')
  const folder = name.replace(/[^\w.-]+/g, '-').replace(/^[-.]+|[-.]+$/g, '').slice(0, 80)
  if (!folder) fail('插件没有可用的名字（package.json 的 name）')
  return folder
}

async function readJson(file) { try { return JSON.parse(await readFile(file, 'utf8')) } catch { return null } }

export function createUserPluginInstaller({ dataRoot, fetchImpl = fetch, now = () => new Date(), sync = async () => {} }) {
  const paths = userPluginPaths(dataRoot)
  const backups = path.join(path.resolve(dataRoot), 'plugin-backups')
  const installedPackage = name => existsSync(path.join(paths.profile, 'node_modules', ...name.split('/'), 'package.json'))
  let tail = Promise.resolve()
  const serial = work => { const run = tail.then(work, work); tail = run.catch(() => {}); return run }
  const stamp = () => now().toISOString().replace(/[:.]/g, '-')

  async function backup(folder) {
    await mkdir(backups, { recursive: true })
    const base = path.join(backups, folder + '-' + stamp())
    let target = base
    for (let index = 2; existsSync(target); index++) target = base + '-' + index
    await rename(path.join(paths.plugins, folder), target)
    return target
  }

  async function place({ pkg, files }, source, fallbackName) {
    const folder = folderFor(pkg, fallbackName)
    if (pkg.name && installedPackage(String(pkg.name))) fail('插件名 ' + pkg.name + ' 与已安装的包重名，不能装进 plugins/')
    const target = path.join(paths.plugins, folder)
    if (existsSync(path.join(target, CARD_MARKER))) fail('plugins/' + folder + ' 是人物卡自带的插件，由人物卡库管理，不能覆盖')
    await mkdir(paths.plugins, { recursive: true })
    const staging = path.join(paths.plugins, '.installing-' + folder + '-' + process.pid)
    await rm(staging, { recursive: true, force: true })
    try {
      for (const [relative, data] of files) {
        const file = path.join(staging, ...relative.split('/'))
        await mkdir(path.dirname(file), { recursive: true })
        await writeFile(file, data)
      }
      await writeFile(path.join(staging, SOURCE_FILE), JSON.stringify({ ...source, version: String(pkg.version || ''), installedAt: now().toISOString() }, null, 2) + '\n')
      const replaced = existsSync(target) ? await backup(folder) : null
      await rename(staging, target)
      await sync()
      return { folder, name: String(pkg.name || folder), version: String(pkg.version || ''), replaced: Boolean(replaced) }
    } finally { await rm(staging, { recursive: true, force: true }) }
  }

  return {
    pluginsDir: paths.plugins,
    async list() {
      const { plugins, problems } = await scanUserPlugins(paths.plugins, { installed: installedPackage })
      let folders = []
      try { folders = (await readdir(paths.plugins, { withFileTypes: true })).filter(item => item.isDirectory() && !item.name.startsWith('.')).map(item => item.name).sort() } catch {}
      return Promise.all(folders.map(async folder => {
        const dir = path.join(paths.plugins, folder)
        const pkg = await readJson(path.join(dir, 'package.json')) || {}
        const problem = problems.find(item => item.folder === folder)
        const status = problem ? null : await readJson(path.join(dir, STATUS_FILE))
        const card = await readJson(path.join(dir, CARD_MARKER))
        return {
          folder, name: String(pkg.name || folder), version: String(pkg.version || ''), description: String(pkg.description || ''),
          source: card ? { kind: 'card' } : await readJson(path.join(dir, SOURCE_FILE)) || { kind: 'folder' },
          state: problem ? 'skipped' : status?.ok === false ? 'failed' : status?.ok === true ? 'loaded' : plugins.some(item => item.folder === folder) ? 'pending' : 'skipped',
          reason: problem ? problem.reason : status?.ok === false ? status.stage + '失败：' + status.message : '',
        }
      }))
    },
    installFromGithub(input) {
      return serial(async () => {
        const source = parseGithubSource(input)
        const downloaded = await downloadGithubPlugin(source, { fetchImpl })
        return place(readPluginArchive(downloaded.bytes), { kind: 'github', repo: source.owner + '/' + source.repo, ref: source.ref, resolved: downloaded.label }, source.repo)
      })
    },
    installFromZip(bytes, fileName) {
      return serial(async () => place(readPluginArchive(bytes), { kind: 'zip', file: String(fileName || '') }, String(fileName || '').replace(/\.zip$/i, '')))
    },
    update(folder) {
      return serial(async () => {
        const source = await readJson(path.join(paths.plugins, String(folder), SOURCE_FILE))
        if (source?.kind !== 'github') fail('这个插件不是从 GitHub 地址装的，没法自动更新；请重新上传新版 ZIP')
        const parsed = parseGithubSource(source.repo)
        parsed.ref = source.ref || null
        const downloaded = await downloadGithubPlugin(parsed, { fetchImpl })
        return place(readPluginArchive(downloaded.bytes), { kind: 'github', repo: source.repo, ref: source.ref || null, resolved: downloaded.label }, parsed.repo)
      })
    },
    remove(folder) {
      return serial(async () => {
        const name = String(folder)
        if (!name || name !== path.basename(name) || name.startsWith('.') || !existsSync(path.join(paths.plugins, name))) fail('插件不存在：' + name)
        if (existsSync(path.join(paths.plugins, name, CARD_MARKER))) fail('这是人物卡自带的插件，请在人物卡库里停用')
        const pkg = await readJson(path.join(paths.plugins, name, 'package.json'))
        const kept = await backup(name)
        // The plugin's own data goes into the same backup, so reinstalling from there brings it back by hand.
        const data = pluginDataFile(dataRoot, String(pkg?.name || name))
        if (existsSync(data)) await rename(data, path.join(kept, '.plugin-data.json'))
        await sync()
        return { folder: name, backup: kept }
      })
    },
  }
}
