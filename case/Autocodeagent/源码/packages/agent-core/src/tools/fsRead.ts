/**
 * 只读工具：read / glob / grep（risk=READ，Ask 模式自动放行）。
 * read 单次 ≤2000 行（§4.3 源头限流），并记录 mtime 供 edit/write 新鲜度校验。
 */
import { readFile, readdir, stat } from 'node:fs/promises';
import { join, relative } from 'node:path';
import { num, str, type Tool } from './types';

export const READ_MAX_LINES = 2000;
const GREP_MAX_MATCHES = 200;
const GLOB_MAX_RESULTS = 500;
const GREP_MAX_FILE_BYTES = 1024 * 1024;
const SKIP_DIRS = new Set(['node_modules', '.git', 'dist', '.agent']);

export const readTool: Tool = {
  name: 'read',
  description: '读取工作区内文本文件，输出带行号内容；单次最多 2000 行，可用 offset/limit 分段。',
  parameters: {
    type: 'object',
    properties: {
      path: { type: 'string', description: '相对或绝对路径' },
      offset: { type: 'number', description: '起始行号（1 起，默认 1）' },
      limit: { type: 'number', description: `最多读取行数（默认且上限 ${READ_MAX_LINES}）` },
    },
    required: ['path'],
  },
  risk: 'READ',
  async execute(ctx, input) {
    const path = await ctx.resolvePath(str(input, 'path'));
    const st = await stat(path);
    if (st.isDirectory()) throw new Error(`是目录，不是文件: ${path}`);
    const raw = await readFile(path, 'utf-8');
    const lines = raw.split(/\r?\n/);
    const offset = Math.max(1, num(input, 'offset', 1));
    const limit = Math.min(READ_MAX_LINES, Math.max(1, num(input, 'limit', READ_MAX_LINES)));
    const window = lines.slice(offset - 1, offset - 1 + limit);
    const body = window.map((l, i) => `${offset + i}\t${l}`).join('\n');
    const more = lines.length - (offset - 1 + window.length);
    ctx.readState.record(path, st.mtimeMs);
    const note = more > 0 ? `\n…（截断：还有 ${more} 行，请用 offset 继续读）` : '';
    return { text: body + note };
  },
};

export const globTool: Tool = {
  name: 'glob',
  description: '按 glob 模式（如 **/*.ts）在工作区内查找文件，返回相对路径列表（≤500）。',
  parameters: {
    type: 'object',
    properties: { pattern: { type: 'string', description: 'glob 模式' } },
    required: ['pattern'],
  },
  risk: 'READ',
  async execute(ctx, input) {
    if (!ctx.workspace) throw new Error('未选择工作区目录');
    const regex = globToRegex(str(input, 'pattern'));
    const hits: string[] = [];
    await walk(ctx.workspace, ctx.workspace, (rel) => {
      if (hits.length < GLOB_MAX_RESULTS && regex.test(rel.replace(/\\/g, '/'))) hits.push(rel);
    });
    if (hits.length === 0) return { text: '（无匹配文件）' };
    return { text: hits.join('\n') + (hits.length >= GLOB_MAX_RESULTS ? '\n…（达到 500 上限）' : '') };
  },
};

export const grepTool: Tool = {
  name: 'grep',
  description: '在工作区文件内容中搜索正则表达式，返回「相对路径:行号: 内容」（≤200 条）。',
  parameters: {
    type: 'object',
    properties: {
      pattern: { type: 'string', description: '正则表达式' },
      path: { type: 'string', description: '限定子目录（可选）' },
      ignoreCase: { type: 'boolean', description: '忽略大小写（可选）' },
    },
    required: ['pattern'],
  },
  risk: 'READ',
  async execute(ctx, input) {
    if (!ctx.workspace) throw new Error('未选择工作区目录');
    let regex: RegExp;
    try {
      regex = new RegExp(str(input, 'pattern'), input['ignoreCase'] === true ? 'i' : '');
    } catch (e) {
      throw new Error(`正则非法: ${e instanceof Error ? e.message : String(e)}`);
    }
    const root = input['path'] ? await ctx.resolvePath(str(input, 'path')) : ctx.workspace;
    const matches: string[] = [];
    await walk(ctx.workspace, root, async (rel, abs) => {
      if (matches.length >= GREP_MAX_MATCHES) return;
      const st = await stat(abs).catch(() => null);
      if (!st || st.size > GREP_MAX_FILE_BYTES) return;
      const content = await readFile(abs, 'utf-8').catch(() => '');
      const lines = content.split(/\r?\n/);
      for (let i = 0; i < lines.length && matches.length < GREP_MAX_MATCHES; i++) {
        if (regex.test(lines[i]!)) matches.push(`${rel.replace(/\\/g, '/')}:${i + 1}: ${lines[i]}`);
      }
    });
    if (matches.length === 0) return { text: '（无匹配）' };
    return { text: matches.join('\n') + (matches.length >= GREP_MAX_MATCHES ? '\n…（达到 200 上限）' : '') };
  },
};

/** 深度优先遍历；onVisit 收相对路径与绝对路径 */
export async function walk(
  wsRoot: string,
  dir: string,
  onVisit: (rel: string, abs: string) => void | Promise<void>,
): Promise<void> {
  const entries = await readdir(dir, { withFileTypes: true }).catch(() => []);
  for (const entry of entries) {
    const abs = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (SKIP_DIRS.has(entry.name)) continue;
      await walk(wsRoot, abs, onVisit);
    } else if (entry.isFile()) {
      await onVisit(relative(wsRoot, abs), abs);
    }
  }
}

/** 最小 glob → RegExp：支持 ** * ? {a,b} */
export function globToRegex(pattern: string): RegExp {
  let out = '';
  let i = 0;
  const p = pattern.replace(/\\/g, '/');
  while (i < p.length) {
    const ch = p[i]!;
    if (ch === '*') {
      if (p[i + 1] === '*') {
        out += '.*';
        i += p[i + 2] === '/' ? 3 : 2;
        continue;
      }
      out += '[^/]*';
      i++;
      continue;
    }
    if (ch === '?') {
      out += '[^/]';
      i++;
      continue;
    }
    if (ch === '{') {
      const end = p.indexOf('}', i);
      if (end > i) {
        out += `(?:${p.slice(i + 1, end).split(',').map(escapeRegex).join('|')})`;
        i = end + 1;
        continue;
      }
    }
    out += escapeRegex(ch);
    i++;
  }
  return new RegExp(`^${out}$`);
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

export const READ_TOOLS: Tool[] = [readTool, globTool, grepTool];
