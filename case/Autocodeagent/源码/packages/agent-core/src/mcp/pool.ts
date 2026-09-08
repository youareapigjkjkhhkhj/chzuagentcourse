/**
 * MCP 连接池（P5 任务 2 / 3 / 5；P6+ 扩展 http/sse 传输）：
 * 官方 SDK `Client` + 三种传输：stdio（进程）/ http（Streamable HTTP）/ sse（旧版）；
 * 启用即连接、禁用/删除即 close()；进程崩溃（onclose）标记离线，不影响内置工具；
 * 状态变化经 onViews 事件广播（§18）。
 * Tools 发现：listTools() 包装为内部 Tool（mcp__{server}__{tool}，risk = NETWORK）。
 */
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import { SSEClientTransport } from '@modelcontextprotocol/sdk/client/sse.js';
import type { Transport } from '@modelcontextprotocol/sdk/shared/transport.js';
import type { McpServerConfig, McpServerView, McpStatus, McpToolView } from '@agentbuddy/shared';
import { resolveEnv } from './env';
import { registerSecret } from '../redact';
import type { McpConfigStore } from './configStore';
import type { Tool, ToolResult } from '../tools/types';

const CLIENT_INFO = { name: 'AgentBuddy', version: '0.1.0' };

interface McpToolFull extends McpToolView {
  inputSchema: Record<string, unknown>;
}

interface Conn {
  cfg: McpServerConfig;
  client: Client | null;
  status: McpStatus;
  tools: McpToolFull[];
  error?: string;
  /** 连接中占位：防并发重复 spawn */
  connecting?: Promise<void>;
}

export interface McpPoolDeps {
  store: McpConfigStore;
  /** 状态变化广播（Main 层转发为 stream:event，AGENTS §18） */
  onViews?: (views: McpServerView[]) => void;
}

/** 工具挂载名：mcp__{server}__{tool}（function name 字符集 + 64 长度护栏） */
export function mcpToolName(server: string, tool: string): string {
  const clean = tool.replace(/[^a-zA-Z0-9_-]/g, '_') || 'tool';
  const prefix = `mcp__${server}__`;
  const maxTool = Math.max(1, 64 - prefix.length);
  return prefix + clean.slice(0, maxTool);
}

/** Tool Trace 展示：mcp__github__create_issue → github / create_issue */
export function mcpDisplayName(name: string): string {
  const m = /^mcp__([^_].*?)__(.+)$/.exec(name);
  return m ? `${m[1]} / ${m[2]}` : name;
}

export class McpPool {
  private readonly conns = new Map<string, Conn>();

  constructor(private readonly deps: McpPoolDeps) {}

  /** 启动：读配置，启用的异步连接（不阻塞窗口初始化） */
  async init(): Promise<void> {
    const configs = await this.deps.store.load();
    for (const cfg of Object.values(configs)) {
      const conn: Conn = { cfg, client: null, status: cfg.enabled ? 'offline' : 'disabled', tools: [] };
      this.conns.set(cfg.name, conn);
      if (cfg.enabled) void this.startConnect(conn);
    }
    this.emit();
  }

  views(): McpServerView[] {
    return [...this.conns.values()].map((c) => ({
      config: c.cfg,
      status: c.status,
      tools: c.tools.map((t) => ({ name: t.name, description: t.description })),
      error: c.error,
    }));
  }

  /** 已连接 server 的工具包装（orchestrator 每轮全量并入 ToolBus，无数量上限） */
  sessionTools(): Tool[] {
    const out: Tool[] = [];
    for (const conn of this.conns.values()) {
      if (conn.status !== 'connected') continue;
      for (const t of conn.tools) out.push(this.wrapTool(conn, t));
    }
    return out;
  }

  /** 系统提示 ⑤ 层目录：已连接连接器（# 提及语义） */
  catalog(): Array<{ name: string; description: string; tools: string[] }> {
    return [...this.conns.values()]
      .filter((c) => c.status === 'connected')
      .map((c) => ({
        name: c.cfg.name,
        description: c.cfg.description ?? '',
        tools: c.tools.map((t) => t.name),
      }));
  }

