/**
 * API Key 密文存储（P6 任务 1）：
 * `{dataDir}/keys.json` = { modelId: vaultToken }；vault 由 Main 注入
 * （Electron safeStorage 实现），agent-core 不依赖 Electron，单测注入可逆 mock。
 * P0 明文迁移：config.json 中 apiKey 非空且 encrypted=false 的条目 → 加密迁出并清明文。
 * 解密结果登记进脱敏中间件（§P6 任务 2），Key 永不进日志。
 */
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import { registerSecret } from '../redact';
import type { ConfigStore } from './configStore';

/** 密文 vault 接口：Main 注入 safeStorage 实现 */
export interface SecretVault {
  encrypt(plain: string): string;
  decrypt(token: string): string;
}

export class KeyStore {
  constructor(
    private readonly file: string,
    private readonly vault: SecretVault,
  ) {}

  /** 取明文（不存在 = ''）；解密结果登记脱敏 */
  async get(modelId: string): Promise<string> {
    const token = (await this.load())[modelId];
    if (!token) return '';
    const plain = this.vault.decrypt(token);
    registerSecret(plain);
    return plain;
  }

  /** 存新 Key：加密落盘，明文登记脱敏 */
  async set(modelId: string, plain: string): Promise<void> {
    registerSecret(plain);
    const map = await this.load();
    map[modelId] = this.vault.encrypt(plain);
    await this.save(map);
  }

  async remove(modelId: string): Promise<void> {
    const map = await this.load();
    if (!(modelId in map)) return;
    delete map[modelId];
    await this.save(map);
  }

  /** P0 明文迁移：加密迁出 + config.json 清明文；返回迁移条数 */
  async migrate(configs: ConfigStore): Promise<number> {
    const models = await configs.list();
    let n = 0;
    for (const m of models) {
      if (m.apiKey && !m.encrypted) {
        await this.set(m.id, m.apiKey);
        await configs.upsert({ ...m, apiKey: '', encrypted: true });
        n++;
      }
    }
    return n;
  }

  private async load(): Promise<Record<string, string>> {
    try {
      const raw = JSON.parse(await readFile(this.file, 'utf-8')) as unknown;
      if (raw && typeof raw === 'object' && !Array.isArray(raw)) return raw as Record<string, string>;
      return {};
    } catch {
      return {};
    }
  }

  private async save(map: Record<string, string>): Promise<void> {
    await mkdir(dirname(this.file), { recursive: true });
    await writeFile(this.file, JSON.stringify(map, null, 2), 'utf-8');
  }
}
