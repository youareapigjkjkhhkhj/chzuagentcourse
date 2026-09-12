/**
 * 页面上要显示的几个数字的格式化（P1-A10）。
 *
 * 这里只做「怎么显示」，不做「显示什么」：页数、时长、百分比都是服务端给的
 * 事实，前端不重算一份 —— 自己算的那份迟早和详情页对不上。
 */

/** 毫秒 → 「6s」「1m5s」。不到 1 秒的显示成「<1s」，0 表示「还没跑完」，给空串。 */
export function formatDurationMs(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return ''
  if (ms < 1000) return '<1s'
  const total = Math.round(ms / 1000)
  if (total < 60) return `${total}s`
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return seconds === 0 ? `${minutes}m` : `${minutes}m${seconds}s`
}

/** 课时（分钟）→ 「25 分钟」。0 分钟表示还没算出来，显示「—」。 */
export function formatMinutes(minutes: number): string {
  return minutes > 0 ? `${minutes} 分钟` : '—'
}

/** 页数 → 「12 页课件」。 */
export function formatPages(count: number): string {
  return `${count} 页课件`
}

/** 时间戳 → 「2 小时前」。解析不了就给空串，页面上少一截比多一句假话好。 */
export function formatRelativeTime(iso: string, now: number = Date.now()): string {
  const at = Date.parse(iso)
  if (!iso || Number.isNaN(at)) return ''
  const minutes = Math.floor(Math.max(0, now - at) / 60_000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days === 1) return '昨天'
  if (days < 7) return `${days} 天前`
  return `${Math.floor(days / 7)} 周前`
}