  /* ── 配置变更入口（三通道统一经此，变更后即时连接 / 断开） ── */

  async upsert(cfg: McpServerConfig): Promise<McpServerConfig> {
    const saved = await this.deps.store.upsert(cfg);
    const old = this.conns.get(saved.name);
    if (old) await this.closeConn(old);
    const conn: Conn = { cfg: saved, client: null, status: saved.enabled ? 'offline' : 'disabled', tools: [] };
    this.conns.set(saved.name, conn);
    if (saved.enabled) void this.startConnect(conn);
    this.emit();
    return saved;
  }

  async remove(name: string): Promise<void> {
    const conn = this.conns.get(name);
    if (conn) await this.closeConn(conn);
    this.conns.delete(name);
    await this.deps.store.remove(name);
    this.emit();
  }

  async setEnabled(name: string, enabled: boolean): Promise<void> {
    const cfg = await this.deps.store.setEnabled(name, enabled);
    const conn = this.conns.get(name);
    if (!conn) throw new Error(`连接器不存在: ${name}`);
    conn.cfg = cfg;
    if (enabled) {
      conn.status = 'offline';
      void this.startConnect(conn);
    } else {
      await this.closeConn(conn);
      conn.status = 'disabled';
    }
    this.emit();
  }

  /** 崩溃 / 失败后的手动重连（验收：重连按钮可恢复） */
  async reconnect(name: string): Promise<void> {
    const conn = this.conns.get(name);
    if (!conn) throw new Error(`连接器不存在: ${name}`);
    if (!conn.cfg.enabled) throw new Error('连接器已停用，请先启用');
    await this.closeConn(conn);
    await this.startConnect(conn);
  }

  async importJson(text: string): Promise<McpServerConfig[]> {
    const imported = await this.deps.store.importJson(text);
    for (const cfg of imported) {
      const old = this.conns.get(cfg.name);
      if (old) await this.closeConn(old);
      const conn: Conn = { cfg, client: null, status: cfg.enabled ? 'offline' : 'disabled', tools: [] };
      this.conns.set(cfg.name, conn);
      if (cfg.enabled) void this.startConnect(conn);
    }
    this.emit();
    return imported;
  }

  /** 退出前收尾：全部 close()（before-quit 调用） */
  async closeAll(): Promise<void> {
    await Promise.all([...this.conns.values()].map((c) => this.closeConn(c)));
  }

  /* ── 内部 ── */

  private emit(): void {
    this.deps.onViews?.(this.views());
  }

  private async closeConn(conn: Conn): Promise<void> {
    const client = conn.client;
    conn.client = null;
    conn.tools = [];
    if (client) await client.close().catch(() => undefined);
  }

  /** 异步连接（防并发重入）；失败标离线并记录错误文案 */
  private startConnect(conn: Conn): Promise<void> {
    if (conn.connecting) return conn.connecting;
    conn.status = 'connecting';
    conn.error = undefined;
    this.emit();
    conn.connecting = this.connect(conn)
      .catch((e) => {
        conn.status = 'offline';
        conn.error = e instanceof Error ? e.message : String(e);
        conn.tools = [];
      })
      .finally(() => {
        conn.connecting = undefined;
        this.emit();
      });
    return conn.connecting;
  }

  private async connect(conn: Conn): Promise<void> {
    const cfg = conn.cfg;
    const transport = this.createTransport(cfg);

    const client = new Client(CLIENT_INFO);
    // 进程退出 / 管道断开 / HTTP 会话终止 → 离线（不影响内置工具；重连按钮可恢复）
    transport.onclose = () => {
      if (conn.client === client) {
        conn.client = null;
        conn.tools = [];
        conn.status = 'offline';
        conn.error = '连接已断开（server 退出或崩溃），可点重连恢复';
        this.emit();
      }
    };
    transport.onerror = (err) => {
      if (conn.client === client) conn.error = err instanceof Error ? err.message : String(err);
    };

    try {
      await client.connect(transport);
    } catch (e) {
      await transport.close().catch(() => undefined);
      throw e instanceof Error ? e : new Error(String(e));
    }

    const list = await client.listTools();
    conn.client = client;
    conn.tools = (list.tools ?? []).map((t) => ({
      name: t.name,
      description: t.description ?? '',
      inputSchema: (t.inputSchema as Record<string, unknown> | undefined) ?? { type: 'object', properties: {} },
    }));
    conn.status = 'connected';
    conn.error = undefined;
  }

