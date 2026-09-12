import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { QARecord, QAChatMessage } from '@/types/qa'
import { qaApi } from '@/api/qa'
import { useAuthStore } from './auth'

export const useQAStore = defineStore('qa', () => {
  const chatMessages = ref<QAChatMessage[]>([])
  const qaHistory = ref<QARecord[]>([])
  const loading = ref(false)
  const sessionId = ref<string>(generateSessionId())

  function generateSessionId(): string {
    return `session_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
  }

  // 发送问题（SSE 流式）
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

    // 创建 AI 消息占位
    const aiMessage: QAChatMessage = {
      id: Date.now() + 1,
      role: 'assistant',
      content: '',
      sources: [],
      timestamp: new Date().toISOString()
    }
    chatMessages.value.push(aiMessage)

    try {
      const authStore = useAuthStore()
      const token = authStore.token

      const response = await fetch('/api/v1/qa/ask_stream', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          question,
          session_id: sessionId.value
        })
      })

      const reader = response.body!.getReader()
      const decoder = new TextDecoder()

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const text = decoder.decode(value, { stream: true })
        const lines = text.split('\n')

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6))

              if (data.type === 'sources') {
                aiMessage.sources = data.sources
              } else if (data.type === 'chunk') {
                aiMessage.content += data.content
                // 实时滚动到底部
                const container = document.querySelector('.chat-messages')
                if (container) {
                  container.scrollTop = container.scrollHeight
                }
              } else if (data.type === 'done') {
                aiMessage.record_id = data.record_id
                aiMessage.response_time = 0
              } else if (data.type === 'error') {
                aiMessage.content = '抱歉，发生了错误: ' + data.message
              }
            } catch (e) {
              // 忽略解析错误
            }
          }
        }
      }

      return aiMessage
    } catch (error) {
      aiMessage.content = '抱歉，发生了错误，请稍后重试。'
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
