import axios from 'axios'

const http = axios.create({ baseURL: '/api' })

export async function listNotes() {
  const { data } = await http.get('/notes')
  return data.notes || []
}

export async function uploadNote(file) {
  const form = new FormData()
  form.append('file', file)
  const { data } = await http.post('/notes/upload', form)
  return data.note
}

export async function deleteNote(id) {
  await http.delete('/notes/' + encodeURIComponent(id))
}

export async function buildIndex() {
  const { data } = await http.post('/index/rebuild')
  return data
}

export async function getIndexStatus() {
  const { data } = await http.get('/index/status')
  return data
}

export async function askQA(question, topK) {
  const { data } = await http.post('/qa', { question, top_k: topK })
  if (data.error) throw new Error(data.error)
  return data
}

// SSE 流式问答：逐 token 回调，结束时返回来源
export async function streamQA(question, topK, onToken, onDone, onError) {
  const resp = await fetch('/api/qa/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, top_k: topK })
  })
  if (!resp.ok) {
    onError('请求失败：' + resp.status)
    return
  }
  const reader = resp.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const parts = buf.split('\n\n')
    buf = parts.pop()
    for (const p of parts) {
      if (p.startsWith('data: ')) {
        try {
          const obj = JSON.parse(p.slice(6))
          if (obj.type === 'token') onToken(obj.content)
          else if (obj.type === 'done') onDone(obj.sources || [])
          else if (obj.type === 'error') onError(obj.message)
        } catch (e) { /* 忽略不完整帧 */ }
      }
    }
  }
}
