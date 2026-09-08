// 通用类型定义
export interface ApiResponse<T = any> {
  code: number
  message: string
  data: T
}

export interface PaginationParams {
  page: number
  per_page: number
}

export interface SearchParams {
  keyword: string
  category_id?: number
  tags?: string[]
}