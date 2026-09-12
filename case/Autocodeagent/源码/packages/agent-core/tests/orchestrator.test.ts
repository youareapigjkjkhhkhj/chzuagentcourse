/** Orchestrator mock-LLM 集成测试（P1 验收：read → edit → bash 一轮 + 拒绝/熔断/并发） */
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { ChatMessage, ModelConfig, NormalizedLLMResponse, Risk, StoredToolCall, StreamEvent } from '@agentbuddy/shared';
import { Checkpoint } from '../src/checkpoint';
import { assembleContext } from '../src/context';
import type { LlmClient, LlmRequest } from '../src/llm/client';
import { MAX_TURNS, runTurn, type TurnDeps } from '../src/orchestrator';
import { PermissionGate, type PermissionAnswer } from '../src/permission';
import { buildSessionBus, createBuiltinBus, type ToolBus } from '../src/tools/bus';
import { ReadState, type Tool } from '../src/tools/types';

const config: ModelConfig = {
  id: 'test', name: 'mock', provider: 'openai', baseUrl: 'http://mock', model: 'gpt-4o-mini',
  apiKey: 'k', encrypted: false, temperature: 0, maxTokens: 100, contextWindow: 128000,
};

interface Step { content?: string; toolCalls?: StoredToolCall[]; finish?: 'stop' | 'length' }

function mockClient(steps: Step[]): { client: LlmClient; calls: () => number } {
  let i = 0;
  const client = {
    async chat(req: LlmRequest): Promise<NormalizedLLMResponse> {
      if (req.signal.aborted) { const e = new Error('已取消'); e.name = 'AbortError'; throw e; }
      const step = steps[Math.min(i++, steps.length - 1)]!;
      req.onDelta(step.content ?? '');
      return {
        message: { id: '', role: 'assistant', content: step.content ?? '', createdAt: Date.now() },
        toolCalls: step.toolCalls,
        usage: { promptTokens: 1, completionTokens: 1, totalTokens: 2, cacheReadTokens: 0 },
        finishReason: step.finish ?? (step.toolCalls ? 'tool_calls' : 'stop'),
      };
    },
  } as unknown as LlmClient;
  return { client, calls: () => i };
}

function tc(id: string, name: string, args: Record<string, unknown>): StoredToolCall {
  return { id, name, arguments: JSON.stringify(args) };
}

let ws: string;
let dataDir: string;

beforeAll(async () => {
  ws = await mkdtemp(join(tmpdir(), 'orch-ws-'));
  dataDir = await mkdtemp(join(tmpdir(), 'orch-data-'));
  await mkdir(join(ws, 'src'), { recursive: true });
});

afterAll(async () => {
  await rm(ws, { recursive: true, force: true });
  await rm(dataDir, { recursive: true, force: true });
});

function deps(steps: Step[], answer: PermissionAnswer, workspace: string | null = ws, onRecord?: TurnDeps['onRecord']): {
  dep: TurnDeps; events: StreamEvent[]; persisted: ChatMessage[];
} {
  const { client, calls } = mockClient(steps);
  const events: StreamEvent[] = [];
  const persisted: ChatMessage[] = [];
  const dep: TurnDeps = {
    sessionId: 's1',
    messages: [{ id: 'u1', role: 'user', content: 'go', createdAt: Date.now() }],
    client,
    config,
    bus: createBuiltinBus(),
    gate: new PermissionGate('Ask', async () => answer),
    checkpoint: new Checkpoint(dataDir),
    readState: new ReadState(),
    workspace,
    workspaceRoots: workspace ? [workspace] : [],
    signal: new AbortController().signal,
    emit: (e) => events.push(e),
    persist: async (m) => { persisted.push(m); },
    onRecord,
  };
  void calls;
  return { dep, events, persisted };
}

