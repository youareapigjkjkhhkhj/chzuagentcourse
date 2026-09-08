/**
 * McpPool 集成测试（P5 验收：启用即连接 / Tools 发现 / 包装调用 / 崩溃离线 / 重连恢复 / 启停）。
 * 使用真实官方 SDK server 夹具（tests/fixtures/mcpEchoServer.mjs，stdio 子进程）。
 */
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { McpServerConfig, McpStatus } from '@agentbuddy/shared';
import { McpConfigStore } from '../src/mcp/configStore';
import { McpPool, mcpDisplayName, mcpToolName } from '../src/mcp/pool';
import type { ToolContext } from '../src/tools/types';
import { ReadState } from '../src/tools/types';

const FIXTURE = fileURLToPath(new URL('./fixtures/mcpEchoServer.mjs', import.meta.url));

const ECHO_CFG: McpServerConfig = {
  name: 'echo', type: 'stdio',
  command: process.execPath,
  args: [FIXTURE],
  env: { ECHO_PROBE: '${AB_TEST_MCP_VAR}' },
  description: '回显测试连接器',
  enabled: true,
};

const ctx: ToolContext = {
  workspace: null,
  signal: new AbortController().signal,
  readState: new ReadState(),
  snapshot: async () => null,
  resolvePath: async (p) => p,
};

/** 轮询等待状态到位（事件驱动在生产层；测试侧轮询断言最终一致） */
async function waitForStatus(pool: McpPool, name: string, status: McpStatus, timeoutMs = 15_000): Promise<void> {
  const start = Date.now();
  for (;;) {
    const view = pool.views().find((v) => v.config.name === name);
    if (view?.status === status) return;
    if (Date.now() - start > timeoutMs) {
      throw new Error(`等待 ${name} → ${status} 超时（当前 ${view?.status ?? '不存在'}：${view?.error ?? ''}）`);
    }
    await new Promise((r) => setTimeout(r, 200));
  }
}

describe('McpPool 集成（真实 stdio server）', () => {
  let dir: string;
  let pool: McpPool;
  const viewEvents: number[] = [];

  beforeAll(async () => {
    dir = await mkdtemp(join(tmpdir(), 'mcp-pool-'));
    process.env['AB_TEST_MCP_VAR'] = 'probe-ok-42';
    pool = new McpPool({
      store: new McpConfigStore(join(dir, 'mcp.json')),
      onViews: (views) => viewEvents.push(views.length),
    });
    await pool.init();
    await pool.upsert(ECHO_CFG);
    await waitForStatus(pool, 'echo', 'connected');
  });

  afterAll(async () => {
    await pool.closeAll();
    delete process.env['AB_TEST_MCP_VAR'];
    await rm(dir, { recursive: true, force: true });
  });

  it('启用即连接 + Tools 发现（4 个工具）+ 状态广播', () => {
    const view = pool.views().find((v) => v.config.name === 'echo');
    expect(view?.status).toBe('connected');
    expect(view?.tools.map((t) => t.name).sort()).toEqual(['crash', 'envprobe', 'failing', 'ping']);
    expect(viewEvents.length).toBeGreaterThan(0); // onViews 事件驱动广播
  });

  it('sessionTools 包装：mcp__{server}__{tool} + risk=NETWORK + 调用回显', async () => {
    const tools = pool.sessionTools();
    const ping = tools.find((t) => t.name === 'mcp__echo__ping');
    expect(ping).toBeTruthy();
    expect(ping?.risk).toBe('NETWORK');
    const res = await ping!.execute(ctx, { text: 'hello' });
    expect(res.text).toBe('pong: hello');
  });

  it('env ${VAR} 占位注入子进程（envprobe 读到解析后的值）', async () => {
    const probe = pool.sessionTools().find((t) => t.name === 'mcp__echo__envprobe');
    const res = await probe!.execute(ctx, {});
    expect(res.text).toBe('probe-ok-42');
  });

  it('catalog 仅含已连接连接器（# 提及目录素材）', () => {
    const catalog = pool.catalog();
    expect(catalog).toHaveLength(1);
    expect(catalog[0]?.name).toBe('echo');
    expect(catalog[0]?.tools).toContain('ping');
  });

  it('server 返回 isError → 包装工具抛错（供熔断回灌）', async () => {
    const failing = pool.sessionTools().find((t) => t.name === 'mcp__echo__failing');
    await expect(failing!.execute(ctx, {})).rejects.toThrow('工具报告了错误');
  });

  it('崩溃 → 标离线、工具清空；重连恢复（P5 验收）', async () => {
    const crash = pool.sessionTools().find((t) => t.name === 'mcp__echo__crash');
    const res = await crash!.execute(ctx, {}); // 结果先回传，随后进程退出
    expect(res.text).toBe('即将崩溃');
    await waitForStatus(pool, 'echo', 'offline');
    const offline = pool.views().find((v) => v.config.name === 'echo');
    expect(offline?.error).toBeTruthy();
    expect(pool.sessionTools()).toHaveLength(0); // 离线不影响内置工具，MCP 工具清空

    await pool.reconnect('echo');
    await waitForStatus(pool, 'echo', 'connected');
    expect(pool.sessionTools().length).toBe(4);
  });

  it('setEnabled(false) → 断开并标 disabled；再启用自动重连', async () => {
    await pool.setEnabled('echo', false);
    expect(pool.views().find((v) => v.config.name === 'echo')?.status).toBe('disabled');
    expect(pool.sessionTools()).toHaveLength(0);
    await pool.setEnabled('echo', true);
    await waitForStatus(pool, 'echo', 'connected');
    expect(pool.sessionTools().length).toBe(4);
  });

  it('env 占位变量缺失 → 离线并仅提示变量名', async () => {
    delete process.env['AB_TEST_MCP_VAR'];
    try {
      await pool.reconnect('echo');
      await waitForStatus(pool, 'echo', 'offline');
      const view = pool.views().find((v) => v.config.name === 'echo');
      expect(view?.error).toContain('AB_TEST_MCP_VAR');
      expect(view?.error).not.toContain('probe-ok-42'); // 绝不泄露值
    } finally {
      process.env['AB_TEST_MCP_VAR'] = 'probe-ok-42';
      await pool.reconnect('echo');
      await waitForStatus(pool, 'echo', 'connected');
    }
  });
});

