import type { Expert } from '@agentbuddy/shared';

/** 绑定工具徽标文案：mcp:github → #github；read → read */
export function toolLabel(t: string): string {
  return t.startsWith('mcp:') ? `#${t.slice(4)}` : t;
}

/** 绑定全量清单（卡片/横幅截断显示时 hover 看全量）：工具 + /技能 空格分隔 */
export function bindTitle(e: Expert): string {
  const parts = [...e.tools.map(toolLabel), ...e.skills.map((s) => `/${s}`)];
  return parts.length > 0 ? parts.join('  ') : '未绑定（全量工具与技能可用）';
}

/** 绑定计数（专家会话横幅摘要用）：内置工具 / MCP 连接器 / 技能 三类 */
export function bindCounts(e: Expert): { builtin: number; mcp: number; skills: number } {
  const mcp = e.tools.filter((t) => t.startsWith('mcp:')).length;
  return { builtin: e.tools.length - mcp, mcp, skills: e.skills.length };
}
