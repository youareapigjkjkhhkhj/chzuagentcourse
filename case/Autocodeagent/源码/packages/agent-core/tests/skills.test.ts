/**
 * P4 单测（验收：frontmatter 解析 / 同名覆盖优先级 / 启停过滤 / 畸形告警 / 内置播种）。
 */
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { BUILTIN_SKILLS, parseSkillMd, SkillHub, type SkillHubDeps } from '../src/skills';
import { createSkillTool } from '../src/tools/skillTool';

const VALID = `---
name: demo
description: 演示技能
---

正文内容
`;

describe('parseSkillMd', () => {
  it('合法：name / description / body 三段解析', () => {
    const r = parseSkillMd(VALID);
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.skill.name).toBe('demo');
    expect(r.skill.description).toBe('演示技能');
    expect(r.skill.body).toBe('正文内容');
  });

  it('缺 frontmatter：返回告警不抛错', () => {
    const r = parseSkillMd('只有正文没有头部');
    expect(r.ok).toBe(false);
    if (!r.ok) expect(r.warning).toContain('frontmatter');
  });

  it('非法 name（含空格）：告警', () => {
    const r = parseSkillMd(`---\nname: bad name\ndescription: x\n---\nbody`);
    expect(r.ok).toBe(false);
  });

  it('缺 description：告警', () => {
    const r = parseSkillMd(`---\nname: ok\n---\nbody`);
    expect(r.ok).toBe(false);
  });
});

describe('SkillHub 两级扫描', () => {
  let globalDir: string;
  let wsRoot: string;
  let disabled: string[];
  let hub: SkillHub;

  const writeSkill = async (root: string, dirName: string, content: string): Promise<void> => {
    await mkdir(join(root, dirName), { recursive: true });
    await writeFile(join(root, dirName, 'SKILL.md'), content, 'utf-8');
  };

  const makeHub = (): SkillHub => {
    const deps: SkillHubDeps = {
      globalDir,
      projectDir: () => wsRoot,
      getDisabled: async () => disabled,
      setDisabled: async (d) => { disabled = d; },
    };
    return new SkillHub(deps);
  };

  beforeAll(async () => {
    globalDir = await mkdtemp(join(tmpdir(), 'p4-global-'));
    wsRoot = await mkdtemp(join(tmpdir(), 'p4-ws-'));
  });

  afterAll(async () => {
    await rm(globalDir, { recursive: true, force: true });
    await rm(wsRoot, { recursive: true, force: true });
  });

  it('seed 播种内置示例（/review /test），已存在不覆盖', async () => {
    disabled = [];
    hub = makeHub();
    await hub.seed();
    const names = (await hub.list()).map((s) => s.name);
    expect(names).toContain('review');
    expect(names).toContain('test');
    // 用户修改不被覆盖
    await writeSkill(globalDir, 'review', VALID);
    await hub.seed();
    const got = await hub.get('demo');
    expect(got?.meta.name).toBe('demo');
    // 恢复内置版供后续用例
    await writeFile(join(globalDir, 'review', 'SKILL.md'), BUILTIN_SKILLS[0]!.content, 'utf-8');
  });

  it('同名时项目级覆盖全局（来源徽标 = project）', async () => {
    disabled = [];
    await writeSkill(globalDir, 'dup', `---\nname: dup\ndescription: 全局版\n---\ng`);
    await writeSkill(join(wsRoot, '.AgentBuddy', 'skills'), 'dup', `---\nname: dup\ndescription: 项目版\n---\np`);
    const list = await hub.list();
    const dup = list.filter((s) => s.name === 'dup');
    expect(dup).toHaveLength(1);
    expect(dup[0]?.source).toBe('project');
    expect(dup[0]?.description).toBe('项目版');
    const got = await hub.get('dup');
    expect(got?.body).toBe('p');
  });

  it('畸形条目：带 warning、不启用、不阻塞其余技能', async () => {
    await writeSkill(globalDir, 'broken', '没有 frontmatter 的裸文件');
    const list = await hub.list();
    const broken = list.find((s) => s.name === 'broken');
    expect(broken?.warning).toBeTruthy();
    expect(broken?.enabled).toBe(false);
    const catalog = await hub.catalog();
    expect(catalog.some((s) => s.name === 'broken')).toBe(false);
    expect(catalog.some((s) => s.name === 'review')).toBe(true);
  });

  it('禁用后目录消失，重新启用恢复（下一次组装生效的持久化开关）', async () => {
    await hub.setEnabled('review', false);
    expect(disabled).toContain('review');
    let catalog = await hub.catalog();
    expect(catalog.some((s) => s.name === 'review')).toBe(false);
    const list = await hub.list();
    expect(list.find((s) => s.name === 'review')?.enabled).toBe(false);
    await hub.setEnabled('review', true);
    catalog = await hub.catalog();
    expect(catalog.some((s) => s.name === 'review')).toBe(true);
  });

  it('get 返回 body（无 frontmatter）与 raw（全文）', async () => {
    const got = await hub.get('dup');
    expect(got?.body).not.toContain('---');
    expect(got?.raw).toContain('name: dup');
  });

  it('save 回写后立即反映（描述变更可见）', async () => {
    const raw = `---\nname: dup\ndescription: 改过的描述\n---\np2`;
    await hub.save('dup', raw);
    const got = await hub.get('dup');
    expect(got?.meta.description).toBe('改过的描述');
    expect(got?.body).toBe('p2');
  });

  it('create：表单新增写入 <name>/SKILL.md（含 frontmatter），可被扫描与触发', async () => {
    const meta = await hub.create({ name: 'fresh', scope: 'global', description: '新建技能', body: '# 指令\n1. 做事' });
    expect(meta.source).toBe('global');
    expect(meta.enabled).toBe(true);
    const list = await hub.list();
    expect(list.find((s) => s.name === 'fresh')?.description).toBe('新建技能');
    const got = await hub.get('fresh');
    expect(got?.body).toContain('# 指令');
    expect(got?.raw).toContain('name: fresh');
  });

  it('create：同范围重名 / 非法名称 / 项目级无工作区均拒绝', async () => {
    await expect(hub.create({ name: 'fresh', scope: 'global', description: 'x', body: 'y' }))
      .rejects.toThrow('同范围已存在');
    await expect(hub.create({ name: 'bad name', scope: 'global', description: 'x', body: 'y' }))
      .rejects.toThrow('非法');
    const noWs = new SkillHub({ globalDir, projectDir: () => null, getDisabled: async () => [], setDisabled: async () => undefined });
    await expect(noWs.create({ name: 'fresh2', scope: 'project', description: 'x', body: 'y' }))
      .rejects.toThrow('工作区');
  });

  it('remove：删除目录并清理禁用清单残留；不存在时报错', async () => {
    await hub.setEnabled('fresh', false);
    expect(disabled).toContain('fresh');
    await hub.remove('fresh');
    expect(disabled).not.toContain('fresh');
    expect((await hub.list()).some((s) => s.name === 'fresh')).toBe(false);
    await expect(hub.remove('fresh')).rejects.toThrow('不存在');
  });

  it('create 项目级：允许与全局同名（项目覆盖语义），删项目版后全局版浮现', async () => {
    await writeSkill(globalDir, 'gonly', `---\nname: gonly\ndescription: 全局版\n---\ng`);
    const meta = await hub.create({ name: 'gonly', scope: 'project', description: '项目新建版', body: 'p3' });
    expect(meta.source).toBe('project');
    const dups = (await hub.list()).filter((s) => s.name === 'gonly');
    expect(dups).toHaveLength(1);
    expect(dups[0]?.source).toBe('project');
    expect((await hub.get('gonly'))?.body).toBe('p3');
    await hub.remove('gonly'); // 删项目版后全局版浮现，供清理
    expect((await hub.get('gonly'))?.body).toBe('g');
  });
});

