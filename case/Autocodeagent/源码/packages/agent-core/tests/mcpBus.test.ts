/**
 * P5 任务 5 + 上下文注入：MCP 工具全量下发（无上限，模型按需自动识别调用）与 ⑤层 MCP 目录。
 */
import { describe, expect, it } from 'vitest';
import { systemPrompt } from '../src/context';
import { buildSessionBus, createBuiltinBus } from '../src/tools/bus';
import { ReadState, type Tool, type ToolContext } from '../src/tools/types';

function fakeMcpTool(i: number): Tool {
  return {
    name: `mcp__srv__tool_${i}`,
    description: `假工具 ${i}`,
    parameters: { type: 'object', properties: {} },
    risk: 'NETWORK',
    execute: async () => ({ text: '' }),
  };
}

describe('buildSessionBus 全量下发（无上限）', () => {
  it('内置工具为 9 个', () => {
    const names = createBuiltinBus().names();
    expect(names).toHaveLength(9);
    expect(names).toContain('webfetch'); // 联网抓取零配置内置
  });

  it('50 个 MCP 工具全量注册（内置 9 + MCP 50 = 59），末尾工具不再被丢弃', () => {
    const mcpTools = Array.from({ length: 50 }, (_, i) => fakeMcpTool(i));
    const bus = buildSessionBus(mcpTools);
    expect(bus.names()).toHaveLength(59);
    expect(bus.get('read')).toBeTruthy();
    expect(bus.get('mcp__srv__tool_0')).toBeTruthy();
    expect(bus.get('mcp__srv__tool_49')).toBeTruthy(); // 旧 40 上限下 tool_32+ 会被丢，现在全保留
  });

  it('无 MCP 工具时等同内置总线', () => {
    expect(buildSessionBus([]).names()).toHaveLength(9);
  });

  it('schemas 全量下发与总线一致', () => {
    const bus = buildSessionBus(Array.from({ length: 50 }, (_, i) => fakeMcpTool(i)));
    expect(bus.schemas()).toHaveLength(59);
  });

  it('extra 工具（use_skill）：专家过滤保留 + 全量注册', () => {
    const extra: Tool = {
      name: 'use_skill', description: '技能自取', parameters: { type: 'object', properties: {} },
      risk: 'READ', execute: async () => ({ text: '' }),
    };
    // 专家绑定 read：extra 与 todo_write 不被过滤掉
    const filtered = buildSessionBus([], ['read'], [extra]);
    expect(filtered.get('use_skill')).toBeTruthy();
    expect(filtered.get('todo_write')).toBeTruthy();
    expect(filtered.get('bash')).toBeUndefined();
    // 全量：内置 9 + extra 1 + MCP 50 = 60
    const full = buildSessionBus(Array.from({ length: 50 }, (_, i) => fakeMcpTool(i)), undefined, [extra]);
    expect(full.names()).toHaveLength(60);
    expect(full.get('use_skill')).toBeTruthy();
  });
});

describe('systemPrompt ⑤层 MCP 目录', () => {
  it('已连接连接器注入：#名称 + 描述 + 工具名', () => {
    const prompt = systemPrompt(null, 'gpt-5-mini', null, 'Ask', undefined, undefined, [
      { name: 'echo', description: '回显测试连接器', tools: ['ping', 'envprobe'] },
    ]);
    expect(prompt).toContain('已连接 MCP 连接器');
    expect(prompt).toContain('#echo');
    expect(prompt).toContain('回显测试连接器');
    expect(prompt).toContain('ping, envprobe');
  });

  it('工具名最多列 10 个，其余以「等 N 个」收口', () => {
    const tools = Array.from({ length: 12 }, (_, i) => `t${i}`);
    const prompt = systemPrompt(null, 'm', null, 'Ask', undefined, undefined, [
      { name: 'big', description: '', tools },
    ]);
    expect(prompt).toContain('t0, t1, t2, t3, t4, t5, t6, t7, t8, t9');
    expect(prompt).not.toContain('t10');
    expect(prompt).toContain('等 12 个');
  });

  it('空目录不注入该段', () => {
    const prompt = systemPrompt(null, 'm', null, 'Ask', undefined, undefined, []);
    expect(prompt).not.toContain('已连接 MCP 连接器');
  });
});

describe('buildSessionBus 按需加载（MCP schema 合计超阈值 → deferred + search_tools）', () => {
  // 大 schema MCP 工具：描述填充使其合计越过 ON_DEMAND_MIN_MCP_SCHEMA_TOKENS(6000)
  function bigMcpTool(i: number): Tool {
    return {
      name: `mcp__gfx__render_${i}`,
      description: `render scene ${i} ${'x'.repeat(1800)}`,
      parameters: { type: 'object', properties: {} },
      risk: 'NETWORK',
      execute: async () => ({ text: '' }),
    };
  }

  it('小规模 MCP（≤ 阈值）：全量常驻，无 search_tools，hasDeferred=false', () => {
    const bus = buildSessionBus(Array.from({ length: 50 }, (_, i) => fakeMcpTool(i)));
    expect(bus.hasDeferred()).toBe(false);
    expect(bus.get('search_tools')).toBeUndefined();
    expect(bus.selectSchemas(new Set())).toHaveLength(59); // 无 deferred：等同全量 schemas()
  });

  it('大规模 MCP（> 阈值）：注册 search_tools，MCP 全部 deferred（可执行、不常驻 schema）', () => {
    const bus = buildSessionBus(Array.from({ length: 10 }, (_, i) => bigMcpTool(i)));
    expect(bus.hasDeferred()).toBe(true);
    expect(bus.get('search_tools')).toBeTruthy();
    // 常驻仅内置 9 + search_tools = 10；MCP 未注入
    const resident = bus.selectSchemas(new Set()).map((t) => t.function.name);
    expect(resident).toHaveLength(10);
    expect(resident).toContain('search_tools');
    expect(resident.some((n) => n.startsWith('mcp__'))).toBe(false);
    // get 仍可取到 deferred 工具（发现后即可执行）
    expect(bus.get('mcp__gfx__render_0')).toBeTruthy();
    // schemas() 全量（含 deferred）：内置 9 + search_tools + MCP 10 = 20
    expect(bus.schemas()).toHaveLength(20);
  });

  it('selectSchemas：已发现的 deferred 注入，其余仍隐藏', () => {
    const bus = buildSessionBus(Array.from({ length: 10 }, (_, i) => bigMcpTool(i)));
    const names = bus.selectSchemas(new Set(['mcp__gfx__render_2', 'mcp__gfx__render_5'])).map((t) => t.function.name);
    expect(names).toContain('mcp__gfx__render_2');
    expect(names).toContain('mcp__gfx__render_5');
    expect(names).not.toContain('mcp__gfx__render_0');
    expect(names).toHaveLength(12); // 10 常驻 + 2 发现
  });
});

