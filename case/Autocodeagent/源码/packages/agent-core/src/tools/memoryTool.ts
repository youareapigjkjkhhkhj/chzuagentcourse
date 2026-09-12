/**
 * remember 工具（Tier3 跨会话记忆写入端）：模型觉察到值得长期记住的偏好 / 项目事实 / 经验教训时主动记一条。
 * 与 todo_write 同构（risk=READ，各权限模式免确认——写的是 app 内部文件 .AgentBuddy/memory.md，非用户文档）；
 * 但 memory 是工作区独立文件（非会话态），故工具直接经 memory.ts 落盘，无需 todo_write 那样的外层回调链。
 * 读取注入端见 context.ts（assembleContext 每轮 readMemory 注入系统提示）。
 */
import { appendMemory } from '../memory';
import { str, type Tool, type ToolResult } from './types';

/** 单条记忆长度上限：一条应是「一句话」，过长说明该拆分或本就不该记 */
const MAX_ENTRY_CHARS = 500;

export const REMEMBER_TOOL: Tool = {
  name: 'remember',
  description:
    '把值得跨会话长期记住的信息写入工作区记忆文件（.AgentBuddy/memory.md）；下次会话开始自动注入，实现「越用越懂这个工作区」。' +
    '应记：用户明确的偏好/习惯（如「回复要简洁」「注释用中文」）、项目长期事实与约定（技术栈、目录约定、构建/测试命令）、可复用的经验教训。' +
    '不应记：一次性任务细节、可从代码或配置直接读出的信息、以及任何敏感凭据（密钥/密码/token 一律禁止记录）。' +
    '一次只记一条；text 为可独立理解的一句话。',
  parameters: {
    type: 'object',
    properties: {
      text: { type: 'string', description: '要记住的一条信息（一句话，简洁具体，≤500 字）' },
    },
    required: ['text'],
  },
  risk: 'READ',
  async execute(ctx, input): Promise<ToolResult> {
    const text = str(input, 'text').trim();
    if (!text) throw new Error('记忆内容不能为空');
    if (text.length > MAX_ENTRY_CHARS) throw new Error(`单条记忆最多 ${MAX_ENTRY_CHARS} 字（请精简或拆分为多条）`);
    if (!ctx.workspace) throw new Error('尚未选择工作区，无法写入记忆文件');
    const line = await appendMemory(ctx.workspace, text);
    return { text: `已记入工作区记忆：${line}` };
  },
};
