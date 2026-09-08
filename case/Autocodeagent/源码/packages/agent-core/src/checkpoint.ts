/**
 * Checkpoint（技术方案 §4.8 / P1 任务 7 / P2 任务 4-5）：
 * WRITE/EXEC 前打快照；ChangeSet 显式建模 modified / created / deleted / renamed 四类，
 * restore 逐类处理（新增→删除、删除→恢复、重命名→反向还原）；
 * accept/restore 状态机：pending → accepted | reverted（审阅只处理一次）。
 * git 仓库：无受影响文件清单时（bash）记 `git stash create --include-untracked` 整树快照，
 *           撤销用 `git checkout <hash> -- .` 还原到快照时刻。
 */
import { execFile } from 'node:child_process';
import { copyFile, mkdir, readdir, readFile, rm, stat, unlink, writeFile } from 'node:fs/promises';
import { dirname, join, relative, sep } from 'node:path';

export type ReviewStatus = 'pending' | 'accepted' | 'reverted';
export type EntryKind = 'modified' | 'created' | 'deleted' | 'renamed';

/** 统一条目模型：from = 原路径/原内容侧，to = 新路径/新内容侧 */
export interface ChangeEntry {
  kind: EntryKind;
  /** modified/deleted：原文件；created：新文件；renamed：原路径 */
  from: string;
  /** created：无；renamed：新路径 */
  to?: string;
  /** 备份文件相对路径（{dataDir}/snapshots/{changeId}/ 内） */
  backup?: string;
}

export interface ChangeSet {
  changeId: string;
  sessionId: string;
  status: ReviewStatus;
  /** git 整树快照（bash 等无受影响清单场景），撤销时 checkout 还原；
   *  也作为条目路径 → 相对路径换算的基准（Diff 视图展示） */
  gitHash?: string;
  /** 快照对应的工作区根 */
  workspace?: string;
  entries: ChangeEntry[];
  createdAt: number;
}

export class Checkpoint {
  private readonly dir: string;

  constructor(dataDir: string) {
    this.dir = join(dataDir, 'snapshots');
  }

  /**
   * WRITE/EXEC 前快照：有受影响文件清单 → 文件级备份（git/非 git 一致，撤销精确）；
   * 无清单且 git 仓库 → 整树快照；否则返回 null。
   */
  async snapshot(workspace: string, affected: string[], changeId: string, sessionId: string): Promise<ChangeSet | null> {
    if (affected.length > 0) {
      const entries: ChangeEntry[] = [];
      for (const abs of affected) {
        const exists = await stat(abs).then((s) => s.isFile()).catch(() => false);
        if (!exists) {
          entries.push({ kind: 'created', from: abs });
          continue;
        }
        const backup = await this.backupFile(changeId, workspace, abs);
        entries.push({ kind: 'modified', from: abs, backup });
      }
      return this.record({ changeId, sessionId, status: 'pending', workspace, entries, createdAt: Date.now() });
    }
    const gitHash = (await gitStashCreate(workspace)) ?? undefined;
    if (!gitHash) return null;
    return this.record({ changeId, sessionId, status: 'pending', gitHash, workspace, entries: [], createdAt: Date.now() });
  }

  /** 显式登记 deleted / renamed 等条目（当前由 bash 之外的扩展工具使用；撤销四类语义完整） */
  async recordEntry(sessionId: string, entry: ChangeEntry): Promise<ChangeSet> {
    const set: ChangeSet = {
      changeId: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
      sessionId,
      status: 'pending',
      entries: [entry],
      createdAt: Date.now(),
    };
    if ((entry.kind === 'deleted' || entry.kind === 'renamed') && entry.backup === undefined) {
      throw new Error(`${entry.kind} 条目必须提供备份或显式 backup 标记`);
    }
    return this.record(set);
  }

  async get(changeId: string): Promise<ChangeSet | null> {
    try {
      return JSON.parse(await readFile(this.metaFile(changeId), 'utf-8')) as ChangeSet;
    } catch {
      return null;
    }
  }

  /** 会话维度的审阅清单（右栏 Diff 面板，倒序） */
  async list(sessionId?: string): Promise<ChangeSet[]> {
    let files: string[];
    try {
      files = await readdir(this.dir);
    } catch {
      return [];
    }
    const result: ChangeSet[] = [];
    for (const f of files) {
      if (!f.endsWith('.json')) continue;
      const set = await this.get(f.slice(0, -5));
      if (set && (!sessionId || set.sessionId === sessionId)) result.push(set);
    }
    return result.sort((a, b) => b.createdAt - a.createdAt);
  }

  /** 接受修改：变更已在工作区，仅固化审阅状态 */
  async accept(changeId: string): Promise<ChangeSet> {
    const set = await this.mustPending(changeId);
    set.status = 'accepted';
    return this.record(set);
  }