describe('runTurn 集成（mock LLM）', () => {
  it('read → edit → bash 一轮完整流程', async () => {
    await writeFile(join(ws, 'src', 'fix.txt'), 'const v = 1;\n');
    const { dep, events, persisted } = deps([
      { toolCalls: [tc('c1', 'read', { path: 'src/fix.txt' })] },
      { toolCalls: [tc('c2', 'edit', { path: 'src/fix.txt', old_string: 'const v = 1;', new_string: 'const v = 2;' })] },
      { toolCalls: [tc('c3', 'bash', { command: 'echo smoke-ok' })] },
      { content: '修复完成' },
    ], { allow: true, remember: false });

    await runTurn(dep);

    expect(readFileSync(join(ws, 'src', 'fix.txt'), 'utf-8')).toBe('const v = 2;\n');
    const toolMsgs = persisted.filter((m) => m.role === 'tool');
    expect(toolMsgs.map((m) => m.toolOk)).toEqual([true, true, true]);
    expect(toolMsgs[2]?.content).toContain('smoke-ok');
    const names = events.filter((e) => e.type === 'tool_start').map((e) => (e as { name: string }).name);
    expect(names).toEqual(['read', 'edit', 'bash']);
    expect(dep.messages.at(-1)?.content).toBe('修复完成');
  });

  it('权限拒绝 → 结构化回灌，模型收到拒绝说明并收尾', async () => {
    await writeFile(join(ws, 'src', 'deny.txt'), 'keep\n');
    const { dep, persisted } = deps([
      { toolCalls: [tc('c1', 'bash', { command: 'echo x' })] },
      { content: '已取消执行' },
    ], { allow: false, remember: false });

    await runTurn(dep);

    const denied = persisted.find((m) => m.toolCallId === 'c1');
    expect(denied?.toolOk).toBe(false);
    expect(denied?.content).toContain('用户拒绝');
    // 拒绝回灌进下一轮上下文
    const wire = await assembleContext({ workspace: ws, config, history: dep.messages });
    expect(wire.some((m) => (m.content ?? '').includes('用户拒绝'))).toBe(true);
  });

  it('同工具同入参连败 2 次熔断', async () => {
    const { dep, events } = deps([
      { toolCalls: [tc('c1', 'edit', { path: 'src/none.txt', old_string: 'a', new_string: 'b' })] },
      { toolCalls: [tc('c2', 'edit', { path: 'src/none.txt', old_string: 'a', new_string: 'b' })] },
      { content: '不应到达' },
    ], { allow: true, remember: false });

    await runTurn(dep);

    const err = events.find((e) => e.type === 'error');
    expect(err && (err as { message: string }).message).toContain('连续失败');
  });

  it('同消息内多个 READ 并发执行（各自落盘）', async () => {
    await writeFile(join(ws, 'src', 'p1.txt'), 'one\n');
    await writeFile(join(ws, 'src', 'p2.txt'), 'two\n');
    const { dep, persisted } = deps([
      { toolCalls: [tc('c1', 'read', { path: 'src/p1.txt' }), tc('c2', 'read', { path: 'src/p2.txt' })] },
      { content: 'ok' },
    ], { allow: true, remember: false });

    await runTurn(dep);
    const toolMsgs = persisted.filter((m) => m.role === 'tool');
    expect(toolMsgs.length).toBe(2);
    expect(toolMsgs.every((m) => m.toolOk)).toBe(true);
  });

  it('未知工具与非法入参回灌错误，两次后熔断', async () => {
    const { dep, events } = deps([
      { toolCalls: [tc('c1', 'nope', { x: 1 })] },
      { toolCalls: [tc('c2', 'nope', { x: 1 })] },
    ], { allow: true, remember: false });

    await runTurn(dep);
    expect(events.some((e) => e.type === 'error')).toBe(true);
    expect(dep.messages.filter((m) => m.role === 'tool').length).toBe(2);
  });

  it('maxTurns 兜底：模型无限调用时终止并报错', async () => {
    const { dep, events } = deps([
      { toolCalls: [tc('cx', 'read', { path: 'src/p1.txt' })] }, // 最后一步无限重复
    ], { allow: true, remember: true });

    await runTurn(dep);
    const err = events.find((e) => e.type === 'error');
    expect(err && (err as { message: string }).message).toContain('maxTurns');
    expect(dep.messages.filter((m) => m.role === 'assistant').length).toBe(MAX_TURNS);
  }, 30_000);

  it('P6 onRecord 钩子：成功 / 未知工具 / 权限拒绝各终态均落一条', async () => {
    await writeFile(join(ws, 'src', 'rec.txt'), 'hi\n');
    const recs: Array<{ tool: string; ok: boolean; risk: string; target: string }> = [];
    const push = (r: { tool: string; target: string; risk: Risk; ok: boolean; ms: number }) => recs.push(r);

    // 成功 + 未知工具（两次熔断）
    const a = deps([
      { toolCalls: [tc('r1', 'read', { path: 'src/rec.txt' })] },
      { toolCalls: [tc('r2', 'ghost', { x: 1 })] },
      { toolCalls: [tc('r3', 'ghost', { x: 1 })] },
    ], { allow: true, remember: false }, ws, push);
    await runTurn(a.dep);

    // 权限拒绝
    const b = deps([
      { toolCalls: [tc('d1', 'bash', { command: 'echo no' })] },
      { content: 'ok' },
    ], { allow: false, remember: false }, ws, push);
    await runTurn(b.dep);

    expect(recs.map((r) => [r.tool, r.ok])).toEqual([
      ['read', true],
      ['ghost', false],
      ['ghost', false],
      ['bash', false],
    ]);
    expect(recs[0]?.risk).toBe('READ');
    expect(recs[0]?.target).toContain('rec.txt');
    expect(recs[3]?.risk).toBe('EXEC');
  });
});

