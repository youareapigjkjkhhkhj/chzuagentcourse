/**
 * P4 Skills 体系（两级技能资产）：
 * 全局 ~/.AgentBuddy/skills/ + 项目 <ws>/.AgentBuddy/skills/，目录式 <name>/SKILL.md；
 * frontmatter（name/description）zod 校验，畸形跳过并告警不阻塞；同名项目覆盖全局；
 * 目录（name+description）进系统提示第④层，正文不进上下文，模型需要时 read 自取。
 */
import { mkdir, readFile, readdir, rm, writeFile } from 'node:fs/promises';
import { join, resolve, sep } from 'node:path';
import { z } from 'zod';
import type { SkillMeta } from '@agentbuddy/shared';
import { parseZip } from './zip';

const SKILL_FILE = 'SKILL.md';

/** frontmatter 校验：name 限 slug 字符，description 一句话摘要 */
export const SkillFrontmatter = z.object({
  name: z.string().min(1).max(64).regex(/^[\w-]+$/, 'name 仅允许字母/数字/_/-'),
  description: z.string().min(1).max(300),
});

export interface ParsedSkill {
  name: string;
  description: string;
  /** frontmatter 之后的正文（/触发时作为高优先级指令） */
  body: string;
}

/** 解析 SKILL.md；畸形返回 warning，不抛错（不阻塞启动） */
export function parseSkillMd(raw: string): { ok: true; skill: ParsedSkill } | { ok: false; warning: string } {
  const m = /^---\s*\n([\s\S]*?)\n---\s*\n?([\s\S]*)$/.exec(raw);
  if (!m) return { ok: false, warning: '缺少 frontmatter（--- 包裹的 name/description 头部）' };
  const fields: Record<string, string> = {};
  for (const line of (m[1] ?? '').split('\n')) {
    const kv = /^(\w[\w-]*):\s*(.+)$/.exec(line.trim());
    if (kv) fields[kv[1]!] = kv[2]!.trim();
  }
  const result = SkillFrontmatter.safeParse(fields);
  if (!result.success) {
    const issue = result.error.issues[0];
    return { ok: false, warning: `frontmatter 非法：${issue?.path.join('.') || '?'} ${issue?.message ?? ''}` };
  }
  return { ok: true, skill: { name: result.data.name, description: result.data.description, body: (m[2] ?? '').trim() } };
}

interface ScannedEntry {
  meta: Omit<SkillMeta, 'enabled'>;
  parsed?: ParsedSkill;
}

/** 扫描单个 skills 根目录（子目录含 SKILL.md = 一个技能） */
async function scanDir(dir: string, source: 'global' | 'project'): Promise<ScannedEntry[]> {
  let entries: string[];
  try {
    entries = await readdir(dir);
  } catch {
    return [];
  }
  const out: ScannedEntry[] = [];
  for (const entry of entries.sort()) {
    const file = join(dir, entry, SKILL_FILE);
    let raw: string;
    try {
      raw = await readFile(file, 'utf-8');
    } catch {
      continue; // 非技能目录跳过
    }
    const parsed = parseSkillMd(raw);
    const name = parsed.ok ? parsed.skill.name : entry;
    out.push({
      meta: {
        name,
        description: parsed.ok ? parsed.skill.description : '',
        source,
        path: file,
        warning: parsed.ok ? undefined : parsed.warning,
      },
      parsed: parsed.ok ? parsed.skill : undefined,
    });
  }
  return out;
}