  /** 撤销 = 按条目逐类还原（P2 任务 4） */
  async restore(changeId: string): Promise<ChangeSet> {
    const set = await this.mustPending(changeId);
    await this.applyRestore(set);
    set.status = 'reverted';
    return this.record(set);
  }

  /**
   * P2 3.3 节点回溯专用：强制回滚单个变更——
   * 与 restore 的区别是不要求 pending（已 accepted 也回滚），供「回到此处重来」逆序批量调用；
   * 已 reverted / 不存在视为已撤销直接跳过。返回 true = 本次实际执行了还原。
   */
  async restoreForRollback(changeId: string): Promise<boolean> {
    const set = await this.get(changeId);
    if (!set || set.status === 'reverted') return false;
    await this.applyRestore(set);
    set.status = 'reverted';
    await this.record(set);
    return true;
  }

  /** 还原实现：git 整树快照 → checkout 到快照时刻；否则逐条目按类还原 */
  private async applyRestore(set: ChangeSet): Promise<void> {
    if (set.gitHash && set.entries.length === 0) {
      await gitCheckout(set.gitHash, this.workspaceOf(set));
    } else {
      for (const e of set.entries) await this.restoreEntry(set.changeId, e);
    }
  }

  async cleanup(changeId: string): Promise<void> {
    await rm(join(this.dir, changeId), { recursive: true, force: true });
    await unlink(this.metaFile(changeId)).catch(() => undefined);
  }

  backupPath(changeId: string, backup: string): string {
    return join(this.dir, changeId, backup);
  }

  private metaFile(changeId: string): string {
    return join(this.dir, `${changeId}.json`);
  }

  private async mustPending(changeId: string): Promise<ChangeSet> {
    const set = await this.get(changeId);
    if (!set) throw new Error(`快照不存在: ${changeId}`);
    if (set.status !== 'pending') throw new Error(`该修改已${set.status === 'accepted' ? '接受' : '撤销'}，不可重复操作`);
    return set;
  }

  /** restore 后工作区已回到快照基线，下一条快照基于干净状态（无脏状态串扰） */
  private async restoreEntry(changeId: string, e: ChangeEntry): Promise<void> {
    if (e.kind === 'created') {
      await unlink(e.from).catch(() => undefined); // 新增文件 → 删除
      return;
    }
    if (!e.backup) throw new Error(`条目缺少备份，无法撤销: ${e.from}`);
    const backup = this.backupPath(changeId, e.backup);
    if (e.kind === 'renamed') {
      if (!e.to) throw new Error('renamed 条目缺少目标路径');
      await unlink(e.to).catch(() => undefined); // 删除重命名后的文件
    }
    await mkdir(dirname(e.from), { recursive: true });
    await copyFile(backup, e.from); // 修改/删除/重命名 → 还原原内容到原路径
  }

  private async backupFile(changeId: string, workspace: string, abs: string): Promise<string> {
    const rel = relSafe(workspace, abs);
    const dest = join(this.dir, changeId, rel);
    await mkdir(dirname(dest), { recursive: true });
    await copyFile(abs, dest);
    return rel;
  }

  private workspaceOf(set: ChangeSet): string {
    if (!set.workspace) throw new Error('git 快照缺少工作区信息');
    return set.workspace;
  }

  private async record(set: ChangeSet): Promise<ChangeSet> {
    await mkdir(this.dir, { recursive: true });
    await writeFile(this.metaFile(set.changeId), JSON.stringify(set, null, 2), 'utf-8');
    return set;
  }
}

function relSafe(workspace: string, abs: string): string {
  const rel = relative(workspace, abs);
  if (rel.startsWith('..') || rel.includes(`..${sep}`)) throw new Error('快照路径异常，已拒绝');
  return rel;
}

/** git 仓库检测 + stash create（不动工作区、无提交噪音）；非 git / 无改动返回 null */
async function gitStashCreate(workspace: string): Promise<string | null> {
  const isRepo = await new Promise<boolean>((resolve) => {
    execFile('git', ['rev-parse', '--is-inside-work-tree'], { cwd: workspace }, (err, out) => {
      resolve(!err && out.trim() === 'true');
    });
  });
  if (!isRepo) return null;
  return new Promise((resolve) => {
    execFile('git', ['stash', 'create', '--include-untracked'], { cwd: workspace }, (err, out) => {
      if (err) return resolve(null);
      resolve(out.trim() || null);
    });
  });
}

/** 整树还原到快照时刻（含被删文件恢复；快照后新增的未跟踪文件不影响已跟踪内容） */
function gitCheckout(hash: string, workspace: string): Promise<void> {
  return new Promise((resolve, reject) => {
    execFile('git', ['checkout', hash, '--', '.'], { cwd: workspace }, (err) => {
      if (err) reject(new Error(`git 快照还原失败: ${err.message}`));
      else resolve();
    });
  });
}
