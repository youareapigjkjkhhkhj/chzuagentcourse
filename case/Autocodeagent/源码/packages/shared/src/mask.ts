/** API Key 展示掩码：仅保留尾 4 位（不足 4 位全掩）。日志与 UI 共用。 */
export function maskKey(key: string): string {
  if (key.length <= 4) return '****';
  return `****${key.slice(-4)}`;
}
