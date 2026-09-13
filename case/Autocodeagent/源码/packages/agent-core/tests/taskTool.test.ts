/**
 * Subagent（task 工具）单测：
 * ① createTaskTool 外壳（派发免询问 / 结果回灌 / 参数校验 / expertId 可选 / signal 透传）
 * ② runPool 手写并发池（并发上限 / 全量执行 / tripped 汇聚 / 空数组安全）
 * ③ runTurn 集成：含 task 批次走 runPool 限流（峰值 ≤ PARALLEL_LIMIT）；纯 read 批次仍全并行
 */
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { ModelConfig, NormalizedLLMResponse, StoredToolCall, StreamEvent } from '@agentbuddy/shared';
import { Checkpoint } from '../src/checkpoint';
import { PARALLEL_LIMIT, runPool, runTurn, type TurnDeps } from '../src/orchestrator';
import { PermissionGate } from '../src/permission';
import { createBuiltinBus, ToolBus, type ToolBus as ToolBusType } from '../src/tools/bus';
import { createTaskTool, TASK_TOOL_NAME, type SpawnSubagent } from '../src/tools/taskTool';
import { ReadState, type Tool } from '../src/tools/types';
import type { LlmClient, LlmRequest } from '../src/llm/client';

const config: ModelConfig = {
  id: 'test', name: 'mock', provider: 'openai', baseUrl: 'http://mock', model: 'gpt-4o-mini',
  apiKey: 'k', encrypted: false, temperature: 0, maxTokens: 100, contextWindow: 128000,
};

function tctx(signal: AbortSignal = new AbortController().signal) {
  return { workspace: null, signal, readState: new ReadState(), snapshot: async () => null, resolvePath: async (p: string) => p };
}

// ---------- ① createTaskTool 外壳 ----------
describe('createTaskTool（子代理派发工具外壳）', () => {
  it('name=task、risk=READ（派发免询问，权限粒度下沉到子代理内部工具）', () => {
    const tool = createTaskTool(async () => 'ok');
    expect(tool.name).toBe(TASK_TOOL_NAME);
    expect(tool.risk).toBe('READ');
  });

  it('execute 调 spawn 并把结果文本回灌', async () => {
    const seen: Array<{ eid: string | undefined; prompt: string }> = [];
    const spawn: SpawnSubagent = async (eid, prompt) => { seen.push({ eid, prompt }); return `完成:${prompt}`; };
    const out = await createTaskTool(spawn).execute(tctx(), { prompt: '写手册1', expertId: 'e1' });
    expect(seen).toEqual([{ eid: 'e1', prompt: '写手册1' }]);
    expect(out.text).toBe('完成:写手册1');
  });

  it('expertId 可选：缺省 / 纯空白 → undefined（通用子代理）', async () => {
    let got: string | undefined = 'sentinel';
    const spawn: SpawnSubagent = async (eid) => { got = eid; return 'ok'; };
    await createTaskTool(spawn).execute(tctx(), { prompt: 'p' });
    expect(got).toBeUndefined();
    await createTaskTool(spawn).execute(tctx(), { prompt: 'p', expertId: '   ' });
    expect(got).toBeUndefined();
  });

  it('prompt 非法：缺失报错、纯空白报错', async () => {
    const tool = createTaskTool(async () => 'ok');
    await expect(tool.execute(tctx(), {})).rejects.toThrow('prompt');
    await expect(tool.execute(tctx(), { prompt: '   ' })).rejects.toThrow('不能为空');
  });

  it('spawn 返回空串 → 兜底提示（不回灌空结果）', async () => {
    const out = await createTaskTool(async () => '').execute(tctx(), { prompt: 'p' });
    expect(out.text).toContain('未返回');
  });

  it('ctx.signal 透传给 spawn（主停子停）', async () => {
    const ac = new AbortController();
    let gotSig: AbortSignal | undefined;
    await createTaskTool(async (_e, _p, sig) => { gotSig = sig; return 'ok'; }).execute(tctx(ac.signal), { prompt: 'p' });
    expect(gotSig).toBe(ac.signal);
  });
});

