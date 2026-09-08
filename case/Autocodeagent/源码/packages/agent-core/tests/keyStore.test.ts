/** P6 任务 1：KeyStore 密文存储单测（vault 注入 mock；验收：磁盘无明文 + migrate 清明文） */
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { ConfigStore } from '../src/store/configStore';
import { KeyStore, type SecretVault } from '../src/store/keyStore';
import { clearSecrets, redact } from '../src/redact';

/** 可逆 mock vault（Electron safeStorage 由 Main 注入，单测不依赖 Electron） */
const mockVault: SecretVault = {
  encrypt: (plain) => `mock1:${Buffer.from(plain, 'utf-8').toString('base64')}`,
  decrypt: (token) => (token.startsWith('mock1:') ? Buffer.from(token.slice(6), 'base64').toString('utf-8') : ''),
};

let dir: string;
let keys: KeyStore;

beforeEach(async () => {
  clearSecrets();
  dir = await mkdtemp(join(tmpdir(), 'keystore-'));
  keys = new KeyStore(join(dir, 'keys.json'), mockVault);
});

afterEach(async () => {
  clearSecrets();
  await rm(dir, { recursive: true, force: true });
});

describe('KeyStore 密文存取', () => {
  it('set / get 往返还原明文', async () => {
    await keys.set('m1', 'sk-plain-secret-123');
    expect(await keys.get('m1')).toBe('sk-plain-secret-123');
  });

  it('不存在的模型返回空串', async () => {
    expect(await keys.get('nope')).toBe('');
  });

  it('keys.json 仅存密文，磁盘无明文', async () => {
    await keys.set('m1', 'sk-plain-secret-123');
    const raw = await readFile(join(dir, 'keys.json'), 'utf-8');
    expect(raw).not.toContain('sk-plain-secret-123');
    expect(raw).toContain('mock1:');
  });

  it('get 解密结果登记脱敏：明文不再出现在日志文本', async () => {
    await keys.set('m1', 'sk-plain-secret-123');
    clearSecrets(); // 清掉 set 时的登记，验证 get 会重新登记
    await keys.get('m1');
    expect(redact('leak sk-plain-secret-123 here')).toBe('leak *** here');
  });

  it('remove 删除后 get 返回空串', async () => {
    await keys.set('m1', 'sk-plain-secret-123');
    await keys.remove('m1');
    expect(await keys.get('m1')).toBe('');
    await keys.remove('m1'); // 幂等
  });
});

describe('migrate：P0 明文一次性迁出', () => {
  it('加密迁出 + config.json 清明文 + encrypted 置位；二次迁移为 0', async () => {
    const cfgDir = await mkdtemp(join(tmpdir(), 'keystore-cfg-'));
    const configs = new ConfigStore(cfgDir);
    await configs.init();
    const list = await configs.list();
    const first = list[0]!;
    await configs.upsert({ ...first, apiKey: 'sk-legacy-plain-key', encrypted: false });

    const n = await keys.migrate(configs);
    expect(n).toBe(1);

    const migrated = (await configs.list())[0]!;
    expect(migrated.apiKey).toBe('');
    expect(migrated.encrypted).toBe(true);
    expect(await keys.get(migrated.id)).toBe('sk-legacy-plain-key');

    const raw = await readFile(join(cfgDir, 'config.json'), 'utf-8');
    expect(raw).not.toContain('sk-legacy-plain-key');

    expect(await keys.migrate(configs)).toBe(0); // 幂等
    await rm(cfgDir, { recursive: true, force: true });
  });
});
