/**
 * P7 专家团：ExpertStore 持久化（正常/异常/边界）+ buildSessionBus 专家绑定过滤 + persona 注入 + 会话 expertId 绑定。
 */
import { mkdtemp, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { ExpertUpsertPayload } from '@agentbuddy/shared';
import { ExpertStore } from '../src/experts';
import { buildSessionBus } from '../src/tools/bus';
import { systemPrompt } from '../src/context';
import { SessionStore } from '../src/store/sessionStore';
import type { Tool } from '../src/tools/types';

function fakeMcpTool(server: string, tool: string): Tool {
  return {
    name: `mcp__${server}__${tool}`,
    description: `假工具 ${server}/${tool}`,
    parameters: { type: 'object', properties: {} },
    risk: 'NETWORK',
    execute: async () => ({ text: '' }),
  };
}

const baseForm = {
  name: '代码审查专家',
  emoji: '🧐',
  description: '只读审查工作区代码',
  tags: ['代码审查', '安全审计'],
  persona: '你是资深代码审查专家，只读分析，不改文件。',
  tools: ['read', 'grep', 'glob'],
  skills: ['review'],
};

async function tempStore(): Promise<ExpertStore> {
  const dir = await mkdtemp(join(tmpdir(), 'agentbuddy-experts-'));
  const store = new ExpertStore(dir);
  await store.init();
  return store;
}

describe('ExpertStore 持久化', () => {
  it('初始为空清单', async () => {
    const store = await tempStore();
    expect(await store.list()).toEqual([]);
  });

  it('新建：无 id → 生成 id + 时间戳，落盘后可读回', async () => {
    const store = await tempStore();
    const created = await store.upsert(baseForm);
    expect(created.id).toBeTruthy();
    expect(created.createdAt).toBeGreaterThan(0);
    expect(await store.get(created.id)).toEqual(created);
    expect(await store.list()).toHaveLength(1);
  });

  it('编辑：有 id → 覆盖字段并保留 createdAt，刷新 updatedAt', async () => {
    const store = await tempStore();
    const created = await store.upsert(baseForm);
    const updated = await store.upsert({ ...baseForm, id: created.id, name: '安全审计专家', tools: ['read'] });
    expect(updated.id).toBe(created.id);
    expect(updated.name).toBe('安全审计专家');
    expect(updated.tools).toEqual(['read']);
    expect(updated.createdAt).toBe(created.createdAt);
    expect(await store.list()).toHaveLength(1);
  });

  it('异常：编辑不存在的 id / 删除不存在的 id 均抛错', async () => {
    const store = await tempStore();
    await expect(store.upsert({ ...baseForm, id: 'ghost' })).rejects.toThrow('专家不存在');
    await expect(store.remove('ghost')).rejects.toThrow('专家不存在');
  });

  it('删除后清单收敛', async () => {
    const store = await tempStore();
    const a = await store.upsert(baseForm);
    await store.upsert({ ...baseForm, name: '测试工程师', emoji: '🧪' });
    await store.remove(a.id);
    const rest = await store.list();
    expect(rest).toHaveLength(1);
    expect(rest[0]!.name).toBe('测试工程师');
  });

  it('边界：文件损坏 / 混入非法条目 → 跳过非法项不击穿读取', async () => {
    const dir = await mkdtemp(join(tmpdir(), 'agentbuddy-experts-'));
    const store = new ExpertStore(dir);
    await store.init();
    const good = await store.upsert(baseForm);
    const file = join(dir, 'experts.json');
    // 正常数组中混入非法条目（缺 name / 字符串）与合法条目 → 仅合法项读回
    await writeFile(file, JSON.stringify([{ emoji: '🧪' }, good, 'junk']), 'utf-8');
    const list = await store.list();
    expect(list).toHaveLength(1);
    expect(list[0]!.id).toBe(good.id);
    // 整个文件非法 JSON → 空清单
    await writeFile(file, '{broken', 'utf-8');
    expect(await store.list()).toEqual([]);
  });
});

describe('ExpertUpsertPayload zod 校验（§23 同一 schema）', () => {
  it('合法表单通过', () => {
    expect(ExpertUpsertPayload.safeParse(baseForm).success).toBe(true);
  });

  it('logo 非 data:image/* 拒绝；合法 data URL 通过', () => {
    expect(ExpertUpsertPayload.safeParse({ ...baseForm, logo: 'http://evil/x.png' }).success).toBe(false);
    expect(ExpertUpsertPayload.safeParse({ ...baseForm, logo: 'data:image/png;base64,AAA' }).success).toBe(true);
  });

  it('边界：name 空 / tags 超 8 个 / persona 超 20000 字符均拒绝', () => {
    expect(ExpertUpsertPayload.safeParse({ ...baseForm, name: '' }).success).toBe(false);
    expect(ExpertUpsertPayload.safeParse({ ...baseForm, tags: Array.from({ length: 9 }, (_, i) => `t${i}`) }).success).toBe(false);
    expect(ExpertUpsertPayload.safeParse({ ...baseForm, persona: 'x'.repeat(20001) }).success).toBe(false);
  });
});

describe('buildSessionBus 专家绑定过滤', () => {
  const mcpTools = [fakeMcpTool('github', 'create_issue'), fakeMcpTool('echo', 'ping')];

  it('allow 缺省 / 空数组 = 不限定（内置 9 + MCP 全量）', () => {
    expect(buildSessionBus(mcpTools).names()).toHaveLength(11);
    expect(buildSessionBus(mcpTools, []).names()).toHaveLength(11);
  });

  it('绑定内置子集：只注册命中项 + todo_write / remember 始终保留', () => {
    const bus = buildSessionBus([], ['read', 'grep']);
    expect(bus.names().sort()).toEqual(['grep', 'read', 'remember', 'todo_write']);
    expect(bus.get('bash')).toBeUndefined();
  });

  it('mcp:连接器名 命中该连接器全部工具，未命中的连接器被过滤', () => {
    const bus = buildSessionBus(mcpTools, ['read', 'mcp:github']);
    expect(bus.get('mcp__github__create_issue')).toBeTruthy();
    expect(bus.get('mcp__echo__ping')).toBeUndefined();
    expect(bus.get('read')).toBeTruthy();
  });

  it('绑定 mcp:echo 时未命中的 srv 工具全部过滤（内置仅留 todo_write / remember）', () => {
    const many = Array.from({ length: 50 }, (_, i) => fakeMcpTool('srv', `t${i}`));
    const bus = buildSessionBus(many, ['mcp:echo']);
    expect(bus.names()).toEqual(['todo_write', 'remember']); // 内置全部未命中被过滤，todo_write / remember 始终保留；srv 工具未命中 mcp:echo 也全过滤
  });
});

describe('systemPrompt 专家人设注入', () => {
  it('persona 追加到系统提示', () => {
    const prompt = systemPrompt(null, 'm', null, 'Ask', undefined, undefined, undefined, undefined, '你是安全审计专家');
    expect(prompt).toContain('专家人设');
    expect(prompt).toContain('你是安全审计专家');
  });

  it('persona 缺省 / 空串不注入该段', () => {
    expect(systemPrompt(null, 'm', null)).not.toContain('专家人设');
    expect(systemPrompt(null, 'm', null, 'Ask', undefined, undefined, undefined, undefined, '')).not.toContain('专家人设');
  });
});

describe('SessionStore expertId 绑定', () => {
  it('create 带 expertId → meta 落盘携带；缺省不写该字段', async () => {
    const dir = await mkdtemp(join(tmpdir(), 'agentbuddy-sessions-'));
    const sessions = new SessionStore(dir);
    await sessions.init();
    const expertSession = await sessions.create('代码审查专家', 'expert-1');
    const normal = await sessions.create('新会话');
    expect(expertSession.expertId).toBe('expert-1');
    expect(normal.expertId).toBeUndefined();
    const metas = await sessions.list();
    expect(metas.find((m) => m.id === expertSession.id)?.expertId).toBe('expert-1');
    // 重新读盘（绕开缓存路径由 get 内部处理）后仍在
    expect((await sessions.get(expertSession.id))?.expertId).toBe('expert-1');
  });
});
