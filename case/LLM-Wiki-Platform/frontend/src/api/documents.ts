import api from './index'
import type { Document, DocumentListResponse } from '@/types/document'

export const documentsApi = {
  // 获取文档列表
  async getDocuments(params: {
    page?: number
    per_page?: number
    category_id?: number
    keyword?: string
    status?: string
  }): Promise<DocumentListResponse> {
    return api.get('/documents', { params })
  },

  // 获取文档详情
  async getDocument(id: number): Promise<{ document: Document }> {
    return api.get(`/documents/${id}`)
  },

  // 创建文档
  async createDocument(data: Partial<Document>): Promise<{ document: Document }> {
    return api.post('/documents', data)
  },

  // 更新文档
  async updateDocument(id: number, data: Partial<Document>): Promise<{ document: Document }> {
    return api.put(`/documents/${id}`, data)
  },

  // 删除文档
  async deleteDocument(id: number): Promise<void> {
    return api.delete(`/documents/${id}`)
  },

  // 切换文档发布状态
  async toggleDocumentStatus(id: number): Promise<{ document: Document }> {
    return api.post(`/documents/${id}/toggle-status`)
  },

  // 搜索文档
  async searchDocuments(keyword: string, category_id?: number, tags?: string[]): Promise<{ results: Document[] }> {
    return api.get('/documents/search', { params: { keyword, category_id, tags } })
  },

  // 获取分类列表
  async getCategories(): Promise<{ categories: any[] }> {
    return api.get('/categories')
  },

  // 获取标签列表
  async getTags(): Promise<{ tags: any[] }> {
    return api.get('/tags')
  }
}