  /** 按配置构建传输：stdio 拉起进程；http = Streamable HTTP（主流网关）；sse = 旧版端点 */
  private createTransport(cfg: McpServerConfig): Transport {
    // ${VAR} 占位符注入（缺失即报错，仅提变量名；值不进日志，§P5 任务 4）
    const resolved = resolveEnv(cfg.env);
    // P6：解析值登记脱敏中间件，任何日志出口均掩为 ***
    for (const value of Object.values(resolved)) registerSecret(value);

    if (cfg.type === 'stdio') {
      if (!cfg.command) throw new Error('stdio 连接器缺少启动命令');
      return new StdioClientTransport({
        command: cfg.command,
        args: cfg.args ?? [],
        env: { ...(process.env as Record<string, string>), ...resolved },
        stderr: 'pipe', // server stderr 不回显、不落日志
      });
    }

    if (!cfg.url) throw new Error(`${cfg.type} 连接器缺少端点 URL`);
    let endpoint: URL;
    try {
      endpoint = new URL(cfg.url);
    } catch {
      throw new Error(`端点 URL 非法: ${cfg.url}`);
    }
    if (endpoint.protocol !== 'http:' && endpoint.protocol !== 'https:') {
      throw new Error(`端点 URL 须为 http/https: ${cfg.url}`);
    }

    // 自定义请求头（鉴权等）：值支持 ${VAR} 占位，解析后同样登记脱敏
    const headers = resolveEnv(cfg.headers);
    for (const value of Object.values(headers)) registerSecret(value);

    if (cfg.type === 'http') {
      return new StreamableHTTPClientTransport(endpoint, { requestInit: { headers } });
    }
    // SSE：requestInit 覆盖 POST 发送请求；eventSourceInit 为初始流请求补同一批头
    return new SSEClientTransport(endpoint, {
      requestInit: { headers },
      eventSourceInit: {
        fetch: (url, init) => {
          const h = new Headers(init.headers);
          for (const [k, v] of Object.entries(headers)) h.set(k, v);
          return fetch(url, { ...init, headers: h });
        },
      },
    });
  }

  private wrapTool(conn: Conn, t: McpToolFull): Tool {
    const server = conn.cfg.name;
    return {
      name: mcpToolName(server, t.name),
      description: t.description || `MCP 连接器 ${server} 提供的外部工具`,
      parameters: t.inputSchema,
      risk: 'NETWORK',
      execute: async (ctx, input): Promise<ToolResult> => {
        const client = conn.client;
        if (!client) throw new Error(`连接器 ${server} 已离线，无法调用 ${t.name}`);
        const res = await client.callTool({ name: t.name, arguments: input }, undefined, { signal: ctx.signal });
        const text = extractText(res);
        if (!res || res.isError) throw new Error(text || 'MCP 工具返回错误（无详情）');
        return { text: text || '（工具执行完成，无返回内容）' };
      },
    };
  }
}

/** callTool 结果 → 纯文本（text 段拼接；其余类型标注占位，不吞信息） */
function extractText(res: unknown): string {
  if (!res || typeof res !== 'object') return '';
  const content = (res as { content?: unknown }).content;
  if (!Array.isArray(content)) return '';
  const parts: string[] = [];
  for (const item of content) {
    if (item && typeof item === 'object' && (item as { type?: unknown }).type === 'text') {
      const text = (item as { text?: unknown }).text;
      if (typeof text === 'string') parts.push(text);
    } else {
      parts.push(`[${String((item as { type?: unknown })?.type ?? 'unknown')} 内容]`);
    }
  }
  return parts.join('\n');
}
