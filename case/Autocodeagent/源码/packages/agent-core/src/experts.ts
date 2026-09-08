/**
 * P7 专家团：Expert 持久化（{dataDir}/experts.json，ConfigStore 同款 JSON 落盘）。
 * 存储读写前均过 ExpertUpsertPayload zod 校验（与 IPC §23 同一 schema，单一事实来源）；
 * 损坏 / 非法条目跳过不击穿启动；agent-core 只提供数据能力，不知道 IPC / UI（§4 模块边界）。
 * 工具绑定过滤见 tools/bus.ts buildSessionBus 的 allow 参数（chatService 传入）。
 */
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname, join } from 'node:path';
import { randomUUID } from 'node:crypto';
import { ExpertUpsertPayload, type Expert, type ExpertUpsertInput } from '@agentbuddy/shared';

export class ExpertStore {
  private readonly file: string;

  constructor(dataDir: string) {
    this.file = join(dataDir, 'experts.json');
  }

  async init(): Promise<void> {
    await mkdir(dirname(this.file), { recursive: true });
  }

  async list(): Promise<Expert[]> {
    return this.load();
  }

  async get(id: string): Promise<Expert | null> {
    return (await this.load()).find((e) => e.id === id) ?? null;
  }

  /** 新增（无 id）或整体覆盖（有 id）；字段全量 zod 校验，非法直接抛错 */
  async upsert(input: ExpertUpsertInput): Promise<Expert> {
    const parsed = ExpertUpsertPayload.parse(input);
    const all = await this.load();
    const now = Date.now();
    if (parsed.id) {
      const idx = all.findIndex((e) => e.id === parsed.id);
      if (idx < 0) throw new Error(`专家不存在: ${parsed.id}`);
      const next: Expert = { ...all[idx]!, ...parsed, updatedAt: now };
      all[idx] = next;
      await this.save(all);
      return next;
    }
    const created: Expert = { ...parsed, id: randomUUID(), createdAt: now, updatedAt: now };
    all.push(created);
    await this.save(all);
    return created;
  }

  async remove(id: string): Promise<void> {
    const all = await this.load();
    const next = all.filter((e) => e.id !== id);
    if (next.length === all.length) throw new Error(`专家不存在: ${id}`);
    await this.save(next);
  }

  /** 读入逐条净化：缺 id 补生成、时间戳缺失补当前，非法条目跳过（文件损坏不阻塞启动） */
  private async load(): Promise<Expert[]> {
    try {
      const raw = JSON.parse(await readFile(this.file, 'utf-8')) as unknown[];
      if (!Array.isArray(raw)) return [];
      const out: Expert[] = [];
      for (const item of raw) {
        const r = ExpertUpsertPayload.safeParse(item);
        if (!r.success) continue;
        const src = (item ?? {}) as Partial<Expert>;
        out.push({
          ...r.data,
          id: r.data.id || randomUUID(),
          createdAt: typeof src.createdAt === 'number' ? src.createdAt : Date.now(),
          updatedAt: typeof src.updatedAt === 'number' ? src.updatedAt : Date.now(),
        });
      }
      return out;
    } catch {
      return [];
    }
  }

  private async save(all: Expert[]): Promise<void> {
    await writeFile(this.file, JSON.stringify(all, null, 2), 'utf-8');
  }
}
