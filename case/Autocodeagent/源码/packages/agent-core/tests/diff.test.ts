/** diff 模块单测（P2 任务 3：行级对比 + ChangeSet → DiffView） */
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { Checkpoint } from '../src/checkpoint';
import { buildDiffView, diffLines, toChangeSetView } from '../src/diff';

describe('diffLines', () => {
  it('相同内容 → 全 ctx', () => {
    const lines = diffLines('a\nb\n', 'a\nb\n');
    expect(lines.every((l) => l.kind === 'ctx')).toBe(true);
    expect(lines.map((l) => l.text)).toEqual(['a', 'b', '']);
  });

  it('中间行替换 → del + add 且保留上下文行号', () => {
    const lines = diffLines('a\nb\nc\n', 'a\nX\nc\n');
    const kinds = lines.filter((l) => l.kind !== 'ctx').map((l) => `${l.kind}:${l.text}`);
    expect(kinds).toEqual(['del:b', 'add:X']);
    const del = lines.find((l) => l.kind === 'del');
    const add = lines.find((l) => l.kind === 'add');
    expect(del?.oldNo).toBe(2);
    expect(add?.newNo).toBe(2);
  });

  it('纯插入与纯删除', () => {
    const ins = diffLines('a\n', 'a\nb\n');
    expect(ins.some((l) => l.kind === 'add' && l.text === 'b')).toBe(true);
    expect(ins.filter((l) => l.kind === 'del').length).toBe(0);

    const del = diffLines('a\nb\n', 'a\n');
    expect(del.some((l) => l.kind === 'del' && l.text === 'b')).toBe(true);
    expect(del.filter((l) => l.kind === 'add').length).toBe(0);
  });

  it('空 → 全文新增 / 全文删除', () => {
    expect(diffLines('', 'x\ny\n').map((l) => l.kind)).toEqual(['add', 'add', 'add']);
    expect(diffLines('x\ny\n', '').map((l) => l.kind)).toEqual(['del', 'del', 'del']);
  });

  it('两侧均为空 → 空序列', () => {
    expect(diffLines('', '')).toEqual([]);
  });

  it('输出序列可重组出两侧原文（正确性不变量）', () => {
    const oldText = '1\n2\n3\n4\n5\n';
    const newText = '1\n2x\n3\n4\n5\n6\n';
    const lines = diffLines(oldText, newText);
    const oldSide = lines.filter((l) => l.kind !== 'add').map((l) => l.text);
    const newSide = lines.filter((l) => l.kind !== 'del').map((l) => l.text);
    expect(oldSide).toEqual(oldText.split('\n').filter((s, i, arr) => !(i === arr.length - 1 && s === '')));
    expect(newSide).toEqual(newText.split('\n').filter((s, i, arr) => !(i === arr.length - 1 && s === '')));
  });
});

describe('ChangeSet → DiffView', () => {
  let ws: string;
  let dataDir: string;
  let checkpoint: Checkpoint;

  beforeAll(async () => {
    ws = await mkdtemp(join(tmpdir(), 'diff-ws-'));
    dataDir = await mkdtemp(join(tmpdir(), 'diff-data-'));
    checkpoint = new Checkpoint(dataDir);
  });

  afterAll(async () => {
    await rm(ws, { recursive: true, force: true });
    await rm(dataDir, { recursive: true, force: true });
  });

  it('modified：旧侧=备份、新侧=当前文件，路径为相对路径', async () => {
    const file = join(ws, 'app.ts');
    await writeFile(file, 'const a = 1;\nconst b = 2;\n');
    const set = await checkpoint.snapshot(ws, [file], 'c-mod', 's1');
    expect(set).not.toBeNull();
    await writeFile(file, 'const a = 1;\nconst b = 3;\nconst c = 4;\n');

    if (!set) throw new Error('snapshot 不应为 null');
    const view = await buildDiffView(checkpoint, set);
    expect(view.isGitSnapshot).toBe(false);
    expect(view.files).toHaveLength(1);
    const f = view.files[0];
    expect(f?.path).toBe('app.ts');
    expect(f?.kind).toBe('modified');
    expect(f?.insertions).toBe(2);
    expect(f?.deletions).toBe(1);
    expect(f?.lines.some((l) => l.kind === 'del' && l.text === 'const b = 2;')).toBe(true);

    const listView = toChangeSetView(set);
    expect(listView.entries[0]?.from).toBe('app.ts');
    expect(listView.status).toBe('pending');
  });

  it('created：旧侧为空，全部为新增行', async () => {
    const file = join(ws, 'new.txt');
    const set = await checkpoint.snapshot(ws, [file], 'c-new', 's1');
    if (!set) throw new Error('snapshot 不应为 null');
    await writeFile(file, 'hello\nworld\n');

    const view = await buildDiffView(checkpoint, set);
    const f = view.files[0];
    expect(f?.kind).toBe('created');
    expect(f?.deletions).toBe(0);
    expect(f?.insertions).toBeGreaterThan(0);
  });

  it('撤销后 Diff 视图回归基线（撤销场景读当前文件 = 备份内容）', async () => {
    const file = join(ws, 'revert.txt');
    await writeFile(file, 'base\n');
    const set = await checkpoint.snapshot(ws, [file], 'c-rev', 's1');
    if (!set) throw new Error('snapshot 不应为 null');
    await writeFile(file, 'changed\n');
    await checkpoint.restore('c-rev');

    expect(await readFile(file, 'utf-8')).toBe('base\n');
    const after = await checkpoint.get('c-rev');
    if (!after) throw new Error('get 不应为 null');
    const view = await buildDiffView(checkpoint, after);
    expect(view.status).toBe('reverted');
    expect(view.files[0]?.insertions).toBe(0);
    expect(view.files[0]?.deletions).toBe(0);
  });

  it('list 按会话过滤且倒序', async () => {
    const list = await checkpoint.list('s1');
    expect(list.length).toBeGreaterThanOrEqual(3);
    expect(list.every((s) => s.sessionId === 's1')).toBe(true);
    expect(list.map((s) => s.changeId)).toContain('c-mod');
    const other = await checkpoint.list('不存在');
    expect(other).toEqual([]);
  });

  it('accept/restore 只处理一次（状态机硬边界）', async () => {
    const file = join(ws, 'once.txt');
    await writeFile(file, 'v1\n');
    const set = await checkpoint.snapshot(ws, [file], 'c-once', 's1');
    if (!set) throw new Error('snapshot 不应为 null');
    await checkpoint.accept('c-once');
    await expect(checkpoint.accept('c-once')).rejects.toThrow(/已接受/);
    await expect(checkpoint.restore('c-once')).rejects.toThrow(/已接受/);
  });
});
