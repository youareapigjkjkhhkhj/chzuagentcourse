/**
 * 统一 Tool 接口（AGENTS §4 tools / P1 任务 1）：
 * name / description / parameters(JSON Schema) / risk / assessRisk / execute。
 * ToolBus 负责注册与分发，Loop 层禁止硬编码工具分支（AGENTS §13）。
 */
import type { Risk, TodoItem } from '@agentbuddy/shared';

export interface ToolResult {
  text: string;
  /** P2：WRITE/EXEC 成功后的变更集元数据，orchestrator 据此发 diff_ready 事件 */
  change?: {
    changeId: string;
    /** 受影响文件（绝对路径）；bash 等无清单场景为空 */
    paths: string[];
  };
}

/** read 时刻 mtime 记录，edit/write 前新鲜度校验（技术方案 §4.3） */
export class ReadState {
  private readonly map = new Map<string, number>();

  record(path: string, mtimeMs: number): void {
    this.map.set(path, mtimeMs);
  }

  known(path: string): number | undefined {
    return this.map.get(path);
  }
}

export interface ToolContext {
  /** 工作区根（绝对路径） */
  workspace: string | null;
  signal: AbortSignal;
  readState: ReadState;
  /** WRITE/EXEC 前打快照（checkpoint v1），返回 changeId 或 null */
  snapshot(affected: string[]): Promise<string | null>;
  /** 用户路径 → 工作区内绝对路径；逃逸抛错（AGENTS §15） */
  resolvePath(userPath: string): Promise<string>;
  /** P4：todo_write 清单变更回调（事件 + 落盘由外层实现，工具不感知存储） */
  onTodos?(todos: TodoItem[]): void;
}

export interface Tool {
  name: string;
  description: string;
  /** JSON Schema（function calling parameters） */
  parameters: Record<string, unknown>;
  /** 静态风险等级 */
  risk: Risk;
  /** 按入参动态升级风险（如 bash 危险命令检测，§4.2） */
  assessRisk?(input: Record<string, unknown>): Risk;
  execute(ctx: ToolContext, input: Record<string, unknown>): Promise<ToolResult>;
}

/** 工具入参字符串字段安全读取 */
export function str(input: Record<string, unknown>, key: string): string {
  const v = input[key];
  if (typeof v !== 'string') throw new Error(`参数 ${key} 必须为字符串`);
  return v;
}

export function num(input: Record<string, unknown>, key: string, fallback: number): number {
  const v = input[key];
  if (v === undefined) return fallback;
  if (typeof v !== 'number' || !Number.isFinite(v)) throw new Error(`参数 ${key} 必须为数字`);
  return Math.floor(v);
}
