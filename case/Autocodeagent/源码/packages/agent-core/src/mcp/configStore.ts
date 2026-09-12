/**
 * MCP 配置存储（P5 任务 1 / 6）：
 * `~/.AgentBuddy/mcp.json`（Claude Desktop 同款 `{ "mcpServers": {...} }` 结构）zod 读写；
 * 文件、表单、JSON 导入三通道统一走 upsert（同名覆盖）；
 * JSON 导入行级校验：任一行非法则整体拒绝，绝不产生半截配置。
 */
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { dirname } from 'node:path';
import { z } from 'zod';
import type { McpServerConfig } from '@agentbuddy/shared';

const NAME_RE = /^[a-zA-Z0-9][a-zA-Z0-9_-]{0,31}$/;

const ServerConfigSchema = z
  .object({
    name: z.string().regex(NAME_RE),
    type: z.enum(['stdio', 'http', 'sse']),
    command: z.string().max(512).optional(),
    args: z.array(z.string().max(1024)).max(64).optional(),
    env: z.record(z.string().max(1024)).optional(),
    url: z.string().max(2048).optional(),
    headers: z.record(z.string().max(1024)).optional(),
    description: z.string().max(300).optional(),
    enabled: z.boolean(),
    alwaysLoad: z.boolean().optional(),
    icon: z.string().max(150_000).optional(),
  })
  .superRefine((v, c) => {
    if (v.type === 'stdio' && !v.command) {
      c.addIssue({ code: z.ZodIssueCode.custom, path: ['command'], message: 'stdio 类型缺少启动命令' });
    }
    if (v.type !== 'stdio' && !v.url) {
      c.addIssue({ code: z.ZodIssueCode.custom, path: ['url'], message: `${v.type} 类型缺少端点 URL` });
    }
  });

const FileSchema = z.object({ mcpServers: z.record(z.unknown()) });

export class McpConfigStore {
  constructor(private readonly file: string) {}

  async load(): Promise<Record<string, McpServerConfig>> {
    const raw = await readFile(this.file, 'utf-8').catch(() => null);
    if (raw === null) return {};
    const parsed = FileSchema.safeParse(JSON.parse(raw));
    if (!parsed.success) throw new Error(`mcp.json 结构非法：${parsed.error.issues[0]?.message ?? '未知'}`);
    const out: Record<string, McpServerConfig> = {};
    for (const [name, value] of Object.entries(parsed.data.mcpServers)) {
      const one = ServerConfigSchema.safeParse(value);
      if (one.success) out[name] = one.data; // 单条损坏跳过，不阻塞其余连接器
    }
    return out;
  }

  private async save(map: Record<string, McpServerConfig>): Promise<void> {
    await mkdir(dirname(this.file), { recursive: true });
    await writeFile(this.file, `${JSON.stringify({ mcpServers: map }, null, 2)}\n`, 'utf-8');
  }

  /** 表单 / 导入统一入口：zod 校验后同名覆盖 */
  async upsert(config: McpServerConfig): Promise<McpServerConfig> {
    const v = ServerConfigSchema.safeParse(config);
    if (!v.success) {
      const issue = v.error.issues[0];
      throw new Error(`连接器配置非法：${issue?.path.join('.') || '?'} ${issue?.message ?? ''}`);
    }
    const map = await this.load();
    map[config.name] = v.data;
    await this.save(map);
    return v.data;
  }

  async remove(name: string): Promise<void> {
    const map = await this.load();
    if (!(name in map)) throw new Error(`连接器不存在: ${name}`);
    delete map[name];
    await this.save(map);
  }

  async setEnabled(name: string, enabled: boolean): Promise<McpServerConfig> {
    const map = await this.load();
    const cfg = map[name];
    if (!cfg) throw new Error(`连接器不存在: ${name}`);
    cfg.enabled = enabled;
    await this.save(map);
    return cfg;
  }

  /** 强制常驻开关：仅更新持久化标志，不触发重连（连接状态与 alwaysLoad 正交，下一轮 buildSessionBus 生效） */
  async setAlwaysLoad(name: string, alwaysLoad: boolean): Promise<McpServerConfig> {
    const map = await this.load();
    const cfg = map[name];
    if (!cfg) throw new Error(`连接器不存在: ${name}`);
    cfg.alwaysLoad = alwaysLoad;
    await this.save(map);
    return cfg;
  }

