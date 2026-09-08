/**
 * Permission Gate（AGENTS §14 硬边界 / 技术方案 §4.2 / P3 完整决策矩阵）。
 * 三模式查表：Plan 仅 READ / Ask 副作用全询问 / Auto READ+WRITE 自动、EXEC 白名单自动。
 * DANGEROUS 任何模式必询问且不提供 allow_always_session（仅「允许一次」）。
 * 会话级授权记忆：bash 同命令前缀复用（复合/管道命令与 DANGEROUS 不复用）、fs 同路径复用；MCP 按 server 信任（同 server 任一工具授权后其余复用）；随会话结束清空。
 * 拒绝结果由 Orchestrator 结构化回灌模型（区分模式拒绝 / 用户拒绝）。
 */
import type { PermissionMode, Risk } from '@agentbuddy/shared';

export type { PermissionMode };

export type MatrixAction = 'auto' | 'ask' | 'deny';

/** §4.2 决策矩阵直接落为查表 */
export const MATRIX: Record<PermissionMode, Record<Risk, MatrixAction>> = {
  Plan: { READ: 'auto', WRITE: 'deny', EXEC: 'deny', NETWORK: 'deny', DANGEROUS: 'deny' },
  Ask: { READ: 'auto', WRITE: 'ask', EXEC: 'ask', NETWORK: 'ask', DANGEROUS: 'ask' },
  Auto: { READ: 'auto', WRITE: 'auto', EXEC: 'ask', NETWORK: 'ask', DANGEROUS: 'ask' },
};

export interface PermissionQuery {
  callId: string;
  name: string;
  risk: Risk;
  /** 模式记忆 key 的目标部分：bash 为命令串，fs 为路径 */
  target: string;
  /** 弹层展示详情 */
  detail: string;
}

export interface PermissionAnswer {
  allow: boolean;
  remember: boolean;
}

export type AskFn = (query: PermissionQuery) => Promise<PermissionAnswer>;

/** 决策结果：allowed + 拒绝来源（orchestrator 据此差异化回灌） */
export interface PermissionDecision {
  allowed: boolean;
  deniedBy: 'mode' | 'user' | null;
}

export interface GateOptions {
  /** Auto 模式 EXEC 低风险白名单匹配器（compileWhitelist 产物） */
  execWhitelist?: (command: string) => boolean;
}

export class PermissionGate {
  /** 会话级授权记忆（随会话结束清空，§4.2） */
  private readonly sessionAllow = new Set<string>();
  mode: PermissionMode;
  private opts: GateOptions;

  constructor(
    mode: PermissionMode,
    private readonly ask: AskFn,
    opts: GateOptions = {},
  ) {
    this.mode = mode;
    this.opts = opts;
  }

  /** 每轮热更新模式与白名单（盾牌切换立即生效）；会话记忆保留 */
  update(mode: PermissionMode, opts: GateOptions = {}): void {
    this.mode = mode;
    this.opts = opts;
  }

  /** 纯查表部分（单测直接断言） */
  actionFor(risk: Risk): MatrixAction {
    return MATRIX[this.mode][risk];
  }

  memoryKey(name: string, target: string): string {
    return `${name}:${target}`;
  }

  /** 完整决策：矩阵 → Auto 白名单升级 → 会话记忆 → 询问用户 */
  async decide(query: PermissionQuery): Promise<PermissionDecision> {
    let action = this.actionFor(query.risk);
    // Auto 模式：EXEC 命中低风险白名单 → 自动执行（§4.2 白名单可配置）
    if (action === 'ask' && this.mode === 'Auto' && query.risk === 'EXEC' && this.opts.execWhitelist?.(query.target)) {
      action = 'auto';
    }
    if (action === 'auto') return { allowed: true, deniedBy: null };
    if (action === 'deny') return { allowed: false, deniedBy: 'mode' };

    if (this.matchMemory(query)) return { allowed: true, deniedBy: null };

    const answer = await this.ask(query);
    // DANGEROUS 不提供 allow_always_session，仅「允许一次」（§4.2）
    if (answer.allow && answer.remember && query.risk !== 'DANGEROUS') {
      this.sessionAllow.add(this.memoryKey(query.name, query.target));
    }
    return answer.allow ? { allowed: true, deniedBy: null } : { allowed: false, deniedBy: 'user' };
  }

  async check(query: PermissionQuery): Promise<boolean> {
    return (await this.decide(query)).allowed;
  }

  /** 会话记忆匹配：精确 key；bash 支持「已记命令为当前命令前缀」（复合/管道命令不复用）；MCP 按 server 前缀信任（P5） */
  private matchMemory(query: PermissionQuery): boolean {
    // P0：DANGEROUS 任何模式必询问——记忆只服务于非危险命令，防「已记前缀 + 危险拼接」绕过
    if (query.risk === 'DANGEROUS') return false;
    if (this.sessionAllow.has(this.memoryKey(query.name, query.target))) return true;
    if (query.name.startsWith('mcp__')) {
      const server = query.name.split('__')[1] ?? '';
      for (const key of this.sessionAllow) {
        if (key.startsWith(`mcp__${server}__`)) return true;
      }
      return false;
    }
    if (query.name !== 'bash') return false;
    for (const key of this.sessionAllow) {
      if (!key.startsWith('bash:')) continue;
      const remembered = key.slice('bash:'.length);
      if (!remembered || !query.target.startsWith(`${remembered} `)) continue;
      // P0：前缀之后出现 shell 元字符（&& / | / ; / 反引号 / $() / 换行）= 复合命令，视为不同命令必须重新询问
      const rest = query.target.slice(remembered.length);
      if (/[;|&`]|\$\(|[\r\n]/.test(rest)) continue;
      return true;
    }
    return false;
  }
}

/** 提取模式记忆目标：bash 取命令串，fs 类取 path，MCP 工具取 server 名（按 server 信任） */
export function primaryTarget(toolName: string, input: Record<string, unknown>): string {
  if (toolName === 'bash') return typeof input['command'] === 'string' ? (input['command'] as string).trim() : '';
  if (toolName.startsWith('mcp__')) return toolName.split('__')[1] ?? '';
  return typeof input['path'] === 'string' ? (input['path'] as string) : '';
}
