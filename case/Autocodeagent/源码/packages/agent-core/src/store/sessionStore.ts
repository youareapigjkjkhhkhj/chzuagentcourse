/**
 * 会话持久化（技术方案 §4.7 / §5）：
 * {dataDir}/sessions/{id}.json 单文件一会话，原子写（临时文件 + rename）。
 * 防抖落盘：普通消息延迟写，关键事件（会话结束）立即写。
 */
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';
import type { ChatMessage, SessionData, SessionMeta, SessionSearchHit, TodoItem } from '@agentbuddy/shared';

export interface SessionSaveOptions {
  /** true = 立即写盘；默认走防抖 */
  flush?: boolean;
}

interface PendingWrite {
  timer: NodeJS.Timeout;
  session: SessionData;
}

/** 搜索摘录：命中位置 ±40 字，压缩空白，两端越界加省略号 */
function excerpt(content: string, idx: number, hitLen: number): string {
  const flat = content.replace(/\s+/g, ' ');
  // 命中点在压缩后串中的精确位置 = 前缀压缩后的长度
  const at = content.slice(0, idx).replace(/\s+/g, ' ').length;
  const start = Math.max(0, at - 40);
  const end = Math.min(flat.length, at + hitLen + 40);
  return `${start > 0 ? '…' : ''}${flat.slice(start, end).trim()}${end < flat.length ? '…' : ''}`;
}

export class SessionStore {
  private pending = new Map<string, PendingWrite>();
  /** 进程内缓存：防抖窗口内读己写一致 */
  private cache = new Map<string, SessionData>();

  constructor(private readonly dir: string, private readonly debounceMs = 500) {}

  async init(): Promise<void> {
    await mkdir(this.dir, { recursive: true });
  }

  /** 会话列表（按 updatedAt 倒序）。workspacePath 省略 = 不过滤（返回全部，内部/测试用）；
   * 传入（含 null）= 仅返回绑定该工作区的会话。旧会话（无字段）不匹配任何值 → 隐藏。 */
  async list(workspacePath?: string | null): Promise<SessionMeta[]> {
    const sessions = await this.readAll();
    const scoped = workspacePath === undefined ? sessions : sessions.filter((s) => s.workspacePath === workspacePath);
    return scoped
      .map(({ messages, ...meta }) => meta)
      .sort((a, b) => b.updatedAt - a.updatedAt);
  }

  async get(id: string): Promise<SessionData | null> {
    const cached = this.cache.get(id);
    if (cached) return cached;
    const file = this.fileOf(id); // 非法 id 先行拒绝，不进入容错分支
    try {
      const raw = await readFile(file, 'utf-8');
      const data = JSON.parse(raw) as SessionData;
      // 磁盘读入必须进缓存：否则后续每次 appendMessage 都基于过期快照，
      // 防抖窗口内的消息会被旧快照覆盖丢失（会话历史只剩 user 消息的根因）
      this.cache.set(id, data);
      return data;
    } catch {
      return null;
    }
  }

  /** P7：expertId 缺省 = 普通助理会话；专家会话随 meta 落盘，ask 时据此套用专家配置。
   * workspacePath = 创建时的活动工作区根（null = 无工作区）；始终落盘该字段，
   * 以便与「旧会话无字段」区分（侧栏按活动工作区过滤，旧会话默认隐藏）。 */
  async create(title: string, expertId?: string, workspacePath?: string | null): Promise<SessionData> {
    const now = Date.now();
    const session: SessionData = {
      id: randomUUID(),
      title: title.slice(0, 60) || '新会话',
      createdAt: now,
      updatedAt: now,
      messageCount: 0,
      messages: [],
      workspacePath: workspacePath ?? null,
      ...(expertId ? { expertId } : {}),
    };
    await this.writeAtomic(session);
    this.cache.set(session.id, session);
    return session;
  }

