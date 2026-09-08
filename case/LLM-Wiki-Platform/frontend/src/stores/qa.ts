import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { QARecord, QAChatMessage } from '@/types/qa'
import { qaApi } from '@/api/qa'

export const useQAStore = defineStore('qa', () => {
  const chatMessages = ref<QAChatMessage[]>([])
  const qaHistory = ref<QARecord[]>([])
  const loading = ref(false)
  const sessionId = ref<string>(generateSessionId())

  function generateSessionId(): string {
    return `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
  }

  // 发送问题
  async function askQuestion(question: string) {
    // 添加用户消息
    const userMessage: QAChatMessage = {
      id: Date.now(),
      role: 'user',
      content: question,
      timestamp: new Date().toISOString()
    }
    chatMessages.value.push(userMessage)

    loading.value = true
    try {
      const response = await qaApi.askQuestion({
        question,
        session_id: sessionId.value
      })

      // 添加AI回答
      const aiMessage: QAChatMessage = {
        id: Date.now() + 1,
        role: 'assistant',
        content: response.answer,
        sources: response.sources,
        confidence: response.confidence,
        response_time: response.response_time,
        record_id: response.record_id,
        timestamp: new Date().toISOString()
      }
      chatMessages.value.push(aiMessage)

      return response
    } catch (error) {
      // 添加错误消息
      const errorMessage: QAChatMessage = {
        id: Date.now() + 1,
        role: 'assistant',
        content: '抱歉，发生了错误，请稍后重试。',
        timestamp: new Date().toISOString()
      }
      chatMessages.value.push(errorMessage)
      throw error
    } finally {
      loading.value = false
    }
  }

  // 获取问答历史
  async function fetchQAHistory(page = 1, perPage = 20) {
    loading.value = true
    try {
      const response = await qaApi.getQAHistory(page, perPage)
      qaHistory.value = response.items
      return response
    } catch (error) {
      console.error('Failed to fetch QA history:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  // 提交反馈
  async function submitFeedback(recordId: number, feedback: string, comment?: string) {
    try {
      await qaApi.submitFeedback({
        record_id: recordId,
        feedback,
        comment
      })
    } catch (error) {
      console.error('Failed to submit feedback:', error)
      throw error
    }
  }

  // 清空聊天记录
  function clearChat() {
    chatMessages.value = []
    sessionId.value = generateSessionId()
  }

  return {
    chatMessages,
    qaHistory,
    loading,
    sessionId,
    askQuestion,
    fetchQAHistory,
    submitFeedback,
    clearChat
  }
})