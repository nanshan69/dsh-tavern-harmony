import { createHash } from 'node:crypto'
import { sessionEvents } from './session-events.js'
import { isProducerSource } from './message-source.js'

// Compare model-visible history, not prepared Chat state. Rewind/fork naturally
// select their own baseline; compaction of the record causes a full refresh.
export function worldbookSnapshot(session, text, pendingMessages = []) {
  text = String(text || '').trim()
  const events = new Map(sessionEvents(session).map(event => [event.seq, event]))
  const messages = (session?.surface?.nodes || []).map(seq => events.get(seq))
    .filter(event => event?.type === 'user/message').map(event => event.data).concat(pendingMessages)
  let previous
  for (const message of messages) {
    const record = message?.source?.worldbookSnapshot
    if (!isProducerSource(message?.source, 'dsh-tavern') || record?.schemaVersion !== 1) continue
    const content = (message.content || []).filter(block => block.type === 'text').map(block => block.text).join('')
    if (content.includes(record.rendered)) previous = record
  }
  // Only the entries triggered this turn; an untriggered turn adds nothing.
  if (!text || previous?.text === text) return null
  const version = createHash('sha256').update(text).digest('hex').slice(0, 16)
  // One complete ordered snapshot keeps cross-entry XML wrappers intact.
  const rendered = `【本轮世界书上下文】\n${text.replace(/^【本轮世界书上下文】\n?/, '')}`
  return { schemaVersion: 1, text, version, rendered }
}
