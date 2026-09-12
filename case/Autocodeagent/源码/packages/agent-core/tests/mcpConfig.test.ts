/**
 * McpConfigStore 单测（P5 任务 1 / 6）：
 * upsert/load/remove/setEnabled 往返；importJson 双格式兼容、行级报错整体拒绝（0/N 写入）、
 * enabled 缺省 true / 显式 false 保持、command→stdio、url→sse。
 */
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import type { McpServerConfig } from '@agentbuddy/shared';
import { McpConfigStore } from '../src/mcp/configStore';

let dir: string;
let store: McpConfigStore;

const STDIO_CFG: McpServerConfig = {
  name: 'github', type: 'stdio', command: 'npx', args: ['-y', 'github-mcp'],
  env: { TOKEN: '${GITHUB_TOKEN}' }, description: 'GitHub 连接器', enabled: true,
};

beforeEach(async () => {
  dir = await mkdtemp(join(tmpdir(), 'mcp-cfg-'));
  store = new McpConfigStore(join(dir, 'mcp.json'));
});

afterEach(async () => {
  await rm(dir, { recursive: true, force: true });
});

describe('upsert / load / remove / setEnabled', () => {
  it('upsert 后 load 往返一致；同名覆盖', async () => {
    await store.upsert(STDIO_CFG);
    expect(await store.load()).toEqual({ github: STDIO_CFG });
    // 同名覆盖（改描述）
    await store.upsert({ ...STDIO_CFG, description: '新描述' });
    expect((await store.load())['github']?.description).toBe('新描述');
    expect(Object.keys(await store.load())).toHaveLength(1);
  });

  it('stdio 缺 command 拒绝写入', async () => {
    await expect(store.upsert({ name: 'x', type: 'stdio', enabled: true })).rejects.toThrow('command');
    expect(await store.load()).toEqual({});
  });

  it('http / sse 缺 url 拒绝写入', async () => {
    await expect(store.upsert({ name: 'x', type: 'http', enabled: true })).rejects.toThrow('url');
    await expect(store.upsert({ name: 'y', type: 'sse', enabled: true })).rejects.toThrow('url');
    expect(await store.load()).toEqual({});
  });

  it('remove 删除已有；不存在抛错', async () => {
    await store.upsert(STDIO_CFG);
    await store.remove('github');
    expect(await store.load()).toEqual({});
    await expect(store.remove('github')).rejects.toThrow('不存在');
  });

  it('setEnabled 持久化启停状态', async () => {
    await store.upsert(STDIO_CFG);
    const disabled = await store.setEnabled('github', false);
    expect(disabled.enabled).toBe(false);
    expect((await store.load())['github']?.enabled).toBe(false);
  });

  it('setAlwaysLoad 持久化强制常驻标志；upsert 往返不丢失 alwaysLoad', async () => {
    await store.upsert(STDIO_CFG);
    const on = await store.setAlwaysLoad('github', true);
    expect(on.alwaysLoad).toBe(true);
    expect((await store.load())['github']?.alwaysLoad).toBe(true); // ServerConfigSchema 未 strip
    await store.upsert({ ...STDIO_CFG, alwaysLoad: true }); // 表单通道携带 alwaysLoad 往返一致
    expect((await store.load())['github']?.alwaysLoad).toBe(true);
    await store.setAlwaysLoad('github', false);
    expect((await store.load())['github']?.alwaysLoad).toBe(false);
  });

  it('load：文件缺失返回空映射；单条损坏跳过不阻塞其余', async () => {
    expect(await store.load()).toEqual({});
    await store.upsert(STDIO_CFG);
    const raw = JSON.parse(await readFile(join(dir, 'mcp.json'), 'utf-8'));
    raw.mcpServers['broken'] = { type: 'stdio', enabled: true }; // 缺 command
    const { writeFile } = await import('node:fs/promises');
    await writeFile(join(dir, 'mcp.json'), JSON.stringify(raw), 'utf-8');
    const loaded = await store.load();
    expect(Object.keys(loaded)).toEqual(['github']);
  });
});