describe('McpPool HTTP 传输（进程内 Streamable HTTP server）', () => {
  let dir: string;
  let pool: McpPool;
  let httpServer: import('node:http').Server;
  let baseUrl = '';
  let lastAuthHeader: string | undefined;

  beforeAll(async () => {
    const { createServer } = await import('node:http');
    const { Server: McpServer } = await import('@modelcontextprotocol/sdk/server/index.js');
    const { StreamableHTTPServerTransport } = await import('@modelcontextprotocol/sdk/server/streamableHttp.js');
    const { ListToolsRequestSchema, CallToolRequestSchema } = await import('@modelcontextprotocol/sdk/types.js');

    const makeServer = () => {
      // 无会话（stateless）模式：每个请求独立 server + transport
      const s = new McpServer({ name: 'http-echo', version: '0.0.1' }, { capabilities: { tools: {} } });
      s.setRequestHandler(ListToolsRequestSchema, async () => ({
        tools: [{ name: 'ping', description: 'http 回显', inputSchema: { type: 'object', properties: { text: { type: 'string' } }, required: ['text'] } }],
      }));
      s.setRequestHandler(CallToolRequestSchema, async (req) => {
        const text = String((req.params.arguments ?? {})['text'] ?? '');
        return { content: [{ type: 'text', text: `http-pong: ${text}` }] };
      });
      return s;
    };

    httpServer = createServer(async (req, res) => {
      lastAuthHeader = req.headers['authorization'];
      const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
      await makeServer().connect(transport);
      await transport.handleRequest(req, res);
    });
    await new Promise<void>((resolve) => httpServer.listen(0, '127.0.0.1', resolve));
    const addr = httpServer.address();
    baseUrl = `http://127.0.0.1:${typeof addr === 'object' && addr ? addr.port : 0}/mcp`;

    dir = await mkdtemp(join(tmpdir(), 'mcp-pool-http-'));
    pool = new McpPool({ store: new McpConfigStore(join(dir, 'mcp.json')) });
    await pool.init();
  });

  afterAll(async () => {
    await pool.closeAll();
    await new Promise<void>((resolve) => httpServer.close(() => resolve()));
    await rm(dir, { recursive: true, force: true });
  });

  it('http 连接器：连接 + Tools 发现 + 调用 + headers 注入', async () => {
    await pool.upsert({
      name: 'cocos', type: 'http', url: baseUrl,
      headers: { Authorization: 'Bearer tok-123' },
      description: 'Streamable HTTP 测试', enabled: true,
    });
    await waitForStatus(pool, 'cocos', 'connected');
    const view = pool.views().find((v) => v.config.name === 'cocos');
    expect(view?.tools.map((t) => t.name)).toEqual(['ping']);

    const ping = pool.sessionTools().find((t) => t.name === 'mcp__cocos__ping');
    expect(ping).toBeTruthy();
    const res = await ping!.execute(ctx, { text: 'yo' });
    expect(res.text).toBe('http-pong: yo');
    expect(lastAuthHeader).toBe('Bearer tok-123'); // 自定义请求头随连接下发
  });

  it('http 连接不可达 → 标离线并带错误文案（不崩溃）', async () => {
    await pool.upsert({ name: 'down', type: 'http', url: 'http://127.0.0.1:1/mcp', enabled: true });
    await waitForStatus(pool, 'down', 'offline', 30_000);
    const view = pool.views().find((v) => v.config.name === 'down');
    expect(view?.error).toBeTruthy();
    await pool.remove('down');
  });
});

describe('mcpToolName / mcpDisplayName（命名消毒与展示映射）', () => {
  it('非法字符消毒为 _，总长 ≤ 64', () => {
    expect(mcpToolName('github', 'create issue!')).toBe('mcp__github__create_issue_');
    const long = mcpToolName('s', 'x'.repeat(200));
    expect(long.length).toBeLessThanOrEqual(64);
  });

  it('展示名映射：mcp__github__create_issue → github / create_issue', () => {
    expect(mcpDisplayName('mcp__github__create_issue')).toBe('github / create_issue');
    expect(mcpDisplayName('read')).toBe('read'); // 非 MCP 工具原样
  });
});
