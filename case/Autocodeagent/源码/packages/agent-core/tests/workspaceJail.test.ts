/** workspace jail 单测（P1 验收：resolveWithinWorkspace 逃逸用例，AGENTS §15） */
import { mkdtemp, mkdir, rm, symlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { resolveWithinWorkspace } from '../src/workspace/workspace';

let root: string;
let outside: string;

beforeAll(async () => {
  root = await mkdtemp(join(tmpdir(), 'jail-ws-'));
  outside = await mkdtemp(join(tmpdir(), 'jail-out-'));
  await mkdir(join(root, 'src'), { recursive: true });
  await writeFile(join(root, 'src', 'a.txt'), 'hello');
  await writeFile(join(outside, 'secret.txt'), 'top secret');
});

afterAll(async () => {
  await rm(root, { recursive: true, force: true });
  await rm(outside, { recursive: true, force: true });
});

describe('resolveWithinWorkspace', () => {
  it('工作区内相对路径放行', async () => {
    const abs = await resolveWithinWorkspace(root, 'src/a.txt');
    expect(abs).toBe(join(root, 'src', 'a.txt'));
  });

  it('工作区内绝对路径放行', async () => {
    const abs = await resolveWithinWorkspace(root, join(root, 'src', 'a.txt'));
    expect(abs).toBe(join(root, 'src', 'a.txt'));
  });

  it('../ 相对逃逸拒绝', async () => {
    await expect(resolveWithinWorkspace(root, '../secret.txt')).rejects.toThrow(/逃出工作区/);
    await expect(resolveWithinWorkspace(root, 'src/../../secret.txt')).rejects.toThrow(/逃出工作区/);
  });

  it('绝对路径逃逸拒绝', async () => {
    await expect(resolveWithinWorkspace(root, join(outside, 'secret.txt'))).rejects.toThrow(/逃出工作区/);
  });

  it('工作区不存在拒绝', async () => {
    await expect(resolveWithinWorkspace(join(root, 'no-such-dir'), 'a.txt')).rejects.toThrow(/工作区不存在/);
  });

  it('符号链接指向工作区外拒绝', async () => {
    try {
      await symlink(outside, join(root, 'escape'));
    } catch {
      return; // 无权限创建符号链接的环境跳过
    }
    await expect(resolveWithinWorkspace(root, 'escape/secret.txt')).rejects.toThrow(/符号链接/);
  });

  it('不存在的深层新文件路径放行（写入场景）', async () => {
    const abs = await resolveWithinWorkspace(root, 'src/new/deep/b.txt');
    expect(abs).toBe(join(root, 'src', 'new', 'deep', 'b.txt'));
  });
});
