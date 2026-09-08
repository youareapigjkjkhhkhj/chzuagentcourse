<template>
  <div class="home-page">
    <!-- 欢迎横幅 -->
    <section class="welcome-banner">
      <div class="banner-content fade-in-up">
        <h1>
          欢迎使用
          <span class="gradient-text">LLM Wiki</span>
        </h1>
        <p>面向企业运维团队的智能知识管理系统</p>
      </div>
      <div class="banner-decoration">
        <div class="glow-orb glow-orb-1"></div>
        <div class="glow-orb glow-orb-2"></div>
      </div>
    </section>
    
    <!-- 统计卡片 -->
    <section class="stats-section fade-in-up delay-1">
      <div class="stat-card" v-for="stat in stats" :key="stat.label">
        <div class="stat-icon" :style="{ background: stat.gradient }">
          <el-icon :size="24"><component :is="stat.icon" /></el-icon>
        </div>
        <div class="stat-info">
          <span class="stat-value">{{ stat.value }}</span>
          <span class="stat-label">{{ stat.label }}</span>
        </div>
      </div>
    </section>
    
    <!-- 快捷操作 -->
    <section class="actions-section fade-in-up delay-2">
      <h2 class="section-title">快捷操作</h2>
      <div class="actions-grid">
        <div 
          class="action-card" 
          v-for="action in quickActions" 
          :key="action.title"
          @click="router.push(action.path)"
        >
          <div class="action-icon" :style="{ background: action.gradient }">
            <el-icon :size="28"><component :is="action.icon" /></el-icon>
          </div>
          <h3>{{ action.title }}</h3>
          <p>{{ action.description }}</p>
          <div class="action-arrow">
            <el-icon><ArrowRight /></el-icon>
          </div>
        </div>
      </div>
    </section>
    
    <!-- 最近更新 -->
    <section class="recent-section fade-in-up delay-3">
      <div class="section-header">
        <h2 class="section-title">最近更新</h2>
        <router-link to="/documents" class="view-all">
          查看全部
          <el-icon><ArrowRight /></el-icon>
        </router-link>
      </div>
      
      <div class="documents-list">
        <div 
          class="document-item" 
          v-for="doc in recentDocuments" 
          :key="doc.id"
          @click="router.push(`/documents/${doc.id}`)"
        >
          <div class="doc-icon">
            <el-icon :size="20"><Document /></el-icon>
          </div>
          <div class="doc-info">
            <h4>{{ doc.title }}</h4>
            <div class="doc-meta">
              <span>
                <el-icon><User /></el-icon>
                {{ doc.author?.username }}
              </span>
              <span>
                <el-icon><View /></el-icon>
                {{ doc.view_count }}
              </span>
            </div>
          </div>
          <div class="doc-time">{{ formatDate(doc.updated_at) }}</div>
        </div>
        
        <el-empty v-if="recentDocuments.length === 0" description="暂无文档">
          <el-button type="primary" @click="router.push('/documents/create')">
            创建第一篇文档
          </el-button>
        </el-empty>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { documentsApi } from '@/api/documents'
import { useDocumentsStore } from '@/stores/documents'
import { statsApi } from '@/api/stats'
import type { Stats } from '@/api/stats'
import { formatDate } from '@/utils/helpers'
import { 
  Document, 
  ChatDotRound, 
  View, 
  User, 
  EditPen, 
  Search, 
  ArrowRight,
  Timer,
  Collection
} from '@element-plus/icons-vue'

const router = useRouter()
const documentsStore = useDocumentsStore()

const recentDocuments = ref<any[]>([])
const statsData = ref<Stats>({ document_count: 0, total_views: 0, qa_count: 0, active_users: 0 })

const stats = computed(() => [
  {
    label: '文档总数',
    value: statsData.value.document_count,
    icon: 'Document',
    gradient: 'linear-gradient(135deg, #0ea5e9 0%, #6366f1 100%)'
  },
  {
    label: '问答次数',
    value: statsData.value.qa_count,
    icon: 'ChatDotRound',
    gradient: 'linear-gradient(135deg, #10b981 0%, #34d399 100%)'
  },
  {
    label: '总浏览量',
    value: statsData.value.total_views,
    icon: 'View',
    gradient: 'linear-gradient(135deg, #f59e0b 0%, #fbbf24 100%)'
  },
  {
    label: '活跃用户',
    value: statsData.value.active_users,
    icon: 'User',
    gradient: 'linear-gradient(135deg, #ef4444 0%, #f87171 100%)'
  }
])

const quickActions = [
  {
    title: '创建文档',
    description: '创建新的知识文档',
    icon: 'EditPen',
    path: '/documents/create',
    gradient: 'linear-gradient(135deg, #0ea5e9 0%, #6366f1 100%)'
  },
  {
    title: '智能问答',
    description: '向AI提问获取答案',
    icon: 'ChatDotRound',
    path: '/qa',
    gradient: 'linear-gradient(135deg, #10b981 0%, #34d399 100%)'
  },
  {
    title: '搜索文档',
    description: '快速查找知识文档',
    icon: 'Search',
    path: '/documents',
    gradient: 'linear-gradient(135deg, #f59e0b 0%, #fbbf24 100%)'
  }
]

const fetchData = async () => {
  try {
    const [docsResp, statsResp] = await Promise.all([
      documentsApi.getDocuments({ per_page: 5 }),
      statsApi.getStats()
    ])
    recentDocuments.value = docsResp.items
    documentsStore.total = docsResp.total
    statsData.value = statsResp
  } catch (error) {
    console.error('Failed to fetch data:', error)
  }
}

onMounted(() => {
  fetchData()
})
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

.home-page {
  padding: $space-6;
  max-width: 1400px;
  margin: 0 auto;
}