  /**
   * JSON 粘贴导入（P5 任务 6）：兼容 `{"mcpServers": {...}}` 与内层对象；
   * `command+args`→stdio、`url`→sse（占位）；缺省 `enabled` 视为 true。
   * 任一行非法 → 汇总行级报错整体拒绝（不写盘）。
   */
  async importJson(text: string): Promise<McpServerConfig[]> {
    let root: unknown;
    try {
      root = JSON.parse(text);
    } catch (e) {
      throw new Error(`JSON 解析失败：${e instanceof Error ? e.message : String(e)}`);
    }
    if (typeof root !== 'object' || root === null || Array.isArray(root)) {
      throw new Error('JSON 顶层必须为对象（{"mcpServers": {...}} 或内层对象）');
    }
    const obj = root as Record<string, unknown>;
    let servers: unknown = obj['mcpServers'];
    if (servers === undefined) {
      if (isSingleServer(obj)) {
        // 单条配置对象（市场复制格式：name/type/command/args 平铺）→ 自动包装为 { name: 配置 }
        const name = obj['name'];
        if (typeof name !== 'string') {
          throw new Error('单条配置缺少 name 字段（或改用 {"mcpServers": {"serverName": {...}}} 映射格式）');
        }
        servers = { [name]: obj };
      } else {
        servers = obj;
      }
    }
    if (typeof servers !== 'object' || servers === null || Array.isArray(servers)) {
      throw new Error('mcpServers 必须为对象映射（名称 → 配置）');
    }

    const errors: string[] = [];
    const configs: McpServerConfig[] = [];
    for (const [name, value] of Object.entries(servers as Record<string, unknown>)) {
      try {
        configs.push(toConfig(name, value));
      } catch (e) {
        errors.push(`· ${name}：${e instanceof Error ? e.message : String(e)}`);
      }
    }
    if (errors.length > 0) {
      throw new Error(`导入失败（0/${Object.keys(servers).length} 条写入，未产生半截配置）：\n${errors.join('\n')}`);
    }

    const map = await this.load();
    for (const cfg of configs) map[cfg.name] = cfg; // 同名覆盖
    await this.save(map);
    return configs;
  }
}

/** 顶层对象看起来是单条 server 配置（含 command/url/type 之一），而非名称→配置映射 */
function isSingleServer(v: Record<string, unknown>): boolean {
  return (
    typeof v['command'] === 'string' ||
    typeof v['url'] === 'string' ||
    v['type'] === 'stdio' ||
    v['type'] === 'sse' ||
    v['type'] === 'http'
  );
}

/** 显式 type/transport 声明 → 内部类型（接受 http / streamable-http 等写法；未知值直接报错） */
function parseTransport(declared: string): McpServerConfig['type'] {
  const d = declared.toLowerCase();
  if (d === 'stdio') return 'stdio';
  if (d === 'sse') return 'sse';
  if (d === 'http' || d === 'streamable-http' || d === 'streamablehttp' || d === 'streamable_http') return 'http';
  throw new Error(`未知传输类型: ${declared}（支持 stdio / http / sse）`);
}

/** 单条 mcpServers 条目 → 内部配置（非法直接抛错，由调用方汇总行级报错） */
function toConfig(name: string, value: unknown): McpServerConfig {
  if (!NAME_RE.test(name)) throw new Error('名称须为 1–32 位字母/数字/下划线/中划线，且字母或数字开头');
  if (typeof value !== 'object' || value === null || Array.isArray(value)) throw new Error('配置必须为对象');
  const v = value as Record<string, unknown>;

  const command = typeof v['command'] === 'string' ? v['command'] : undefined;
  const url = typeof v['url'] === 'string' ? v['url'] : undefined;
  if (!command && !url) throw new Error('缺少 command（stdio）或 url（http/sse）');

  // 传输类型：显式 type/transport 优先；缺省按 command→stdio、url→sse（旧格式兼容）
  const declared = typeof v['type'] === 'string' ? v['type'] : typeof v['transport'] === 'string' ? v['transport'] : undefined;
  let type: McpServerConfig['type'];
  if (declared !== undefined) {
    type = parseTransport(declared);
    if (type === 'stdio' && !command) throw new Error('stdio 类型缺少 command');
    if (type !== 'stdio' && !url) throw new Error(`${type} 类型缺少 url`);
  } else {
    type = command ? 'stdio' : 'sse';
  }

  let args: string[] | undefined;
  if (v['args'] !== undefined) {
    if (!Array.isArray(v['args']) || v['args'].some((a) => typeof a !== 'string')) throw new Error('args 必须为字符串数组');
    args = v['args'] as string[];
  }

  let env: Record<string, string> | undefined;
  if (v['env'] !== undefined) {
    if (typeof v['env'] !== 'object' || v['env'] === null || Array.isArray(v['env'])) throw new Error('env 必须为字符串映射');
    for (const [k, val] of Object.entries(v['env'] as Record<string, unknown>)) {
      if (typeof val !== 'string') throw new Error(`env.${k} 必须为字符串（可用 \${VAR} 占位）`);
    }
    env = v['env'] as Record<string, string>;
  }

  let headers: Record<string, string> | undefined;
  if (v['headers'] !== undefined) {
    if (typeof v['headers'] !== 'object' || v['headers'] === null || Array.isArray(v['headers'])) throw new Error('headers 必须为字符串映射');
    for (const [k, val] of Object.entries(v['headers'] as Record<string, unknown>)) {
      if (typeof val !== 'string') throw new Error(`headers.${k} 必须为字符串（可用 \${VAR} 占位）`);
    }
    headers = v['headers'] as Record<string, string>;
  }

  const description = typeof v['description'] === 'string' ? v['description'] : undefined;
  const enabled = v['enabled'] === undefined ? true : v['enabled'] === true;
  const alwaysLoad = v['alwaysLoad'] === true;

  return { name, type, command, args, env, url, headers, description, enabled, alwaysLoad };
}
