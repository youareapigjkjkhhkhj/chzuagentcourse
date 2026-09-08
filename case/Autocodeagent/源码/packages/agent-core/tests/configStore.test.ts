/** ConfigStore 多模型配置单测：列表 / upsert / 激活切换 / 删除保护 / 旧格式迁移 */
import { mkdtemp, readFile, rm, writeFile, mkdir } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { ModelConfig } from '@agentbuddy/shared';
import { ConfigStore, DEFAULT_MODEL_CONFIG } from '../src/store/configStore';

let dir: string;
let store: ConfigStore;

function model(over: Partial<ModelConfig>): ModelConfig {
  return { ...DEFAULT_MODEL_CONFIG, id: over.id ?? 'm1', ...over };
}

beforeAll(async () => {
  dir = await mkdtemp(join(tmpdir(), 'cfg-'));
  store = new ConfigStore(dir);
  await store.init();
});

afterAll(async () => {
  await rm(dir, { recursive: true, force: true });
});

describe('ConfigStore 多模型', () => {
  it('首次读取给出默认单配置，且 get() 返回激活项', async () => {
    const list = await store.list();
    expect(list.length).toBe(1);
    const active = await store.get();
    expect(active.id).toBe(list[0]?.id);
  });

  it('upsert 新增后出现在列表；首个配置自动激活', async () => {
    await store.upsert(model({ id: 'a', name: '模型A' }));
    await store.upsert(model({ id: 'b', name: '模型B' }));
    const list = await store.list();
    expect(list.map((m) => m.id)).toContain('a');
    expect(list.map((m) => m.id)).toContain('b');
  });

  it('setActive 切换后 get() 返回新激活配置', async () => {
    await store.setActive('b');
    expect((await store.get()).id).toBe('b');
    await expect(store.setActive('不存在')).rejects.toThrow(/不存在/);
  });

  it('激活项禁止删除；非激活项可删', async () => {
    await expect(store.remove('b')).rejects.toThrow(/正在使用/);
    await store.remove('a');
    expect((await store.list()).map((m) => m.id)).not.toContain('a');
    await expect(store.remove('不存在')).rejects.toThrow(/不存在/);
  });

  it('upsert 同 id 覆盖更新', async () => {
    await store.upsert(model({ id: 'b', name: '模型B改', model: 'gpt-5-mini' }));
    const got = await store.get();
    expect(got.name).toBe('模型B改');
    expect(got.model).toBe('gpt-5-mini');
    expect((await store.list()).filter((m) => m.id === 'b').length).toBe(1);
  });

  it('旧格式（单对象）自动迁移为列表', async () => {
    const legacyDir = await mkdtemp(join(tmpdir(), 'cfg-legacy-'));
    await mkdir(legacyDir, { recursive: true });
    await writeFile(join(legacyDir, 'config.json'), JSON.stringify({ name: '旧配置', provider: 'deepseek', baseUrl: 'https://api.deepseek.com', model: 'deepseek-chat', apiKey: 'sk-x', encrypted: false, temperature: 0.1, maxTokens: 2048 }));
    const legacy = new ConfigStore(legacyDir);
    await legacy.init();
    const list = await legacy.list();
    expect(list.length).toBe(1);
    expect(list[0]?.name).toBe('旧配置');
    expect((await legacy.get()).id).toBe(list[0]?.id);
    await rm(legacyDir, { recursive: true, force: true });
  });

  it('落盘结构为 { models, activeId }', async () => {
    const raw = JSON.parse(await readFile(join(dir, 'config.json'), 'utf-8')) as { models: unknown[]; activeId: string };
    expect(Array.isArray(raw.models)).toBe(true);
    expect(typeof raw.activeId).toBe('string');
  });
});
