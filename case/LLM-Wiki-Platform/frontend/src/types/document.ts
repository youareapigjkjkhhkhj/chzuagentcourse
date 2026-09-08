// 文档类型定义
import type { User } from './user'

export interface Document {
  id: number
  title: string
  content?: string
  summary?: string
  author?: User
  category?: Category
  tags: Tag[]
  status: 'draft' | 'published' | 'archived'
  visibility: 'public' | 'private' | 'department'
  view_count: number
  like_count: number
  comment_count: number
  version: number
  is_pinned: boolean
  is_featured: boolean
  allow_comment: boolean
  created_at: string
  updated_at: string
  published_at?: string
}

export interface Category {
  id: number
  name: string
  description?: string
  parent_id?: number
  level: number
  sort_order: number
  icon?: string
  color?: string
  is_active: boolean
  document_count: number
  children?: Category[]
}

export interface Tag {
  id: number
  name: string
  description?: string
  color: string
  usage_count: number
}

export interface DocumentListParams {
  page?: number
  per_page?: number
  category_id?: number
  keyword?: string
  status?: string
}

export interface DocumentListResponse {
  items: Document[]
  total: number
  pages: number
  current_page: number
}