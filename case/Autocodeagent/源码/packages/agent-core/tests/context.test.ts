/** 上下文组装与截断单测（P1 验收：旧工具结果占位摘要，技术方案 §4.3） */
import { describe, expect, it } from 'vitest';
import type { ChatMessage, LlmToolSchema, LlmWireMessage, ModelConfig } from '@agentbuddy/shared';
import { assembleContext, compactPlaceholder, computePromptBudget, dropOldMessages, estimateTokens, pruneToolsToWindow, toWire, trimToBudget } from '../src/context';

const config: ModelConfig = {
  id: 'test', name: 't', provider: 'openai', baseUrl: 'http://x', model: 'gpt-4o-mini',
  apiKey: 'k', encrypted: false, temperature: 0.2, maxTokens: 100, contextWindow: 128000,
};

function msg(over: Partial<ChatMessage>): ChatMessage {
  return { id: over.id ?? 'm1', role: 'user', content: 'hi', createdAt: 0, ...over };
}

describe('estimateTokens（P0：CJK 加权，中文不再被 length/4 低估）', () => {
  it('ASCII 保持 0.25 token/字符基线（与原 length/4 一致）', () => {
    expect(estimateTokens('a'.repeat(100))).toBe(25);
  });

  it('中文按 0.7 token/字', () => {
    expect(estimateTokens('中'.repeat(100))).toBe(70);
  });

  it('中英混排加权求和', () => {
    expect(estimateTokens('中'.repeat(10) + 'a'.repeat(40))).toBe(17);
  });
});

describe('toWire', () => {
  it('assistant 带 tool_calls；tool 带 tool_call_id', () => {
    const a = toWire(msg({ role: 'assistant', content: '', toolCalls: [{ id: 'c1', name: 'read', arguments: '{"path":"a"}' }] }));
    expect(a.role).toBe('assistant');
    expect(a.content).toBeNull();
    expect(a.tool_calls?.[0]?.function.name).toBe('read');

    const t = toWire(msg({ role: 'tool', toolCallId: 'c1', toolName: 'read', content: 'out' }));
    expect(t.role).toBe('tool');
    expect(t.tool_call_id).toBe('c1');
  });
});

describe('trimToBudget', () => {
  it('不超限不压缩', () => {
    const wire: LlmWireMessage[] = [{ role: 'system', content: 's' }, { role: 'tool', content: 'short', tool_call_id: 'c1' }];
    trimToBudget(wire, 100000);
    expect(wire[1]?.content).toBe('short');
  });

  it('超限时旧工具结果替换为占位摘要（保留首 10 行）', () => {
    const big = Array.from({ length: 50 }, (_, i) => `line-${i}`).join('\n');
    const wire: LlmWireMessage[] = [
      { role: 'system', content: 's' },
      { role: 'tool', content: big, tool_call_id: 'c1' },
      { role: 'tool', content: 'r2', tool_call_id: 'c2' },
      { role: 'tool', content: 'r3', tool_call_id: 'c3' },
      { role: 'tool', content: 'r4', tool_call_id: 'c4' },
    ];
    trimToBudget(wire, 20);
    const c = wire[1]?.content ?? '';
    expect(c.startsWith('[已压缩')).toBe(true);
    expect(c).toContain('line-0');
    expect(c).toContain('line-9');
    expect(c).not.toContain('line-10');
  });

  it('最近 3 条工具结果不压缩，从更旧的开始', () => {
    const big = Array.from({ length: 100 }, (_, i) => `L${i}`).join('\n');
    const wire: LlmWireMessage[] = [
      { role: 'system', content: 's' },
      { role: 'tool', content: big, tool_call_id: 'c1' },
      { role: 'tool', content: big, tool_call_id: 'c2' },
      { role: 'tool', content: big, tool_call_id: 'c3' },
      { role: 'tool', content: big, tool_call_id: 'c4' },
    ];
    trimToBudget(wire, estimateTokens(big) * 3 + 50);
    expect(wire[1]?.content?.startsWith('[已压缩')).toBe(true); // 最旧先压
    expect(wire[4]?.content).toBe(big); // 最近一条不动
  });

  it('已压缩内容不重复压缩', () => {
    const placeholder = compactPlaceholder('abc');
    const wire: LlmWireMessage[] = [
      { role: 'tool', content: placeholder, tool_call_id: 'c1' },
      { role: 'tool', content: placeholder, tool_call_id: 'c2' },
      { role: 'tool', content: placeholder, tool_call_id: 'c3' },
      { role: 'tool', content: placeholder, tool_call_id: 'c4' },
    ];
    trimToBudget(wire, 1);
    expect(wire.every((m) => m.content === placeholder)).toBe(true);
  });
});

