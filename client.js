// dsh-tavern-harmony — 浏览器半边：左下角一个「酒馆」开关。
// 与 packages/dsh-tavern-gate/client.js 是同一份逻辑，只换了模块 id：
// 首次安装后那一轮启动由本文件画按钮（那时 gate 行还没进 bundles），
// 之后 bundles 换成 gate 行，本文件不再被加载。
// 只跟 host 的 /api/tavern-gate 通信，不直接碰任何酒馆代码。
//
// 这里还负责两件纯样式的事（都只在酒馆打开时生效）：
//   1. 侧栏实色：dream-skin 壁纸模式会把 --dsw-alias-bg-base 压成 0.45 透明，
//      右侧栏面板用它当底 → 正文透上来。这里换成本地算出的不透明同色。
//   2. 左侧面板可点击：DSHM 会在左侧面板上盖一层全屏遮罩（fixed / z-index 35 /
//      无 class 的空 div），既吃点击又蒙一层灰。这里给它挖一个和面板同形的洞：
//      洞内点击落到面板，洞外仍归遮罩（点外侧关闭照旧），并清掉它的半透明视觉。
window.__ModuleLoader__.load({
  id: 'dsh-tavern-harmony',
  factory: function (require) {
    var module = { exports: {} }
    var exports = module.exports

    function status() {
      return fetch('/api/tavern-gate/status', { credentials: 'same-origin' })
        .then(function (r) { return r.json() })
        .catch(function () { return { loaded: false, error: 'gate 不可达' } })
    }

    function toggle(on) {
      return fetch('/api/tavern-gate/toggle?on=' + (on ? '1' : '0'), {
        method: 'POST', credentials: 'same-origin'
      }).then(function (r) { return r.json() })
    }

    function render(state) {
      var old = document.getElementById('dsh-tavern-gate')
      if (old) old.remove()
      var b = document.createElement('button')
      b.id = 'dsh-tavern-gate'
      b.type = 'button'
      b.textContent = state.loaded ? '酒馆：开' : '酒馆：关'
      b.title = state.error ? ('酒馆未运行：' + state.error) : (state.loaded ? '点击关闭酒馆（重启后自动关）' : '点击在本次会话内打开酒馆')
      b.style.cssText = 'position:fixed;left:14px;bottom:14px;z-index:2147483647;padding:8px 12px;'
        + 'border-radius:999px;border:1px solid rgba(255,255,255,.22);background:rgba(18,20,26,.86);'
        + 'color:#fff;font:12px/1.2 system-ui,sans-serif;cursor:pointer;opacity:.85'
      b.addEventListener('click', function (ev) {
        ev.preventDefault()
        ev.stopPropagation()
        b.disabled = true
        b.textContent = state.loaded ? '正在关闭…' : '正在加载…'
        // 切换后刷新页面：酒馆前端在 factory 里同步问 /api/tavern-gate/status，
        // 只有 host 已加载时才会挂载。刷新是让这个判断重新跑一次。
        toggle(!state.loaded).then(function () { location.reload() })
      })
      document.body.appendChild(b)
    }

    // ── 不透明底色 ────────────────────────────────────────────────────────
    // dream-skin 开壁纸后会把 --dsw-alias-bg-base 改写成 rgba(底色, α)
    // （自动压暗时 α≈0.45）。把同一个底色算成不透明 RGB 放进 --dsh-tavern-solid，
    // 只替换侧栏子树里的值，不动对话区、也不改全局主题 token。
    function resolveSolidBase() {
      var probe = document.createElement('div')
      probe.style.cssText = 'position:fixed;left:-9999px;top:0;width:1px;height:1px;'
        + 'pointer-events:none;background-color:var(--dsw-alias-bg-base,#f7f5f2)'
      ;(document.body || document.documentElement).appendChild(probe)
      var color = window.getComputedStyle(probe).backgroundColor
      if (probe.parentNode) probe.parentNode.removeChild(probe)
      var match = /rgba?\(([^)]+)\)/.exec(color || '')
      if (!match) return null
      var parts = match[1].split(',').map(function (x) { return parseFloat(x) })
      if (parts.length < 3) return null
      // 完全透明说明此刻主题变量还没生效（落到了 transparent），
      // 不要写 rgb(0,0,0) 把面板刷黑，等下一次重算。
      if (parts.length > 3 && parts[3] === 0) return null
      return 'rgb(' + Math.round(parts[0]) + ',' + Math.round(parts[1]) + ',' + Math.round(parts[2]) + ')'
    }

    function syncSolidBase() {
      var solid = resolveSolidBase()
      if (!solid) return
      var root = document.documentElement
      if (root.style.getPropertyValue('--dsh-tavern-solid') !== solid) {
        root.style.setProperty('--dsh-tavern-solid', solid)
      }
    }

    // 主题是异步套用的（皮肤 / 壁纸 / 明暗都可能晚于本模块），所以：
    // 立刻算一次 + 两次延迟重算 + 监听 <html> 属性变化。
    function watchTheme() {
      syncSolidBase()
      setTimeout(syncSolidBase, 450)
      setTimeout(syncSolidBase, 1600)
      try {
        new MutationObserver(function () { syncSolidBase() }).observe(
          document.documentElement,
          { attributes: true, attributeFilter: ['class', 'style', 'data-theme'] }
        )
      } catch (error) { /* 老内核没有 MutationObserver 就只靠定时重算 */ }
    }

    function injectStyles() {
      if (document.getElementById('dsh-tavern-gate-style')) return
      var style = document.createElement('style')
      style.id = 'dsh-tavern-gate-style'
      var solid = 'var(--dsh-tavern-solid,var(--dsw-alias-bg-base,#f7f5f2))'
      // 实测：酒馆界面在【原生右侧栏】里，P3OORG_panel 是全屏包裹，
      // 真正带半透明背景的是它内部的 section._tabHost_*. _pane_*（background: bg-base）。
      // 只刷这一层，外层包裹不碰（它若常驻挂载，刷实色会盖住正文）。
      var panel = '[class*="P3OORG_panel"] [class*="_pane_"]'
      style.textContent = '.dsh-tavern-hero-lockup{display:none!important}'
        + panel + '{--dsw-alias-bg-base:' + solid + ';'
        + 'background-color:' + solid + '!important;background-image:none!important}'
        // 起点页卡片是 rgba(255,255,255,.08) 的薄片，叠在实底上仍偏淡。
        + '[class*="P3OORG_"] .dsh-tavern-start-card{background-color:rgba(255,255,255,.10)!important}'
        // 候选行动卡同样用的是 bg-base。
        + '.dsh-tavern-question,.dsh-tavern-candidate-question{background-color:' + solid + '!important}'
        + '.dsh-tavern-candidate-question .dsh-tavern-question-head{background-color:' + solid + '!important}'
        + '.dsh-tavern-question-option{background-color:' + solid + '!important}'
      ;(document.head || document.documentElement).appendChild(style)
    }

    // ── 左侧面板上的 DSHM 遮罩 ──────────────────────────────────────────
    // 遮罩特征：position:fixed / z-index ≥ 1 / 无 class / 无子元素。
    // 处理：清掉半透明底色、背景滤镜与阴影，再用 clip-path(evenodd) 按面板矩形
    // 挖洞 —— 洞内点击归面板，洞外仍然归遮罩，所以“点外侧关闭”不受影响。
    var SIDEBAR_SCRIM = null

    function scrimClip(scrim, sidebar) {
      var box = scrim.getBoundingClientRect()
      var rect = sidebar.getBoundingClientRect()
      if (!box.width || !box.height) return
      var left = Math.max(0, rect.left - box.left)
      var top = Math.max(0, rect.top - box.top)
      var right = Math.min(box.width, rect.right - box.left)
      var bottom = Math.min(box.height, rect.bottom - box.top)
      if (right <= left || bottom <= top) return
      var poly = 'polygon(evenodd, 0px 0px, ' + box.width + 'px 0px, '
        + box.width + 'px ' + box.height + 'px, 0px ' + box.height + 'px, 0px 0px, '
        + left + 'px ' + top + 'px, ' + left + 'px ' + bottom + 'px, '
        + right + 'px ' + bottom + 'px, ' + right + 'px ' + top + 'px, '
        + left + 'px ' + top + 'px)'
      if (scrim.style.clipPath !== poly) scrim.style.clipPath = poly
    }

    function resetScrim() {
      if (SIDEBAR_SCRIM === null) return
      SIDEBAR_SCRIM.style.clipPath = ''
      SIDEBAR_SCRIM.style.pointerEvents = ''
      SIDEBAR_SCRIM = null
    }

    function unblockSidebar() {
      var sidebar = document.querySelector('.dsh-tavern-sidebar')
      if (!sidebar) { resetScrim(); return }
      var rect = sidebar.getBoundingClientRect()
      if (rect.width < 80 || rect.height < 80) { resetScrim(); return }
      // ① 抬层级（对某些层级组合不够，但先试最轻的）
      if (window.getComputedStyle(sidebar).position === 'static') {
        sidebar.style.position = 'relative'
      }
      if (sidebar.style.zIndex !== '36') sidebar.style.zIndex = '36'

      // 已经锁定的遮罩：跟着面板尺寸重算洞口（面板可能是动画/拖拽打开的）
      if (SIDEBAR_SCRIM !== null && SIDEBAR_SCRIM.isConnected) {
        scrimClip(SIDEBAR_SCRIM, sidebar)
        return
      }
      SIDEBAR_SCRIM = null

      var cx = Math.round(rect.left + rect.width / 2)
      var cy = Math.round(rect.top + rect.height / 2)
      var stack = document.elementsFromPoint(cx, cy) || []
      var top = stack[0]
      if (!top || sidebar.contains(top)) return
      var cs = window.getComputedStyle(top)
      var isScrim = (cs.position === 'fixed' || cs.position === 'absolute')
        && String(top.className || '') === ''
        && top.children.length === 0
        && parseInt(cs.zIndex || '0', 10) >= 1
      if (!isScrim) return

      var bg = cs.backgroundColor
      if (bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent') {
        top.style.setProperty('background-color', 'transparent', 'important')
        top.style.setProperty('background-image', 'none', 'important')
      }
      if (cs.backdropFilter && cs.backdropFilter !== 'none') {
        top.style.setProperty('backdrop-filter', 'none', 'important')
        top.style.setProperty('-webkit-backdrop-filter', 'none', 'important')
      }
      if (cs.boxShadow && cs.boxShadow !== 'none') {
        top.style.setProperty('box-shadow', 'none', 'important')
      }

      // ② 挖洞：洞外保留它的点击（点外侧关闭），洞内让给面板
      scrimClip(top, sidebar)
      var after = document.elementsFromPoint(cx, cy) || []
      if (after[0] && sidebar.contains(after[0])) {
        SIDEBAR_SCRIM = top
      } else {
        // 内核不支持 clip-path（或结构不同）：退回禁点击。
        // 代价是点外侧不再自动收起，用左上角开关关闭。
        top.style.setProperty('pointer-events', 'none')
      }
    }

    // 关闭酒馆时，之前用酒馆会话补丁写出的会话在原生界面读不出来
    // （assistant/message 内嵌 source stream，原生读取器会拒绝）。
    // 这里在开机时就把“只读兼容补丁”装上：仅替换 SessionEventStream 的读取方法，
    // 不加载酒馆 UI / 回合逻辑；酒馆关闭时也能正常打开那些会话。
    async function installSessionReadPatch() {
      try {
        var res = await fetch('/api/tavern-gate/session-patch-client', { credentials: 'same-origin' })
        var data = await res.json()
        if (!data || typeof data.source !== 'string' || data.source.length === 0) return
        var live
        try { live = require('@deepseek-ai/dsh-api-session-controller/client') } catch (error) { return }
        var proto = live && live.SessionEventStream && live.SessionEventStream.prototype
        if (!proto || typeof proto.readPage !== 'function' || typeof proto.follow !== 'function') return
        if (proto.__dshTavernSessionPatch) return
        var exports
        var previous = window.__ModuleLoader__
        window.__ModuleLoader__ = { load: function (descriptor) { exports = descriptor.factory(require) } }
        try { (0, eval)(data.source) } finally { window.__ModuleLoader__ = previous }
        var patched = exports && exports.SessionEventStream && exports.SessionEventStream.prototype
        if (!patched) return
        proto.readPage = function () { return patched.readPage.apply(this, arguments) }
        proto.follow = function () { return patched.follow.apply(this, arguments) }
        Object.defineProperty(proto, '__dshTavernSessionPatch', { value: true })
      } catch (error) { /* 补丁装不上时保持原生行为 */ }
    }

    function applyStylesFor(state) {
      if (state && state.loaded) {
        injectStyles()
        watchTheme()
        return
      }
      // 酒馆没开：一行 CSS 都不留，遮罩也恢复原样
      var style = document.getElementById('dsh-tavern-gate-style')
      if (style && style.parentNode) style.parentNode.removeChild(style)
      resetScrim()
    }

    async function apply() {
      await installSessionReadPatch()
      var ready = function () {
        status().then(function (state) {
          applyStylesFor(state)
          render(state)
          if (state && state.loaded) {
            // DSHM 的遮罩会被重建，所以隔一会儿再兜一次。
            setInterval(unblockSidebar, 2000)
            setTimeout(unblockSidebar, 800)
          }
        })
      }
      if (document.body) ready()
      else document.addEventListener('DOMContentLoaded', ready, { once: true })
    }

    exports.apply = apply
    exports.inject = []
    return module.exports
  }
});
