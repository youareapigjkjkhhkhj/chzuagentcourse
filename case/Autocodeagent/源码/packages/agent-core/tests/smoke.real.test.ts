/**
 * 真模型冒烟（P1 验收：1 次完整修 bug 流程）。
 * 门控运行：仅当 SMOKE_BASE_URL / SMOKE_API_KEY 存在时执行，
 * 例：$env:SMOKE_BASE_URL='https://api.chatanywhere.tech'; npx vitest run tests/smoke.real.test.ts
 */
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import type { ChatMessage, ModelConfig, StreamEvent } from '@agentbuddy/shared';
import { Checkpoint } from '../src/checkpoint';
import { LlmClient } from '../src/llm/client';
import { runTurn, type TurnDeps } from '../src/orchestrator';
import { PermissionGate } from '../src/permission';
import { SkillHub } from '../src/skills';
import { McpConfigStore } from '../src/mcp/configStore';
import { McpPool } from '../src/mcp/pool';
import { buildSessionBus, createBuiltinBus } from '../src/tools/bus';
import { ReadState } from '../src/tools/types';

const hasCreds = Boolean(process.env['SMOKE_BASE_URL'] && process.env['SMOKE_API_KEY']);

describe.skipIf(!hasCreds)('真模型冒烟：gpt-5-mini 修 bug 全流程', () => {
  it(
    'read → edit → 收尾（tool_calls 真实往返 + 权限自动放行）',
    async () => {
      const ws = await mkdtemp(join(tmpdir(), 'smoke-ws-'));
      const dataDir = await mkdtemp(join(tmpdir(), 'smoke-data-'));
      await mkdir(join(ws, 'src'), { recursive: true });
      await writeFile(join(ws, 'src', 'calc.js'), 'function add(a, b) {\n  return a - b; // BUG\n}\nmodule.exports = { add };\n');

      const config: ModelConfig = {
        id: 'smoke', name: 'smoke', provider: 'openai',
        baseUrl: process.env['SMOKE_BASE_URL']!,
        model: process.env['SMOKE_MODEL'] ?? 'gpt-5-mini',
        apiKey: process.env['SMOKE_API_KEY']!,
        encrypted: false, temperature: 0.2, maxTokens: 4096, contextWindow: 128000,
      };

      const events: StreamEvent[] = [];
      const persisted: ChatMessage[] = [];
      const dep: TurnDeps = {
        sessionId: 'smoke',
        messages: [{
          id: 'u1', role: 'user', createdAt: Date.now(),
          content: 'src/calc.js 里 add 函数有 bug：本应返回 a + b 却写成了 a - b。请先 read 该文件，再用 edit 工具把错误修正，最后用一句话总结。',
        }],
        client: new LlmClient(config),
        config,
        bus: createBuiltinBus(),
        gate: new PermissionGate('Ask', async () => ({ allow: true, remember: false })),
        checkpoint: new Checkpoint(dataDir),
        readState: new ReadState(),
        workspace: ws,
        workspaceRoots: [ws],
        signal: new AbortController().signal,
        emit: (e) => events.push(e),
        persist: async (m) => { persisted.push(m); },
      };

      await runTurn(dep);

      const fixed = await readFile(join(ws, 'src', 'calc.js'), 'utf-8');
      expect(fixed).toContain('a + b'); // 真实修改落盘
      expect(persisted.some((m) => m.role === 'tool' && m.toolName === 'read')).toBe(true);
      expect(persisted.some((m) => m.role === 'tool' && m.toolName === 'edit')).toBe(true);
      expect(events.some((e) => e.type === 'tool_start')).toBe(true);
      // P2：edit 成功 → diff_ready 事件 + tool 消息落 toolChangeId（右栏审阅入口）
      expect(events.some((e) => e.type === 'diff_ready')).toBe(true);
      expect(persisted.some((m) => m.role === 'tool' && m.toolName === 'edit' && m.toolChangeId)).toBe(true);
      expect(dep.messages.at(-1)?.role).toBe('assistant');

      await rm(ws, { recursive: true, force: true });
      await rm(dataDir, { recursive: true, force: true });
    },
    180_000,
  );
});