describe('importJson', () => {
  it('Claude Desktop 完整格式（mcpServers 外层）', async () => {
    const text = JSON.stringify({
      mcpServers: {
        github: { command: 'npx', args: ['-y', 'github-mcp'], env: { TOKEN: '${GITHUB_TOKEN}' } },
      },
    });
    const imported = await store.importJson(text);
    expect(imported).toHaveLength(1);
    expect(imported[0]).toMatchObject({ name: 'github', type: 'stdio', command: 'npx', enabled: true });
    expect(imported[0]?.args).toEqual(['-y', 'github-mcp']);
  });

  it('内层对象格式（无 mcpServers 外层）', async () => {
    const text = JSON.stringify({ myserver: { command: 'node', args: ['srv.js'] } });
    const imported = await store.importJson(text);
    expect(imported[0]?.name).toBe('myserver');
    expect(imported[0]?.type).toBe('stdio');
  });

  it('url → sse 类型；enabled:false 显式保持、缺省默认 true', async () => {
    const text = JSON.stringify({
      mcpServers: {
        remote: { url: 'https://example.com/mcp', enabled: false },
        other: { command: 'node' },
      },
    });
    const imported = await store.importJson(text);
    expect(imported.find((c) => c.name === 'remote')).toMatchObject({ type: 'sse', url: 'https://example.com/mcp', enabled: false });
    expect(imported.find((c) => c.name === 'other')?.enabled).toBe(true);
  });

  it('alwaysLoad 字段透传（导入即强制常驻）；缺省为 false', async () => {
    const imported = await store.importJson(JSON.stringify({
      mcpServers: { gfx: { command: 'node', args: ['s.js'], alwaysLoad: true }, other: { command: 'node' } },
    }));
    expect(imported.find((c) => c.name === 'gfx')?.alwaysLoad).toBe(true);
    expect(imported.find((c) => c.name === 'other')?.alwaysLoad).toBe(false);
  });

  it('transport: http 字段 → http 类型（Cocos Creator / 主流网关格式）', async () => {
    const text = JSON.stringify({
      mcpServers: {
        'cocos-creator': { url: 'http://127.0.0.1:3000/mcp', transport: 'http' },
      },
    });
    const imported = await store.importJson(text);
    expect(imported[0]).toMatchObject({ name: 'cocos-creator', type: 'http', url: 'http://127.0.0.1:3000/mcp', enabled: true });
  });

  it('transport 别名 streamable-http → http；未知传输类型行级报错', async () => {
    const ok = await store.importJson(JSON.stringify({ s1: { url: 'https://a.b/mcp', transport: 'streamable-http' } }));
    expect(ok[0]?.type).toBe('http');
    await expect(
      store.importJson(JSON.stringify({ s2: { url: 'https://a.b/mcp', transport: 'carrier-pigeon' } })),
    ).rejects.toThrow('未知传输类型');
  });

  it('headers 字段解析透传；非字符串值行级报错', async () => {
    const imported = await store.importJson(JSON.stringify({
      mcpServers: { auth: { url: 'https://a.b/mcp', transport: 'http', headers: { Authorization: 'Bearer ${TOKEN}' } } },
    }));
    expect(imported[0]?.headers).toEqual({ Authorization: 'Bearer ${TOKEN}' });
    await expect(
      store.importJson(JSON.stringify({ mcpServers: { bad: { url: 'https://a.b', transport: 'http', headers: { A: 1 } } } })),
    ).rejects.toThrow('headers.A 必须为字符串');
  });

  it('单条配置对象（市场复制格式：name/type/command/args 平铺）自动包装导入', async () => {
    const text = JSON.stringify({
      name: 'web-search', type: 'stdio', command: 'uvx',
      args: ['--with', 'mcp==1.27.1', 'heventure-search-mcp'],
    });
    const imported = await store.importJson(text);
    expect(imported).toHaveLength(1);
    expect(imported[0]).toMatchObject({
      name: 'web-search', type: 'stdio', command: 'uvx', enabled: true,
    });
    expect(imported[0]?.args).toEqual(['--with', 'mcp==1.27.1', 'heventure-search-mcp']);
  });

  it('单条配置缺 name → 明确提示（不误报为映射格式）', async () => {
    await expect(store.importJson(JSON.stringify({ command: 'uvx', args: [] }))).rejects.toThrow('缺少 name');
  });

  it('任一行非法 → 汇总行级报错整体拒绝（0/N 写入，文件未变）', async () => {
    await store.upsert(STDIO_CFG);
    const before = await readFile(join(dir, 'mcp.json'), 'utf-8');
    const text = JSON.stringify({
      mcpServers: {
        good: { command: 'node' },
        'bad name!': { command: 'node' },
        nocmd: {},
      },
    });
    await expect(store.importJson(text)).rejects.toThrow('0/3');
    await expect(store.importJson(text)).rejects.toThrow('bad name!');
    await expect(store.importJson(text)).rejects.toThrow('nocmd');
    // 半截拒绝：文件内容与导入前完全一致
    expect(await readFile(join(dir, 'mcp.json'), 'utf-8')).toBe(before);
  });

  it('非法 JSON / 顶层非对象抛错', async () => {
    await expect(store.importJson('{oops')).rejects.toThrow('JSON 解析失败');
    await expect(store.importJson('[1,2]')).rejects.toThrow('顶层必须为对象');
  });

  it('导入同名覆盖既有配置', async () => {
    await store.upsert(STDIO_CFG);
    await store.importJson(JSON.stringify({ github: { command: 'uvx', args: ['gh'] } }));
    const loaded = await store.load();
    expect(loaded['github']?.command).toBe('uvx');
  });
});
