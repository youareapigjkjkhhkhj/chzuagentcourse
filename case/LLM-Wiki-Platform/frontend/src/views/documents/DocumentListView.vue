<template>
  <div class="document-list">
    <!-- 搜索和筛选 -->
    <div class="filter-bar">
      <el-input
        v-model="searchKeyword"
        placeholder="搜索文档..."
        prefix-icon="Search"
        class="search-input"
        @keyup.enter="handleSearch"
      />
      
      <el-select v-model="selectedCategory" placeholder="选择分类" clearable>
        <el-option
          v-for="category in categories"
          :key="category.id"
          :label="category.name"
          :value="category.id"
        />
      </el-select>
      
      <el-button type="primary" @click="handleSearch">搜索</el-button>
      
      <el-button
        v-if="authStore.isEditor"
        type="success"
        @click="router.push('/documents/create')"
      >
        创建文档
      </el-button>
    </div>
    
    <!-- 文档列表 -->
    <div class="document-cards" v-loading="documentsStore.loading">
      <el-card
        v-for="document in documentsStore.documents"
        :key="document.id"
        class="document-card"
        shadow="hover"
        @click="router.push(`/documents/${document.id}`)"
      >
        <div class="card-header">
          <el-tag v-if="document.is_pinned" type="danger" size="small">置顶</el-tag>
          <el-tag v-if="document.is_featured" type="warning" size="small">精选</el-tag>
          <el-tag :type="getStatusType(document.status)" size="small">
            {{ getStatusText(document.status) }}
          </el-tag>
        </div>
        
        <h3 class="card-title">{{ document.title }}</h3>
        
        <p class="card-summary">{{ document.summary || '暂无摘要' }}</p>
        
        <div class="card-tags">
          <el-tag
            v-for="tag in document.tags"
            :key="tag.id"
            :color="tag.color"
            size="small"
          >
            {{ tag.name }}
          </el-tag>
        </div>
        
        <div class="card-footer">
          <div class="card-meta">
            <span>
              <el-icon><User /></el-icon>
              {{ document.author?.username }}
            </span>
            <span>
              <el-icon><View /></el-icon>
              {{ document.view_count }}
            </span>
            <span>
              <el-icon><ChatDotRound /></el-icon>
              {{ document.comment_count }}
            </span>
          </div>
          
          <span class="card-date">{{ formatDate(document.created_at) }}</span>
        </div>
      </el-card>
    </div>
    
    <!-- 分页 -->
    <div class="pagination" v-if="documentsStore.total > 0">
      <el-pagination
        v-model:current-page="currentPage"
        :page-size="documentsStore.pageSize"
        :total="documentsStore.total"
        layout="total, prev, pager, next, jumper"
        @current-change="handlePageChange"
      />
    </div>
    
    <!-- 空状态 -->
    <el-empty v-if="!documentsStore.loading && documentsStore.documents.length === 0">
      <template #description>
        <p>暂无文档数据</p>
      </template>
      <el-button type="primary" @click="router.push('/documents/create')">
        创建第一篇文档
      </el-button>
    </el-empty>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useDocumentsStore } from '@/stores/documents'
import { useAuthStore } from '@/stores/auth'
import { documentsApi } from '@/api/documents'
import type { Category } from '@/types/document'
import { formatDate } from '@/utils/helpers'
import { User, View, ChatDotRound } from '@element-plus/icons-vue'

const route = useRoute()
const router = useRouter()
const documentsStore = useDocumentsStore()
const authStore = useAuthStore()

const searchKeyword = ref((route.query.keyword as string) || '')
const selectedCategory = ref<number | undefined>()
const currentPage = ref(1)
const categories = ref<Category[]>([])

// 获取分类列表
const fetchCategories = async () => {
  try {
    const response = await documentsApi.getCategories()
    categories.value = response.categories
  } catch (error) {
    console.error('Failed to fetch categories:', error)
  }
}

// 获取文档列表
const fetchDocuments = async () => {
  await documentsStore.fetchDocuments({
    page: currentPage.value,
    keyword: searchKeyword.value,
    category_id: selectedCategory.value
  })
}

// 搜索
const handleSearch = () => {
  currentPage.value = 1
  fetchDocuments()
}

// 分页
const handlePageChange = (page: number) => {
  currentPage.value = page
  fetchDocuments()
}

// 获取状态类型
const getStatusType = (status: string) => {
  const types: Record<string, string> = {
    published: 'success',
    draft: 'info',
    archived: 'warning'
  }
  return types[status] || 'info'
}

// 获取状态文本
const getStatusText = (status: string) => {
  const texts: Record<string, string> = {
    published: '已发布',
    draft: '草稿',
    archived: '已归档'
  }
  return texts[status] || status
}

// 监听路由参数变化
watch(
  () => route.query.keyword,
  (newKeyword) => {
    if (newKeyword) {
      searchKeyword.value = newKeyword as string
      fetchDocuments()
    }
  }
)

onMounted(() => {
  fetchCategories()
  fetchDocuments()
})
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

.document-list {
  padding: $space-6;
}

.filter-bar {
  display: flex;
  gap: $space-3;
  margin-bottom: $space-6;

  .search-input {
    width: 320px;
  }
}

.document-cards {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: $space-5;
}

.document-card {
  cursor: pointer;
  transition: all $transition-base;

  &:hover {
    transform: translateY(-3px);
  }

  .card-header {
    display: flex;
    gap: $space-2;
    margin-bottom: $space-3;
  }

  .card-title {
    margin: 0 0 $space-2 0;
    font-family: $font-display;
    font-size: $font-size-lg;
    font-weight: 600;
    color: $text-primary;
    display: -webkit-box;
    -webkit-line-clamp: 2;
    -webkit-box-orient: vertical;
    overflow: hidden;
    letter-spacing: -0.01em;
  }

  .card-summary {
    color: $text-secondary;
    font-size: $font-size-sm;
    line-height: 1.65;
    display: -webkit-box;
    -webkit-line-clamp: 3;
    -webkit-box-orient: vertical;
    overflow: hidden;
    margin-bottom: $space-4;
  }

  .card-tags {
    display: flex;
    flex-wrap: wrap;
    gap: $space-2;
    margin-bottom: $space-4;

    :deep(.el-tag) {
      color: #fff;
      border-color: transparent;
    }
  }

  .card-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    color: $text-muted;
    font-size: $font-size-xs;

    .card-meta {
      display: flex;
      gap: $space-4;

      span {
        display: flex;
        align-items: center;
        gap: $space-1;
      }
    }
  }
}

.pagination {
  display: flex;
  justify-content: center;
  margin-top: $space-8;
}
</style>