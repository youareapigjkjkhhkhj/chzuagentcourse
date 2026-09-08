<template>
  <div class="document-detail" v-loading="loading">
    <div class="back-link" @click="router.push('/documents')">
      <el-icon><ArrowLeft /></el-icon>
      <span>返回文档列表</span>
    </div>

    <div class="document-header">
      <h1>{{ document?.title }}</h1>
      
      <div class="document-meta">
        <span>
          <el-icon><User /></el-icon>
          {{ document?.author?.username }}
        </span>
        <span>
          <el-icon><Calendar /></el-icon>
          {{ formatDate(document?.created_at) }}
        </span>
        <span>
          <el-icon><View /></el-icon>
          {{ document?.view_count }} 次浏览
        </span>
        <span>
          <el-icon><Document /></el-icon>
          版本 {{ document?.version }}
        </span>
      </div>
      
      <div class="document-tags">
        <el-tag
          v-for="tag in document?.tags"
          :key="tag.id"
          :color="tag.color"
        >
          {{ tag.name }}
        </el-tag>
      </div>
      
      <div class="document-actions" v-if="authStore.isEditor">
        <el-button type="primary" @click="router.push(`/documents/${document?.id}/edit`)">
          <el-icon><Edit /></el-icon>
          编辑
        </el-button>
        <el-button type="danger" @click="handleDelete">
          <el-icon><Delete /></el-icon>
          删除
        </el-button>
      </div>
    </div>
    
    <div class="document-content" v-if="document?.content">
      <div v-html="renderMarkdown(document.content)" />
    </div>
    
    <el-empty v-else description="暂无内容" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDocumentsStore } from '@/stores/documents'
import { useAuthStore } from '@/stores/auth'
import { formatDate } from '@/utils/helpers'
import { ElMessage, ElMessageBox } from 'element-plus'
import MarkdownIt from 'markdown-it'
import { User, Calendar, View, Document, Edit, Delete, ArrowLeft } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const documentsStore = useDocumentsStore()
const authStore = useAuthStore()

const loading = ref(false)
const document = ref<any>(null)

const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true
})

const renderMarkdown = (text: string) => {
  return md.render(text)
}

const fetchDocument = async () => {
  loading.value = true
  try {
    const id = Number(route.params.id)
    document.value = await documentsStore.fetchDocument(id)
  } catch (error) {
    console.error('Failed to fetch document:', error)
    ElMessage.error('获取文档失败')
  } finally {
    loading.value = false
  }
}

const handleDelete = async () => {
  try {
    await ElMessageBox.confirm('确定要删除这篇文档吗？', '确认删除', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
    
    await documentsStore.deleteDocument(Number(route.params.id))
    ElMessage.success('删除成功')
    router.push('/documents')
  } catch (error) {
    if (error !== 'cancel') {
      console.error('Failed to delete document:', error)
      ElMessage.error('删除失败')
    }
  }
}

onMounted(() => {
  fetchDocument()
})
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

.document-detail {
  max-width: 960px;
  margin: 0 auto;
  padding: $space-6 $space-4;

  .back-link {
    display: inline-flex;
    align-items: center;
    gap: $space-1;
    color: $text-secondary;
    font-size: $font-size-sm;
    margin-bottom: $space-4;
    cursor: pointer;
    transition: color $transition-fast;

    &:hover { color: $primary-light; }
  }
}

.document-header {
  margin-bottom: $space-6;
  padding-bottom: $space-4;
  border-bottom: 1px solid $border-color;

  h1 {
    margin: 0 0 $space-3 0;
    font-size: $font-size-3xl;
    font-weight: 700;
    color: $text-primary;
    line-height: 1.3;
  }
}

.document-meta {
  display: flex;
  flex-wrap: wrap;
  gap: $space-4;
  color: $text-secondary;
  font-size: $font-size-sm;
  margin-bottom: $space-3;

  span {
    display: inline-flex;
    align-items: center;
    gap: $space-1;

    .el-icon { color: $primary-light; }
  }
}

.document-tags {
  display: flex;
  flex-wrap: wrap;
  gap: $space-2;
  margin-bottom: $space-4;

  .el-tag {
    border: none;
    font-weight: 500;
  }
}

.document-actions {
  display: flex;
  gap: $space-2;
}

.document-content {
  background: $bg-card;
  backdrop-filter: blur(12px);
  padding: $space-8;
  border-radius: $radius-lg;
  border: 1px solid $border-color;
  box-shadow: $shadow-md;
  line-height: 1.75;
  color: $text-primary;
  font-size: $font-size-base;

  :deep(h1),
  :deep(h2),
  :deep(h3),
  :deep(h4),
  :deep(h5),
  :deep(h6) {
    margin-top: $space-6;
    margin-bottom: $space-3;
    color: $text-primary;
    font-weight: 600;
    line-height: 1.4;

    &:first-child { margin-top: 0; }
  }
  :deep(h1) { font-size: $font-size-2xl; border-bottom: 1px solid $border-color; padding-bottom: $space-2; }
  :deep(h2) { font-size: $font-size-xl; }
  :deep(h3) { font-size: $font-size-lg; color: $primary-light; }

  :deep(p) {
    margin: $space-3 0;
    color: $text-primary;
  }

  :deep(a) {
    color: $primary-light;
    text-decoration: none;
    border-bottom: 1px solid transparent;
    transition: border-color $transition-fast;
    &:hover { border-bottom-color: $primary-light; }
  }

  :deep(strong) { color: $text-primary; font-weight: 600; }
  :deep(ul), :deep(ol) {
    margin: $space-3 0;
    padding-left: $space-6;
    color: $text-primary;
    li { margin: $space-1 0; }
  }

  :deep(code) {
    background: rgba(14, 165, 233, 0.12);
    color: $primary-light;
    padding: 2px 6px;
    border-radius: $radius-sm;
    font-family: $font-mono;
    font-size: 0.9em;
  }

  :deep(pre) {
    background: #0b1220;
    color: #e2e8f0;
    padding: $space-4;
    border-radius: $radius-md;
    border: 1px solid $border-color;
    overflow-x: auto;
    margin: $space-4 0;

    code {
      background: none;
      color: inherit;
      padding: 0;
    }
  }

  :deep(blockquote) {
    border-left: 3px solid $primary-color;
    margin: $space-4 0;
    padding: $space-2 $space-4;
    background: rgba(14, 165, 233, 0.06);
    color: $text-secondary;
    border-radius: 0 $radius-sm $radius-sm 0;
  }

  :deep(table) {
    width: 100%;
    border-collapse: collapse;
    margin: $space-4 0;
    font-size: $font-size-sm;
    th, td {
      padding: $space-2 $space-3;
      border: 1px solid $border-color;
      text-align: left;
    }
    th { background: $bg-secondary; color: $text-primary; font-weight: 600; }
  }

  :deep(hr) {
    border: none;
    border-top: 1px solid $border-color;
    margin: $space-6 0;
  }
}
</style>