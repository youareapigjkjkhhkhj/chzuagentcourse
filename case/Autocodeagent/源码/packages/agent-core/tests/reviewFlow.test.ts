/**
 * P2 集成测试（验收：read → edit → Diff → bash 接受/撤销两分支）：
 * 分支 A：edit 产生变更 → diff_ready → DiffView 红绿明细 → 接受（文件不动、状态固化）；
 * 分支 B：edit 变更 → 撤销 → 文件回到基线且 Diff 归零；
 * 分支 C（git 仓库）：bash 整树快照 → 撤销 → 工作区还原到执行前。
 */
import { execFile } from 'node:child_process';
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';
import type { ChatMessage, ModelConfig, NormalizedLLMResponse, StoredToolCall, StreamEvent } from '@agentbuddy/shared';
import { Checkpoint } from '../src/checkpoint';
import { buildDiffView, toChangeSetView } from '../src/diff';
import type { LlmClient, LlmRequest } from '../src/llm/client';
import { runTurn, type TurnDeps } from '../src/orchestrator';
import { PermissionGate } from '../src/permission';
import { createBuiltinBus } from '../src/tools/bus';
import { ReadState } from '../src/tools/types';

const config: ModelConfig = {
  id: 'test', name: 'mock', provider: 'openai', baseUrl: 'http://mock', model: 'gpt-4o-mini',
  apiKey: 'k', encrypted: false, temperature: 0, maxTokens: 100, contextWindow: 128000,
};

interface Step { content?: string; toolCalls?: StoredToolCall[] }

function mockClient(steps: Step[]): LlmClient {
  let i = 0;
  return {
    async chat(req: LlmRequest): Promise<NormalizedLLMResponse> {
      const step = steps[Math.min(i++, steps.length - 1)]!;
      req.onDelta(step.content ?? '');
      return {
        message: { id: '', role: 'assistant', content: step.content ?? '', createdAt: Date.now() },
        toolCalls: step.toolCalls,
        usage: { promptTokens: 1, completionTokens: 1, totalTokens: 2, cacheReadTokens: 0 },
        finishReason: step.toolCalls ? 'tool_calls' : 'stop',
      };
    },
  } as unknown as LlmClient;
}

function tc(id: string, name: string, args: Record<string, unknown>): StoredToolCall {
  return { id, name, arguments: JSON.stringify(args) };
}

function git(cwd: string, ...args: string[]): Promise<void> {
  return new Promise((resolve, reject) => {
    execFile('git', args, { cwd }, (err) => (err ? reject(err) : resolve()));
  });
}

let ws: string;
let gitWs: string;
let dataDir: string;

beforeAll(async () => {
  ws = await mkdtemp(join(tmpdir(), 'review-ws-'));
  gitWs = await mkdtemp(join(tmpdir(), 'review-gitws-'));
  dataDir = await mkdtemp(join(tmpdir(), 'review-data-'));
  await mkdir(join(ws, 'src'), { recursive: true });
  // git 仓库工作区：提交基线，供 bash 整树快照分支使用
  await writeFile(join(gitWs, 'app.txt'), 'v1\n');
  await git(gitWs, 'init', '-b', 'main');
  await git(gitWs, 'config', 'core.autocrlf', 'false'); // 固定 LF，避免 checkout 还原时被 CRLF 转换污染断言
  await git(gitWs, 'config', 'user.email', 't@t.t');
  await git(gitWs, 'config', 'user.name', 't');
  await git(gitWs, 'add', '.');
  await git(gitWs, 'commit', '-m', 'baseline');
});

afterAll(async () => {
  await rm(ws, { recursive: true, force: true });
  await rm(gitWs, { recursive: true, force: true });
  await rm(dataDir, { recursive: true, force: true });
});

function deps(steps: Step[], workspace: string, checkpoint: Checkpoint): {
  dep: TurnDeps; events: StreamEvent[]; persisted: ChatMessage[];
} {
  const events: StreamEvent[] = [];
  const persisted: ChatMessage[] = [];
  const dep: TurnDeps = {
    sessionId: 'review-s1',
    messages: [{ id: 'u1', role: 'user', content: 'go', createdAt: Date.now() }],
    client: mockClient(steps),
    config,
    bus: createBuiltinBus(),
    gate: new PermissionGate('Ask', async () => ({ allow: true, remember: false })),
    checkpoint,
    readState: new ReadState(),
    workspace,
    workspaceRoots: [workspace],
    signal: new AbortController().signal,
    emit: (e) => events.push(e),
    persist: async (m) => { persisted.push(m); },
  };
  return { dep, events, persisted };
}

