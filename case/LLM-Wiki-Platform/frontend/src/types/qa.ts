// 问答类型定义
export interface QARecord {
  id: number
  user_id: number
  question: string
  answer: string
  document_ids?: number[]
  confidence?: number
  feedback?: 'helpful' | 'not_helpful' | 'neutral'
  feedback_comment?: string
  response_time?: number
  model_used?: string
  tokens_used?: number
  session_id?: string
  created_at: string
}

export interface QAChatMessage {
  id: number
  role: 'user' | 'assistant'
  content: string
  sources?: QASource[]
  confidence?: number
  response_time?: number
  record_id?: number
  timestamp: string
}

export interface QASource {
  document_id: number
  content: string
  score: number
  metadata?: Record<string, any>
}

export interface QAAskResponse {
  answer: string
  sources: QASource[]
  confidence: number
  response_time: number
  record_id: number
}

export interface QAHistoryResponse {
  items: QARecord[]
  total: number
  pages: number
  current_page: number
}