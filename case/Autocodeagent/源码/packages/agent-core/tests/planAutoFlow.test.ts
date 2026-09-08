/**
 * P3 集成测试（验收：Plan 只读拒绝回灌 / Auto 白名单自动执行）：
 * Plan：edit 被拒 → 模型收到「Plan 模式」拒绝说明并转纯分析，文件不动；
 * Auto：白名单命令（echo）自动执行无 permission_request；非白名单（npm install x）仍询问。
 */
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { ChatMessage, ModelConfig, NormalizedLLMResponse, StoredToolCall, StreamEvent } from '@agentbuddy/shared';
import { Checkpoint } from '../src/checkpoint';
import { compileWhitelist } from '../src/execWhitelist';
import type { LlmClient, LlmRequest } from '../src/llm/client';
import { runTurn, type TurnDeps } from '../src/orchestrator';
import { PermissionGate } from '../src/permission';
import { createBuiltinBus } from '../src/tools/bus';
import { ReadState } from '../src/tools/types';

const config: ModelConfig = {
  id: 'test', name: 'mock', provider: 'openai', baseUrl: 'http://mock', model: 'gpt-4o-mini',
  apiKey: 'k', encrypted: false, temperature: 0, maxTokens: 100, contextWindow: 128000,
};

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

function tc(id: string, name: string, args: Record<string, unknown>): StoredToolCall {
  return { id, name, arguments: JSON.stringify(args) };
}

let ws: string;
let dataDir: string;

beforeAll(async () => {
  ws = await mkdtemp(join(tmpdir(), 'p3-ws-'));
  dataDir = await mkdtemp(join(tmpdir(), 'p3-data-'));
  await mkdir(join(ws, 'src'), { recursive: true });
});

afterAll(async () => {
  await rm(ws, { recursive: true, force: true });
  await rm(dataDir, { recursive: true, force: true });
});

function deps(steps: Step[], gate: PermissionGate): {
  dep: TurnDeps; events: StreamEvent[]; persisted: ChatMessage[];
} {
  const events: StreamEvent[] = [];
  const persisted: ChatMessage[] = [];
  const dep: TurnDeps = {
    sessionId: 'p3-s1',
    messages: [{ id: 'u1', role: 'user', content: 'go', createdAt: Date.now() }],
    client: mockClient(steps),
    config,
    bus: createBuiltinBus(),
    gate,
    checkpoint: new Checkpoint(dataDir),
    readState: new ReadState(),
    workspace: ws,
    workspaceRoots: [ws],
    signal: new AbortController().signal,
    emit: (e) => events.push(e),
    persist: async (m) => { persisted.push(m); },
  };
  return { dep, events, persisted };
}

describe('P3 模式集成流', () => {
  it('Plan：edit 被拒 → 回灌「Plan 模式」说明，文件不动，模型转纯分析', async () => {
    await writeFile(join(ws, 'src', 'plan.txt'), 'v1\n');
    let asked = 0;
    const gate = new PermissionGate('Plan', async () => { asked++; return { allow: true, remember: false }; });
    const { dep, persisted } = deps([
      { toolCalls: [tc('e1', 'edit', { path: 'src/plan.txt', old_string: 'v1', new_string: 'v2' })] },
      { content: '好的，Plan 模式下我只做只读分析。' },
    ], gate);

    await runTurn(dep);

    expect(asked).toBe(0); // 模式拒绝不弹用户确认
    const toolMsg = persisted.find((m) => m.toolCallId === 'e1');
    expect(toolMsg?.content).toContain('Plan 模式');
    expect(await readFile(join(ws, 'src', 'plan.txt'), 'utf-8')).toBe('v1\n');
    // 模型收到拒绝后继续产出（转纯分析）
    expect(persisted.some((m) => m.role === 'assistant' && m.content.includes('只读分析'))).toBe(true);
  });

  it('Auto：白名单命令自动执行；非白名单仍询问（拒绝后不执行）', async () => {
    const askedTargets: string[] = [];
    const gate = new PermissionGate('Auto', async (q) => { askedTargets.push(q.target); return { allow: false, remember: false }; }, {
      execWhitelist: compileWhitelist(),
    });
    const { dep, events, persisted } = deps([
      { toolCalls: [tc('b1', 'bash', { command: 'echo hi' })] },
      { toolCalls: [tc('b2', 'bash', { command: 'npm install x' })] },
      { content: '完成' },
    ], gate);

    await runTurn(dep);

    // echo hi 命中白名单自动执行（不询问）；npm install x 未命中 → 询问一次
    // （permission_request 事件由 ChatService.askUser 挂起时发，测试注入 ask 直接断言询问目标）
    expect(askedTargets).toEqual(['npm install x']);
    const r1 = events.find((e) => e.type === 'tool_result' && e.callId === 'b1') as { ok: boolean } | undefined;
    expect(r1?.ok).toBe(true);
    // npm install x 被拒：tool 消息落盘失败态
    const denied = persisted.find((m) => m.toolCallId === 'b2');
    expect(denied?.toolOk).toBe(false);
  });
});