describe('length 截断续写', () => {
  it('finish=length 无工具调用 → 自动续写一轮；续写指令仅 live 不落盘', async () => {
    const { dep, persisted } = deps([
      { content: '前半段', finish: 'length' },
      { content: '后半段' },
    ], { allow: true, remember: false });

    await runTurn(dep);

    // live：u1 + assistant(前半) + user(续写指令) + assistant(后半)
    expect(dep.messages).toHaveLength(4);
    expect(dep.messages[2]?.role).toBe('user');
    expect(dep.messages[2]?.content).toContain('截断');
    // 落盘仅两条 assistant（续写指令不污染回放与 UI）
    expect(persisted.map((m) => m.role)).toEqual(['assistant', 'assistant']);
    expect(persisted.map((m) => m.content)).toEqual(['前半段', '后半段']);
  });

  it('续写上限 3 次：连续 length 第 4 轮正常收尾', async () => {
    const len = { content: 'x', finish: 'length' as const };
    const { dep, persisted } = deps([len, len, len, len, len], { allow: true, remember: false });

    await runTurn(dep);

    // u1 + 3×(assistant + 续写指令) + 第 4 条 assistant = 8
    expect(dep.messages).toHaveLength(8);
    expect(persisted).toHaveLength(4);
  });

  it('finish=length 但带工具调用 → 不续写（截断的是工具参数，走 parse 失败回灌）', async () => {
    const { dep, persisted } = deps([
      { content: '半截', finish: 'length', toolCalls: [tc('c1', 'read', { path: 'src/fix.txt' })] },
      { content: '收尾' },
    ], { allow: true, remember: false });

    await runTurn(dep);

    // 无续写指令插入：u1 + assistant + tool + assistant
    expect(dep.messages.filter((m) => m.role === 'user')).toHaveLength(1);
    expect(persisted.some((m) => m.role === 'tool')).toBe(true);
  });
});