describe.skipIf(!hasCreds)('真模型冒烟：P4 /review 技能触发', () => {
  it(
    '/review 注入后回复遵循技能正文的审查清单结构',
    async () => {
      const ws = await mkdtemp(join(tmpdir(), 'smoke4-ws-'));
      const dataDir = await mkdtemp(join(tmpdir(), 'smoke4-data-'));
      await mkdir(join(ws, 'src'), { recursive: true });
      // 含明显问题的待审代码：除零风险 + 硬编码密钥 + 无测试
      await writeFile(
        join(ws, 'src', 'pay.js'),
        'const SECRET = "sk-live-abcdef123456";\nfunction split(a, b) {\n  return a / b;\n}\nmodule.exports = { split, SECRET };\n',
      );

      const config: ModelConfig = {
        id: 'smoke', name: 'smoke', provider: 'openai',
        baseUrl: process.env['SMOKE_BASE_URL']!,
        model: process.env['SMOKE_MODEL'] ?? 'gpt-5-mini',
        apiKey: process.env['SMOKE_API_KEY']!,
        encrypted: false, temperature: 0.2, maxTokens: 4096, contextWindow: 128000,
      };

      // 与 main 一致的装配：播种内置技能 → 目录注入 + /review 正文高优先级指令
      let disabled: string[] = [];
      const hub = new SkillHub({
        globalDir: join(dataDir, 'skills'),
        projectDir: () => ws,
        getDisabled: async () => disabled,
        setDisabled: async (d) => { disabled = d; },
      });
      await hub.seed();
      const got = await hub.get('review');
      expect(got).toBeTruthy();

      const events: StreamEvent[] = [];
      const persisted: ChatMessage[] = [];
      const dep: TurnDeps = {
        sessionId: 'smoke4',
        messages: [{ id: 'u1', role: 'user', createdAt: Date.now(), content: '/review 审查 src/pay.js' }],
        client: new LlmClient(config),
        config,
        bus: createBuiltinBus(),
        gate: new PermissionGate('Plan', async () => ({ allow: true, remember: false })),
        checkpoint: new Checkpoint(dataDir),
        readState: new ReadState(),
        workspace: ws,
        workspaceRoots: [ws],
        signal: new AbortController().signal,
        emit: (e) => events.push(e),
        persist: async (m) => { persisted.push(m); },
        skillCatalog: await hub.catalog(),
        skillInstruction: got!.body,
      };

      await runTurn(dep);

      const reply = persisted.filter((m) => m.role === 'assistant').map((m) => m.content).join('\n');
      // 技能正文约束：总体结论 + 问题清单 + 优先修复，四节清单至少命中主要项（容忍措辞微调）
      expect(reply).toContain('总体结论');
      expect(reply).toMatch(/正确性/);
      expect(reply).toMatch(/安全/);
      expect(reply).toMatch(/优先修复|Top\s*3/i);
      // 真实读了待审文件（只读工具）
      expect(persisted.some((m) => m.role === 'tool' && m.toolName === 'read')).toBe(true);
      expect(events.some((e) => e.type === 'tool_start')).toBe(true);
      // Plan 模式：不产生任何写操作（无 edit/write 落盘）
      expect(persisted.some((m) => m.role === 'tool' && (m.toolName === 'edit' || m.toolName === 'write') && m.toolOk)).toBe(false);

      await rm(ws, { recursive: true, force: true });
      await rm(dataDir, { recursive: true, force: true });
    },
    180_000,
  );
});

describe.skipIf(!hasCreds)('真模型冒烟：P5 MCP 工具调用（#echo 提及 + NETWORK 权限放行）', () => {
  it(
    '#echo 提及 → 模型调用 mcp__echo__ping → 工具结果回灌并总结',
    async () => {
      const ws = await mkdtemp(join(tmpdir(), 'smoke5-ws-'));
      const dataDir = await mkdtemp(join(tmpdir(), 'smoke5-data-'));

      // 真实 stdio server 夹具（官方 SDK）
      const fixture = fileURLToPath(new URL('./fixtures/mcpEchoServer.mjs', import.meta.url));
      const pool = new McpPool({ store: new McpConfigStore(join(dataDir, 'mcp.json')) });
      await pool.init();
      await pool.upsert({
        name: 'echo', type: 'stdio', command: process.execPath, args: [fixture],
        description: '回显测试连接器', enabled: true,
      });
      const start = Date.now();
      while (pool.views().find((v) => v.config.name === 'echo')?.status !== 'connected') {
        if (Date.now() - start > 15_000) throw new Error('MCP 连接器未能在 15s 内连上');
        await new Promise((r) => setTimeout(r, 200));
      }

      const config: ModelConfig = {
        id: 'smoke', name: 'smoke', provider: 'openai',
        baseUrl: process.env['SMOKE_BASE_URL']!,
        model: process.env['SMOKE_MODEL'] ?? 'gpt-5-mini',
        apiKey: process.env['SMOKE_API_KEY']!,
        encrypted: false, temperature: 0.2, maxTokens: 4096, contextWindow: 128000,
      };

      const bus = buildSessionBus(pool.sessionTools());
      expect(bus.get('mcp__echo__ping')).toBeTruthy();

      const events: StreamEvent[] = [];
      const persisted: ChatMessage[] = [];
      const dep: TurnDeps = {
        sessionId: 'smoke5',
        messages: [{
          id: 'u1', role: 'user', createdAt: Date.now(),
          content: '#echo 请调用 echo 连接器的 ping 工具，text 参数传 "mcp-smoke"，然后用一句话告诉我结果。',
        }],
        client: new LlmClient(config),
        config,
        bus,
        gate: new PermissionGate('Ask', async () => ({ allow: true, remember: false })),
        checkpoint: new Checkpoint(dataDir),
        readState: new ReadState(),
        workspace: ws,
        workspaceRoots: [ws],
        signal: new AbortController().signal,
        emit: (e) => events.push(e),
        persist: async (m) => { persisted.push(m); },
        mcpCatalog: pool.catalog(),
      };

      await runTurn(dep);

      // MCP 工具真实往返：包装名落盘 + 结果回灌；risk=NETWORK 经权限放行后执行
      const mcpTool = persisted.find((m) => m.role === 'tool' && m.toolName?.startsWith('mcp__echo__'));
      expect(mcpTool).toBeTruthy();
      expect(mcpTool?.toolOk).toBe(true);
      expect(mcpTool?.content).toContain('pong');
      expect(events.some((e) => e.type === 'tool_start')).toBe(true);
      expect(dep.messages.at(-1)?.role).toBe('assistant');

      await pool.closeAll();
      await rm(ws, { recursive: true, force: true });
      await rm(dataDir, { recursive: true, force: true });
    },
    180_000,
  );
});
