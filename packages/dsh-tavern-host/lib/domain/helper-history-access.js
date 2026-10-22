import { createHmac, randomBytes, timingSafeEqual } from 'node:crypto'

// A read-only capability for one immutable Chat revision. No caller-supplied
// chat/revision can widen it; restarting the host invalidates all capabilities.
export function createHelperHistoryAccess({read}) {
 // 性能优化：token 里固化了 chatId/revision/messageCount，同一个 token+区间
 // 的结果在一次运行内是 immutable 的，可以安全缓存，避免一轮里反复读同一段历史。
 const cache=new Map(),cacheTtlMs=60000,cacheMax=128
 const secret=randomBytes(32)
 const sign=body=>createHmac('sha256',secret).update(body).digest()
 function issue({chatId,revision,messageCount}) {
  const body=Buffer.from(JSON.stringify({chatId,revision,messageCount})).toString('base64url')
  return {token:body+'.'+sign(body).toString('base64url'),revision,messageCount}
 }
 async function selected(token,from,to) {
  const [body,signature,...extra]=String(token||'').split('.')
  const supplied=Buffer.from(signature||'','base64url'),expected=sign(body||'')
  if(extra.length||supplied.length!==expected.length||!timingSafeEqual(supplied,expected))throw Error('Invalid history capability')
  const scope=JSON.parse(Buffer.from(body,'base64url').toString())
  if(!Number.isSafeInteger(from)||!Number.isSafeInteger(to)||from<0||to<from||to>=scope.messageCount||to-from>=48)throw Error('Invalid history range')
  const cacheKey=token+'|'+from+'|'+to
  const cached=cache.get(cacheKey)
  if(cached!==undefined&&Date.now()-cached.at<cacheTtlMs)return structuredClone(cached.value)
  const result=await read(scope.chatId,{from,to,revision:scope.revision})
  if(!result)throw Error('History revision unavailable')
  const value={revision:scope.revision,from,to,messages:result.context.messages}
  cache.set(cacheKey,{at:Date.now(),value})
  if(cache.size>cacheMax)cache.delete(cache.keys().next().value)
  return structuredClone(value)
 }
 return Object.freeze({issue,read:selected})
}