describe('systemPrompt 按需加载指引（onDemandTools）', () => {
  const catalog = [{ name: 'gfx', description: '渲染连接器', tools: ['render_scene'] }];

  it('onDemandTools=true：措辞改为发现索引 + 先 search_tools 检索（目录仍列出）', () => {
    const prompt = systemPrompt(null, 'm', null, 'Ask', undefined, undefined, catalog, undefined, undefined, undefined, true);
    expect(prompt).toContain('按需加载');
    expect(prompt).toContain('search_tools');
    expect(prompt).toContain('#gfx');
  });

  it('onDemandTools 缺省：沿用「#名称 提及优先使用」措辞，不提按需加载', () => {
    const prompt = systemPrompt(null, 'm', null, 'Ask', undefined, undefined, catalog);
    expect(prompt).toContain('用 #名称 提及时优先使用');
    expect(prompt).not.toContain('按需加载');
  });
});

describe('buildSessionBus alwaysLoad 分区（强制常驻连接器跳过按需分流）', () => {
  // 与「按需加载」describe 同源的大 schema 工具（每个 ≈668 token），按连接器名区分
  function bigTool(server: string, i: number): Tool {
    return {
      name: `mcp__${server}__render_${i}`,
      description: `render scene ${i} ${'x'.repeat(1800)}`,
      parameters: { type: 'object', properties: {} },
      risk: 'NETWORK',
      execute: async () => ({ text: '' }),
    };
  }

  it('alwaysLoad 连接器强制常驻；其余（rest）超阈值仍 deferred，阈值只按 rest 计', () => {
    const always = Array.from({ length: 4 }, (_, i) => bigTool('gfx', i)); // 强制常驻
    const rest = Array.from({ length: 10 }, (_, i) => bigTool('bulk', i)); // 10×大 schema > 阈值
    const bus = buildSessionBus([...always, ...rest], undefined, [], { alwaysLoadServers: new Set(['gfx']) });
    expect(bus.hasDeferred()).toBe(true);
    expect(bus.get('search_tools')).toBeTruthy();
    const resident = bus.selectSchemas(new Set()).map((t) => t.function.name);
    // 内置 9 + search_tools + gfx 常驻 4 = 14；bulk 全部 deferred 不常驻
    expect(resident.filter((n) => n.startsWith('mcp__gfx__'))).toHaveLength(4);
    expect(resident.some((n) => n.startsWith('mcp__bulk__'))).toBe(false);
    expect(resident).toHaveLength(14);
    expect(bus.get('mcp__bulk__render_0')).toBeTruthy(); // deferred 仍可取（发现后可执行）
  });

  it('alwaysLoad 拉走后 rest 不足阈值 → 不启用按需，全部常驻', () => {
    const always = Array.from({ length: 6 }, (_, i) => bigTool('gfx', i));
    const rest = Array.from({ length: 4 }, (_, i) => bigTool('bulk', i)); // 4×大 schema < 阈值
    // 合计 10 个 > 阈值，但 rest 仅 4 个 < 阈值 → 不该 defer（阈值只对 rest 计）
    const bus = buildSessionBus([...always, ...rest], undefined, [], { alwaysLoadServers: new Set(['gfx']) });
    expect(bus.hasDeferred()).toBe(false);
    expect(bus.get('search_tools')).toBeUndefined();
    expect(bus.selectSchemas(new Set())).toHaveLength(19); // 内置 9 + gfx 6 + bulk 4
  });

  it('search_tools 索引只覆盖 rest：命中 bulk，不命中已常驻的 alwaysLoad 连接器', async () => {
    const always = Array.from({ length: 4 }, (_, i) => bigTool('gfx', i));
    const rest = Array.from({ length: 10 }, (_, i) => bigTool('bulk', i));
    const bus = buildSessionBus([...always, ...rest], undefined, [], { alwaysLoadServers: new Set(['gfx']) });
    const discovered: string[] = [];
    const ctx: ToolContext = {
      workspace: null,
      signal: new AbortController().signal,
      readState: new ReadState(),
      snapshot: async () => null,
      resolvePath: async (p) => p,
      onDiscoverTools: (names) => discovered.push(...names),
    };
    await bus.get('search_tools')!.execute(ctx, { query: 'render', k: 20 });
    expect(discovered.length).toBeGreaterThan(0);
    expect(discovered.every((n) => n.startsWith('mcp__bulk__'))).toBe(true); // gfx 未进索引
  });
});
