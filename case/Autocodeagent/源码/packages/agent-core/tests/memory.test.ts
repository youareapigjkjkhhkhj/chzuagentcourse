/**
 * 工作区记忆单测：memory.ts 文件 I/O（追加/读取/尾部截断）+ REMEMBER_TOOL 校验与落盘 + bus 注册。
 */
import { mkdir, mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import { appendMemory, MEMORY_DIR, MEMORY_FILE, memoryPath, readMemory } from '../src/memory';
import { REMEMBER_TOOL } from '../src/tools/memoryTool';
import { createBuiltinBus } from '../src/tools/bus';
import { ReadState, type ToolContext } from '../src/tools/types';

let ws: string;
beforeAll(async () => {
  ws = await mkdtemp(join(tmpdir(), 'mem-ws-'));
});
afterAll(async () => {
  await rm(ws, { recursive: true, force: true });
});

function ctx(workspace: string | null): ToolContext {
  return {
    workspace,
    signal: new AbortController().signal,
    readState: new ReadState(),
    snapshot: async () => null,
    resolvePath: async (p) => p,
  };
}

/** 每个用例独立临时工作区，避免记忆文件互相污染 */
async function freshWs(tag: string): Promise<string> {
  return mkdtemp(join(tmpdir(), `mem-${tag}-`));
}

describe('memory 文件 I/O', () => {
  it('memoryPath 指向 <ws>/.AgentBuddy/memory.md', () => {
    expect(memoryPath(ws)).toBe(join(ws, MEMORY_DIR, MEMORY_FILE));
  });

  it('readMemory：文件缺失返回 null', async () => {
    const dir = await freshWs('absent');
    expect(await readMemory(dir)).toBeNull();
    await rm(dir, { recursive: true, force: true });
  });

  it('appendMemory：首次创建写文件头 + 追加带日期条目；readMemory 可读回', async () => {
    const dir = await freshWs('first');
    const line = await appendMemory(dir, '用户偏好简洁回复');
    expect(line).toMatch(/^- \[\d{4}-\d{2}-\d{2}\] 用户偏好简洁回复$/);
    const raw = await readFile(memoryPath(dir), 'utf-8');
    expect(raw).toContain('# AgentBuddy 工作区记忆'); // 文件头
    expect(raw).toContain('- [');
    expect(await readMemory(dir)).toContain('用户偏好简洁回复');
    await rm(dir, { recursive: true, force: true });
  });

  it('appendMemory：多次追加累积；多行文本压成单行 bullet', async () => {
    const dir = await freshWs('multi');
    await appendMemory(dir, '第一条');
    await appendMemory(dir, '第二条\n换行');
    const body = (await readMemory(dir))!;
    expect(body).toContain('第一条');
    expect(body).toContain('第二条 换行'); // 换行被压成空格
    expect(body.match(/^- \[/gm)).toHaveLength(2); // 两条 bullet
    await rm(dir, { recursive: true, force: true });
  });

  it('readMemory：超上限保近端尾部 + 省略提示（丢最早、留最近）', async () => {
    const dir = await freshWs('cap');
    await mkdir(join(dir, MEMORY_DIR), { recursive: true });
    const many = Array.from({ length: 400 }, (_, i) => `- [2026-09-12] 记忆条目 ${i} ${'x'.repeat(40)}`).join('\n');
    await writeFile(memoryPath(dir), `# AgentBuddy 工作区记忆\n\n${many}\n`);
    const body = (await readMemory(dir))!;
    expect(body).toContain('较早记忆已省略');
    expect(body).toContain('记忆条目 399'); // 保留最近
    expect(body).not.toContain('记忆条目 0 '); // 丢弃最早
    expect(body.length).toBeLessThan(8400); // 上限 8000 + 省略提示
    await rm(dir, { recursive: true, force: true });
  });
});

describe('remember 工具', () => {
  it('合法：写入记忆文件 + 回执', async () => {
    const dir = await freshWs('tool-ok');
    const out = await REMEMBER_TOOL.execute(ctx(dir), { text: '项目用 pnpm 而非 npm' });
    expect(out.text).toContain('已记入工作区记忆');
    expect(await readMemory(dir)).toContain('项目用 pnpm 而非 npm');
    await rm(dir, { recursive: true, force: true });
  });

  it('非法：空 / 超长 / 无工作区 均报错', async () => {
    const dir = await freshWs('tool-bad');
    await expect(REMEMBER_TOOL.execute(ctx(dir), { text: '   ' })).rejects.toThrow('不能为空');
    await expect(REMEMBER_TOOL.execute(ctx(dir), { text: 'x'.repeat(501) })).rejects.toThrow('500');
    await expect(REMEMBER_TOOL.execute(ctx(null), { text: '有效内容' })).rejects.toThrow('工作区');
    await expect(REMEMBER_TOOL.execute(ctx(dir), {})).rejects.toThrow('必须为字符串');
    await rm(dir, { recursive: true, force: true });
  });

  it('注册进内置 bus，风险 READ（各模式免确认）', () => {
    expect(createBuiltinBus().get('remember')).toBeTruthy();
    expect(REMEMBER_TOOL.risk).toBe('READ');
  });
});
