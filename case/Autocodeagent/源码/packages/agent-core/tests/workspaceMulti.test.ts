/** 多工作区单测：roots + active 持久化、多根 jail 解析、多根文件树前缀挂载 */
import { mkdtemp, mkdir, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { basename, join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { Workspace, resolveWithinRoots } from '../src/workspace/workspace';
import { readWorkspaceFileBase64, workspaceTree } from '../src/workspace/info';

async function makeRoot(name: string): Promise<string> {
  const root = await mkdtemp(join(tmpdir(), `ws-${name}-`));
  await mkdir(join(root, 'src'), { recursive: true });
  await writeFile(join(root, 'src', `${name}.txt`), 'x', 'utf-8');
  return root;
}

describe('Workspace 多根状态', () => {
  it('open 追加根并切换活动，旧根保留', async () => {
    const dir = await mkdtemp(join(tmpdir(), 'ws-state-'));
    const a = await makeRoot('a');
    const b = await makeRoot('b');
    const ws = new Workspace(dir);
    await ws.init();
    await ws.open(a);
    const st = await ws.open(b);
    expect(st.roots).toEqual([a, b]);
    expect(st.active).toBe(b);
  });

  it('remove 移除活动根后回落到首个根；setActive 仅认已关联根', async () => {
    const dir = await mkdtemp(join(tmpdir(), 'ws-state-'));
    const a = await makeRoot('a');
    const b = await makeRoot('b');
    const ws = new Workspace(dir);
    await ws.init();
    await ws.open(a);
    await ws.open(b);
    const st = await ws.remove(b);
    expect(st.roots).toEqual([a]);
    expect(st.active).toBe(a);
    const outsider = await makeRoot('out');
    expect((await ws.setActive(outsider)).active).toBe(a);
  });

  it('持久化往返 + 旧格式 { path } 兼容升级', async () => {
    const dir = await mkdtemp(join(tmpdir(), 'ws-state-'));
    const a = await makeRoot('a');
    const b = await makeRoot('b');
    const ws = new Workspace(dir);
    await ws.init();
    await ws.open(a);
    await ws.open(b);
    const reloaded = new Workspace(dir);
    await reloaded.init();
    expect(reloaded.state()).toEqual({ roots: [a, b], active: b });

    const legacyDir = await mkdtemp(join(tmpdir(), 'ws-legacy-'));
    await writeFile(join(legacyDir, 'workspace.json'), JSON.stringify({ path: a }), 'utf-8');
    const legacy = new Workspace(legacyDir);
    await legacy.init();
    expect(legacy.state()).toEqual({ roots: [a], active: a });
  });
});

describe('resolveWithinRoots 多根 jail', () => {
  it('相对路径落活动根；带根名前缀落对应根；绝对路径认任一根', async () => {
    const a = await makeRoot('a');
    const b = await makeRoot('b');
    const rel = await resolveWithinRoots([a, b], a, join('src', 'a.txt'));
    expect(rel).toBe(join(a, 'src', 'a.txt'));
    const prefixed = await resolveWithinRoots([a, b], a, `${basename(b)}/src/b.txt`);
    expect(prefixed).toBe(join(b, 'src', 'b.txt'));
    const abs = await resolveWithinRoots([a, b], a, join(b, 'src', 'b.txt'));
    expect(abs).toBe(join(b, 'src', 'b.txt'));
  });

  it('新建场景（不存在的路径）带前缀仍落对应根', async () => {
    const a = await makeRoot('a');
    const b = await makeRoot('b');
    const fresh = await resolveWithinRoots([a, b], a, `${basename(b)}/src/new.txt`);
    expect(fresh).toBe(join(b, 'src', 'new.txt'));
  });

  it('逃逸拒绝：绝对路径出全部根 / 相对 ../ 出根', async () => {
    const a = await makeRoot('a');
    const b = await makeRoot('b');
    const outside = await mkdtemp(join(tmpdir(), 'ws-out-'));
    await expect(resolveWithinRoots([a, b], a, join(outside, 'secret.txt'))).rejects.toThrow(/逃出工作区/);
    await expect(resolveWithinRoots([a, b], a, '../secret.txt')).rejects.toThrow(/逃出工作区/);
  });
});

describe('workspaceTree 多根挂载', () => {
  it('活动根平铺顶层，非活动根以目录名节点挂载且子路径带前缀', async () => {
    const a = await makeRoot('a');
    const b = await makeRoot('b');
    const tree = await workspaceTree([a, b], a);
    const names = tree.map((n) => n.name);
    expect(names).toContain('src'); // 活动根条目平铺
    const bNode = tree.find((n) => n.name === basename(b) && n.dir);
    expect(bNode).toBeDefined();
    const bSrc = bNode!.children?.find((n) => n.name === 'src');
    expect(bSrc?.path).toBe(`${basename(b)}/src`);
    const bFile = bSrc?.children?.find((n) => n.name === 'b.txt');
    expect(bFile?.path).toBe(`${basename(b)}/src/b.txt`);
  });
});

describe('readWorkspaceFileBase64 预览读取', () => {
  it('正常返回 base64 与 mime（html / png）', async () => {
    const a = await makeRoot('pv');
    await writeFile(join(a, 'demo.html'), '<h1>hi</h1>', 'utf-8');
    const png = Buffer.from([0x89, 0x50, 0x4e, 0x47]);
    await writeFile(join(a, 'demo.png'), png);
    const html = await readWorkspaceFileBase64([a], a, 'demo.html');
    expect(html.mime).toContain('text/html');
    expect(Buffer.from(html.base64, 'base64').toString('utf-8')).toBe('<h1>hi</h1>');
    const img = await readWorkspaceFileBase64([a], a, 'demo.png');
    expect(img.mime).toBe('image/png');
    expect(Buffer.from(img.base64, 'base64').equals(png)).toBe(true);
  });

  it('jail 逃逸拒绝', async () => {
    const a = await makeRoot('pv');
    const outside = await mkdtemp(join(tmpdir(), 'ws-pvout-'));
    await writeFile(join(outside, 's.html'), 'x', 'utf-8');
    await expect(readWorkspaceFileBase64([a], a, join(outside, 's.html'))).rejects.toThrow(/逃出工作区/);
  });

  it('超过预览上限拒绝', async () => {
    const a = await makeRoot('pv');
    await writeFile(join(a, 'big.pdf'), Buffer.alloc(26 * 1024 * 1024));
    await expect(readWorkspaceFileBase64([a], a, 'big.pdf')).rejects.toThrow(/文件过大/);
  });
});
