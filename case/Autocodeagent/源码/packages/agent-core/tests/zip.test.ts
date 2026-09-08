/**
 * ZIP 导入单测：
 * 1) parseZip —— 用测试内打包器构造 stored/deflate/混合条目，验证解包与损坏拒绝；
 * 2) SkillHub.importZip —— 合法包落盘、畸形/重名/无 SKILL.md 拒绝（原子语义）。
 */
import { deflateRawSync } from 'node:zlib';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { parseZip } from '../src/zip';
import { SkillHub, type SkillHubDeps } from '../src/skills';

/** 测试用极简打包器：按 ZIP 规范写局部头 + 中央目录 + EOCD（crc 置 0，解析器不校验） */
function buildZip(files: Array<{ name: string; data: string; deflate?: boolean }>): Buffer {
  const chunks: Buffer[] = [];
  const central: Buffer[] = [];
  let offset = 0;
  for (const f of files) {
    const nameBuf = Buffer.from(f.name, 'utf-8');
    const raw = Buffer.from(f.data, 'utf-8');
    const comp = f.deflate ? deflateRawSync(raw) : raw;
    const method = f.deflate ? 8 : 0;

    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0, 6);
    local.writeUInt16LE(method, 8);
    local.writeUInt32LE(comp.length, 18);
    local.writeUInt32LE(raw.length, 22);
    local.writeUInt16LE(nameBuf.length, 26);
    chunks.push(local, nameBuf, comp);

    const cd = Buffer.alloc(46);
    cd.writeUInt32LE(0x02014b50, 0);
    cd.writeUInt16LE(20, 4);
    cd.writeUInt16LE(20, 6);
    cd.writeUInt16LE(method, 10);
    cd.writeUInt32LE(comp.length, 20);
    cd.writeUInt32LE(raw.length, 24);
    cd.writeUInt16LE(nameBuf.length, 28);
    cd.writeUInt32LE(offset, 42);
    central.push(cd, nameBuf);

    offset += 30 + nameBuf.length + comp.length;
  }
  const cdBuf = Buffer.concat(central);
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(0x06054b50, 0);
  eocd.writeUInt16LE(files.length, 8);
  eocd.writeUInt16LE(files.length, 10);
  eocd.writeUInt32LE(cdBuf.length, 12);
  eocd.writeUInt32LE(offset, 16);
  return Buffer.concat([...chunks, cdBuf, eocd]);
}

describe('parseZip', () => {
  it('stored 与 deflate 混合条目均可解出原文', () => {
    const buf = buildZip([
      { name: 'a.txt', data: 'hello stored' },
      { name: 'dir/b.txt', data: 'hello deflate 中文内容'.repeat(20), deflate: true },
    ]);
    const entries = parseZip(buf);
    expect(entries).toHaveLength(2);
    expect(entries[0]!.data.toString('utf-8')).toBe('hello stored');
    expect(entries[1]!.name).toBe('dir/b.txt');
    expect(entries[1]!.data.toString('utf-8')).toBe('hello deflate 中文内容'.repeat(20));
  });

  it('目录条目（以 / 结尾）被跳过', () => {
    const buf = buildZip([
      { name: 'skill/', data: '' },
      { name: 'skill/SKILL.md', data: 'x' },
    ]);
    const entries = parseZip(buf);
    expect(entries).toHaveLength(1);
    expect(entries[0]!.name).toBe('skill/SKILL.md');
  });

  it('非 ZIP / 尾部注释干扰均正确识别或拒绝', () => {
    expect(() => parseZip(Buffer.from('not a zip'))).toThrow('未找到目录结束标记');
    // EOCD 后带注释仍能找到
    const buf = Buffer.concat([buildZip([{ name: 'a', data: '1' }]), Buffer.from('尾注内容')]);
    expect(parseZip(buf)).toHaveLength(1);
  });

  it('损坏的中央目录拒绝', () => {
    const buf = buildZip([{ name: 'a', data: '1' }]);
    const eocd = buf.length - 22;
    buf.writeUInt32LE(buf.readUInt32LE(eocd + 16) + 5, eocd + 16); // 指错偏移
    expect(() => parseZip(buf)).toThrow();
  });

  it('Windows 工具的反斜杠条目名归一化为正斜杠', () => {
    const buf = buildZip([{ name: 'commit\\SKILL.md', data: 'x' }]);
    expect(parseZip(buf)[0]!.name).toBe('commit/SKILL.md');
  });
});

