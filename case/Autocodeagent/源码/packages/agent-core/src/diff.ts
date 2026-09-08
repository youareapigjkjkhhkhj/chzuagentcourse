/**
 * Diff 模块（P2 任务 3）：行级对比（Myers 贪心，受控规模）+
 * ChangeSet → DiffView 计算（备份内容 = 旧侧，当前工作区 = 新侧）。
 * 展示类型复用 @agentbuddy/shared（三层共用，无 Node 依赖）。
 */
import { readFile } from 'node:fs/promises';
import { relative, sep } from 'node:path';
import type { ChangeSetView, DiffLine, DiffView, FileDiff } from '@agentbuddy/shared';
import type { ChangeSet } from './checkpoint';
import { Checkpoint } from './checkpoint';

/** 单侧行数上限，超过则不做逐行对比（防止 Myers O((N+M)·D) 爆炸） */
const MAX_DIFF_LINES = 4000;

/** 行级 Myers diff：返回 ctx/del/add 序列，携带双侧行号 */
export function diffLines(oldText: string, newText: string): DiffLine[] {
  const a = splitLines(oldText);
  const b = splitLines(newText);
  if (a.length > MAX_DIFF_LINES || b.length > MAX_DIFF_LINES) {
    return [
      ...a.map((text, i) => ({ kind: 'del' as const, text, oldNo: i + 1 })),
      ...b.map((text, i) => ({ kind: 'add' as const, text, newNo: i + 1 })),
    ];
  }

  const n = a.length;
  const m = b.length;
  const max = n + m;
  if (max === 0) return [];

  // v[k] = 对角线 k 上到达的最远 x；trace 记录每轮快照用于回溯（贪心 Myers）
  const v = new Map<number, number>([[1, 0]]);
  const trace: Array<Map<number, number>> = [];
  let dFinal = 0;
  outer: for (let d = 0; d <= max; d++) {
    trace.push(new Map(v));
    dFinal = d;
    for (let k = -d; k <= d; k += 2) {
      const down = k === -d || (k !== d && (v.get(k - 1) ?? 0) < (v.get(k + 1) ?? 0));
      let x = down ? (v.get(k + 1) ?? 0) : (v.get(k - 1) ?? 0) + 1;
      let y = x - k;
      while (x < n && y < m && a[x] === b[y]) {
        x++;
        y++;
      }
      v.set(k, x);
      if (x >= n && y >= m) break outer;
    }
  }

  // 回溯编辑路径：每步记录蛇形滑对角线的终点 (x, y)
  const path: Array<[number, number]> = [];
  let x = n;
  let y = m;
  for (let d = dFinal; d > 0; d--) {
    const vd = trace[d] ?? new Map<number, number>();
    const k = x - y;
    // 蛇形终点：从 k-1 向右（删除）或从 k+1 向下（插入）到达 k
    const sx = k > -d && (k === d || (vd.get(k - 1) ?? 0) >= (vd.get(k + 1) ?? 0)) ? (vd.get(k - 1) ?? 0) + 1 : (vd.get(k + 1) ?? 0);
    path.push([sx, sx - k]);
    // 编辑前位置（上一步蛇形终点）
    const pk = k > -d && (k === d || (vd.get(k - 1) ?? 0) >= (vd.get(k + 1) ?? 0)) ? k - 1 : k + 1;
    const px = vd.get(pk) ?? 0;
    x = px;
    y = px - pk;
  }
  path.push([x, y]);
  path.reverse();

  // 拐点序列 → ctx/del/add 行序列
  const lines: DiffLine[] = [];
  let cx = 0;
  let cy = 0;
  for (const [px, py] of path) {
    while (cx < px && cy < py) {
      lines.push({ kind: 'ctx', text: a[cx] ?? '', oldNo: cx + 1, newNo: cy + 1 });
      cx++;
      cy++;
    }
    while (cy < py) {
      lines.push({ kind: 'add', text: b[cy] ?? '', newNo: cy + 1 });
      cy++;
    }
    while (cx < px) {
      lines.push({ kind: 'del', text: a[cx] ?? '', oldNo: cx + 1 });
      cx++;
    }
  }
  return lines;
}

/** ChangeSet → 会话审阅清单条目（路径换算为工作区相对路径） */
export function toChangeSetView(set: ChangeSet): ChangeSetView {
  return {
    changeId: set.changeId,
    sessionId: set.sessionId,
    status: set.status,
    createdAt: set.createdAt,
    isGitSnapshot: Boolean(set.gitHash) && set.entries.length === 0,
    entries: set.entries.map((e) => ({
      kind: e.kind,
      from: relOf(set, e.from),
      to: e.to ? relOf(set, e.to) : undefined,
    })),
  };
}

/** 计算完整 Diff 视图：旧侧 = 备份内容，新侧 = 当前工作区内容 */
export async function buildDiffView(checkpoint: Checkpoint, set: ChangeSet): Promise<DiffView> {
  const isGitSnapshot = Boolean(set.gitHash) && set.entries.length === 0;
  const files: FileDiff[] = [];
  for (const e of set.entries) {
    const oldText = e.backup ? await readFile(checkpoint.backupPath(set.changeId, e.backup), 'utf-8').catch(() => '') : '';
    const newPath = e.kind === 'renamed' ? e.to : e.from;
    const newText = e.kind === 'deleted' ? '' : await readFile(newPath ?? '', 'utf-8').catch(() => '');
    const lines = diffLines(oldText, newText);
    files.push({
      path: e.kind === 'renamed' ? `${relOf(set, e.from)} → ${relOf(set, e.to ?? '')}` : relOf(set, e.from),
      kind: e.kind,
      insertions: lines.filter((l) => l.kind === 'add').length,
      deletions: lines.filter((l) => l.kind === 'del').length,
      lines,
    });
  }
  return { changeId: set.changeId, status: set.status, createdAt: set.createdAt, isGitSnapshot, files };
}

function relOf(set: ChangeSet, abs: string): string {
  if (!set.workspace) return abs;
  const rel = relative(set.workspace, abs);
  return rel.startsWith('..') || rel.includes(`..${sep}`) ? abs : rel.split(sep).join('/');
}

function splitLines(text: string): string[] {
  if (text === '') return [];
  return text.split(/\r?\n/);
}