  async delete(id: string): Promise<void> {
    this.cancelPending(id);
    this.cache.delete(id);
    try {
      const { unlink } = await import('node:fs/promises');
      await unlink(this.fileOf(id));
    } catch {
      /* 文件不存在视为已删除 */
    }
  }

  /** 追加消息后落盘；flush=会话结束/中断等关键事件时立即写 */
  async appendMessage(id: string, message: ChatMessage, opts: SessionSaveOptions = {}): Promise<SessionData | null> {
    const session = await this.get(id);
    if (!session) return null;
    session.messages.push(message);
    session.messageCount = session.messages.length;
    session.updatedAt = Date.now();
    if (session.messages.length === 1 && message.role === 'user') {
      session.title = message.content.slice(0, 30); // 首条消息生成标题
    }
    if (opts.flush) {
      this.cancelPending(id);
      await this.writeAtomic(session);
    } else {
      this.scheduleWrite(session);
    }
    return session;
  }

  /** 重命名标题（LLM 自动命名 / 后续手动改名）：不动 updatedAt，避免侧栏排序被改名跳动 */
  async rename(id: string, title: string): Promise<SessionData | null> {
    const session = await this.get(id);
    if (!session) return null;
    session.title = title.slice(0, 60) || session.title;
    this.cancelPending(id);
    await this.writeAtomic(session);
    return session;
  }

  /** 侧栏搜索：标题 + user/assistant 消息内容全文 grep（大小写不敏感），
   * snippet 取首个命中位置 ±40 字上下文；上限 30 条，按 updatedAt 倒序 */
  async search(query: string, workspacePath?: string | null): Promise<SessionSearchHit[]> {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    // 缓存优先：防抖窗口内刚落的消息立即可搜（与 get 读己写一致同源）
    let sessions = (await this.readAll()).map((s) => this.cache.get(s.id) ?? s);
    // 与 list 同源的工作区隔离：传入（含 null）则仅在当前工作区内检索，旧会话（无字段）不命中
    if (workspacePath !== undefined) sessions = sessions.filter((s) => s.workspacePath === workspacePath);
    const hits: SessionSearchHit[] = [];
    for (const s of sessions) {
      let snippet: string | null = null;
      if (s.title.toLowerCase().includes(q)) {
        snippet = s.title;
      } else {
        for (const m of s.messages) {
          if (m.role !== 'user' && m.role !== 'assistant') continue;
          const idx = m.content.toLowerCase().indexOf(q);
          if (idx < 0) continue;
          snippet = excerpt(m.content, idx, q.length);
          break;
        }
      }
      if (!snippet) continue;
      hits.push({ id: s.id, title: s.title, ...(s.expertId ? { expertId: s.expertId } : {}), updatedAt: s.updatedAt, snippet });
      if (hits.length >= 30) break;
    }
    return hits.sort((a, b) => b.updatedAt - a.updatedAt);
  }

  /** P4：todo_write 清单变更落盘（走防抖，回放从 session.todos 恢复） */
  async updateTodos(id: string, todos: TodoItem[]): Promise<SessionData | null> {
    const session = await this.get(id);
    if (!session) return null;
    session.todos = todos;
    session.updatedAt = Date.now();
    this.scheduleWrite(session);
    return session;
  }

