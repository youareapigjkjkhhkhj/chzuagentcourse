/**
 * 按需工具加载（Tool Search，harness 侧）单测：
 * 词法检索 ranking + search_tools 发现回填 + 阈值/索引构建。
 */
import { describe, expect, it } from 'vitest';
import {
  createSearchTool,
  mcpSchemaTokens,
  ON_DEMAND_MIN_MCP_SCHEMA_TOKENS,
  registryFromTools,
  SEARCH_TOOLS_NAME,
  ToolRegistry,
  type ToolIndexEntry,
} from '../src/tools/toolSearch';
import { ReadState, type Tool, type ToolContext } from '../src/tools/types';

function entry(name: string, description: string, server?: string): ToolIndexEntry {
  return { name, description, ...(server ? { server } : {}) };
}

function mockCtx(onDiscover?: (names: string[]) => void): ToolContext {
  return {
    workspace: null,
    signal: new AbortController().signal,
    readState: new ReadState(),
    snapshot: async () => null,
    resolvePath: async (p) => p,
    ...(onDiscover ? { onDiscoverTools: onDiscover } : {}),
  };
}

function mcpTool(name: string, description: string): Tool {
  return {
    name, description, parameters: { type: 'object', properties: {} },
    risk: 'NETWORK', execute: async () => ({ text: '' }),
  };
}

describe('ToolRegistry 词法检索', () => {
  const reg = new ToolRegistry([
    entry('mcp__gfx__render_scene', '渲染当前 3D 场景为图片', 'gfx'),
    entry('mcp__im__send_message', '发送消息到频道', 'im'),
    entry('mcp__db__query_rows', 'query rows from database', 'db'),
  ]);

  it('name 命中权重最高：query 含工具本名子串排在前', () => {
    expect(reg.search('render')[0]?.name).toBe('mcp__gfx__render_scene');
  });

  it('description 命中也可检索（英文子串）', () => {
    expect(reg.search('database').map((h) => h.name)).toContain('mcp__db__query_rows');
  });

  it('server 命中加权：按连接器名检索', () => {
    expect(reg.search('gfx')[0]?.server).toBe('gfx');
  });

  it('空 query / 无匹配 token → 空结果', () => {
    expect(reg.search('')).toEqual([]);
    expect(reg.search('   ')).toEqual([]);
    expect(reg.search('zzzznomatch')).toEqual([]);
  });

  it('k 限制返回数（夹在 [1, MAX_TOP_K=20]）', () => {
    const many = new ToolRegistry(Array.from({ length: 30 }, (_, i) => entry(`mcp__s__t${i}`, 'common token hit', 's')));
    expect(many.search('common', 3)).toHaveLength(3);
    expect(many.search('common', 0)).toHaveLength(1); // 下限 1
    expect(many.search('common', 999)).toHaveLength(20); // 上限 MAX_TOP_K
  });

  it('size 反映索引条目数', () => {
    expect(reg.size).toBe(3);
  });
});

describe('createSearchTool（发现回填 + 文案）', () => {
  const reg = registryFromTools([
    mcpTool('mcp__gfx__render_scene', '渲染场景'),
    mcpTool('mcp__gfx__export_png', '导出 PNG'),
    mcpTool('mcp__im__send_message', '发送消息'),
  ]);
  const tool = createSearchTool(reg);

  it('工具名固定 search_tools，风险 READ（只检索、无副作用）', () => {
    expect(tool.name).toBe(SEARCH_TOOLS_NAME);
    expect(tool.name).toBe('search_tools');
    expect(tool.risk).toBe('READ');
  });

  it('命中：经 onDiscoverTools 回报工具名，文案列出命中项 + 下一轮可用', async () => {
    const discovered: string[] = [];
    const out = await tool.execute(mockCtx((n) => discovered.push(...n)), { query: 'render' });
    expect(discovered).toContain('mcp__gfx__render_scene');
    expect(out.text).toContain('mcp__gfx__render_scene');
    expect(out.text).toContain('下一轮');
  });

  it('未命中：不回报，文案提示换关键词 + 索引规模', async () => {
    let called = false;
    const out = await tool.execute(mockCtx(() => { called = true; }), { query: 'zzz不存在' });
    expect(called).toBe(false);
    expect(out.text).toContain('未匹配');
    expect(out.text).toContain('3'); // registry.size
  });

  it('k 参数透传：限制发现数量', async () => {
    const discovered: string[] = [];
    await tool.execute(mockCtx((n) => discovered.push(...n)), { query: 'gfx', k: 1 });
    expect(discovered).toHaveLength(1);
  });
});

describe('registryFromTools / mcpSchemaTokens', () => {
  it('从挂载名解析 server（mcp__server__tool）', () => {
    const reg = registryFromTools([mcpTool('mcp__gfx__render', 'r'), mcpTool('mcp__im__send', 's')]);
    expect(reg.search('gfx')[0]?.server).toBe('gfx');
  });

  it('schema 合计 token 随描述增大而增大，可据阈值判定是否启用按需加载', () => {
    const small = [mcpTool('mcp__s__t', 'x')];
    const big = Array.from({ length: 40 }, (_, i) => mcpTool(`mcp__s__t${i}`, 'y'.repeat(1500)));
    expect(mcpSchemaTokens(small)).toBeLessThan(ON_DEMAND_MIN_MCP_SCHEMA_TOKENS);
    expect(mcpSchemaTokens(big)).toBeGreaterThan(ON_DEMAND_MIN_MCP_SCHEMA_TOKENS);
  });
});
