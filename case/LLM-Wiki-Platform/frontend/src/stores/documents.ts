import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { Document, DocumentListParams } from '@/types/document'
import { documentsApi } from '@/api/documents'

export const useDocumentsStore = defineStore('documents', () => {
  const documents = ref<Document[]>([])
  const currentDocument = ref<Document | null>(null)
  const loading = ref(false)
  const total = ref(0)
  const currentPage = ref(1)
  const pageSize = ref(20)

  // 计算属性
  const hasMore = computed(() => documents.value.length < total.value)

  // 获取文档列表
  async function fetchDocuments(params: DocumentListParams = {}) {
    loading.value = true
    try {
      const response = await documentsApi.getDocuments({
        page: currentPage.value,
        per_page: pageSize.value,
        ...params
      })
      documents.value = response.items
      total.value = response.total
      return response
    } catch (error) {
      console.error('Failed to fetch documents:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  // 获取文档详情
  async function fetchDocument(id: number) {
    loading.value = true
    try {
      const response = await documentsApi.getDocument(id)
      currentDocument.value = response.document
      return response.document
    } catch (error) {
      console.error('Failed to fetch document:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  // 创建文档
  async function createDocument(data: Partial<Document>) {
    loading.value = true
    try {
      const response = await documentsApi.createDocument(data)
      documents.value.unshift(response.document)
      return response.document
    } catch (error) {
      console.error('Failed to create document:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  // 更新文档
  async function updateDocument(id: number, data: Partial<Document>) {
    loading.value = true
    try {
      const response = await documentsApi.updateDocument(id, data)
      const index = documents.value.findIndex(doc => doc.id === id)
      if (index !== -1) {
        documents.value[index] = response.document
      }
      if (currentDocument.value?.id === id) {
        currentDocument.value = response.document
      }
      return response.document
    } catch (error) {
      console.error('Failed to update document:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  // 删除文档
  async function deleteDocument(id: number) {
    loading.value = true
    try {
      await documentsApi.deleteDocument(id)
      documents.value = documents.value.filter(doc => doc.id !== id)
      if (currentDocument.value?.id === id) {
        currentDocument.value = null
      }
    } catch (error) {
      console.error('Failed to delete document:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  // 切换文档发布状态
  async function toggleDocumentStatus(id: number) {
    loading.value = true
    try {
      const response = await documentsApi.toggleDocumentStatus(id)
      const index = documents.value.findIndex(doc => doc.id === id)
      if (index !== -1) {
        documents.value[index] = response.document
      }
      if (currentDocument.value?.id === id) {
        currentDocument.value = response.document
      }
      return response.document
    } catch (error) {
      console.error('Failed to toggle document status:', error)
      throw error
    } finally {
      loading.value = false
    }
  }

  return {
    documents,
    currentDocument,
    loading,
    total,
    currentPage,
    pageSize,
    hasMore,
    fetchDocuments,
    fetchDocument,
    createDocument,
    updateDocument,
    deleteDocument,
    toggleDocumentStatus
  }
})