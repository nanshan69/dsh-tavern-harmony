// Synchronous Helper APIs share the host's regex engine, with live context reads.
// Keep this installer self-contained for script and message iframe serialization.
function installTavernHelperRegexApi(options) {
  const target = options.window
  const engine = options.createEngine()
  const placements = { user_input: 1, ai_output: 2, slash_command: 3, world_info: 5, reasoning: 6 }

  function boundCharacter(state) {
    // DSH applies enabled rules on a bound card without SillyTavern's separate
    // avatar opt-in. This reports the same permission as the Helper facade's
    // character_allowed_regex projection, even when all individual rules are off.
    return state.character !== null && typeof state.character === 'object' && !Array.isArray(state.character)
  }

  function substituteIdentity(value, state, characterName, escape = false) {
    function replacement(value) {
      const text = String(value)
      return escape ? text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') : text
    }
    return String(value ?? '').replace(/{{\s*(user|char)\s*}}/gi, function (_match, name) {
      return replacement(name.toLowerCase() === 'user'
        ? state.playerName || '你'
        : characterName ?? (state.characterName || state.character?.name || state.character?.data?.name || '角色'))
    })
  }

  target.isCharacterTavernRegexesEnabled = function () {
    return boundCharacter(options.context() || {})
  }

  target.formatAsTavernRegexedString = function (value, source, destination, settings = {}) {
    if (!Object.prototype.hasOwnProperty.call(placements, source)) throw new TypeError('无效的正则来源: ' + String(source))
    if (destination !== 'display' && destination !== 'prompt') throw new TypeError('无效的正则目标: ' + String(destination))
    if (!settings || typeof settings !== 'object' || Array.isArray(settings)) throw new TypeError('正则选项必须是对象')
    if (settings.depth !== undefined && (typeof settings.depth !== 'number' || !Number.isFinite(settings.depth))) {
      throw new TypeError('正则深度必须是有限数字')
    }
    const state = options.context() || {}
    const groups = state.regexScripts || {}
    const list = value => Array.isArray(value) ? value : []
    // Preserve DSH's global, preset, character priority; preset rules participate
    // when the host supplies that group. No state or stored message is modified.
    const scripts = list(groups.global).concat(list(groups.preset), boundCharacter(state) ? list(groups.character) : [])
      .filter(script => script && typeof script === 'object')
      .map(function (script) {
        const mode = Number(script.substituteRegex)
        return {
          ...script,
          findRegex: mode === 1 || mode === 2
            ? substituteIdentity(script.findRegex, state, settings.character_name, mode === 2) : script.findRegex,
          trimStrings: list(script.trimStrings).map(value => substituteIdentity(value, state, settings.character_name))
        }
      })
    const result = engine.applyTavernRegexText(value, scripts, {
      placement: placements[source], isMarkdown: destination === 'display', isEdit: false,
      depth: settings.depth, ignoreDepth: settings.depth === undefined
    })
    for (const warning of result.warnings) target.console?.warn?.('[TavernHelper regex] ' + warning)
    // Apply identity macros first, then the shared read-only macro adapter.
    // Unknown or side-effecting macros remain literal during formatting.
    const formatted = substituteIdentity(result.text, state, settings.character_name)
    return typeof target.substitudeMacros === 'function' ? target.substitudeMacros(formatted, {
      character_name: settings.character_name,
      message_id: settings.depth === undefined ? undefined : (state.messages || []).length - settings.depth - 1
    }) : formatted
  }

  return {
    formatAsTavernRegexedString: target.formatAsTavernRegexedString,
    isCharacterTavernRegexesEnabled: target.isCharacterTavernRegexesEnabled
  }
}

export { installTavernHelperRegexApi }
