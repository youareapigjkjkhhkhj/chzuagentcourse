/**
 * 模型配置持久化：{dataDir}/config.json，多模型列表 + 激活项。
 * 兼容旧格式（单个 ModelConfig 对象）：读取时自动迁移为单元素列表。
 * P0 明文保存（仅本机个人数据）；P6 用 Electron safeStorage 加密 apiKey。
 */
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { join, dirname } from 'node:path';
import { randomUUID } from 'node:crypto';
import type { AppSettings, ModelConfig } from '@agentbuddy/shared';

export const DEFAULT_SETTINGS: AppSettings = {
  permissionMode: 'Ask',
  execWhitelist: [],
  disabledSkills: [],
  websearch: { enabled: false, provider: 'tavily' },
};

export const DEFAULT_MODEL_CONFIG: ModelConfig = {
  id: 'default',
  name: '默认模型',
  provider: 'openai',
  baseUrl: 'https://api.openai.com/v1',
  model: 'gpt-4o-mini',
  apiKey: '',
  encrypted: false,
  temperature: 0.2,
  maxTokens: 8192,
  contextWindow: 128000,
};

interface ConfigFile {
  models: ModelConfig[];
  activeId: string;
  /** P3 应用级设置（模式 + 白名单）；缺省回退 DEFAULT_SETTINGS */
  settings?: Partial<AppSettings>;
}

export class ConfigStore {
  private readonly file: string;

  constructor(dataDir: string) {
    this.file = join(dataDir, 'config.json');
  }

  async init(): Promise<void> {
    await mkdir(dirname(this.file), { recursive: true });
    await this.save(await this.load()); // 首次/迁移后立即落盘，保证配置 id 稳定
  }

  async list(): Promise<ModelConfig[]> {
    return (await this.load()).models;
  }

  /** 当前激活配置（ChatService 使用） */
  async get(): Promise<ModelConfig> {
    const file = await this.load();
    return file.models.find((m) => m.id === file.activeId) ?? file.models[0] ?? { ...DEFAULT_MODEL_CONFIG };
  }

  /** 新增或更新：无 id 新建，有 id 覆盖 */
  async upsert(model: ModelConfig): Promise<ModelConfig> {
    const file = await this.load();
    const idx = file.models.findIndex((m) => m.id === model.id);
    if (idx >= 0) file.models[idx] = model;
    else file.models.push(model);
    if (file.models.length === 1) file.activeId = model.id;
    await this.save(file);
    return model;
  }

  async setActive(id: string): Promise<void> {
    const file = await this.load();
    if (!file.models.some((m) => m.id === id)) throw new Error('模型配置不存在');
    file.activeId = id;
    await this.save(file);
  }

  /** 删除非激活配置；激活项禁止删除（先切换再删） */
  async remove(id: string): Promise<void> {
    const file = await this.load();
    if (file.activeId === id) throw new Error('不能删除正在使用的配置，请先切换激活模型');
    const before = file.models.length;
    file.models = file.models.filter((m) => m.id !== id);
    if (file.models.length === before) throw new Error('模型配置不存在');
    await this.save(file);
  }

  /** P3：应用设置读取（合并默认值 + 容错净化，配置损坏不击穿权限体系） */
  async getSettings(): Promise<AppSettings> {
    const file = await this.load();
    const raw = file.settings ?? {};
    const mode = raw.permissionMode === 'Plan' || raw.permissionMode === 'Auto' ? raw.permissionMode : 'Ask';
    const whitelist = Array.isArray(raw.execWhitelist) ? raw.execWhitelist.filter((p): p is string => typeof p === 'string') : [];
    const disabledSkills = Array.isArray(raw.disabledSkills) ? raw.disabledSkills.filter((p): p is string => typeof p === 'string') : [];
    // 联网搜索：仅 enabled 需容错（provider 目前唯一 tavily）；密钥不在此，存 KeyStore
    const websearch = { enabled: raw.websearch?.enabled === true, provider: 'tavily' as const };
    return { permissionMode: mode, execWhitelist: whitelist, disabledSkills, websearch };
  }

  /** P3：部分更新应用设置并落盘（切换立即生效） */
  async setSettings(patch: Partial<AppSettings>): Promise<AppSettings> {
    const file = await this.load();
    file.settings = { ...DEFAULT_SETTINGS, ...file.settings, ...patch };
    await this.save(file);
    return { ...DEFAULT_SETTINGS, ...file.settings };
  }

  private async load(): Promise<ConfigFile> {
    try {
      const raw = JSON.parse(await readFile(this.file, 'utf-8')) as Partial<ConfigFile> & Partial<ModelConfig>;
      if (Array.isArray(raw.models)) {
        const models = raw.models.map((m) => ({ ...DEFAULT_MODEL_CONFIG, ...m, id: m.id || randomUUID() }));
        const activeId = raw.activeId && models.some((m) => m.id === raw.activeId) ? raw.activeId : (models[0]?.id ?? '');
        return { models, activeId, settings: raw.settings };
      }
      // 旧格式：单个配置对象 → 迁移为单元素列表
      if (raw.model || raw.baseUrl) {
        const single = { ...DEFAULT_MODEL_CONFIG, ...raw, id: randomUUID() } as ModelConfig;
        return { models: [single], activeId: single.id };
      }
      return this.fresh();
    } catch {
      return this.fresh();
    }
  }

  private fresh(): ConfigFile {
    const model = { ...DEFAULT_MODEL_CONFIG, id: randomUUID() };
    return { models: [model], activeId: model.id };
  }

  private async save(file: ConfigFile): Promise<void> {
    await writeFile(this.file, JSON.stringify(file, null, 2), 'utf-8');
  }
}
