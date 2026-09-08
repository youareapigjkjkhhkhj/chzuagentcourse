/**
 * P5 任务 5 + 上下文注入：MCP 工具全量下发（无上限，模型按需自动识别调用）与 ⑤层 MCP 目录。
 */
import { describe, expect, it } from 'vitest';
import { systemPrompt } from '../src/context';
import { buildSessionBus, createBuiltinBus } from '../src/tools/bus';
import type { Tool } from '../src/tools/types';

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
  it('内置工具为 8 个', () => {
    const names = createBuiltinBus().names();
    expect(names).toHaveLength(8);
    expect(names).toContain('webfetch'); // 联网抓取零配置内置
  });

  it('50 个 MCP 工具全量注册（内置 8 + MCP 50 = 58），末尾工具不再被丢弃', () => {
    const mcpTools = Array.from({ length: 50 }, (_, i) => fakeMcpTool(i));
    const bus = buildSessionBus(mcpTools);
    expect(bus.names()).toHaveLength(58);
    expect(bus.get('read')).toBeTruthy();
    expect(bus.get('mcp__srv__tool_0')).toBeTruthy();
    expect(bus.get('mcp__srv__tool_49')).toBeTruthy(); // 旧 40 上限下 tool_32+ 会被丢，现在全保留
  });

  it('无 MCP 工具时等同内置总线', () => {
    expect(buildSessionBus([]).names()).toHaveLength(8);
  });

  it('schemas 全量下发与总线一致', () => {
    const bus = buildSessionBus(Array.from({ length: 50 }, (_, i) => fakeMcpTool(i)));
    expect(bus.schemas()).toHaveLength(58);
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
    // 全量：内置 8 + extra 1 + MCP 50 = 59
    const full = buildSessionBus(Array.from({ length: 50 }, (_, i) => fakeMcpTool(i)), undefined, [extra]);
    expect(full.names()).toHaveLength(59);
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