describe('dropOldMessages（降级 2：成组丢弃，支撑 200 轮长任务）', () => {
  /** system + 首条 user + 8 组（assistant(tool_calls) + tool 大结果） */
  function longWire(): LlmWireMessage[] {
    const big = 'x'.repeat(4000); // 约 1000 token / 条
    const wire: LlmWireMessage[] = [
      { role: 'system', content: 's' },
      { role: 'user', content: '任务定义' },
    ];
    for (let n = 1; n <= 8; n++) {
      wire.push({
        role: 'assistant', content: '思考',
        tool_calls: [{ id: `c${n}`, type: 'function', function: { name: 'read', arguments: '{}' } }],
      });
      wire.push({ role: 'tool', content: big, tool_call_id: `c${n}` });
    }
    return wire;
  }

  it('成组丢弃最旧：system / 首条用户消息 / 最近尾部保留，断点插入提示', () => {
    const wire = longWire();
    dropOldMessages(wire, 6500); // 总量约 8000 → 需丢约 2 组
    expect(wire[0]?.role).toBe('system');
    expect(wire[1]?.content).toBe('任务定义');
    expect(wire[2]?.content).toContain('上下文管理');
    // 最旧组已丢、最近尾部保留
    expect(wire.some((m) => m.tool_call_id === 'c1')).toBe(false);
    expect(wire[wire.length - 1]?.tool_call_id).toBe('c8');
  });

  it('配对完整：剩余 tool 消息均有对应 assistant tool_calls 声明', () => {
    const wire = longWire();
    dropOldMessages(wire, 5000);
    const declared = new Set(wire.flatMap((m) => (m.tool_calls ?? []).map((c) => c.id)));
    for (const m of wire) {
      if (m.role === 'tool') expect(declared.has(m.tool_call_id ?? '')).toBe(true);
    }
    // assistant 若有 tool_calls，其后紧跟的 tool 结果仍在（未被拆组）
    wire.forEach((m, idx) => {
      if (m.role === 'assistant' && m.tool_calls?.length === 1) {
        expect(wire[idx + 1]?.role).toBe('tool');
      }
    });
  });

  it('预算充足时不动任何消息', () => {
    const wire = longWire();
    const before = wire.length;
    dropOldMessages(wire, 1_000_000);
    expect(wire.length).toBe(before);
    expect(wire.some((m) => (m.content ?? '').includes('上下文管理'))).toBe(false);
  });
});