describe('createSkillTool（use_skill 技能自取）', () => {
  let dir: string;
  let disabled: string[] = [];
  let hub: SkillHub;
  // execute 不使用 ctx，传 never 占位
  const ctx = null as never;

  beforeAll(async () => {
    dir = await mkdtemp(join(tmpdir(), 'p4-skilltool-'));
    hub = new SkillHub({
      globalDir: dir,
      projectDir: () => null,
      getDisabled: async () => disabled,
      setDisabled: async (d) => { disabled = d; },
    });
    await mkdir(join(dir, 'demo'), { recursive: true });
    await writeFile(join(dir, 'demo', 'SKILL.md'), VALID, 'utf-8');
  });

  afterAll(async () => {
    await rm(dir, { recursive: true, force: true });
  });

  it('READ 风险且正常返回正文（模型自主调用无需权限确认）', async () => {
    disabled = [];
    const tool = createSkillTool(hub);
    expect(tool.name).toBe('use_skill');
    expect(tool.risk).toBe('READ');
    const out = await tool.execute(ctx, { name: 'demo' });
    expect(out.text).toBe('正文内容');
  });

  it('容忍 / 前缀入参', async () => {
    disabled = [];
    const out = await createSkillTool(hub).execute(ctx, { name: '/demo' });
    expect(out.text).toBe('正文内容');
  });

  it('不存在 / 已禁用均结构化报错（回灌模型自纠）', async () => {
    disabled = [];
    const tool = createSkillTool(hub);
    await expect(tool.execute(ctx, { name: 'nope' })).rejects.toThrow('不存在');
    disabled = ['demo'];
    await expect(tool.execute(ctx, { name: 'demo' })).rejects.toThrow('已禁用');
    disabled = [];
  });

  it('专家绑定硬边界：未绑定技能拒绝并列出可用', async () => {
    const tool = createSkillTool(hub, ['other']);
    await expect(tool.execute(ctx, { name: 'demo' })).rejects.toThrow('未绑定');
  });
});