describe('P2 审阅流程集成', () => {
  it('分支 A：read → edit → diff_ready → DiffView 明细 → 接受', async () => {
    await writeFile(join(ws, 'src', 'a.txt'), 'const v = 1;\n');
    const checkpoint = new Checkpoint(dataDir);
    const { dep, events, persisted } = deps([
      { toolCalls: [tc('c1', 'read', { path: 'src/a.txt' })] },
      { toolCalls: [tc('c2', 'edit', { path: 'src/a.txt', old_string: 'const v = 1;', new_string: 'const v = 2;' })] },
      { content: '修复完成' },
    ], ws, checkpoint);

    await runTurn(dep);

    // diff_ready 事件携带 changeId，且 tool 消息落盘 toolChangeId（回放恢复审阅入口）
    const ready = events.find((e) => e.type === 'diff_ready') as { callId: string; changeId: string } | undefined;
    expect(ready?.callId).toBe('c2');
    const toolMsg = persisted.find((m) => m.toolCallId === 'c2');
    expect(toolMsg?.toolChangeId).toBe(ready?.changeId);

    // DiffView：modified 条目 + 红绿明细
    const set = await checkpoint.get(ready!.changeId);
    expect(set?.status).toBe('pending');
    const view = await buildDiffView(checkpoint, set!);
    expect(view.files).toHaveLength(1);
    expect(view.files[0]?.path).toBe('src/a.txt');
    expect(view.files[0]?.lines.some((l) => l.kind === 'del' && l.text === 'const v = 1;')).toBe(true);
    expect(view.files[0]?.lines.some((l) => l.kind === 'add' && l.text === 'const v = 2;')).toBe(true);

    // 接受 = 固化状态，文件内容不动
    const accepted = await checkpoint.accept(ready!.changeId);
    expect(accepted.status).toBe('accepted');
    expect(await readFile(join(ws, 'src', 'a.txt'), 'utf-8')).toBe('const v = 2;\n');
    // 会话清单视图（右栏展示）
    const list = await checkpoint.list('review-s1');
    expect(toChangeSetView(list[0]!).entries[0]?.from).toBe('src/a.txt');
  });

  it('分支 B：edit → 撤销 → 文件回到基线且 Diff 归零', async () => {
    await writeFile(join(ws, 'src', 'b.txt'), 'origin\n');
    const checkpoint = new Checkpoint(dataDir);
    const { dep, events } = deps([
      { toolCalls: [tc('c1', 'read', { path: 'src/b.txt' })] },
      { toolCalls: [tc('c2', 'edit', { path: 'src/b.txt', old_string: 'origin', new_string: 'changed' })] },
      { content: 'done' },
    ], ws, checkpoint);

    await runTurn(dep);
    const ready = events.find((e) => e.type === 'diff_ready') as { changeId: string };
    expect(await readFile(join(ws, 'src', 'b.txt'), 'utf-8')).toBe('changed\n');

    await checkpoint.restore(ready.changeId);
    // 撤销后基线干净：文件还原 + Diff 视图零差异
    expect(await readFile(join(ws, 'src', 'b.txt'), 'utf-8')).toBe('origin\n');
    const after = await checkpoint.get(ready.changeId);
    expect(after?.status).toBe('reverted');
    const view = await buildDiffView(checkpoint, after!);
    expect(view.files[0]?.insertions).toBe(0);
    expect(view.files[0]?.deletions).toBe(0);
    // 状态机硬边界：不可重复撤销
    await expect(checkpoint.restore(ready.changeId)).rejects.toThrow(/已撤销/);
  });

  it('分支 C：bash（git 整树快照）→ 撤销 → 工作区还原到执行前', async () => {
    const checkpoint = new Checkpoint(dataDir);
    const { dep, events, persisted } = deps([
      { toolCalls: [tc('c1', 'read', { path: 'app.txt' })] },
      { toolCalls: [tc('c2', 'edit', { path: 'app.txt', old_string: 'v1', new_string: 'v2' })] },
      // git 命令修改已跟踪文件（平台无关；避免 cmd /c 剥离引号），验证整树快照撤销还原已跟踪内容；
      // 注：不能重定向到被读文件自身（shell 先截断）
      { toolCalls: [tc('c3', 'bash', { command: 'git diff >> app.txt' })] },
      { content: 'done' },
    ], gitWs, checkpoint);

    await runTurn(dep);

    const readyList = events.filter((e) => e.type === 'diff_ready') as Array<{ callId: string; changeId: string }>;
    expect(readyList.map((r) => r.callId)).toEqual(['c2', 'c3']);
    expect(persisted.find((m) => m.toolCallId === 'c3')?.toolChangeId).toBe(readyList[1]?.changeId);
    // bash 把 git diff 追加到 app.txt（内容包含 -v1/+v2 差异行）
    expect(await readFile(join(gitWs, 'app.txt'), 'utf-8')).toContain('-v1\n');

    // bash 变更集 = git 整树快照（无逐文件清单）
    const bashSet = await checkpoint.get(readyList[1]!.changeId);
    expect(bashSet?.gitHash).toBeTruthy();
    const bashView = await buildDiffView(checkpoint, bashSet!);
    expect(bashView.isGitSnapshot).toBe(true);
    expect(bashView.files).toEqual([]);

    // 撤销 bash：回到执行前（edit 之后）的状态，已跟踪文件内容精确还原
    await checkpoint.restore(readyList[1]!.changeId);
    expect(await readFile(join(gitWs, 'app.txt'), 'utf-8')).toBe('v2\n');

    // 再撤销 edit：回到最初基线（撤销链路无脏状态串扰）
    await checkpoint.restore(readyList[0]!.changeId);
    expect(await readFile(join(gitWs, 'app.txt'), 'utf-8')).toBe('v1\n');
  });
});

