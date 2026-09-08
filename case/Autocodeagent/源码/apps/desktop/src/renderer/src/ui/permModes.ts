/** P3：权限三档元数据（原型 permOptions 文案 + 配色），顶栏状态 chip 与盾牌弹层共用 */
import type { PermissionMode } from '@agentbuddy/shared';

export interface PermModeMeta {
  v: PermissionMode;
  /** 弹层描述文案 */
  d: string;
  /** 盾牌按钮整体配色（含边框） */
  btn: string;
  /** 弹层内模式名单色 */
  tag: string;
  /** 顶栏状态 chip 配色 */
  chip: string;
}

/** 三档配色：Plan 蓝 / Ask 琥 / Auto 绿 */
export const PERM_OPTIONS: PermModeMeta[] = [
  { v: 'Plan', d: '只读分析，不改文件、不执行命令', btn: 'bg-blue-500/10 text-blue-700 border-blue-500/25', tag: 'text-blue-700', chip: 'text-blue-700 bg-blue-500/10' },
  { v: 'Ask', d: '副作用操作均逐次确认（默认，推荐）', btn: 'bg-amber-500/10 text-amber-700 border-amber-500/25', tag: 'text-amber-700', chip: 'text-amber-700 bg-amber-500/10' },
  { v: 'Auto', d: '读文件 / 写工作区 / 低风险命令自动，高风险仍询问', btn: 'bg-emerald-500/10 text-emerald-700 border-emerald-500/25', tag: 'text-emerald-700', chip: 'text-emerald-700 bg-emerald-500/10' },
];

export function modeMeta(mode: PermissionMode): PermModeMeta {
  return PERM_OPTIONS.find((o) => o.v === mode) ?? PERM_OPTIONS[1]!;
}