describe('assembleContext', () => {
  it('首条为 system；预算 = contextWindow − 8k 生效', async () => {
    const wire = await assembleContext({ workspace: null, config, history: [msg({})] });
    expect(wire[0]?.role).toBe('system');
    expect(wire[0]?.content).toContain('尚未选择工作区');
    expect(wire[1]?.role).toBe('user');
  });

  it('P3：模式约束前置注入（Plan 只读 / Auto 白名单说明）', async () => {
    const plan = await assembleContext({ workspace: null, config, history: [msg({})], mode: 'Plan' });
    expect(plan[0]?.content).toContain('当前权限模式 Plan');
    expect(plan[0]?.content).toContain('不要尝试任何写操作');
    const auto = await assembleContext({ workspace: null, config, history: [msg({})], mode: 'Auto' });
    expect(auto[0]?.content).toContain('当前权限模式 Auto');
    // 缺省回退 Ask
    const def = await assembleContext({ workspace: null, config, history: [msg({})] });
    expect(def[0]?.content).toContain('当前权限模式 Ask');
  });

  it('P4：④层技能目录注入（仅摘要，正文不进）', async () => {
    const wire = await assembleContext({
      workspace: null, config, history: [msg({})],
      skillCatalog: [{ name: 'review', description: '代码审查清单' }],
    });
    const sys = wire[0]?.content ?? '';
    expect(sys).toContain('可用技能');
    expect(sys).toContain('/review：代码审查清单');
    expect(sys).not.toContain('技能正文不应出现'); // 正文由模型 read 自取，不预注入
  });

  it('P4：/ 命令注入位置——高优先级指令位于目录之后（系统提示末尾）', async () => {
    const wire = await assembleContext({
      workspace: null, config, history: [msg({})],
      skillCatalog: [{ name: 'review', description: '代码审查清单' }],
      skillInstruction: '【审查清单正文】逐项检查正确性',
    });
    const sys = wire[0]?.content ?? '';
    const catalogIdx = sys.indexOf('/review：代码审查清单');
    const instructIdx = sys.indexOf('高优先级指令');
    expect(catalogIdx).toBeGreaterThan(-1);
    expect(instructIdx).toBeGreaterThan(catalogIdx); // 指令在目录之后追加，优先级最高层位
    expect(sys).toContain('【审查清单正文】逐项检查正确性');
  });
});

describe('computePromptBudget（工具 schema 计入 + 估算余量，防 prompt+max_tokens 超窗触发 400）', () => {
  it('无工具：(contextWindow − max(8k, maxTokens)) × 0.95', () => {
    // config: contextWindow=128000, maxTokens=100 → reserve=8000
    expect(computePromptBudget(config)).toBe(Math.floor((128000 - 8000) * 0.95));
  });

  it('工具 schema 越大预算越小（此前遗漏 schema 是「消息已 trim 仍超窗」的主因）', () => {
    const tools: LlmToolSchema[] = [
      { type: 'function', function: { name: 'big', description: 'd', parameters: { p: 'y'.repeat(4000) } } },
    ];
    expect(computePromptBudget(config, tools)).toBeLessThan(computePromptBudget(config));
  });

  it('maxTokens 超过 OUTPUT_RESERVE 时按 maxTokens 预留输出', () => {
    expect(computePromptBudget({ ...config, maxTokens: 20000 })).toBe(Math.floor((128000 - 20000) * 0.95));
  });

  it('窗口极小时下限 4000 兜底（不为 0 / 负）', () => {
    expect(computePromptBudget({ ...config, contextWindow: 5000, maxTokens: 4000 })).toBe(4000);
  });
});

describe('pruneToolsToWindow（窗口物理容量裁剪：schema 装不下时新会话也会 400）', () => {
  const schema = (name: string, pad = 0): LlmToolSchema => ({
    type: 'function',
    function: { name, description: `d ${'x'.repeat(pad)}`, parameters: { type: 'object', properties: {} } },
  });

  it('窗口充足：全量保留，dropped 空', () => {
    const tools = [schema('read'), schema('mcp__a__t1', 500), schema('mcp__a__t2', 500)];
    const { kept, dropped } = pruneToolsToWindow(tools, 128000, 4096);
    expect(kept).toHaveLength(3);
    expect(dropped).toEqual([]);
  });

  it('窗口装不下：内置恒保留，MCP 按序裁剪（保留前缀连续段）', () => {
    const tools = [schema('read'), ...Array.from({ length: 40 }, (_, i) => schema(`mcp__a__t${i}`, 1500))];
    const { kept, dropped } = pruneToolsToWindow(tools, 32768, 4096);
    expect(kept[0]!.function.name).toBe('read');
    expect(dropped.length).toBeGreaterThan(0);
    expect(kept.length + dropped.length).toBe(41);
    expect(dropped[0]).toBe(`mcp__a__t${kept.length - 1}`);
  });

  it('窗口极小：MCP 全丢、内置仍保留（极端兜底，不再静默超窗）', () => {
    const tools = [schema('read'), schema('mcp__a__t1', 1500)];
    const { kept, dropped } = pruneToolsToWindow(tools, 9000, 4096);
    expect(kept.map((t) => t.function.name)).toEqual(['read']);
    expect(dropped).toEqual(['mcp__a__t1']);
  });
});
