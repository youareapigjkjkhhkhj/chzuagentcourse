/** write / edit 工具单测（P1 验收：edit 替换 + 新鲜度校验，技术方案 §4.3） */
import { mkdtemp, mkdir, rm, utimes, writeFile } from 'node:fs/promises';
import { readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { resolveWithinWorkspace } from '../src/workspace/workspace';
import { ReadState, type ToolContext } from '../src/tools/types';
import { editTool, writeTool, countOccurrences } from '../src/tools/fsWrite';
import { readTool } from '../src/tools/fsRead';

let ws: string;
let readState: ReadState;
let snapshots: string[][];

function ctx(): ToolContext {
  return {
    workspace: ws,
    signal: new AbortController().signal,
    readState,
    snapshot: async (affected) => { snapshots.push(affected); return 'snap-1'; },
    resolvePath: (p) => resolveWithinWorkspace(ws, p),
  };
}

async function read(path: string): Promise<void> {
  await readTool.execute(ctx(), { path });
}

beforeAll(async () => {
  ws = await mkdtemp(join(tmpdir(), 'fswrite-ws-'));
  await mkdir(join(ws, 'src'), { recursive: true });
});

afterAll(async () => {
  await rm(ws, { recursive: true, force: true });
});

describe('edit', () => {
  it('唯一命中精确替换，且执行前打快照', async () => {
    readState = new ReadState();
    snapshots = [];
    await writeFile(join(ws, 'src', 'a.txt'), 'foo bar foo\n');
    await read('src/a.txt');
    const res = await editTool.execute(ctx(), { path: 'src/a.txt', old_string: 'bar', new_string: 'baz' });
    expect(res.text).toContain('已替换 1 处');
    expect(readFileSync(join(ws, 'src', 'a.txt'), 'utf-8')).toBe('foo baz foo\n');
    expect(snapshots.length).toBe(1); // 写前 checkpoint
  });

  it('多处命中且未 replace_all 报错', async () => {
    readState = new ReadState();
    await writeFile(join(ws, 'src', 'b.txt'), 'x x x\n');
    await read('src/b.txt');
    await expect(editTool.execute(ctx(), { path: 'src/b.txt', old_string: 'x', new_string: 'y' }))
      .rejects.toThrow(/不唯一/);
  });

  it('replace_all 全量替换', async () => {
    readState = new ReadState();
    await writeFile(join(ws, 'src', 'c.txt'), 'x x x\n');
    await read('src/c.txt');
    await editTool.execute(ctx(), { path: 'src/c.txt', old_string: 'x', new_string: 'y', replace_all: true });
    expect(readFileSync(join(ws, 'src', 'c.txt'), 'utf-8')).toBe('y y y\n');
  });

  it('未 read 先改 → 拒绝', async () => {
    readState = new ReadState();
    await writeFile(join(ws, 'src', 'd.txt'), 'old\n');
    await expect(editTool.execute(ctx(), { path: 'src/d.txt', old_string: 'old', new_string: 'new' }))
      .rejects.toThrow(/必须先 read/);
  });

  it('read 后被外部修改 → 拒绝并要求重新 read', async () => {
    readState = new ReadState();
    const file = join(ws, 'src', 'e.txt');
    await writeFile(file, 'v1\n');
    await read('src/e.txt');
    await writeFile(file, 'v2-changed\n');
    await utimes(file, new Date(Date.now() + 5000), new Date(Date.now() + 5000)); // 确保 mtime 变化
    await expect(editTool.execute(ctx(), { path: 'src/e.txt', old_string: 'v1', new_string: 'v3' }))
      .rejects.toThrow(/外部修改/);
    await read('src/e.txt'); // 重新 read 后可改
    await editTool.execute(ctx(), { path: 'src/e.txt', old_string: 'v2-changed', new_string: 'v3' });
    expect(readFileSync(file, 'utf-8')).toBe('v3\n');
  });

  it('自身写入后对自己免重读（刷新 mtime 记录）', async () => {
    readState = new ReadState();
    await writeFile(join(ws, 'src', 'f.txt'), 'one\n');
    await read('src/f.txt');
    await editTool.execute(ctx(), { path: 'src/f.txt', old_string: 'one', new_string: 'two' });
    await editTool.execute(ctx(), { path: 'src/f.txt', old_string: 'two', new_string: 'three' });
    expect(readFileSync(join(ws, 'src', 'f.txt'), 'utf-8')).toBe('three\n');
  });
});

describe('write', () => {
  it('创建新文件无需 read', async () => {
    readState = new ReadState();
    const res = await writeTool.execute(ctx(), { path: 'src/new.txt', content: 'hi' });
    expect(res.text).toContain('已创建');
  });

  it('覆写已存在文件必须先 read', async () => {
    readState = new ReadState();
    await writeFile(join(ws, 'src', 'old.txt'), 'legacy\n');
    await expect(writeTool.execute(ctx(), { path: 'src/old.txt', content: 'new' }))
      .rejects.toThrow(/必须先 read/);
    await read('src/old.txt');
    await writeTool.execute(ctx(), { path: 'src/old.txt', content: 'new' });
    expect(readFileSync(join(ws, 'src', 'old.txt'), 'utf-8')).toBe('new');
  });
});

describe('countOccurrences', () => {
  it('计数不重叠出现', () => {
    expect(countOccurrences('aaa', 'aa')).toBe(1);
    expect(countOccurrences('x-x-x', 'x')).toBe(3);
    expect(countOccurrences('abc', 'z')).toBe(0);
  });
});
