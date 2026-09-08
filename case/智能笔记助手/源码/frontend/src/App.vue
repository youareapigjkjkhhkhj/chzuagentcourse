<template>
  <div class="app">
    <header class="topbar">
      <div class="brand">
        <span class="logo">📒</span>
        <div>
          <h1>智能笔记助手</h1>
          <p>LangChain + RAG + FAISS · 让笔记会回答</p>
        </div>
      </div>
      <div class="status">
        <span :class="['dot', indexStatus.indexed ? 'on' : 'off']"></span>
        {{ indexStatus.indexed ? '知识库已就绪' : '知识库未构建' }}
        <span class="muted" v-if="indexStatus.vector_count != null">· 向量 {{ indexStatus.vector_count }}</span>
      </div>
    </header>

    <main class="layout">
      <NotePanel @changed="refreshStatus" />
      <ChatPanel />
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import NotePanel from './components/NotePanel.vue'
import ChatPanel from './components/ChatPanel.vue'
import { getIndexStatus } from './api'

const indexStatus = ref({ indexed: false, note_count: 0, vector_count: null })

async function refreshStatus() {
  try { indexStatus.value = await getIndexStatus() } catch (e) { /* ignore */ }
}
onMounted(refreshStatus)
</script>
