import api from './index'

export interface Stats {
  document_count: number
  total_views: number
  qa_count: number
  active_users: number
}

export const statsApi = {
  async getStats(): Promise<Stats> {
    return api.get('/stats')
  }
}