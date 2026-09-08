<template>
  <div class="qa-history">
    <h2>问答历史</h2>
    
    <el-table :data="qaStore.qaHistory" style="width: 100%" v-loading="qaStore.loading">
      <el-table-column prop="question" label="问题" min-width="300">
        <template #default="{ row }">
          <div class="question-text">{{ row.question }}</div>
        </template>
      </el-table-column>
      
      <el-table-column prop="answer" label="回答" min-width="400">
        <template #default="{ row }">
          <div class="answer-text">{{ truncateText(row.answer, 100) }}</div>
        </template>
      </el-table-column>
      
      <el-table-column prop="confidence" label="置信度" width="100">
        <template #default="{ row }">
          <el-tag v-if="row.confidence" :type="getConfidenceType(row.confidence)">
            {{ (row.confidence * 100).toFixed(0) }}%
          </el-tag>
        </template>
      </el-table-column>
      
      <el-table-column prop="feedback" label="反馈" width="100">
        <template #default="{ row }">
          <el-tag v-if="row.feedback" :type="getFeedbackType(row.feedback)">
            {{ getFeedbackText(row.feedback) }}
          </el-tag>
          <span v-else class="no-feedback">-</span>
        </template>
      </el-table-column>
      
      <el-table-column prop="created_at" label="时间" width="180">
        <template #default="{ row }">
          {{ formatDate(row.created_at) }}
        </template>
      </el-table-column>
    </el-table>
    
    <div class="pagination" v-if="total > 0">
      <el-pagination
        v-model:current-page="currentPage"
        :page-size="20"
        :total="total"
        layout="total, prev, pager, next, jumper"
        @current-change="handlePageChange"
      />
    </div>
    
    <el-empty v-if="!qaStore.loading && qaStore.qaHistory.length === 0">
      <template #description>
        <p>暂无问答历史</p>
      </template>
      <el-button type="primary" @click="router.push('/qa')">
        开始提问
      </el-button>
    </el-empty>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useQAStore } from '@/stores/qa'
import { formatDate, truncateText } from '@/utils/helpers'

const router = useRouter()
const qaStore = useQAStore()

const currentPage = ref(1)
const total = ref(0)

const fetchHistory = async () => {
  const response = await qaStore.fetchQAHistory(currentPage.value)
  total.value = response.total
}

const handlePageChange = (page: number) => {
  currentPage.value = page
  fetchHistory()
}

const getConfidenceType = (confidence: number) => {
  if (confidence >= 0.8) return 'success'
  if (confidence >= 0.6) return 'warning'
  return 'danger'
}

const getFeedbackType = (feedback: string) => {
  const types: Record<string, string> = {
    helpful: 'success',
    not_helpful: 'danger',
    neutral: 'info'
  }
  return types[feedback] || 'info'
}

const getFeedbackText = (feedback: string) => {
  const texts: Record<string, string> = {
    helpful: '有帮助',
    not_helpful: '无帮助',
    neutral: '一般'
  }
  return texts[feedback] || feedback
}

onMounted(() => {
  fetchHistory()
})
</script>

<style lang="scss" scoped>
@use '@/styles/variables.scss' as *;

.qa-history {
  padding: 20px;
  
  h2 {
    margin: 0 0 20px 0;
    font-size: 24px;
    color: $text-primary;
  }
}

.question-text {
  color: $text-primary;
  font-weight: 500;
}

.answer-text {
  color: $text-secondary;
  font-size: 13px;
  line-height: 1.5;
}

.no-feedback {
  color: $text-muted;
}

.pagination {
  display: flex;
  justify-content: center;
  margin-top: 20px;
}
</style>