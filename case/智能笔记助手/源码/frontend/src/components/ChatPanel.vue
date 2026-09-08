<template>
  <section class="panel chat">
    <h2>智能问答</h2>
    <label class="toggle">
      <input type="checkbox" v-model="useStream" /> 流式输出
    </label>

    <div class="messages" ref="box">
      <div v-for="(m, i) in messages" :key="i" :class="['msg', m.role]">
        <div class="role">{{ m.role === 'user' ? '我' : '助手' }}</div>
        <div class="text">{{ m.content || '…' }}</div>
        <div class="sources" v-if="m.sources && m.sources.length">
          来源：
          <span class="chip" v-for="s in m.sources" :key="s.source">{{ s.source }}</span>
        </div>
      </div>
      <p v-if="!messages.length" class="hint" style="color:var(--muted)">
        先在左侧上传笔记并「构建知识库」，然后在这里提问。
      </p>
    </div>

    <div class="composer">
      <textarea
        v-model="question"
        @keydown.ctrl.enter="send"
        placeholder="输入问题，Ctrl + Enter 发送…"
      ></textarea>
      <button class="primary" :disabled="sending || !question.trim()" @click="send">
        {{ sending ? '生成中…' : '发送' }}
      </button>
    </div>
  </section>
</template>

<script setup>
import { ref, nextTick } from 'vue'
import { askQA, streamQA } from '../api'

const messages = ref([])
const question = ref('')
const sending = ref(false)
const useStream = ref(true)
const box = ref(null)

async function scroll() {
  await nextTick()
  if (box.value) box.value.scrollTop = box.value.scrollHeight
}

async function send() {
  const q = question.value.trim()
  if (!q || sending.value) return
  sending.value = true
  messages.value.push({ role: 'user', content: q })
  const assistant = { role: 'assistant', content: '', sources: [] }
  messages.value.push(assistant)
  question.value = ''
  await scroll()

  try {
    if (useStream.value) {
      await streamQA(
        q,
        null,
        (tok) => { assistant.content += tok; scroll() },
        (sources) => { assistant.sources = sources },
        (msg) => { assistant.content = '⚠️ ' + msg }
      )
    } else {
      const data = await askQA(q, null)
      assistant.content = data.answer
      assistant.sources = data.sources || []
    }
  } catch (e) {
    assistant.content = '⚠️ 出错了：' + (e.message || e)
  } finally {
    sending.value = false
    await scroll()
  }
}
</script>