  /** P2 3.3：以某消息节点为分叉点新建分支会话——复制 [0..messageId] 的消息与 todos，
   *  标题加「分支」标记；原会话保持不动（时间旅行保留原时间线）。 */
  async branchFrom(id: string, messageId: string): Promise<SessionData | null> {
    const src = await this.get(id);
    if (!src) return null;
    const idx = src.messages.findIndex((m) => m.id === messageId);
    if (idx < 0) return null;
    const now = Date.now();
    // 深拷贝消息与其 toolCalls：分支与原会话各自持有独立引用，互不串改
    const messages = src.messages
      .slice(0, idx + 1)
      .map((m) => ({ ...m, ...(m.toolCalls ? { toolCalls: m.toolCalls.map((t) => ({ ...t })) } : {}) }));
    const branch: SessionData = {
      id: randomUUID(),
      title: `${src.title} · 分支`.slice(0, 60),
      createdAt: now,
      updatedAt: now,
      messageCount: messages.length,
      messages,
      // 分支继承源会话的工作区归属（侧栏过滤据此，回溯出的分支留在同一工作区）
      workspacePath: src.workspacePath ?? null,
      ...(src.expertId ? { expertId: src.expertId } : {}),
      ...(src.todos ? { todos: src.todos.map((t) => ({ ...t })) } : {}),
    };
    await this.writeAtomic(branch);
    this.cache.set(branch.id, branch);
    return branch;
  }

  /** 消息撤回 / 重发：删除该条及其之后全部消息（对话回滚到该条之前），立即落盘 */
  async truncateFrom(id: string, messageId: string): Promise<SessionData | null> {
    const session = await this.get(id);
    if (!session) return null;
    const idx = session.messages.findIndex((m) => m.id === messageId);
    if (idx < 0) return session;
    session.messages = session.messages.slice(0, idx);
    session.messageCount = session.messages.length;
    session.updatedAt = Date.now();
    this.cancelPending(id);
    await this.writeAtomic(session);
    return session;
  }

  /** 删除单条消息（清理个别气泡），立即落盘 */
  async deleteMessage(id: string, messageId: string): Promise<SessionData | null> {
    const session = await this.get(id);
    if (!session) return null;
    const before = session.messages.length;
    session.messages = session.messages.filter((m) => m.id !== messageId);
    if (session.messages.length === before) return session;
    session.messageCount = session.messages.length;
    session.updatedAt = Date.now();
    this.cancelPending(id);
    await this.writeAtomic(session);
    return session;
  }

  /** 应用退出前强制落盘所有挂起会话 */
  async flushAll(): Promise<void> {
    const entries = [...this.pending.entries()];
    this.pending.clear();
    for (const [, { timer, session }] of entries) {
      clearTimeout(timer);
      await this.writeAtomic(session);
    }
  }

  /** 单个会话立即落盘（回合结束/中断等关键事件） */
  async flush(id: string): Promise<void> {
    this.cancelPending(id);
    const session = await this.get(id);
    if (session) await this.writeAtomic(session);
  }

  private scheduleWrite(session: SessionData): void {
    this.cancelPending(session.id);
    const timer = setTimeout(() => {
      this.pending.delete(session.id);
      void this.writeAtomic(session);
    }, this.debounceMs);
    timer.unref?.();
    this.pending.set(session.id, { timer, session });
  }

  private cancelPending(id: string): void {
    const entry = this.pending.get(id);
    if (entry) {
      clearTimeout(entry.timer);
      this.pending.delete(id);
    }
  }

  private async writeAtomic(session: SessionData): Promise<void> {
    const target = this.fileOf(session.id);
    const tmp = `${target}.tmp`;
    await writeFile(tmp, JSON.stringify(session), 'utf-8');
    await rename(tmp, target);
  }

  private fileOf(id: string): string {
    if (!/^[a-zA-Z0-9-]+$/.test(id)) throw new Error('非法会话 id');
    return join(this.dir, `${id}.json`);
  }

  private async readAll(): Promise<SessionData[]> {
    const { readdir } = await import('node:fs/promises');
    let files: string[];
    try {
      files = await readdir(this.dir);
    } catch {
      return [];
    }
    const result: SessionData[] = [];
    for (const f of files) {
      if (!f.endsWith('.json')) continue;
      try {
        const raw = await readFile(join(this.dir, f), 'utf-8');
        result.push(JSON.parse(raw) as SessionData);
      } catch {
        /* 损坏文件跳过，不影响列表 */
      }
    }
    return result;
  }
}
