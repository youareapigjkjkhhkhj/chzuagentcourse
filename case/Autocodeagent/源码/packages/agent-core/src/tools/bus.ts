/**
 * ToolBus（AGENTS §4 toolbus）：注册 / 查询 / schema 导出 / 分发。
 * 不实现具体工具业务；Loop 只依赖 ToolBus（§13）。
 */
import type { LlmToolSchema } from '@agentbuddy/shared';
import { BASH_TOOLS } from './bashTool';
import { READ_TOOLS } from './fsRead';
import { WRITE_TOOLS } from './fsWrite';
import { TODO_TOOL } from './todoTool';
import type { Tool } from './types';
import { webfetchTool } from './webTool';

export class ToolBus {
  private readonly tools = new Map<string, Tool>();

  register(tool: Tool): void {
    this.tools.set(tool.name, tool);
  }

  get(name: string): Tool | undefined {
    return this.tools.get(name);
  }

  /** P7：专家绑定过滤时移除未命中的内置工具 */
  unregister(name: string): void {
    this.tools.delete(name);
  }

  names(): string[] {
    return [...this.tools.keys()];
  }

  /** function calling schema 全量下发（P5 起与 MCP 合并，无数量上限） */
  schemas(): LlmToolSchema[] {
    return [...this.tools.values()].map((t) => ({
      type: 'function',
      function: { name: t.name, description: t.description, parameters: t.parameters },
    }));
  }
}

/** 内置工具：P1 六件套 + P4 todo_write + 联网 webfetch（websearch 需配置 key，由外层按需注入 extra） */
export function createBuiltinBus(): ToolBus {
  const bus = new ToolBus();
  for (const tool of [...READ_TOOLS, ...WRITE_TOOLS, ...BASH_TOOLS, TODO_TOOL, webfetchTool]) bus.register(tool);
  return bus;
}

/**
 * P7 专家绑定判定：内置按工具名匹配；'mcp:连接器名' 命中该连接器全部工具
 * （挂载名 mcp__{server}__{tool}）。只影响 schema 下发，权限矩阵仍全程生效（§14）。
 */
function expertAllows(name: string, allow: string[]): boolean {
  const m = /^mcp__([^_].*?)__/.exec(name);
  return m ? allow.includes(`mcp:${m[1]!}`) : allow.includes(name);
}

/**
 * 会话工具总线：内置全量 + extra（如 use_skill 技能自取）+ 已连接 MCP 工具全量注册。
 * 不设数量上限——schema 全量下发，由模型按需自动识别调用（对齐 opencode）；精简靠停用连接器 / 专家绑定清单。
 * allow（P7 专家绑定清单）：缺省/空 = 不限定；非空 = 内置与 MCP 均只注册命中项
 * （todo_write 与 extra 始终保留：计划面板 / 技能自取不随专家工具绑定消失）。
 */
export function buildSessionBus(
  mcpTools: Tool[],
  allow?: string[],
  extra: Tool[] = [],
): ToolBus {
  const bus = createBuiltinBus();
  for (const tool of extra) bus.register(tool);
  const keep = new Set(['todo_write', ...extra.map((t) => t.name)]);
  if (allow && allow.length > 0) {
    // names() 是 Map keys 的活视图，先快照再删，避免边迭代边删漏项
    for (const name of [...bus.names()]) {
      if (!keep.has(name) && !expertAllows(name, allow)) bus.unregister(name);
    }
  }
  const candidates = allow && allow.length > 0 ? mcpTools.filter((t) => expertAllows(t.name, allow)) : mcpTools;
  for (const tool of candidates) bus.register(tool);
  return bus;
}
