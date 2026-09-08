/**
 * Workspace 模块（P0：open / current；P1：resolveWithinWorkspace jail；多工作区：roots + active）。
 * 持久化：{dataDir}/workspace.json；新格式 { roots, active }，兼容旧格式 { path }。
 * 路径存在性由调用方（dialog）保证。
 */
import { existsSync } from 'node:fs';
import { mkdir, readFile, realpath, writeFile } from 'node:fs/promises';
import { basename, dirname, isAbsolute, join, normalize, resolve, sep } from 'node:path';
import type { WorkspaceState } from '@agentbuddy/shared';

export class Workspace {
  private roots: string[] = [];
  private active: string | null = null;
  private readonly file: string;

  constructor(dataDir: string) {
    this.file = join(dataDir, 'workspace.json');
  }

  async init(): Promise<void> {
    await mkdir(dirname(this.file), { recursive: true });
    try {
      const raw = await readFile(this.file, 'utf-8');
      const parsed = JSON.parse(raw) as { path?: unknown; roots?: unknown; active?: unknown };
      if (Array.isArray(parsed.roots)) {
        this.roots = parsed.roots.filter((r): r is string => typeof r === 'string' && r.length > 0);
        this.active = typeof parsed.active === 'string' && this.roots.includes(parsed.active) ? parsed.active : this.roots[0] ?? null;
      } else if (typeof parsed.path === 'string' && parsed.path) {
        // 旧格式兼容：单根直接升级为新格式
        this.roots = [parsed.path];
        this.active = parsed.path;
      }
    } catch {
      /* 首次运行无文件 */
    }
  }

  /** 关联目录（已存在则仅切换活动）；返回最新状态 */
  async open(path: string): Promise<WorkspaceState> {
    const p = normalize(path);
    if (!this.roots.includes(p)) this.roots.push(p);
    this.active = p;
    await this.persist();
    return this.state();
  }

  /** 移除关联目录；移除活动目录时回落到首个根 */
  async remove(path: string): Promise<WorkspaceState> {
    const p = normalize(path);
    this.roots = this.roots.filter((r) => r !== p);
    if (this.active === p) this.active = this.roots[0] ?? null;
    await this.persist();
    return this.state();
  }

  /** 切换活动目录（须已关联） */
  async setActive(path: string): Promise<WorkspaceState> {
    const p = normalize(path);
    if (this.roots.includes(p)) {
      this.active = p;
      await this.persist();
    }
    return this.state();
  }

  state(): WorkspaceState {
    return { roots: [...this.roots], active: this.active };
  }

  rootsList(): string[] {
    return [...this.roots];
  }

  /** 活动目录（相对路径解析 / 命令 cwd / git 归属）；未选择时 null */
  activePath(): string | null {
    return this.active;
  }

  /** 工具层统一入口：用户路径 → 多根工作区内绝对路径，逃逸直接抛错 */
  resolvePath(userPath: string): Promise<string> {
    if (!this.active) return Promise.reject(new Error('未选择工作区目录'));
    return resolveWithinRoots(this.roots, this.active, userPath);
  }

  /** 序列化落盘：连续 open/setActive 的写必须按调用序完成（fire-and-forget 曾致并发乱写、
   * 重载/快速退出读到旧态）；payload 取调用时快照，单次失败不阻塞后续写 */
  private writeChain: Promise<void> = Promise.resolve();
  private persist(): Promise<void> {
    const payload = JSON.stringify({ roots: this.roots, active: this.active });
    const next = this.writeChain.then(() => writeFile(this.file, payload, 'utf-8'));
    this.writeChain = next.catch(() => undefined);
    return next;
  }
}

/**
 * 多根工作区解析（多工作区机制）：
 * - 绝对路径：须落在任一根内，按该根走单根 jail；
 * - 相对路径：候选 = 活动根优先的逐根拼接 + 「首段 = 某根目录名」的去首段拼接（@ 菜单对非活动根带根名前缀）；
 *   已存在的候选优先命中；都不存在时（新建场景）去首段命中根优先，否则落活动根。
 */
export async function resolveWithinRoots(roots: string[], active: string, userPath: string): Promise<string> {
  if (roots.length === 0) throw new Error('未选择工作区目录');
  if (isAbsolute(userPath)) {
    const root = roots.find((r) => isWithin(r, normalize(userPath)));
    if (!root) throw new Error(`路径逃出工作区，已拒绝: ${userPath}`);
    return resolveWithinWorkspace(root, userPath);
  }
  const ordered = [active, ...roots.filter((r) => r !== active)];
  const firstSeg = userPath.split(/[\\/]/)[0] ?? '';
  const stripped = roots.find((r) => basename(r) === firstSeg);
  const candidates: Array<{ root: string; abs: string }> = [
    ...ordered.map((root) => ({ root, abs: normalize(resolve(root, userPath)) })),
    ...(stripped ? [{ root: stripped, abs: normalize(join(stripped, userPath.slice(firstSeg.length).replace(/^[\\/]/, ''))) }] : []),
  ];
  for (const c of candidates) {
    if (existsSync(c.abs)) return resolveWithinWorkspace(c.root, c.abs);
  }
  const fallback = stripped
    ? candidates.find((c) => c.root === stripped && c.abs !== normalize(resolve(stripped, userPath)))
    : undefined;
  const chosen = fallback ?? candidates[0]!;
  return resolveWithinWorkspace(chosen.root, chosen.abs);
}

export function isWithin(root: string, target: string): boolean {
  const r = normalize(root);
  const t = normalize(target);
  return t === r || t.startsWith(r.endsWith(sep) ? r : r + sep);
}

async function realpathOrNone(p: string): Promise<string | null> {
  try {
    return await realpath(p);
  } catch (e) {
    const code = (e as NodeJS.ErrnoException).code;
    if (code === 'ENOENT' || code === 'ENOTDIR') return null;
    throw e; // 无法确认安全 → 拒绝，而不是猜测（AGENTS §15）
  }
}

/**
 * workspace jail（AGENTS §15）：
 * 1) 归一化后必须落在工作区内（拦 ../ 与绝对路径逃逸）；
 * 2) 最深存在祖先的 realpath 必须落在工作区 realpath 内（拦符号链接逃逸）。
 */
export async function resolveWithinWorkspace(root: string, userPath: string): Promise<string> {
  const abs = normalize(isAbsolute(userPath) ? userPath : resolve(root, userPath));
  if (!isWithin(root, abs)) throw new Error(`路径逃出工作区，已拒绝: ${userPath}`);

  const realRoot = await realpathOrNone(root);
  if (realRoot === null) throw new Error(`工作区不存在或不可访问: ${root}`);

  let cur = abs;
  for (;;) {
    const real = await realpathOrNone(cur);
    if (real !== null) {
      if (!isWithin(realRoot, real)) throw new Error(`符号链接指向工作区外，已拒绝: ${userPath}`);
      break;
    }
    const parent = dirname(cur);
    if (parent === cur) break;
    cur = parent;
  }
  return abs;
}