// ---------- ② runPool 并发池 ----------
describe('runPool（手写并发池，无新依赖）', () => {
  it('并发峰值不超过 limit，且确实并行', async () => {
    let active = 0, peak = 0;
    await runPool(Array.from({ length: 12 }, (_, i) => i), 3, async () => {
      active++; peak = Math.max(peak, active);
      await new Promise((r) => setTimeout(r, 5));
      active--; return false;
    });
    expect(peak).toBeLessThanOrEqual(3);
    expect(peak).toBeGreaterThan(1);
  });

  it('全部条目都被执行', async () => {
    let n = 0;
    await runPool(Array.from({ length: 9 }, (_, i) => i), 4, async () => { n++; return false; });
    expect(n).toBe(9);
  });

  it('任一 fn 返回 true → 整体 tripped=true；全 false → false；空数组安全', async () => {
    expect(await runPool([1, 2, 3], 2, async (x) => x === 2)).toBe(true);
    expect(await runPool([1, 2], 2, async () => false)).toBe(false);
    expect(await runPool([], 4, async () => true)).toBe(false);
  });

  it('PARALLEL_LIMIT 为约定的子代理并发上限', () => {
    expect(PARALLEL_LIMIT).toBe(4);
  });
});

// ---------- ③ runTurn 集成：task 限流 / 纯 read 全并行 ----------
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

let dataDir: string;
beforeAll(async () => { dataDir = await mkdtemp(join(tmpdir(), 'task-orch-')); });
afterAll(async () => { await rm(dataDir, { recursive: true, force: true }); });

function depWith(steps: Step[], bus: ToolBusType): { dep: TurnDeps; events: StreamEvent[] } {
  const events: StreamEvent[] = [];
  const dep: TurnDeps = {
    sessionId: 's-task',
    messages: [{ id: 'u1', role: 'user', content: 'go', createdAt: Date.now() }],
    client: mockClient(steps),
    config,
    bus,
    gate: new PermissionGate('Auto', async () => ({ allow: true, remember: false })),
    checkpoint: new Checkpoint(dataDir),
    readState: new ReadState(),
    workspace: null,
    workspaceRoots: [],
    signal: new AbortController().signal,
    emit: (e) => events.push(e),
    persist: async () => undefined,
  };
  return { dep, events };
}

/** 记录并发峰值的假工具（risk=READ，Auto 模式免询问） */
function peakTool(name: string, hold: () => void, release: () => void): Tool {
  return {
    name, description: '', parameters: { type: 'object', properties: {} }, risk: 'READ',
    async execute() {
      hold();
      await new Promise((r) => setTimeout(r, 20));
      release();
      return { text: 'ok' };
    },
  };
}

describe('runTurn 集成：task 批次限流并行', () => {
  it('一轮 8 个 task → 并发峰值 ≤ PARALLEL_LIMIT（走 runPool 限流）且任务全部完成', async () => {
    let active = 0, peak = 0;
    const bus = createBuiltinBus();
    bus.register(peakTool(TASK_TOOL_NAME, () => { active++; peak = Math.max(peak, active); }, () => { active--; }));
    const calls = Array.from({ length: 8 }, (_, i) => tc(`t${i}`, TASK_TOOL_NAME, { prompt: `p${i}` }));
    const { dep } = depWith([{ toolCalls: calls }, { content: '汇总完成' }], bus);
    await runTurn(dep);
    expect(peak).toBeLessThanOrEqual(PARALLEL_LIMIT);
    expect(peak).toBeGreaterThan(1); // 确有限流内的并行
    expect(dep.messages.filter((m) => m.role === 'tool')).toHaveLength(8); // 8 个子任务都执行
    expect(dep.messages.at(-1)?.content).toBe('汇总完成');
  });

  it('纯 read 批次不受 task 限流（Promise.all 全并行，峰值可超 PARALLEL_LIMIT）', async () => {
    let active = 0, peak = 0;
    const bus = new ToolBus();
    bus.register(peakTool('read', () => { active++; peak = Math.max(peak, active); }, () => { active--; }));
    const calls = Array.from({ length: 8 }, (_, i) => tc(`r${i}`, 'read', { path: `f${i}` }));
    const { dep } = depWith([{ toolCalls: calls }, { content: '读完' }], bus);
    await runTurn(dep);
    expect(peak).toBeGreaterThan(PARALLEL_LIMIT); // 全并行，不被限到 4
    expect(dep.messages.filter((m) => m.role === 'tool')).toHaveLength(8);
  });
});