// Welcome banner
.welcome-banner {
  position: relative;
  padding: $space-12 $space-10;
  background: $gradient-dark;
  border-radius: $radius-xl;
  border: 1px solid $border-color;
  overflow: hidden;
  margin-bottom: $space-6;
}

.banner-content {
  position: relative;
  z-index: 10;

  h1 {
    font-family: $font-display;
    font-size: $font-size-4xl;
    font-weight: 800;
    color: $text-primary;
    margin: 0 0 $space-3 0;
    letter-spacing: -0.04em;
    line-height: 1.15;
  }

  p {
    font-size: $font-size-lg;
    color: $text-secondary;
    margin: 0;
  }
}

.gradient-text {
  background: $gradient-primary;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.banner-decoration {
  position: absolute;
  inset: 0;
  overflow: hidden;
}

.glow-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);

  &-1 {
    width: 350px;
    height: 350px;
    background: rgba(245, 158, 11, 0.12);
    top: -120px;
    right: -60px;
    animation: float 6s ease-in-out infinite;
  }

  &-2 {
    width: 250px;
    height: 250px;
    background: rgba(239, 68, 68, 0.08);
    bottom: -60px;
    left: 20%;
    animation: float 8s ease-in-out infinite reverse;
  }
}

// Stats
.stats-section {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: $space-4;
  margin-bottom: $space-6;
}

.stat-card {
  display: flex;
  align-items: center;
  gap: $space-4;
  padding: $space-5;
  background: $bg-card;
  border: 1px solid $border-color;
  border-radius: $radius-lg;
  backdrop-filter: blur(8px);
  transition: all $transition-base;

  &:hover {
    border-color: $border-color-hover;
    transform: translateY(-2px);
    box-shadow: $shadow-lg, 0 0 20px rgba(245, 158, 11, 0.06);
  }
}

.stat-icon {
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: $radius-lg;
  color: white;
  flex-shrink: 0;
}

.stat-info {
  display: flex;
  flex-direction: column;
}

.stat-value {
  font-family: $font-display;
  font-size: $font-size-2xl;
  font-weight: 700;
  color: $text-primary;
  line-height: 1;
  letter-spacing: -0.03em;
}

.stat-label {
  font-size: $font-size-sm;
  color: $text-secondary;
  margin-top: $space-1;
}

// Quick actions
.actions-section {
  margin-bottom: $space-6;
}

.section-title {
  font-family: $font-display;
  font-size: $font-size-xl;
  font-weight: 700;
  color: $text-primary;
  margin: 0 0 $space-4 0;
  letter-spacing: -0.02em;
}

.section-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: $space-4;
}

.view-all {
  display: flex;
  align-items: center;
  gap: $space-1;
  font-size: $font-size-sm;
  color: $primary-light;
  text-decoration: none;
  transition: all $transition-fast;

  &:hover {
    color: $primary-color;
    gap: $space-2;
  }
}

.actions-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: $space-4;
}

.action-card {
  position: relative;
  padding: $space-6;
  background: $bg-card;
  border: 1px solid $border-color;
  border-radius: $radius-lg;
  cursor: pointer;
  transition: all $transition-base;
  overflow: hidden;

  &:hover {
    border-color: $border-color-hover;
    transform: translateY(-4px);
    box-shadow: $shadow-lg, 0 0 24px rgba(245, 158, 11, 0.08);

    .action-arrow {
      opacity: 1;
      transform: translateX(0);
    }
  }

  h3 {
    font-family: $font-display;
    font-size: $font-size-lg;
    font-weight: 600;
    color: $text-primary;
    margin: $space-4 0 $space-2 0;
  }

  p {
    font-size: $font-size-sm;
    color: $text-secondary;
    margin: 0;
  }
}

.action-icon {
  width: 56px;
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: $radius-lg;
  color: white;
}

.action-arrow {
  position: absolute;
  bottom: $space-4;
  right: $space-4;
  width: 32px;
  height: 32px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(245, 158, 11, 0.1);
  border-radius: $radius-full;
  color: $primary-light;
  opacity: 0;
  transform: translateX(-10px);
  transition: all $transition-base;
}

// Recent updates
.recent-section {
  background: $bg-card;
  border: 1px solid $border-color;
  border-radius: $radius-lg;
  padding: $space-5;
}

.documents-list {
  display: flex;
  flex-direction: column;
}

.document-item {
  display: flex;
  align-items: center;
  gap: $space-4;
  padding: $space-4;
  border-radius: $radius-md;
  cursor: pointer;
  transition: background $transition-fast;

  &:hover {
    background: rgba(245, 158, 11, 0.03);
  }

  &:not(:last-child) {
    border-bottom: 1px solid $border-color;
  }
}

.doc-icon {
  width: 40px;
  height: 40px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(245, 158, 11, 0.08);
  border-radius: $radius-md;
  color: $primary-light;
  flex-shrink: 0;
}

.doc-info {
  flex: 1;
  min-width: 0;

  h4 {
    font-family: $font-body;
    font-size: $font-size-base;
    font-weight: 500;
    color: $text-primary;
    margin: 0 0 $space-1 0;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
}

.doc-meta {
  display: flex;
  gap: $space-4;

  span {
    display: flex;
    align-items: center;
    gap: $space-1;
    font-size: $font-size-xs;
    color: $text-muted;
  }
}

.doc-time {
  font-size: $font-size-xs;
  color: $text-muted;
  white-space: nowrap;
}

// Responsive
@media (max-width: 1024px) {
  .stats-section {
    grid-template-columns: repeat(2, 1fr);
  }

  .actions-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .stats-section {
    grid-template-columns: 1fr;
  }

  .welcome-banner {
    padding: $space-6 $space-4;

    h1 {
      font-size: $font-size-2xl;
    }
  }
}
</style>