/** 内置示例技能（首次启动播种到全局目录，已存在不覆盖） */
export const BUILTIN_SKILLS: Array<{ name: string; content: string }> = [
  {
    name: 'review',
    content: `---
name: review
description: 按清单对工作区代码做结构化审查（正确性/安全/可读/测试）
---

# 代码审查技能

你现在执行代码审查。严格按以下清单逐项检查用户工作区的相关代码，并输出结构化报告：

1. **正确性**：边界条件、空值、异常路径是否处理；有无明显逻辑错误。
2. **安全**：注入、路径逃逸、敏感信息硬编码、不安全的命令执行。
3. **可读性**：命名、函数长度、重复代码、注释是否解释"为什么"。
4. **测试**：关键路径是否有测试覆盖；测试是否断言行为而非实现。

输出格式：先给「总体结论」一段话，再按上述四节列「问题清单」（每条：文件/位置 + 问题 + 建议），最后给「优先修复 Top3」。
只读分析，不要修改文件，除非用户明确要求。
`,
  },
  {
    name: 'test',
    content: `---
name: test
description: 运行工作区测试并结构化汇报结果（失败先定位再修）
---

# 运行测试技能

按以下步骤执行测试任务：

1. 先读 package.json / pytest.ini 等配置，确定测试命令（如 npm test / npx vitest run / pytest）。
2. 用 bash 执行测试命令，完整阅读输出。
3. 汇报格式：「通过/失败数量」→ 失败用例逐条「用例名 + 报错摘要 + 可疑位置」。
4. 若用户要求修复：先复现，再最小化修改，修完重跑测试验证。
`,
  },
];

export interface SkillHubDeps {
  /** 全局 skills 根目录（~/.AgentBuddy/skills） */
  globalDir: string;
  /** 当前工作区（项目级 skills 根 = <ws>/.AgentBuddy/skills） */
  projectDir: () => string | null;
  getDisabled: () => Promise<string[]>;
  setDisabled: (disabled: string[]) => Promise<void>;
}

/** 新增技能表单（原型同款：名称 + 来源 + 描述 + 正文） */
export interface CreateSkillInput {
  name: string;
  scope: 'global' | 'project';
  description: string;
  body: string;
}

export class SkillHub {
  constructor(private readonly deps: SkillHubDeps) {}

  /** 指定来源的 skills 根；项目级未选工作区时抛错 */
  private rootOf(scope: 'global' | 'project'): string {
    if (scope === 'global') return this.deps.globalDir;
    const ws = this.deps.projectDir();
    if (!ws) throw new Error('尚未选择工作区，无法创建项目级技能');
    return join(ws, '.AgentBuddy', 'skills');
  }

  /** 新增技能：校验 slug + 同范围不重名 → 写 <name>/SKILL.md（含 frontmatter） */
  async create(input: CreateSkillInput): Promise<SkillMeta> {
    const name = input.name.trim();
    const fm = SkillFrontmatter.safeParse({ name, description: input.description.trim() });
    if (!fm.success) {
      const issue = fm.error.issues[0];
      throw new Error(`技能字段非法：${issue?.path.join('.') || '?'} ${issue?.message ?? ''}`);
    }
    if (input.body.trim().length > 50000) throw new Error('正文过长（上限 50000 字符）');
    const root = this.rootOf(input.scope);
    const dir = join(root, name);
    try {
      await readFile(join(dir, SKILL_FILE));
      throw new Error(`同范围已存在技能 /${name}，请先删除或改用编辑`);
    } catch (e) {
      if (e instanceof Error && e.message.startsWith('同范围已存在')) throw e;
    }
    await mkdir(dir, { recursive: true });
    await writeFile(join(dir, SKILL_FILE), `---\nname: ${name}\ndescription: ${input.description.trim()}\n---\n\n${input.body.trim()}\n`, 'utf-8');
    return { name, description: input.description.trim(), source: input.scope, path: join(dir, SKILL_FILE), enabled: true };
  }

  /** 删除技能：仅删其 <name> 目录（路径从扫描结果来，天然在两级根内），并清理禁用清单残留 */
  async remove(name: string): Promise<void> {
    const all = await this.list();
    const meta = all.find((s) => s.name === name);
    if (!meta) throw new Error(`技能不存在: ${name}`);
    const dir = resolve(meta.path, '..');
    const root = resolve(meta.source === 'global' ? this.deps.globalDir : this.rootOf('project'));
    if (!dir.startsWith(root + sep)) throw new Error('技能路径越界，拒绝删除');
    await rm(dir, { recursive: true, force: true });
    const disabled = await this.deps.getDisabled();
    if (disabled.includes(name)) await this.deps.setDisabled(disabled.filter((n) => n !== name));
  }

