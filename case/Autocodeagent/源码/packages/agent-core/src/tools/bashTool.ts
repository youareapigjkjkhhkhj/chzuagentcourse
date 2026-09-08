/**
 * bash 工具（risk=EXEC，危险命令升级 DANGEROUS，§4.2 / AGENTS §16）。
 * 统一走 process.run()：cwd 强制工作区、超时默认 120s、输出 ≤20KB、平台化杀树。
 * 风险启发式检测只是安全辅助，真正边界是 Permission Gate + workspace jail。
 */
import { DEFAULT_OUTPUT_LIMIT, run } from '../process/run';
import { assessCommandRisk } from './risk';
import { num, str, type Tool } from './types';

const BASH_DEFAULT_TIMEOUT_S = 120;
const BASH_MAX_TIMEOUT_S = 600;

export const bashTool: Tool = {
  name: 'bash',
  description: '在工作区目录内执行 shell 命令（默认超时 120s，输出截断 20KB）。用于跑测试、构建、git 只读命令等。',
  parameters: {
    type: 'object',
    properties: {
      command: { type: 'string', description: '完整命令行' },
      timeout: { type: 'number', description: `超时秒数（默认 ${BASH_DEFAULT_TIMEOUT_S}，上限 ${BASH_MAX_TIMEOUT_S}）` },
    },
    required: ['command'],
  },
  risk: 'EXEC',
  assessRisk(input) {
    const cmd = typeof input['command'] === 'string' ? (input['command'] as string) : '';
    return assessCommandRisk(cmd);
  },
  async execute(ctx, input) {
    if (!ctx.workspace) throw new Error('未选择工作区目录，无法执行命令');
    const command = str(input, 'command');
    const timeoutS = Math.min(BASH_MAX_TIMEOUT_S, Math.max(1, num(input, 'timeout', BASH_DEFAULT_TIMEOUT_S)));
    const changeId = await ctx.snapshot([]); // EXEC 前快照（git 仓库才有意义；非 git 无受影响文件清单）
    const result = await run(command, {
      cwd: ctx.workspace,
      timeoutMs: timeoutS * 1000,
      outputLimit: DEFAULT_OUTPUT_LIMIT,
      signal: ctx.signal,
    });
    const flags = [
      result.timedOut ? `超时 ${timeoutS}s 已杀进程树` : '',
      result.truncated ? '输出超 20KB 已截断' : '',
    ].filter(Boolean).join('，');
    const head = `exit=${result.exitCode ?? 'null'}${result.ms ? ` · ${result.ms}ms` : ''}${flags ? ` · ${flags}` : ''}`;
    return {
      text: `${head}\n${result.output || '（无输出）'}`,
      change: changeId ? { changeId, paths: [] } : undefined,
    };
  },
};

export const BASH_TOOLS: Tool[] = [bashTool];
