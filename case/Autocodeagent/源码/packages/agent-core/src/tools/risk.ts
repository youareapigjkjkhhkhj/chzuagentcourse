/**
 * 命令风险启发式（P3 任务 3，§4.2 / AGENTS §16）。
 * 文档定位：启发式安全辅助而非安全边界——真正边界是 Permission Gate + workspace jail。
 * bash 工具 assessRisk 引用本模块；单测独立锁定模式清单。
 */
import type { Risk } from '@agentbuddy/shared';

/** 命中即升级 DANGEROUS（任何模式下必询问，§4.2） */
export const DANGEROUS_PATTERNS: RegExp[] = [
  /rm\s+(-\w*[rf]\w*|--force|--recursive)/i,
  /\bsudo\b/,
  /git\s+push\s+(--force|-f)\b/i,
  /git\s+reset\s+--hard/i,
  /git\s+clean\s+-\w*f/i,
  /npm\s+publish/i,
  /DROP\s+(TABLE|DATABASE)/i,
  /\b(format|mkfs)\b\s+[a-z]:/i,
  /\b(rd|del)\s+\/[sq]\b/i,
  /\bdd\s+if=/i,
  /\b(shutdown|reboot)\b/i,
  /curl[^|;&]*\|\s*(sh|bash)/i,
];

/** 命令串 → EXEC 或 DANGEROUS */
export function assessCommandRisk(command: string): Risk {
  return DANGEROUS_PATTERNS.some((re) => re.test(command)) ? 'DANGEROUS' : 'EXEC';
}