describe('SkillHub.importZip', () => {
  let globalDir: string;
  let wsRoot: string;
  let hub: SkillHub;

  const SKILL = (name: string, desc = '描述'): string => `---\nname: ${name}\ndescription: ${desc}\n---\n\n# ${name} 正文`;

  beforeAll(async () => {
    globalDir = await mkdtemp(join(tmpdir(), 'zip-global-'));
    wsRoot = await mkdtemp(join(tmpdir(), 'zip-ws-'));
    const deps: SkillHubDeps = {
      globalDir,
      projectDir: () => wsRoot,
      getDisabled: async () => [],
      setDisabled: async () => undefined,
    };
    hub = new SkillHub(deps);
  });

  afterAll(async () => {
    await rm(globalDir, { recursive: true, force: true });
    await rm(wsRoot, { recursive: true, force: true });
  });

  it('合法包：多技能 + references/scripts 附属文件整目录解出', async () => {
    const zip = buildZip([
      { name: 'deploy/SKILL.md', data: SKILL('deploy', '部署技能'), deflate: true },
      { name: 'deploy/references/checklist.md', data: '# 部署清单' },
      { name: 'deploy/scripts/check.py', data: 'print(1)' },
      { name: 'ops/SKILL.md', data: SKILL('ops', '运维技能') },
      { name: 'readme.txt', data: '孤儿文件应被忽略' },
    ]);
    const metas = await hub.importZip(zip, 'global');
    expect(metas.map((m) => m.name).sort()).toEqual(['deploy', 'ops']);
    // 附属文件保持目录结构落盘
    expect(await readFile(join(globalDir, 'deploy', 'references', 'checklist.md'), 'utf-8')).toBe('# 部署清单');
    expect(await readFile(join(globalDir, 'deploy', 'scripts', 'check.py'), 'utf-8')).toBe('print(1)');
    expect((await hub.get('deploy'))?.body).toContain('# deploy 正文');
  });

  it('根级 SKILL.md：整包视为单技能，根级附属一并解出', async () => {
    const zip = buildZip([
      { name: 'SKILL.md', data: SKILL('solo', '根级单技能') },
      { name: 'references/a.md', data: 'ref' },
      { name: 'scripts/run.sh', data: '#!/bin/sh' },
    ]);
    const metas = await hub.importZip(zip, 'global');
    expect(metas.map((m) => m.name)).toEqual(['solo']);
    expect(await readFile(join(globalDir, 'solo', 'references', 'a.md'), 'utf-8')).toBe('ref');
    expect(await readFile(join(globalDir, 'solo', 'scripts', 'run.sh'), 'utf-8')).toBe('#!/bin/sh');
  });

  it('嵌套 SKILL.md 视为参考文件，不当作新技能', async () => {
    const zip = buildZip([
      { name: 'kit/SKILL.md', data: SKILL('kit', '套件') },
      { name: 'kit/references/SKILL.md', data: '只是参考文档' },
    ]);
    const metas = await hub.importZip(zip, 'global');
    expect(metas.map((m) => m.name)).toEqual(['kit']);
    expect(await readFile(join(globalDir, 'kit', 'references', 'SKILL.md'), 'utf-8')).toBe('只是参考文档');
  });

  it('zip-slip 成员路径（../）整体拒绝', async () => {
    const zip = buildZip([
      { name: 'slip/SKILL.md', data: SKILL('slip', 'x') },
      { name: 'slip/../../evil.md', data: 'evil' },
    ]);
    await expect(hub.importZip(zip, 'global')).rejects.toThrow('zip-slip');
    expect((await hub.list()).some((s) => s.name === 'slip')).toBe(false); // 原子：未落盘
  });

  it('无 SKILL.md：拒绝', async () => {
    const zip = buildZip([{ name: 'docs/readme.md', data: 'hi' }]);
    await expect(hub.importZip(zip, 'global')).rejects.toThrow('未找到 SKILL.md');
  });

  it('任一畸形：整体拒绝，不落盘任何技能（原子）', async () => {
    const zip = buildZip([
      { name: 'good/SKILL.md', data: SKILL('good') },
      { name: 'bad/SKILL.md', data: '没有 frontmatter' },
    ]);
    await expect(hub.importZip(zip, 'global')).rejects.toThrow('bad/SKILL.md');
    expect((await hub.list()).some((s) => s.name === 'good')).toBe(false);
  });

  it('同范围重名 / 包内重名：拒绝', async () => {
    const dupExisting = buildZip([{ name: 'deploy/SKILL.md', data: SKILL('deploy') }]);
    await expect(hub.importZip(dupExisting, 'global')).rejects.toThrow('同范围已存在');
    const dupInPack = buildZip([
      { name: 'a/SKILL.md', data: SKILL('same') },
      { name: 'b/SKILL.md', data: SKILL('same', '另一个') },
    ]);
    await expect(hub.importZip(dupInPack, 'global')).rejects.toThrow('包内重名');
  });

  it('项目级导入：写入工作区目录且覆盖语义生效', async () => {
    const zip = buildZip([{ name: 'deploy/SKILL.md', data: SKILL('deploy', '项目版部署') }]);
    const metas = await hub.importZip(zip, 'project');
    expect(metas[0]!.source).toBe('project');
    const list = await hub.list();
    expect(list.find((s) => s.name === 'deploy')?.description).toBe('项目版部署'); // 项目覆盖全局
  });
});
