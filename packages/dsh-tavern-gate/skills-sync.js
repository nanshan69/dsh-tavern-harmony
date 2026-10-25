// skills-sync.js — 把本包 skills/ 铺到 <dsh-home>/skills/
//
// 为什么需要它：新设备只贴一个仓库链接，装完插件就应当自带这些技能；
// 升级时（方式 B 覆盖 packages/*，或重新贴链接）也要把新版本技能带过来。
//
// 规则（幂等）：
//   · 目标不存在      → 写入
//   · 内容完全相同    → 不写盘（正常启动零 IO 写）
//   · 内容不同        → 旧文件先备份到 <home>/skills-backup/<时间戳>/ 再覆盖
//
// 备份目录刻意放在 skills/ 之外：放在里面会被技能加载器当成一个技能目录。
// 只覆盖同名文件，不删除 <home>/skills 下用户自己放的任何技能。
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname, join } from 'node:path'

const SKIP_NAMES = new Set(['.DS_Store', 'Thumbs.db', '.git'])

function listFiles(root, prefix) {
  const out = []
  for (const entry of readdirSync(join(root, prefix), { withFileTypes: true })) {
    if (SKIP_NAMES.has(entry.name)) continue
    const rel = prefix === '' ? entry.name : prefix + '/' + entry.name
    if (entry.isDirectory()) out.push(...listFiles(root, rel))
    else if (entry.isFile()) out.push(rel)
  }
  return out
}

export function syncBundledSkills({ source, target, backupRoot, preserve = [] }) {
  if (typeof source !== 'string' || source === '' || !existsSync(source)) {
    return { status: 'no-source', source }
  }
  const files = listFiles(source, '')
  if (files.length === 0) return { status: 'empty-source', source }

  mkdirSync(target, { recursive: true })
  const stamp = new Date().toISOString().replaceAll(':', '-').replaceAll('.', '-')
  const backupDir = join(backupRoot, stamp)
  let copied = 0
  let same = 0
  let kept = 0
  let backed = 0

  for (const rel of files) {
    const from = join(source, rel)
    const to = join(target, rel)
    const bytes = readFileSync(from)
    const head = rel.includes('/') ? rel.slice(0, rel.indexOf('/')) : rel
    if (existsSync(to) && preserve.some((prefix) => head.startsWith(prefix))) { kept += 1; continue }
    if (existsSync(to)) {
      const old = readFileSync(to)
      if (old.equals(bytes)) { same += 1; continue }
      const bak = join(backupDir, rel)
      mkdirSync(dirname(bak), { recursive: true })
      writeFileSync(bak, old)
      backed += 1
    }
    mkdirSync(dirname(to), { recursive: true })
    writeFileSync(to, bytes)
    copied += 1
  }
  return { status: 'ok', files: files.length, copied, same, kept, backed, target }
}