  /**
   * 导入 ZIP 技能包（原型「导入 ZIP 技能包」的真实现）：
   * 零依赖解包 → 识别顶层 SKILL.md（嵌套在其他技能目录里的视为参考文件）→ frontmatter 全验过才落盘（原子）；
   * 技能名取 frontmatter（slug 校验）；references/scripts 等附属文件随技能整目录解出并保持结构；
   * 成员路径逐段归一 + jail 防 zip-slip；包内/同范围重名整体拒绝。
   */
  async importZip(data: Uint8Array, scope: 'global' | 'project' = 'global'): Promise<SkillMeta[]> {
    const entries = parseZip(Buffer.from(data));
    const defs = entries.filter((e) => /(^|\/)SKILL\.md$/i.test(e.name));
    if (defs.length === 0) throw new Error('ZIP 内未找到 SKILL.md（技能包需含 <name>/SKILL.md）');

    // 顶层定义：某 SKILL.md 的目录前缀嵌套在另一定义内 → 它是参考文件而非新技能
    const prefixes = defs
      .map((e) => e.name.slice(0, e.name.length - SKILL_FILE.length))
      .sort((a, b) => a.length - b.length);
    const tops: string[] = [];
    for (const p of prefixes) if (!tops.some((t) => p.startsWith(t))) tops.push(p);
    if (tops.length > 20) throw new Error('单个技能包最多导入 20 个技能');
    const topDefs = defs.filter((e) => tops.includes(e.name.slice(0, e.name.length - SKILL_FILE.length)));

    // 全量校验：任一畸形则整体拒绝（不留半成品）
    const parsed = topDefs.map((f) => {
      const raw = f.data.toString('utf-8');
      const r = parseSkillMd(raw);
      if (!r.ok) throw new Error(`${f.name}：${r.warning}`);
      const prefix = f.name.slice(0, f.name.length - SKILL_FILE.length);
      // 同技能成员：前缀下的条目，排除其他顶层技能的子树
      const members = entries.filter(
        (e) => e.name.startsWith(prefix) && !tops.some((t) => t !== prefix && e.name.startsWith(t)),
      );
      return { skill: r.skill, raw, prefix, members };
    });

    // 查重 + 成员路径 jail：全部校验通过才写盘
    const root = resolve(this.rootOf(scope));
    const seen = new Set<string>();
    const plans: Array<{ dir: string; files: Array<{ rel: string; data: Buffer }> }> = [];
    for (const p of parsed) {
      if (seen.has(p.skill.name)) throw new Error(`技能包内重名：/${p.skill.name}`);
      seen.add(p.skill.name);
      try {
        await readFile(join(root, p.skill.name, SKILL_FILE));
        throw new Error(`同范围已存在技能 /${p.skill.name}，请先删除再导入`);
      } catch (e) {
        if (e instanceof Error && e.message.startsWith('同范围已存在')) throw e;
      }
      const dir = join(root, p.skill.name);
      const files: Array<{ rel: string; data: Buffer }> = [];
      for (const m of p.members) {
        const rel = m.name.slice(p.prefix.length);
        if (!rel || rel.toLowerCase() === SKILL_FILE.toLowerCase()) continue; // SKILL.md 单独写
        const safe = rel.split('/').filter(Boolean);
        if (safe.some((seg) => seg === '.' || seg === '..')) throw new Error(`非法成员路径（zip-slip）：${m.name}`);
        if (safe.length > 8) throw new Error(`附属文件层级过深（上限 8 层）：${m.name}`);
        const target = resolve(dir, ...safe);
        if (!target.startsWith(resolve(dir) + sep)) throw new Error(`非法成员路径（zip-slip）：${m.name}`);
        files.push({ rel: safe.join(sep), data: m.data });
      }
      if (files.length > 100) throw new Error(`技能 /${p.skill.name} 附属文件过多（上限 100）`);
      plans.push({ dir, files });
    }

    const metas: SkillMeta[] = [];
    for (let i = 0; i < parsed.length; i++) {
      const p = parsed[i]!;
      const plan = plans[i]!;
      await mkdir(plan.dir, { recursive: true });
      await writeFile(join(plan.dir, SKILL_FILE), p.raw, 'utf-8');
      for (const f of plan.files) {
        const target = join(plan.dir, f.rel);
        await mkdir(resolve(target, '..'), { recursive: true });
        await writeFile(target, f.data); // 二进制保真（脚本/图片等）
      }
      metas.push({ name: p.skill.name, description: p.skill.description, source: scope, path: join(plan.dir, SKILL_FILE), enabled: true });
    }
    return metas;
  }

