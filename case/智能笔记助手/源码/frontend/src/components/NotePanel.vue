<template>
  <section class="panel">
    <h2>笔记管理</h2>

    <div class="upload">
      <input type="file" accept=".md,.txt,.pdf,.markdown" @change="onFile" ref="fileInput" />
      <button :disabled="!file || uploading" @click="upload">
        {{ uploading ? '上传中…' : '上传笔记' }}
      </button>
    </div>

    <div class="actions">
      <button class="primary" :disabled="building" @click="build">
        {{ building ? '构建中…' : '构建知识库' }}
      </button>
    </div>
    <p class="hint" :class="{ err: buildErr }" v-if="buildMsg">{{ buildMsg }}</p>

    <h3>已上传 ({{ notes.length }})</h3>
    <ul class="notes">
      <li v-for="n in notes" :key="n.id">
        <span :title="n.name">{{ n.name }}</span>
        <button class="link" @click="remove(n.id)">删除</button>
      </li>
      <li v-if="!notes.length" class="empty">暂无笔记，先上传一份 .md / .txt / .pdf</li>
    </ul>
  </section>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { listNotes, uploadNote, deleteNote, buildIndex } from '../api'

const emit = defineEmits(['changed'])
const notes = ref([])
const file = ref(null)
const uploading = ref(false)
const building = ref(false)
const buildMsg = ref('')
const buildErr = ref(false)
const fileInput = ref(null)

async function load() { notes.value = await listNotes() }
function onFile(e) { file.value = e.target.files[0] || null }

async function upload() {
  if (!file.value) return
  uploading.value = true
  try {
    await uploadNote(file.value)
    file.value = null
    if (fileInput.value) fileInput.value.value = ''
    await load()
    emit('changed')
  } catch (e) {
    alert('上传失败：' + (e.message || e))
  } finally {
    uploading.value = false
  }
}

async function remove(id) {
  if (!confirm('确认删除该笔记？删除后知识库需重新构建。')) return
  await deleteNote(id)
  await load()
  emit('changed')
}

async function build() {
  building.value = true
  buildMsg.value = ''
  buildErr.value = false
  try {
    const r = await buildIndex()
    buildMsg.value = `已构建：${r.note_count} 篇笔记 / ${r.chunk_count} 切片 / ${r.vector_count} 向量`
    emit('changed')
  } catch (e) {
    buildErr.value = true
    buildMsg.value = '构建失败：' + (e.response?.data?.error || e.message || e)
  } finally {
    building.value = false
  }
}

onMounted(load)
</script>