describe('runTurn 上下文窗口自愈（400 探测真实窗口 + schema 物理裁剪）', () => {
  function bigMcpTool(i: number): Tool {
    return {
      name: `mcp__big__tool_${i}`,
      description: `假工具 ${i} ${'x'.repeat(1500)}`,
      parameters: { type: 'object', properties: {} },
      risk: 'READ',
      execute: async () => ({ text: '' }),
    };
  }

  function bigBus(): ToolBus {
    const bus = createBuiltinBus();
    for (let i = 0; i < 60; i++) bus.register(bigMcpTool(i));
    return bus;
  }

  function probeClient(requests: LlmRequest[], failFirstWith: string | null): LlmClient {
    let n = 0;
    return {
      async chat(req: LlmRequest): Promise<NormalizedLLMResponse> {
        requests.push(req);
        if (failFirstWith !== null && n++ === 0) throw new Error(failFirstWith);
        req.onDelta('ok');
        return {
          message: { id: '', role: 'assistant', content: 'ok', createdAt: Date.now() },
          toolCalls: undefined,
          usage: { promptTokens: 1, completionTokens: 1, totalTokens: 2, cacheReadTokens: 0 },
          finishReason: 'stop',
        };
      },
    } as unknown as LlmClient;
  }

  function ctxDep(client: LlmClient, events: StreamEvent[]): TurnDeps {
    return {
      sessionId: 's-ctx',
      messages: [{ id: 'u1', role: 'user', content: 'go', createdAt: Date.now() }],
      client,
      config: { ...config, baseUrl: 'http://probe', model: 'ctx-probe' },
      bus: bigBus(),
      gate: new PermissionGate('Ask', async () => ({ allow: false, remember: false })),
      checkpoint: new Checkpoint(dataDir),
      readState: new ReadState(),
      workspace: null,
      workspaceRoots: [],
      signal: new AbortController().signal,
      emit: (e) => events.push(e),
      persist: async () => {},
    };
  }

  it('配置窗口偏大 → 400 探测真实窗口，裁剪 schema 后本轮重试成功', async () => {
    const requests: LlmRequest[] = [];
    const events: StreamEvent[] = [];
    const dep = ctxDep(probeClient(requests, "400: This model's maximum context length is 32768 tokens. However, you requested 100 output tokens and your prompt contains at least 40000 input tokens."), events);

    await runTurn(dep);

    expect(requests).toHaveLength(2); // 首次 400 → 探测后重试
    expect(requests[0]!.tools).toHaveLength(68); // 配置 128k：全量下发
    const second = requests[1]!.tools!;
    expect(second).toHaveLength(35); // 32768 物理容量：内置 8 + MCP 27
    expect(events.some((e) => e.type === 'notice')).toBe(true); // 少挂载需用户可见
  });

  it('已探测过的模型：首轮即裁剪，不再触发 400', async () => {
    const requests: LlmRequest[] = [];
    const dep = ctxDep(probeClient(requests, null), []);

    await runTurn(dep);

    expect(requests).toHaveLength(1);
    expect(requests[0]!.tools!.length).toBeLessThan(68);
  });

  it('输出上限超窗（max_tokens>max_model_len）→ 探测窗口 4096，收敛输出上限后重试 + 小窗口提示', async () => {
    const requests: LlmRequest[] = [];
    const events: StreamEvent[] = [];
    const base = ctxDep(
      probeClient(requests, '400: Bad Request - max_tokens=8192 cannot be greater than max_model_len=max_total_tokens=4096. Please request fewer output tokens.'),
      events,
    );
    // 独立 windowKey（不复用前面用例学到的 32768）+ 大 maxTokens，验证输出上限被真实窗口收敛
    const dep: TurnDeps = { ...base, config: { ...base.config, model: 'ctx-probe-tiny', maxTokens: 8192 } };

    await runTurn(dep);

    expect(requests).toHaveLength(2); // 首次 400 → 探测后重试
    expect(requests[0]!.maxTokens).toBe(8192); // 首轮窗口未知（配置 128k）：按配置下发
    expect(requests[1]!.maxTokens).toBe(2048); // 学到 4096：max_tokens 收敛到窗口一半，消除该 400
    expect(events.some((e) => e.type === 'notice')).toBe(true); // 窗口 < 8192：明确提示换模型 / 调大 --max-model-len
  });
});

