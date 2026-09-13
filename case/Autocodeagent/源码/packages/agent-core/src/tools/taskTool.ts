/**
 * task 工具（主流 Agent 同款 subagent 派发）：
 * 主 agent 把可并行 / 需上下文隔离的子任务派发给「专家」子代理，子代理在独立上下文跑一个嵌套 runTurn，
 * 完成后仅把结果摘要回灌主循环（不污染主上下文）。适合批量产出（如分别生成多个文档）等场景。
 * 风险 READ（派发本身免询问）；子代理内部各工具调用仍各自走权限 gate（权限粒度下沉，不双重询问）。
 * 子代理定义复用现有 Expert（persona 做子系统提示、tools 限定子工具集）；spawn 由外层（chatService）注入，
 * agent-core 不感知 Expert 存储 / 模型配置（§4 模块边界）。depth 固定 1：子 bus 不含 task（外层构建时收口）。
 */
import type { Tool } from './types';
import { str } from './types';

export const TASK_TOOL_NAME = 'task';

/** 子代理派发器：由外层注入（负责组装嵌套 runTurn 的模型 / 权限 / 专家依赖），返回子代理最终结果文本 */
export type SpawnSubagent = (expertId: string | undefined, prompt: string, signal: AbortSignal) => Promise<string>;

/**
 * 构造 task（子代理派发）工具。
 * @param spawn 子代理派发器（外层注入；agent-core 只提供工具外壳与参数校验，不感知 Expert / 模型）
 */
export function createTaskTool(spawn: SpawnSubagent): Tool {
  return {
    name: TASK_TOOL_NAME,
    description:
      '把子任务派发给子代理在独立上下文中执行，完成后返回其结果摘要。适合：可并行的批量任务（如分别生成多个文档、处理多个彼此独立的条目）、需要与主对话隔离上下文的探索或产出。' +
      '同一轮可派发多个 task 并行处理（各子代理上下文互不干扰）。expertId 可选：指定则套用该专家的人设与工具限定，缺省为通用子代理。' +
      'prompt 必须自包含子任务所需的全部信息——子代理看不到主对话历史。',
    parameters: {
      type: 'object',
      properties: {
        prompt: { type: 'string', description: '子任务的完整指令（自包含，子代理无主对话上下文）' },
        expertId: { type: 'string', description: '可选：处理该子任务的专家 id（套用人设与工具限定）' },
      },
      required: ['prompt'],
    },
    risk: 'READ',
    async execute(ctx, input) {
      const prompt = str(input, 'prompt').trim();
      if (!prompt) throw new Error('参数 prompt 不能为空');
      const rawExpertId = input['expertId'];
      const expertId = typeof rawExpertId === 'string' && rawExpertId.trim() ? rawExpertId.trim() : undefined;
      const result = await spawn(expertId, prompt, ctx.signal);
      return { text: result || '（子代理未返回内容）' };
    },
  };
}
