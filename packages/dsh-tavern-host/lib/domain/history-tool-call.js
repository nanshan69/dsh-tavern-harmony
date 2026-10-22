import { createHash } from 'node:crypto'

// Story prose is the one thing a turn contributes to the transcript: the model's
// reply and the player's own input. Replayed as plain text they read as "this was
// already written"; replaying them as the submission tool's own arguments keeps
// the same characters and tokens while the model treats them as structured
// parameters instead of prose in the narration channel.
// Measured on Gemini 4: the identical body is refused as assistant text and
// accepted as tool arguments, so this projection is a containment measure, not a
// cosmetic one. The identifier is derived from the message id so repeated
// requests produce byte-identical history and keep provider caches warm.
//
// The id must also survive transport: OpenAI-compatible gateways cap call ids at
// 40 characters and many only pass `[A-Za-z0-9_-]`, silently turning anything else
// into an unmatched call or a 400. `tvh_` plus 32 hex digits is 36 characters of
// that alphabet, so the pair stays legal on every backend this plugin talks to.
export const HISTORY_CALL_PREFIX = 'tvh_'
export const HISTORY_RECEIPT_TEXT = '已收到。'

function str(value) {
  return typeof value === 'string' ? value : (value === undefined || value === null ? '' : String(value))
}

/**
 * Story prose worth replaying: a model reply, or the player's own message.
 *
 * Plugin injections (world book, rules, frames, snapshots) are instructions, not
 * story, and keep their native shape. So does anything carrying reasoning, an
 * image or an existing tool call: only a message that is nothing but visible text
 * can become arguments without loss.
 */
function isProse(message) {
  if (message === null || typeof message !== 'object') return false
  const source = message.source
  if (source === null || typeof source !== 'object') return false
  const author = message.role === 'assistant' ? 'model' : message.role === 'user' ? 'user' : ''
  if (author === '' || source.kind !== author) return false
  const content = message.content
  if (!Array.isArray(content) || content.length === 0) return false
  return content.every(function (block) {
    return block !== null && typeof block === 'object' && block.type === 'text' && str(block.text).trim() !== ''
  })
}

function callIdOf(message, text) {
  const identity = str(message.id) !== '' ? str(message.id) : text
  return HISTORY_CALL_PREFIX + createHash('sha256').update(identity).digest('hex').slice(0, 32)
}

/**
 * Replay every past body as a submission call with a matching receipt.
 *
 * @param messages - provider-bound messages for this request.
 * @param options - `toolName` names the submission tool; `receipt` overrides the
 *   tool output text; `preserve(message, index)` opts a message out (the input of
 *   the turn being requested must stay the prompt). All optional, but without a
 *   tool name nothing changes.
 * @returns the same array when no body qualifies, otherwise a new array.
 */
export function projectHistoryAsToolCalls(messages, options = {}) {
  if (!Array.isArray(messages) || messages.length === 0) return messages
  const toolName = str(options.toolName)
  if (toolName === '') return messages
  const receiptText = str(options.receipt) || HISTORY_RECEIPT_TEXT
  const preserve = typeof options.preserve === 'function' ? options.preserve : null
  // Whatever else is replayed, the newest player message stays the prompt this
  // request is answering; a transcript that ends in a receipt has no question.
  let lastUserIndex = -1
  for (let index = messages.length - 1; index >= 0; index--) {
    if (messages[index] && messages[index].role === 'user') { lastUserIndex = index; break }
  }
  let changed = false
  const projected = []
  messages.forEach(function (message, index) {
    if (index === lastUserIndex || !isProse(message) || (preserve !== null && preserve(message, index))) {
      projected.push(message)
      return
    }
    const text = message.content.map(function (block) { return str(block.text) }).join('')
    const callId = callIdOf(message, text)
    // A tool call is emitted by the assistant, so a replayed player message is
    // carried under that role while keeping its id (and therefore its call id).
    projected.push({
      ...message,
      role: 'assistant',
      content: [{ type: 'tool-call', id: callId, name: toolName, arguments: JSON.stringify({ content: text }) }]
    })
    // The receipt is what makes the pair legal for providers that require every
    // call to be answered; it carries no body so the text appears exactly once.
    // DSH 0.2 (session v4) sends tool results as first-class tool messages.
    projected.push({
      id: callId + ':receipt',
      role: 'tool',
      source: { kind: 'tool', callId },
      toolCallId: callId,
      content: [{ type: 'text', text: receiptText }],
      isError: false
    })
    changed = true
  })
  return changed ? projected : messages
}
