/**
 * 按需工具加载（Tool Search，harness 侧实现）。
 * 背景：AgentBuddy 走 OpenAI 兼容后端，拿不到 Anthropic 的服务端 defer_loading 特性，
 * 故在客户端实现同等能力——MCP 工具默认不常驻 schema，模型经 search_tools 检索命中后，
 * 其 schema 于「下一轮」注入可调用列表（由 orchestrator 的 discovered 集驱动）。
 * 对齐 Anthropic Tool Search Tool：常驻只留核心工具 + 一个检索入口，大幅压低每次请求的 schema token。
 */
import { estimateSchemaTokens } from '../context';
import { num, str, type Tool, type ToolContext } from './types';

/** MCP schema 合计超此 token 阈值才启用按需加载：小规模连接器全量常驻更省事（省一次检索往返），
 * 大规模才值得（对齐 Anthropic「工具定义 >10K token / 10+ 工具」的建议）。 */
export const ON_DEMAND_MIN_MCP_SCHEMA_TOKENS = 6000;
/** 检索入口工具名（context.ts 据此推断按需模式，措辞与 webfetch/websearch 的字面量约定一致） */
export const SEARCH_TOOLS_NAME = 'search_tools';
/** 单次检索默认返回数（Top-K）：够模型下一步选型，又不至于一次拉回太多 schema */
const DEFAULT_TOP_K = 5;
const MAX_TOP_K = 20;

export interface ToolIndexEntry {
  name: string;
  description: string;
  /** 连接器名（从挂载名 mcp__server__tool 解析），用于排序加权与结果展示 */
  server?: string;
}

/** 词法检索：query 分词后对 name/server/description 加权打分，无外部依赖（本地轻量优先，不上 embedding）。 */
export class ToolRegistry {
  constructor(private readonly entries: ToolIndexEntry[]) {}

  get size(): number {
    return this.entries.length;
  }

  /** 返回 score>0 的 Top-K（k 夹在 [1, MAX_TOP_K]）；name 命中权重最高，其次 server，再次 description。 */
  search(query: string, k = DEFAULT_TOP_K): ToolIndexEntry[] {
    const terms = tokenize(query);
    if (terms.length === 0) return [];
    const limit = Math.min(Math.max(1, Math.floor(k)), MAX_TOP_K);
    return this.entries
      .map((e) => ({ e, score: scoreEntry(e, terms, query) }))
      .filter((x) => x.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, limit)
      .map((x) => x.e);
  }
}

/** 分词：按非字母数字/非中日韩切分，转小写；保留中文整段（中文无词边界，按子串匹配即可） */
function tokenize(text: string): string[] {
  return text
    .toLowerCase()
    .split(/[^a-z0-9\u4e00-\u9fff]+/)
    .filter((t) => t.length > 0);
}

function scoreEntry(e: ToolIndexEntry, terms: string[], rawQuery: string): number {
  const name = e.name.toLowerCase();
  const server = (e.server ?? '').toLowerCase();
  const desc = e.description.toLowerCase();
  let score = 0;
  for (const t of terms) {
    if (name.includes(t)) score += 6;
    if (server && server.includes(t)) score += 4;
    if (desc.includes(t)) score += 2;
  }
  // 工具本名（挂载名末段）整串出现在 query 中 = 强信号（如 query 直接写了 render_scene）
  const tail = name.split('__').pop() ?? name;
  if (tail.length > 2 && rawQuery.toLowerCase().includes(tail)) score += 5;
  return score;
}

/** 从 MCP 工具构造检索索引（server 从挂载名 mcp__server__tool 解析） */
export function registryFromTools(tools: Tool[]): ToolRegistry {
  return new ToolRegistry(
    tools.map((t) => {
      const m = /^mcp__([^_].*?)__/.exec(t.name);
      return { name: t.name, description: t.description, ...(m ? { server: m[1]! } : {}) };
    }),
  );
}

/** MCP 工具 schema 合计 token（决定是否越过阈值启用按需加载），与 pruneToolsToWindow 同源估算系数 */
export function mcpSchemaTokens(tools: Tool[]): number {
  return tools.reduce(
    (sum, t) => sum + estimateSchemaTokens({ name: t.name, description: t.description, parameters: t.parameters }),
    0,
  );
}

/**
 * search_tools：模型的能力检索入口。命中后经 ctx.onDiscoverTools 记录工具名，
 * orchestrator 在下一轮把这些工具的 schema 并入下发列表，模型即可真正调用（发现与调用分两轮）。
 */
export function createSearchTool(registry: ToolRegistry): Tool {
  return {
    name: SEARCH_TOOLS_NAME,
    description:
      '按能力检索可用的 MCP 连接器工具。当需要某连接器能力（渲染 / 发消息 / 查数据 / 操作外部系统等）但当前可调用工具列表里没有对应工具时，用自然语言描述需求调用本工具；命中的工具会从下一轮起自动加入可调用列表，然后再调用它。',
    parameters: {
      type: 'object',
      properties: {
        query: { type: 'string', description: '需求描述，如「blender 渲染当前场景为 4K PNG」' },
        k: { type: 'number', description: `返回数量上限（默认 ${DEFAULT_TOP_K}，最大 ${MAX_TOP_K}）` },
      },
      required: ['query'],
    },
    risk: 'READ',
    execute: async (ctx: ToolContext, input: Record<string, unknown>) => {
      const query = str(input, 'query');
      const hits = registry.search(query, num(input, 'k', DEFAULT_TOP_K));
      if (hits.length === 0) {
        return { text: `未匹配到与「${query}」相关的连接器工具（索引共 ${registry.size} 个）。可换用更贴近目标能力的关键词重试，或改用内置工具完成。` };
      }
      ctx.onDiscoverTools?.(hits.map((h) => h.name));
      const lines = hits.map((h) => `- ${h.name}${h.server ? `（连接器 ${h.server}）` : ''}：${h.description || '（无描述）'}`);
      return { text: `已找到 ${hits.length} 个工具，从下一轮起可直接调用：\n${lines.join('\n')}` };
    },
  };
}