describe('P2 3.3 节点回溯：强制回滚 + 逆序还原', () => {
  it('restoreForRollback 强制回滚已接受的变更（不要求 pending），已撤销/不存在跳过', async () => {
    await writeFile(join(ws, 'src', 'rb1.txt'), 'base\n');
    const checkpoint = new Checkpoint(dataDir);
    const { dep, events } = deps([
      { toolCalls: [tc('c1', 'read', { path: 'src/rb1.txt' })] },
      { toolCalls: [tc('c2', 'edit', { path: 'src/rb1.txt', old_string: 'base', new_string: 'changed' })] },
      { content: 'done' },
    ], ws, checkpoint);
    await runTurn(dep);
    const ready = events.find((e) => e.type === 'diff_ready') as { changeId: string };
    expect(await readFile(join(ws, 'src', 'rb1.txt'), 'utf-8')).toBe('changed\n');

    // 接受后普通 restore 因非 pending 抛错（状态机硬边界，见 mustPending）
    await checkpoint.accept(ready.changeId);
    await expect(checkpoint.restore(ready.changeId)).rejects.toThrow(/已接受/);

    // restoreForRollback 无视状态强制回滚：文件还原 + 状态 reverted + 返回 true
    expect(await checkpoint.restoreForRollback(ready.changeId)).toBe(true);
    expect(await readFile(join(ws, 'src', 'rb1.txt'), 'utf-8')).toBe('base\n');
    expect((await checkpoint.get(ready.changeId))?.status).toBe('reverted');

    // 幂等：已 reverted / 不存在 → false（跳过，不抛错）
    expect(await checkpoint.restoreForRollback(ready.changeId)).toBe(false);
    expect(await checkpoint.restoreForRollback('no-such-change')).toBe(false);
  });

  it('逆序回滚尊重备份链：A 改 v0→v1、B 改 v1→v2，逆序还原精确回到 v0', async () => {
    await writeFile(join(ws, 'src', 'rb2.txt'), 'v0\n');
    const checkpoint = new Checkpoint(dataDir);
    const { dep, events } = deps([
      { toolCalls: [tc('c1', 'read', { path: 'src/rb2.txt' })] },
      // 连续两次 edit 同一文件：edit 写后自刷新 mtime，第二次无需重读（fsWrite.refreshReadTime）
      { toolCalls: [tc('c2', 'edit', { path: 'src/rb2.txt', old_string: 'v0', new_string: 'v1' })] },
      { toolCalls: [tc('c3', 'edit', { path: 'src/rb2.txt', old_string: 'v1', new_string: 'v2' })] },
      { content: 'done' },
    ], ws, checkpoint);
    await runTurn(dep);
    const readyList = events.filter((e) => e.type === 'diff_ready') as Array<{ callId: string; changeId: string }>;
    expect(readyList.map((r) => r.callId)).toEqual(['c2', 'c3']);
    const A = readyList[0]!.changeId; // backup = v0（首次改动前的基线）
    const B = readyList[1]!.changeId; // backup = v1（A 应用后的状态）
    expect(await readFile(join(ws, 'src', 'rb2.txt'), 'utf-8')).toBe('v2\n');

    // 模拟「回到 A 之前」：A 已接受、B 仍 pending，两者都必须回滚
    await checkpoint.accept(A);
    // 逆序（newest→oldest）：先 B（v2→v1）再 A（v1→v0）。
    // 若正序则 A.backup=v0 覆盖后又被 B.backup=v1 污染，错误止于 v1——逆序是备份链的硬要求
    expect(await checkpoint.restoreForRollback(B)).toBe(true);
    expect(await checkpoint.restoreForRollback(A)).toBe(true);
    expect(await readFile(join(ws, 'src', 'rb2.txt'), 'utf-8')).toBe('v0\n');
  });
});
