/**
 * P4 todo_write：会话任务清单（内存态，随会话落盘）。
 * 风险为 READ：不触碰文件系统，副作用经 ctx.onTodos 回调上抛（事件 + 持久化由外层实现）。
 */
import type { TodoItem } from '@agentbuddy/shared';
import type { Tool, ToolResult } from './types';

const STATUSES = ['pending', 'in_progress', 'done', 'cancelled'] as const;
const MAX_ITEMS = 50;

function coerceTodos(raw: unknown): TodoItem[] {
  if (!Array.isArray(raw)) throw new Error('参数 todos 必须为数组');
  if (raw.length > MAX_ITEMS) throw new Error(`todos 最多 ${MAX_ITEMS} 项`);
  if (raw.length === 0) throw new Error('todos 不能为空（清空请整体传入当前全量清单）');
  const seen = new Set<string>();
  return raw.map((item, i) => {
    const obj = item as Record<string, unknown>;
    const id = typeof obj['id'] === 'string' ? (obj['id'] as string).trim() : '';
    const content = typeof obj['content'] === 'string' ? (obj['content'] as string).trim() : '';
    const status = obj['status'];
    if (!id || id.length > 64) throw new Error(`todos[${i}].id 必须为 1-64 字符`);
    if (seen.has(id)) throw new Error(`todos[${i}].id 重复: ${id}`);
    seen.add(id);
    if (!content || content.length > 200) throw new Error(`todos[${i}].content 必须为 1-200 字符`);
    if (!STATUSES.includes(status as (typeof STATUSES)[number])) {
      throw new Error(`todos[${i}].status 必须为 ${STATUSES.join('/')}`);
    }
    return { id, content, status: status as TodoItem['status'] };
  });
}

export const TODO_TOOL: Tool = {
  name: 'todo_write',
  description:
    '维护当前会话的任务清单（Checklist）。处理多步骤任务（≥3 步）时先整体写入计划，随后每完成一项就更新状态；' +
    '入参为全量清单（整体覆盖）。status: pending=待办, in_progress=进行中（同时最多 1 项）, done=完成, cancelled=取消。',
  parameters: {
    type: 'object',
    properties: {
      todos: {
        type: 'array',
        items: {
          type: 'object',
          properties: {
            id: { type: 'string' },
            content: { type: 'string' },
            status: { type: 'string', enum: ['pending', 'in_progress', 'done', 'cancelled'] },
          },
          required: ['id', 'content', 'status'],
        },
      },
    },
    required: ['todos'],
  },
  risk: 'READ',
  async execute(ctx, input): Promise<ToolResult> {
    const todos = coerceTodos(input['todos']);
    const done = todos.filter((t) => t.status === 'done').length;
    ctx.onTodos?.(todos);
    return { text: `任务清单已更新：${todos.length} 项（完成 ${done}）` };
  },
};
