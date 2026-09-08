/**
 * P4 单测：todo_write 工具 + runTurn 集成（plan 事件 / 落盘回调）+ SessionStore 清单持久化。
 */
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { ChatMessage, ModelConfig, NormalizedLLMResponse, StoredToolCall, StreamEvent, TodoItem } from '@agentbuddy/shared';
import { Checkpoint } from '../src/checkpoint';
import { runTurn, type TurnDeps } from '../src/orchestrator';
import { PermissionGate } from '../src/permission';
import { SessionStore } from '../src/store/sessionStore';
import { createBuiltinBus } from '../src/tools/bus';
import { TODO_TOOL } from '../src/tools/todoTool';
import { ReadState } from '../src/tools/types';
import type { LlmClient, LlmRequest } from '../src/llm/client';

const config: ModelConfig = {
  id: 'test', name: 'mock', provider: 'openai', baseUrl: 'http://mock', model: 'gpt-4o-mini',
  apiKey: 'k', encrypted: false, temperature: 0, maxTokens: 100, contextWindow: 128000,
};

function tc(id: string, name: string, args: Record<string, unknown>): StoredToolCall {
  return { id, name, arguments: JSON.stringify(args) };
}

const TODOS: TodoItem[] = [
  { id: '1', content: '读代码', status: 'in_progress' },
  { id: '2', content: '写计划', status: 'pending' },
];

describe('todo_write 工具', () => {
  it('合法清单：回调上抛 + 汇总文案', async () => {
    let got: TodoItem[] = [];
    const out = await TODO_TOOL.execute(
      { workspace: null, signal: new AbortController().signal, readState: new ReadState(), snapshot: async () => null, resolvePath: async (p) => p, onTodos: (t) => { got = t; } },
      { todos: TODOS },
    );
    expect(got).toEqual(TODOS);
    expect(out.text).toContain('2 项');
  });

  it('非法入参：空数组 / 重复 id / 非法 status 均报错', async () => {
    const ctx = { workspace: null, signal: new AbortController().signal, readState: new ReadState(), snapshot: async () => null, resolvePath: async (p: string) => p };
    await expect(TODO_TOOL.execute(ctx, { todos: [] })).rejects.toThrow('不能为空');
    await expect(TODO_TOOL.execute(ctx, { todos: [{ id: 'a', content: 'x', status: 'pending' }, { id: 'a', content: 'y', status: 'pending' }] })).rejects.toThrow('重复');
    await expect(TODO_TOOL.execute(ctx, { todos: [{ id: 'a', content: 'x', status: 'wip' }] })).rejects.toThrow('status');
    await expect(TODO_TOOL.execute(ctx, {})).rejects.toThrow('必须为数组');
  });

  it('注册进内置 bus，风险为 READ（各模式免询问）', () => {
    expect(createBuiltinBus().get('todo_write')).toBeTruthy();
    expect(TODO_TOOL.risk).toBe('READ');
  });
});

interface Step { content?: string; toolCalls?: StoredToolCall[] }

function mockClient(steps: Step[]): LlmClient {
  let i = 0;
  return {
    async chat(req: LlmRequest): Promise<NormalizedLLMResponse> {
      const step = steps[Math.min(i++, steps.length - 1)]!;
      req.onDelta(step.content ?? '');
      return {
        message: { id: '', role: 'assistant', content: step.content ?? '', createdAt: Date.now() },
        toolCalls: step.toolCalls,
        usage: { promptTokens: 1, completionTokens: 1, totalTokens: 2, cacheReadTokens: 0 },
        finishReason: step.toolCalls ? 'tool_calls' : 'stop',
      };
    },
  } as unknown as LlmClient;
}

describe('runTurn 集成：todo_write → plan 事件 + onTodos 落盘回调', () => {
  let dataDir: string;

  beforeAll(async () => {
    dataDir = await mkdtemp(join(tmpdir(), 'p4-todo-'));
  });
  afterAll(async () => {
    await rm(dataDir, { recursive: true, force: true });
  });

  it('模型调 todo_write：发 plan 事件且清单经 onTodos 上抛（Plan 模式也免询问）', async () => {
    const events: StreamEvent[] = [];
    const persisted: ChatMessage[] = [];
    const captured: TodoItem[][] = [];
    const dep: TurnDeps = {
      sessionId: 'p4-s1',
      messages: [{ id: 'u1', role: 'user', content: '做个计划', createdAt: Date.now() }],
      client: mockClient([
        { toolCalls: [tc('t1', 'todo_write', { todos: TODOS })] },
        { toolCalls: [tc('t2', 'todo_write', { todos: [{ id: '1', content: '读代码', status: 'done' }, { id: '2', content: '写计划', status: 'in_progress' }] })] },
        { content: '计划已建好。' },
      ]),
      config,
      bus: createBuiltinBus(),
      gate: new PermissionGate('Plan', async () => ({ allow: true, remember: false })),
      checkpoint: new Checkpoint(dataDir),
      readState: new ReadState(),
      workspace: null,
      workspaceRoots: [],
      signal: new AbortController().signal,
      emit: (e) => events.push(e),
      persist: async (m) => { persisted.push(m); },
      onTodos: (todos) => captured.push(todos),
    };

    await runTurn(dep);

    expect(captured).toHaveLength(2);
    expect(captured[1]?.find((t) => t.id === '1')?.status).toBe('done');
    const plans = events.filter((e) => e.type === 'plan');
    expect(plans).toHaveLength(2);
    const last = plans.at(-1);
    if (last?.type === 'plan') expect(last.todos.find((t) => t.id === '2')?.status).toBe('in_progress');
    // 工具结果落盘成功
    expect(persisted.find((m) => m.toolCallId === 't2')?.toolOk).toBe(true);
  });
});

describe('SessionStore：todos 随会话落盘', () => {
  it('updateTodos 后重新读取可见（回放恢复 Checklist）', async () => {
    const dir = await mkdtemp(join(tmpdir(), 'p4-sess-'));
    const store = new SessionStore(dir, 0);
    await store.init();
    const session = await store.create('t');
    await store.updateTodos(session.id, TODOS);
    await store.flush(session.id);
    // 新实例读取磁盘（排除内存缓存）
    const fresh = new SessionStore(dir, 0);
    const data = await fresh.get(session.id);
    expect(data?.todos).toEqual(TODOS);
    await rm(dir, { recursive: true, force: true });
  });
});
