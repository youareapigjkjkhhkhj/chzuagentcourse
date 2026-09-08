/**
 * 右栏工作台状态（P2 任务 2/3/7）：Diff 审阅 / 代码只读查看 / 文件树。
 * 事件驱动（AGENTS §18）：diff_ready 信号到达时 openDiff 自动展开；
 * 接受/撤销后刷新清单并回调 onChanged（外层刷新 git 状态条）。
 */
import { computed, ref, type Ref } from 'vue';
import type { ChangeSetView, DiffView, ReviewStatus, TreeNode } from '@agentbuddy/shared';
import { agent } from '../api/bridge';
import { previewKind } from '../ui/previewKind';

export type PanelTab = 'diff' | 'code' | 'files' | 'preview';

export interface WorkbenchStore {
  visible: Ref<boolean>;
  tab: Ref<PanelTab>;
  changes: Ref<ChangeSetView[]>;
  selected: Ref<string | null>;
  diffView: Ref<DiffView | null>;
  loadingDiff: Ref<boolean>;
  actionError: Ref<string>;
  pendingCount: Ref<number>;
  tree: Ref<TreeNode[]>;
  codeFile: Ref<string>;
  codeContent: Ref<string>;
  codeError: Ref<string>;
  reviewStatus(changeId: string | undefined): ReviewStatus | null;
  refresh(): Promise<void>;
  openDiff(changeId: string): Promise<void>;
  select(changeId: string): Promise<void>;
  close(): void;
  accept(changeId: string): Promise<void>;
  revert(changeId: string): Promise<void>;
  acceptAll(): Promise<void>;
  showFiles(): Promise<void>;
  openCode(path: string): Promise<void>;
  previewFile: Ref<string>;
  openPreview(path: string): void;
  /** 文件树点击路由：预览类格式进预览 Tab，其余进代码 Tab */
  openFile(path: string): Promise<void>;
  reset(): void;
}

export function useWorkbench(sessionId: Ref<string | null>, onChanged: () => void): WorkbenchStore {
  const visible = ref(false);
  const tab = ref<PanelTab>('diff');
  const changes = ref<ChangeSetView[]>([]);
  const selected = ref<string | null>(null);
  const diffView = ref<DiffView | null>(null);
  const loadingDiff = ref(false);
  const actionError = ref('');
  const tree = ref<TreeNode[]>([]);
  const codeFile = ref('');
  const codeContent = ref('');
  const codeError = ref('');
  const previewFile = ref('');

  const pendingCount = computed(() => changes.value.filter((c) => c.status === 'pending').length);

  function reviewStatus(changeId: string | undefined): ReviewStatus | null {
    if (!changeId) return null;
    return changes.value.find((c) => c.changeId === changeId)?.status ?? null;
  }

  async function refresh(): Promise<void> {
    if (!sessionId.value) return;
    const res = await agent().diff.list(sessionId.value);
    changes.value = res.ok && res.data ? res.data : [];
  }

  async function loadView(changeId: string): Promise<void> {
    loadingDiff.value = true;
    diffView.value = null;
    const res = await agent().diff.get(changeId);
    loadingDiff.value = false;
    if (res.ok && res.data) {
      diffView.value = res.data;
      actionError.value = '';
    } else {
      actionError.value = res.error ?? '加载 Diff 失败';
    }
  }

  async function openDiff(changeId: string): Promise<void> {
    visible.value = true;
    tab.value = 'diff';
    await refresh();
    await select(changeId);
  }

  async function select(changeId: string): Promise<void> {
    selected.value = changeId;
    await loadView(changeId);
  }

  function close(): void {
    visible.value = false;
  }

  /** 接受/撤销后：刷新清单 + 重算当前视图（状态横幅），并通知外层刷新 git 状态 */
  async function afterAction(): Promise<void> {
    await refresh();
    onChanged();
    if (selected.value) await loadView(selected.value);
  }

  async function accept(changeId: string): Promise<void> {
    const res = await agent().diff.accept(changeId);
    if (!res.ok) {
      actionError.value = res.error ?? '接受失败';
      return;
    }
    await afterAction();
  }

  async function revert(changeId: string): Promise<void> {
    const res = await agent().diff.revert(changeId);
    if (!res.ok) {
      actionError.value = res.error ?? '撤销失败';
      return;
    }
    await afterAction();
  }

  async function acceptAll(): Promise<void> {
    if (!sessionId.value) return;
    const res = await agent().diff.acceptAll(sessionId.value);
    if (!res.ok) {
      actionError.value = res.error ?? '一键接受失败';
      return;
    }
    await afterAction();
  }

  async function showFiles(): Promise<void> {
    tab.value = 'files';
    if (tree.value.length === 0) {
      const res = await agent().workspace.tree();
      tree.value = res.ok && res.data ? res.data : [];
    }
  }

  async function openCode(path: string): Promise<void> {
    tab.value = 'code';
    codeFile.value = path;
    codeContent.value = '';
    codeError.value = '';
    const res = await agent().workspace.file(path);
    if (res.ok && res.data !== undefined) codeContent.value = res.data;
    else codeError.value = res.error ?? '读取文件失败';
  }

  function openPreview(path: string): void {
    visible.value = true;
    tab.value = 'preview';
    previewFile.value = path;
  }

  async function openFile(path: string): Promise<void> {
    if (previewKind(path) !== null) openPreview(path);
    else await openCode(path);
  }

  function reset(): void {
    visible.value = false;
    changes.value = [];
    selected.value = null;
    diffView.value = null;
    tree.value = [];
    codeFile.value = '';
    codeContent.value = '';
    previewFile.value = '';
    actionError.value = '';
  }

  return {
    visible, tab, changes, selected, diffView, loadingDiff, actionError, pendingCount,
    tree, codeFile, codeContent, codeError, previewFile,
    reviewStatus, refresh, openDiff, select, close, accept, revert, acceptAll, showFiles, openCode, openPreview, openFile, reset,
  };
}
