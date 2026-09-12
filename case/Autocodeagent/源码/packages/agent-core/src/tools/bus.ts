/**
 * ToolBus（AGENTS §4 toolbus）：注册 / 查询 / schema 导出 / 分发。
 * 不实现具体工具业务；Loop 只依赖 ToolBus（§13）。
 */
import type { LlmToolSchema } from '@agentbuddy/shared';
import { BASH_TOOLS } from './bashTool';
import { READ_TOOLS } from './fsRead';
import { WRITE_TOOLS } from './fsWrite';
import { TODO_TOOL } from './todoTool';
import { createSearchTool, mcpSchemaTokens, ON_DEMAND_MIN_MCP_SCHEMA_TOKENS, registryFromTools } from './toolSearch';
import type { Tool } from './types';
import { webfetchTool } from './webTool';

export class ToolBus {
  private readonly tools = new Map<string, Tool>();
  /** 按需加载：注册为 deferred 的工具（MCP）可被 get/execute，但默认不进 schema 下发，经 search_tools 发现后才注入 */
  private readonly deferred = new Set<string>();

  register(tool: Tool): void {
    this.tools.set(tool.name, tool);
  }

  /** 按需加载：注册为 deferred（不常驻 schema）；与 register 的区别仅在于是否默认下发 */
  registerDeferred(tool: Tool): void {
    this.tools.set(tool.name, tool);
    this.deferred.add(tool.name);
  }

  get(name: string): Tool | undefined {
    return this.tools.get(name);
  }

  /** P7：专家绑定过滤时移除未命中的内置工具 */
  unregister(name: string): void {
    this.tools.delete(name);
    this.deferred.delete(name);
  }

  names(): string[] {
    return [...this.tools.keys()];
  }

  /** function calling schema 全量（含 deferred）：与总线注册一致，测试 / 无按需模式下用 */
  schemas(): LlmToolSchema[] {
    return [...this.tools.values()].map((t) => ({
      type: 'function',
      function: { name: t.name, description: t.description, parameters: t.parameters },
    }));
  }

  /** 是否启用了按需加载（存在 deferred 工具） */
  hasDeferred(): boolean {
    return this.deferred.size > 0;
  }

  /** 本轮实际下发的 schema：非 deferred 全量常驻 + 已发现的 deferred。无 deferred 时等同 schemas()。 */
  selectSchemas(discovered: ReadonlySet<string>): LlmToolSchema[] {
    return [...this.tools.values()]
      .filter((t) => !this.deferred.has(t.name) || discovered.has(t.name))
      .map((t) => ({
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

/** 从挂载名 mcp__{server}__{tool} 解析连接器名（专家绑定 / alwaysLoad 分区共用） */
function mcpServerOf(name: string): string | undefined {
  return /^mcp__([^_].*?)__/.exec(name)?.[1];
}

/**
 * P7 专家绑定判定：内置按工具名匹配；'mcp:连接器名' 命中该连接器全部工具
 * （挂载名 mcp__{server}__{tool}）。只影响 schema 下发，权限矩阵仍全程生效（§14）。
 */
function expertAllows(name: string, allow: string[]): boolean {
  const server = mcpServerOf(name);
  return server ? allow.includes(`mcp:${server}`) : allow.includes(name);
}

/**
 * 会话工具总线：内置全量 + extra（如 use_skill 技能自取）+ 已连接 MCP 工具。
 * MCP 不设数量上限，但按 schema 合计 token 分两种下发模式：
 * - 小规模（≤ 阈值）：全量常驻，模型按需自动识别调用（对齐 opencode）；
 * - 大规模（> 阈值）：全部 deferred（可执行、不常驻）+ 注册 search_tools 发现入口，命中后下一轮注入 schema
 *   （harness 侧 Tool Search，见 tools/toolSearch.ts）——大幅压低每次请求的 schema token。
 * 两种模式下 pruneToolsToWindow 都作窗口物理容量的二次安全网；精简亦可靠停用连接器 / 专家绑定清单。
 * allow（P7 专家绑定清单）：缺省/空 = 不限定；非空 = 内置与 MCP 均只注册命中项
 * （todo_write 与 extra 始终保留：计划面板 / 技能自取不随专家工具绑定消失）。
 * opts.alwaysLoadServers（Phase 2 强制常驻）：这批连接器的工具先全量 register（跳过按需分流），
 * 阈值判定与 search_tools 索引只覆盖其余（rest）工具——关键连接器免于「先检索再调用」的往返。
 */
export function buildSessionBus(
  mcpTools: Tool[],
  allow?: string[],
  extra: Tool[] = [],
  opts: { alwaysLoadServers?: ReadonlySet<string> } = {},
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
  // alwaysLoad 分区：强制常驻连接器的工具直接 register，其余（rest）走阈值分流
  const always = opts.alwaysLoadServers;
  const rest: Tool[] = [];
  for (const tool of candidates) {
    const server = mcpServerOf(tool.name);
    if (server && always?.has(server)) bus.register(tool);
    else rest.push(tool);
  }
  // search_tools 在内置过滤之后注册，不会被专家绑定误删；索引只覆盖 rest（always 已常驻，无需检索）
  if (mcpSchemaTokens(rest) > ON_DEMAND_MIN_MCP_SCHEMA_TOKENS) {
    bus.register(createSearchTool(registryFromTools(rest)));
    for (const tool of rest) bus.registerDeferred(tool);
  } else {
    for (const tool of rest) bus.register(tool);
  }
  return bus;
}