  /** 首次启动播种内置示例（已存在不覆盖，尊重用户修改） */
  async seed(): Promise<void> {
    for (const skill of BUILTIN_SKILLS) {
      const file = join(this.deps.globalDir, skill.name, SKILL_FILE);
      try {
        await readFile(file);
      } catch {
        await mkdir(join(this.deps.globalDir, skill.name), { recursive: true });
        await writeFile(file, skill.content, 'utf-8');
      }
    }
  }

  /** 两级扫描 + 同名项目覆盖全局 + 启用状态合并；畸形条目带 warning 一并返回 */
  async list(): Promise<SkillMeta[]> {
    const disabled = new Set(await this.deps.getDisabled());
    const global = await scanDir(this.deps.globalDir, 'global');
    const project = await scanDir(this.deps.projectDir() ? join(this.deps.projectDir()!, '.AgentBuddy', 'skills') : '', 'project');
    const byName = new Map<string, ScannedEntry>();
    for (const entry of global) byName.set(entry.meta.name, entry);
    for (const entry of project) byName.set(entry.meta.name, entry); // 项目覆盖全局
    return [...byName.values()]
      .map((e) => ({ ...e.meta, enabled: !disabled.has(e.meta.name) && !e.meta.warning }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }

  /** 按名取技能；body = 正文（无 frontmatter，/触发注入用），raw = 全文（管理页查看/编辑用） */
  async get(name: string): Promise<{ meta: SkillMeta; body: string; raw: string } | null> {
    const all = await this.list();
    const meta = all.find((s) => s.name === name);
    if (!meta) return null;
    const raw = await readFile(meta.path, 'utf-8').catch(() => null);
    if (raw === null) return null;
    const parsed = parseSkillMd(raw);
    return { meta, body: parsed.ok ? parsed.skill.body : raw, raw };
  }

  /** 编辑回写 SKILL.md；路径必须落在两级 skills 根内（jail） */
  async save(name: string, body: string): Promise<SkillMeta> {
    const all = await this.list();
    const meta = all.find((s) => s.name === name);
    if (!meta) throw new Error(`技能不存在: ${name}`);
    const root = resolve(meta.source === 'global' ? this.deps.globalDir : this.rootOf('project'));
    const file = resolve(meta.path);
    if (!file.startsWith(root + sep)) throw new Error('技能路径越界，拒绝写入');
    await writeFile(file, body, 'utf-8');
    return (await this.list()).find((s) => s.name === name) ?? meta;
  }

  /** 启用/禁用（持久化 settings.disabledSkills，下一次上下文组装生效） */
  async setEnabled(name: string, enabled: boolean): Promise<void> {
    const disabled = new Set(await this.deps.getDisabled());
    if (enabled) disabled.delete(name);
    else disabled.add(name);
    await this.deps.setDisabled([...disabled]);
  }

  /** 系统提示第④层目录：仅启用且无告警的技能 */
  async catalog(): Promise<Array<{ name: string; description: string }>> {
    const all = await this.list();
    return all.filter((s) => s.enabled).map((s) => ({ name: s.name, description: s.description }));
  }
}
