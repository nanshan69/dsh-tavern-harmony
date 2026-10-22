// dsh-tavern-harmony — 浏览器半边：左下角一个「酒馆」开关。
//
// 和 packages/dsh-tavern-gate/client.js 是同一份逻辑，只换了模块 id：
// 首次安装后的那次启动由本文件画按钮（那时 gate 行还没进 bundles）；
// 之后 bundles 里换成 gate 行，本文件不再被加载。
// 只跟 host 的 /api/tavern-gate 通信，不直接碰任何酒馆代码。
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

    // 酒馆的“空对话”起始页会铺一个巨大的 logo，挡住聊天/思考区。
    // 这里只把 logo 隐藏掉，不动酒馆其它界面（可随时删掉这段）。
    // 另外：主题（dream-skin）把 --dsw-alias-bg-layer-1 做成半透明，
    // better-sidebar 的标签条正好用它当背景 → 下面的文字透上来。
    // 面板主体用的是 --dsw-alias-bg-base（不透明），这里让标签条跟主体一致。
    function injectStyles() {
      if (document.getElementById('dsh-tavern-gate-style')) return
      var style = document.createElement('style')
      style.id = 'dsh-tavern-gate-style'
      style.textContent = '.dsh-tavern-hero-lockup{display:none!important}'
        + '[class*="_tabBar"]{background:var(--dsw-alias-bg-base,#f7f5f2)!important;'
        + 'border-bottom:1px solid var(--dsw-alias-border-l1,transparent)}'
        // 窄屏（两屏/单屏）时侧栏会变成底部停靠面板、候选行动框变成浮动卡片，
        // 主题把 layer-1 / sidebar-fill 做成半透明 → 下面文字透上来。
        + '[class*="_bottomPanel"]{background:var(--dsw-alias-bg-base,#f7f5f2)!important}'
        + '[class*="_bottomPanel"] [class*="_pane"]{background:var(--dsw-alias-bg-base,#f7f5f2)!important}'
        + '.dsh-tavern-question,.dsh-tavern-candidate-question{background:var(--dsw-alias-bg-base,#f7f5f2)!important}'
        + '.dsh-tavern-candidate-question .dsh-tavern-question-head{background:var(--dsw-alias-bg-base,#f7f5f2)!important}'
        + '.dsh-tavern-question-option{background:var(--dsw-alias-bg-base,#f7f5f2)}'
      ;(document.head || document.documentElement).appendChild(style)
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

    async function apply() {
      injectStyles()
      await installSessionReadPatch()
      if (document.body) status().then(render)
      else document.addEventListener('DOMContentLoaded', function () { status().then(render) }, { once: true })
    }

    exports.apply = apply
    exports.inject = []
    return module.exports
  }
});
