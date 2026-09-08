/**
 * 工作区只读浏览（P2 任务 7 / 顶栏状态条）：
 * 文件树（排除噪音目录、条目数封顶）、单文件只读读取（大小封顶，经 workspace jail）、
 * git 信息（分支 + 脏文件数，非仓库返回 null）。
 */
import { execFile } from 'node:child_process';
import { readFile, readdir, stat } from 'node:fs/promises';
import { basename, extname, join } from 'node:path';
import type { GitInfo, TreeNode } from '@agentbuddy/shared';
import { resolveWithinRoots } from './workspace';

/** 文件树排除目录（依赖产物/缓存噪音） */
const EXCLUDED_DIRS = new Set(['node_modules', '.git', 'dist', 'build', '.next', '__pycache__', '.venv', 'coverage']);
const MAX_TREE_NODES = 2000;
const MAX_TREE_DEPTH = 8;
/** 代码查看单文件上限（512KB），超出提示过大 */
const MAX_FILE_BYTES = 512 * 1024;

/** 递归构建文件树（目录优先、按名排序；超额截断并停止扩展）。
 * 多工作区：活动根条目平铺顶层；非活动根以「根目录名」为顶层文件夹节点挂载（@ 提及路径带该前缀） */
export async function workspaceTree(roots: string[], active: string | null): Promise<TreeNode[]> {
  let count = 0;

  async function walk(abs: string, rel: string, depth: number): Promise<TreeNode[]> {
    if (depth > MAX_TREE_DEPTH || count >= MAX_TREE_NODES) return [];
    let entries;
    try {
      entries = await readdir(abs, { withFileTypes: true });
    } catch {
      return [];
    }
    const nodes: TreeNode[] = [];
    const sorted = entries
      .filter((e) => !(e.isDirectory() && EXCLUDED_DIRS.has(e.name)))
      .sort((a, b) => (a.isDirectory() === b.isDirectory() ? a.name.localeCompare(b.name) : a.isDirectory() ? -1 : 1));
    for (const e of sorted) {
      if (count >= MAX_TREE_NODES) break;
      count++;
      const path = rel ? `${rel}/${e.name}` : e.name;
      if (e.isDirectory()) {
        nodes.push({ name: e.name, path, dir: true, children: await walk(join(abs, e.name), path, depth + 1) });
      } else if (e.isFile()) {
        nodes.push({ name: e.name, path, dir: false });
      }
    }
    return nodes;
  }

  const out: TreeNode[] = [];
  const ordered = [...(active ? [active] : []), ...roots.filter((r) => r !== active)];
  for (const root of ordered) {
    if (count >= MAX_TREE_NODES) break;
    if (root === active) {
      out.push(...await walk(root, '', 0));
    } else {
      count++;
      out.push({ name: basename(root), path: basename(root), dir: true, children: await walk(root, basename(root), 1) });
    }
  }
  return out;
}

/** 只读读取工作区文件：用户路径 → 多根 jail 校验 → 大小封顶（返回空表示空文件） */
export async function readWorkspaceFile(roots: string[], active: string | null, userPath: string): Promise<string> {
  if (!active) throw new Error('未选择工作区目录');
  const abs = await resolveWithinRoots(roots, active, userPath);
  const st = await stat(abs);
  if (!st.isFile()) throw new Error('不是文件，无法读取');
  if (st.size > MAX_FILE_BYTES) throw new Error(`文件过大（${Math.round(st.size / 1024)}KB），暂不支持查看`);
  return readFile(abs, 'utf-8');
}

/** 预览单文件上限（25MB）：文档/二进制预览比代码查看放宽 */
const PREVIEW_MAX_BYTES = 25 * 1024 * 1024;

/** 预览 mime 映射（按扩展名）；未列出的回落 octet-stream */
const PREVIEW_MIME: Record<string, string> = {
  html: 'text/html; charset=utf-8',
  htm: 'text/html; charset=utf-8',
  md: 'text/markdown; charset=utf-8',
  markdown: 'text/markdown; charset=utf-8',
  svg: 'image/svg+xml',
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  gif: 'image/gif',
  webp: 'image/webp',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  pdf: 'application/pdf',
};

export interface WorkspacePreview {
  base64: string;
  mime: string;
  size: number;
}

/** 预览读取：jail 校验 → 大小封顶 → base64（文档/二进制统一通道，渲染端按 mime 分流渲染） */
export async function readWorkspaceFileBase64(roots: string[], active: string | null, userPath: string): Promise<WorkspacePreview> {
  if (!active) throw new Error('未选择工作区目录');
  const abs = await resolveWithinRoots(roots, active, userPath);
  const st = await stat(abs);
  if (!st.isFile()) throw new Error('不是文件，无法预览');
  if (st.size > PREVIEW_MAX_BYTES) throw new Error(`文件过大（${Math.round(st.size / 1024 / 1024)}MB），暂不支持预览`);
  const buf = await readFile(abs);
  const ext = extname(abs).slice(1).toLowerCase();
  return { base64: buf.toString('base64'), mime: PREVIEW_MIME[ext] ?? 'application/octet-stream', size: st.size };
}

/** git 分支与脏文件数；非仓库或无 git 返回 null */
export async function gitInfo(root: string): Promise<GitInfo | null> {
  const branch = await git(root, ['rev-parse', '--abbrev-ref', 'HEAD']);
  if (branch === null) return null;
  const status = await git(root, ['status', '--porcelain']);
  const dirty = status === null ? 0 : status.split('\n').filter((l) => l.trim().length > 0).length;
  return { branch, dirty };
}

function git(cwd: string, args: string[]): Promise<string | null> {
  return new Promise((resolve) => {
    execFile('git', args, { cwd }, (err, out) => {
      resolve(err ? null : out.trim());
    });
  });
}

export const WORKSPACE_VIEW_LIMITS = { maxNodes: MAX_TREE_NODES, maxDepth: MAX_TREE_DEPTH, maxFileBytes: MAX_FILE_BYTES };
