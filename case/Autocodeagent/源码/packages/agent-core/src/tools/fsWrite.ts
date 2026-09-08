/**
 * 写工具：write / edit（risk=WRITE，Ask 模式逐次确认）。
 * 新鲜度校验：文件在 read 之后被外部修改 → 拒绝并要求重新 read（§4.3）；
 * 执行前经 ctx.snapshot 打 checkpoint（§4.8）。
 */
import { readFile, stat, writeFile } from 'node:fs/promises';
import { str, type Tool } from './types';

type FreshCtx = { readState: { known(p: string): number | undefined; record(p: string, m: number): void } };

async function assertFresh(ctx: FreshCtx, path: string): Promise<void> {
  const known = ctx.readState.known(path);
  if (known === undefined) throw new Error('修改前必须先 read 该文件（防止基于陈旧内容盲改）');
  const st = await stat(path);
  if (st.mtimeMs !== known) throw new Error('文件在 read 之后被外部修改，已拒绝执行，请重新 read');
}

export const writeTool: Tool = {
  name: 'write',
  description: '创建或整体覆写工作区文件。覆写已存在文件前必须先 read（新鲜度校验）。',
  parameters: {
    type: 'object',
    properties: {
      path: { type: 'string', description: '相对或绝对路径' },
      content: { type: 'string', description: '完整文件内容' },
    },
    required: ['path', 'content'],
  },
  risk: 'WRITE',
  async execute(ctx, input) {
    const path = await ctx.resolvePath(str(input, 'path'));
    const content = str(input, 'content');
    const exists = await stat(path).then((s) => s.isFile()).catch(() => false);
    if (exists) await assertFresh(ctx, path);
    const changeId = await ctx.snapshot([path]);
    await writeFile(path, content, 'utf-8');
    await refreshReadTime(ctx, path);
    return {
      text: `${exists ? '已覆写' : '已创建'}: ${path}（${content.length} 字符）`,
      change: changeId ? { changeId, paths: [path] } : undefined,
    };
  },
};

export const editTool: Tool = {
  name: 'edit',
  description: '精确字符串替换（str_replace）。old_string 必须唯一命中，除非 replace_all=true。',
  parameters: {
    type: 'object',
    properties: {
      path: { type: 'string' },
      old_string: { type: 'string', description: '要被替换的原文（精确匹配，含空白）' },
      new_string: { type: 'string' },
      replace_all: { type: 'boolean', description: '替换全部出现处（默认 false）' },
    },
    required: ['path', 'old_string', 'new_string'],
  },
  risk: 'WRITE',
  async execute(ctx, input) {
    const path = await ctx.resolvePath(str(input, 'path'));
    const oldStr = str(input, 'old_string');
    const newStr = str(input, 'new_string');
    if (!oldStr) throw new Error('old_string 不能为空');
    if (oldStr === newStr) throw new Error('old_string 与 new_string 相同，无需修改');

    await assertFresh(ctx, path);
    const raw = await readFile(path, 'utf-8');
    const count = countOccurrences(raw, oldStr);
    if (count === 0) throw new Error('old_string 未在文件中找到，请重新 read 后核对原文');
    if (count > 1 && input['replace_all'] !== true) {
      throw new Error(`old_string 命中 ${count} 处不唯一，请提供更多上下文或设置 replace_all=true`);
    }
    const replaced = input['replace_all'] === true ? raw.split(oldStr).join(newStr) : raw.replace(oldStr, newStr);
    const changeId = await ctx.snapshot([path]);
    await writeFile(path, replaced, 'utf-8');
    await refreshReadTime(ctx, path);
    return {
      text: `已替换 ${count} 处: ${path}`,
      change: changeId ? { changeId, paths: [path] } : undefined,
    };
  },
};

export function countOccurrences(haystack: string, needle: string): number {
  let count = 0;
  let idx = haystack.indexOf(needle);
  while (idx !== -1) {
    count++;
    idx = haystack.indexOf(needle, idx + needle.length);
  }
  return count;
}

export const WRITE_TOOLS: Tool[] = [writeTool, editTool];

/** 自身写入后刷新 mtime 记录，避免对自己刚写的内容强制重读 */
async function refreshReadTime(ctx: FreshCtx, path: string): Promise<void> {
  const st = await stat(path).catch(() => null);
  if (st) ctx.readState.record(path, st.mtimeMs);
}
