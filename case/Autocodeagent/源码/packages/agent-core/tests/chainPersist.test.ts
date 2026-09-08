/** 端到端复现：会话持久化全链路（真实 SessionStore + runTurn），模拟重启后读盘校验 */
import { mkdtemp, rm } from 'node:fs/promises';
import { readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { ChatMessage, ModelConfig, NormalizedLLMResponse, SessionData } from '@agentbuddy/shared';
import { Checkpoint } from '../src/checkpoint';
import type { LlmClient, LlmRequest } from '../src/llm/client';
import { runTurn } from '../src/orchestrator';
import { PermissionGate } from '../src/permission';
import { SessionStore } from '../src/store/sessionStore';
import { createBuiltinBus } from '../src/tools/bus';
import { ReadState } from '../src/tools/types';

const config: ModelConfig = {
  id: 'test', name: 'mock', provider: 'openai', baseUrl: 'http://mock', model: 'gpt-4o-mini',
  apiKey: 'k', encrypted: false, temperature: 0, maxTokens: 100, contextWindow: 128000,
};

function mockClient(steps: Array<{ content?: string }>): LlmClient {
  let i = 0;
  return {
    async chat(req: LlmRequest): Promise<NormalizedLLMResponse> {
      const step = steps[Math.min(i++, steps.length - 1)]!;
      req.onDelta(step.content ?? '');
      return {
        message: { id: '', role: 'assistant', content: step.content ?? '', createdAt: Date.now() },
        toolCalls: undefined,
        usage: { promptTokens: 1, completionTokens: 1, totalTokens: 2, cacheReadTokens: 0 },
        finishReason: 'stop',
      };
    },
  } as unknown as LlmClient;
}

let dataDir: string;

beforeAll(async () => {
  dataDir = await mkdtemp(join(tmpdir(), 'chain-persist-'));
});

afterAll(async () => {
  await rm(dataDir, { recursive: true, force: true });
});

describe('会话持久化全链路', () => {
  it('chatService 同款流程：user + assistant 都落盘，重启后读盘可见', async () => {
    const store = new SessionStore(join(dataDir, 'sessions'), 50);
    await store.init();
    const session = await store.create('复现');

    // ── 模拟 chatService.ask ──
    const userMessage: ChatMessage = { id: 'u1', role: 'user', content: '你好', createdAt: Date.now() };
    await store.appendMessage(session.id, userMessage);

    // append 后再读：与 chatService.ask 同款（缓存同一对象引用，已含 userMessage，不可再拼一次）
    const latest = await store.get(session.id);
    const messages = [...(latest?.messages ?? [])];
    await runTurn({
      sessionId: session.id,
      messages,
      client: mockClient([{ content: '你好，我在' }]),
      config,
      bus: createBuiltinBus(),
      gate: new PermissionGate('Ask', async () => ({ allow: true, remember: false })),
      checkpoint: new Checkpoint(dataDir),
      readState: new ReadState(),
      workspace: dataDir,
      workspaceRoots: [dataDir],
      signal: new AbortController().signal,
      emit: () => undefined,
      persist: (msg) => store.appendMessage(session.id, msg).then(() => undefined),
    });
    await store.flush(session.id);

    // ── 模拟下次启动：绕过进程内缓存，直接读盘 ──
    const reloaded = JSON.parse(readFileSync(join(dataDir, 'sessions', `${session.id}.json`), 'utf-8')) as SessionData;
    const roles = reloaded.messages.map((m) => m.role);
    expect(roles).toContain('user');
    expect(roles).toContain('assistant');
    // user 消息不重复（组装顺序回归）
    expect(roles.filter((r) => r === 'user')).toHaveLength(1);
    expect(reloaded.messages.find((m) => m.role === 'assistant')?.content).toBe('你好，我在');
  });
});