describe('runTurn 按需加载（search_tools 发现 → 下一轮注入 schema → 调用）', () => {
  // 大 schema MCP 工具：合计越过阈值 → buildSessionBus 走 deferred + search_tools
  function gfxTool(i: number): Tool {
    return {
      name: `mcp__gfx__render_${i}`,
      description: `render scene variant ${i} ${'x'.repeat(1800)}`,
      parameters: { type: 'object', properties: {} },
      risk: 'NETWORK',
      execute: async () => ({ text: `rendered ${i}` }),
    };
  }

  function recordingClient(steps: Step[], requests: LlmRequest[]): LlmClient {
    let i = 0;
    return {
      async chat(req: LlmRequest): Promise<NormalizedLLMResponse> {
        requests.push(req);
        const step = steps[Math.min(i++, steps.length - 1)]!;
        req.onDelta(step.content ?? '');
        return {
          message: { id: '', role: 'assistant', content: step.content ?? '', createdAt: Date.now() },
          toolCalls: step.toolCalls,
          usage: { promptTokens: 1, completionTokens: 1, totalTokens: 2, cacheReadTokens: 0 },
          finishReason: step.finish ?? (step.toolCalls ? 'tool_calls' : 'stop'),
        };
      },
    } as unknown as LlmClient;
  }

  it('轮1 只发常驻（含 search_tools，无 MCP）；命中后轮2 注入发现的 MCP schema 并可真正调用', async () => {
    const bus = buildSessionBus(Array.from({ length: 10 }, (_, i) => gfxTool(i)));
    expect(bus.hasDeferred()).toBe(true);

    const requests: LlmRequest[] = [];
    const persisted: ChatMessage[] = [];
    const dep: TurnDeps = {
      sessionId: 's-ondemand',
      messages: [{ id: 'u1', role: 'user', content: 'render it', createdAt: Date.now() }],
      client: recordingClient([
        { toolCalls: [tc('s1', 'search_tools', { query: 'render' })] }, // 轮1：检索
        { toolCalls: [tc('s2', 'mcp__gfx__render_0', {})] }, // 轮2：调用发现的工具
        { content: 'done' },
      ], requests),
      config: { ...config, baseUrl: 'http://ondemand', model: 'gfx' },
      bus,
      gate: new PermissionGate('Ask', async () => ({ allow: true, remember: false })),
      checkpoint: new Checkpoint(dataDir),
      readState: new ReadState(),
      workspace: null,
      workspaceRoots: [],
      signal: new AbortController().signal,
      emit: () => {},
      persist: async (m) => { persisted.push(m); },
    };

    await runTurn(dep);

    // 轮1：search_tools 常驻，MCP 未注入 schema
    const t0 = requests[0]!.tools!.map((t) => t.function.name);
    expect(t0).toContain('search_tools');
    expect(t0.some((n) => n.startsWith('mcp__'))).toBe(false);
    // 轮2：命中工具（默认 top-k=5）已注入，可被模型调用
    const t1 = requests[1]!.tools!.map((t) => t.function.name);
    expect(t1).toContain('mcp__gfx__render_0');
    expect(t1.filter((n) => n.startsWith('mcp__gfx__'))).toHaveLength(5);
    // 发现的工具真正执行成功（结果落盘）
    const renderMsg = persisted.find((m) => m.toolName === 'mcp__gfx__render_0');
    expect(renderMsg?.toolOk).toBe(true);
    expect(renderMsg?.content).toContain('rendered 0');
    // 发现集跨轮累积保留：轮3 仍含 render_0
    expect(requests[2]!.tools!.map((t) => t.function.name)).toContain('mcp__gfx__render_0');
  });

  it('per-session 发现集：跨多次 runTurn 复用同一 Set → 第二次提问无需重复 search_tools', async () => {
    const bus = buildSessionBus(Array.from({ length: 10 }, (_, i) => gfxTool(i)));
    const discovered = new Set<string>(); // 模拟 chatService 按 sessionId 持有、跨 ask 复用的发现集
    const makeDep = (client: LlmClient): TurnDeps => ({
      sessionId: 's-session',
      messages: [{ id: 'u', role: 'user', content: 'render', createdAt: Date.now() }],
      client,
      config: { ...config, baseUrl: 'http://ondemand-session', model: 'gfx' },
      bus,
      gate: new PermissionGate('Ask', async () => ({ allow: true, remember: false })),
      checkpoint: new Checkpoint(dataDir),
      readState: new ReadState(),
      workspace: null,
      workspaceRoots: [],
      signal: new AbortController().signal,
      emit: () => {},
      persist: async () => {},
      discovered,
    });

    // 第一次提问：search_tools 命中 → 命中工具名写入会话级 discovered
    const req1: LlmRequest[] = [];
    await runTurn(makeDep(recordingClient([{ toolCalls: [tc('s1', 'search_tools', { query: 'render' })] }, { content: 'ok' }], req1)));
    expect(discovered.size).toBeGreaterThan(0);

    // 第二次提问：同一 bus + 同一 discovered，模型不再 search_tools，首轮即注入已发现工具
    const req2: LlmRequest[] = [];
    await runTurn(makeDep(recordingClient([{ content: 'done' }], req2)));
    expect(req2).toHaveLength(1); // 单轮结束，无检索往返
    expect(req2[0]!.tools!.map((t) => t.function.name).some((n) => n.startsWith('mcp__gfx__'))).toBe(true);
  });
});
