import api from './index'
import type { QARecord, QAAskResponse, QAHistoryResponse } from '@/types/qa'

export const qaApi = {
  // 提问
  async askQuestion(data: {
    question: string
    context?: Record<string, any>
    session_id?: string
  }): Promise<QAAskResponse> {
    return api.post('/qa/ask', data)
  },

  // 获取问答历史
  async getQAHistory(page: number = 1, per_page: number = 20): Promise<QAHistoryResponse> {
    return api.get('/qa/history', { params: { page, per_page } })
  },

  // 提交反馈
  async submitFeedback(data: {
    record_id: number
    feedback: string
    comment?: string
  }): Promise<void> {
    return api.post('/qa/feedback', data)
  }
}