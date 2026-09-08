import { format } from 'date-fns'

export function formatDate(date: string | Date | null, formatStr: string = 'yyyy-MM-dd HH:mm'): string {
  if (!date) return '-'
  const d = typeof date === 'string' ? new Date(date) : date
  if (isNaN(d.getTime())) {
    // 兼容后端无时区 ISO 时间（如 "2026-08-27T12:03:40"，new Date 会解析为 Invalid Date）
    const s = String(date)
    return s.length >= 16 ? s.slice(0, 16).replace('T', ' ') : (s || '-')
  }
  return format(d, formatStr)
}

export function truncateText(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text
  return text.substring(0, maxLength) + '...'
}

export function generateSlug(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .replace(/[-\s]+/g, '-')
    .trim()
}

export function debounce<T extends (...args: any[]) => any>(
  func: T,
  wait: number
): (...args: Parameters<T>) => void {
  let timeout: ReturnType<typeof setTimeout> | null = null
  return (...args: Parameters<T>) => {
    if (timeout) clearTimeout(timeout)
    timeout = setTimeout(() => func(...args), wait)
  }
}