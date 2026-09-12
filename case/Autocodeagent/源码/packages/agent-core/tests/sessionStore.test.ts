import { mkdtemp, rm, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { SessionStore } from '../src/store/sessionStore';

let dir: string;
let store: SessionStore;

beforeEach(async () => {
  dir = await mkdtemp(join(tmpdir(), 'ab-test-'));
  store = new SessionStore(join(dir, 'sessions'), 50);
  await store.init();
});

afterEach(async () => {
  await store.flushAll(); // 先落盘挂起的防抖写，再清理目录，避免 unhandled rejection
  await rm(dir, { recursive: true, force: true });
});

describe('SessionStore', () => {
  it('create → get 回环', async () => {
    const s = await store.create('测试会话');
    const got = await store.get(s.id);
    expect(got?.title).toBe('测试会话');
    expect(got?.messages).toEqual([]);
  });

  it('appendMessage：首条用户消息生成标题；消息可回读', async () => {
    const s = await store.create('');
    await store.appendMessage(s.id, { id: 'm1', role: 'user', content: '帮我重构登录模块', createdAt: 1 });
    const got = await store.get(s.id);
    expect(got?.title).toBe('帮我重构登录模块');
    expect(got?.messageCount).toBe(1);
  });

  it('list 按更新时间倒序，且不含 messages', async () => {
    const a = await store.create('旧');
    const b = await store.create('新');
    const list = await store.list();
    expect(list[0]?.id).toBe(b.id);
    expect('messages' in (list[0] as object)).toBe(false);
    expect(a.id).not.toBe(b.id);
  });

  it('防抖落盘 + flushAll 兜底', async () => {
    const s = await store.create('t');
    await store.appendMessage(s.id, { id: 'm1', role: 'user', content: 'hi', createdAt: 1 }); // 走防抖
    await store.flushAll(); // 退出路径：立即落盘挂起数据
    const got = await store.get(s.id);
    expect(got?.messages).toHaveLength(1);
  });

  it('delete 后 get 返回 null；重复删除不报错', async () => {
    const s = await store.create('t');
    await store.delete(s.id);
    expect(await store.get(s.id)).toBeNull();
    await expect(store.delete(s.id)).resolves.toBeUndefined();
  });

  it('非法 id 拒绝（路径逃逸防护）', async () => {
    await expect(store.get('../../etc/passwd')).rejects.toThrow('非法会话 id');
  });

  it('不存在的会话 append 返回 null', async () => {
    expect(await store.appendMessage('no-such', { id: 'm', role: 'user', content: 'x', createdAt: 1 })).toBeNull();
  });

  it('回归：重启后新实例防抖窗口内连续 append 不互相覆盖（读盘进缓存）', async () => {
    const s = await store.create('回归');
    await store.appendMessage(s.id, { id: 'u1', role: 'user', content: '你好', createdAt: 1 });
    await store.flushAll(); // 模拟退出：user 已落盘，缓存失效（重启）
    // 模拟重启：新实例首次 get 走读盘；若读盘不进缓存，后续每次 append 都基于
    // 过期磁盘快照，后写覆盖先写，历史只剩单条消息（原根因）
    const rebooted = new SessionStore(join(dir, 'sessions'), 60_000);
    await rebooted.appendMessage(s.id, { id: 'a1', role: 'assistant', content: '我在', createdAt: 2 });
    await rebooted.appendMessage(s.id, { id: 't1', role: 'tool', content: 'ok', createdAt: 3 });
    await rebooted.flushAll(); // 模拟 before-quit 退出落盘
    // 再重启读盘：三条消息必须都在且有序
    const final = new SessionStore(join(dir, 'sessions'), 50);
    const got = await final.get(s.id);
    expect(got?.messages.map((m) => m.id)).toEqual(['u1', 'a1', 't1']);
  });

  it('truncateFrom：删除该条及之后全部消息并立即落盘（撤回 / 重发底层）', async () => {
    const s = await store.create('t');
    for (const [i, role] of [['u1', 'user'], ['a1', 'assistant'], ['u2', 'user'], ['a2', 'assistant']] as const) {
      await store.appendMessage(s.id, { id: i, role, content: i, createdAt: 1 });
    }
    await store.truncateFrom(s.id, 'u2');
    // 新实例读盘验证立即落盘（不等防抖）
    const fresh = new SessionStore(join(dir, 'sessions'), 60_000);
    const got = await fresh.get(s.id);
    expect(got?.messages.map((m) => m.id)).toEqual(['u1', 'a1']);
    expect(got?.messageCount).toBe(2);
    // 不存在的 messageId = 空操作
    await store.truncateFrom(s.id, 'nope');
    expect((await store.get(s.id))?.messages).toHaveLength(2);
  });

  it('deleteMessage：仅删单条并立即落盘；不存在时空操作', async () => {
    const s = await store.create('t');
    await store.appendMessage(s.id, { id: 'u1', role: 'user', content: 'q', createdAt: 1 });
    await store.appendMessage(s.id, { id: 'a1', role: 'assistant', content: 'x', createdAt: 2 });
    await store.deleteMessage(s.id, 'a1');
    const fresh = new SessionStore(join(dir, 'sessions'), 60_000);
    expect((await fresh.get(s.id))?.messages.map((m) => m.id)).toEqual(['u1']);
    await store.deleteMessage(s.id, 'nope');
    expect((await store.get(s.id))?.messages).toHaveLength(1);
  });

  it('clear：清空全部消息与 todos、标题复位「新会话」、保留会话壳（原地重开），立即落盘', async () => {
    const s = await store.create('原始标题');
    await store.appendMessage(s.id, { id: 'u1', role: 'user', content: '帮我重构登录', createdAt: 1 });
    await store.appendMessage(s.id, { id: 'a1', role: 'assistant', content: '好的', createdAt: 2 });
    await store.updateTodos(s.id, [{ id: 't1', content: '任务', status: 'pending' }]);
    await store.clear(s.id);
    // 新实例读盘验证立即落盘（不等防抖）
    const fresh = new SessionStore(join(dir, 'sessions'), 60_000);
    const got = await fresh.get(s.id);
    expect(got).not.toBeNull(); // 会话壳保留（未删除）
    expect(got?.id).toBe(s.id); // id 不变 = 原地重开而非新建
    expect(got?.messages).toEqual([]);
    expect(got?.messageCount).toBe(0);
    expect(got?.todos).toEqual([]);
    expect(got?.title).toBe('新会话'); // 标题复位
    // 不存在的会话返回 null（与 truncateFrom/deleteMessage 一致）
    expect(await store.clear('no-such')).toBeNull();
  });

  it('rename：立即落盘、截断 60 字、不动 updatedAt；不存在返回 null', async () => {
    const s = await store.create('旧标题');
    const before = (await store.get(s.id))!.updatedAt;
    const renamed = await store.rename(s.id, 'LLM 自动生成的新标题');
    expect(renamed?.title).toBe('LLM 自动生成的新标题');
    expect(renamed?.updatedAt).toBe(before); // 改名不参与侧栏时间排序
    const fresh = new SessionStore(join(dir, 'sessions'), 60_000);
    expect((await fresh.get(s.id))?.title).toBe('LLM 自动生成的新标题');
    // 超长截断 60；空串 = 保留原标题；不存在 = null
    expect((await store.rename(s.id, 'x'.repeat(100)))?.title).toHaveLength(60);
    expect((await store.rename(s.id, ''))?.title).toBe('x'.repeat(60));
    expect(await store.rename('no-such', 't')).toBeNull();
  });

  it('search：命中标题或消息内容（大小写不敏感），snippet 带上下文，按 updatedAt 倒序', async () => {
    const a = await store.create('');
    await store.appendMessage(a.id, { id: 'u1', role: 'user', content: '帮我修复 Login 页面的样式问题', createdAt: 1 }); // 首条消息生成标题
    const b = await store.create('部署咨询');
    await store.appendMessage(b.id, { id: 'u1', role: 'user', content: 'docker compose 怎么配置', createdAt: 2 });
    await store.appendMessage(b.id, { id: 'a1', role: 'assistant', content: '登录令牌过期时间建议设置为 2 小时', createdAt: 3 });
    // 同毫秒创建时 updatedAt 可能相同：借 rename 不动 updatedAt 的特性显式压低 a，保证倒序断言稳定；
    // 同时把 a 标题改为含「登录」，与 b 的 assistant 消息构成双命中
    const aData = (await store.get(a.id))!;
    aData.updatedAt = 1;
    await store.rename(a.id, '登录页面样式修复');
    // 标题命中（内容不含「样式修复」，命中必经标题）
    const byTitle = await store.search('样式修复');
    expect(byTitle.map((h) => h.id)).toEqual([a.id]);
    expect(byTitle[0]!.snippet).toBe('登录页面样式修复');
    // 内容命中（大小写不敏感）+ snippet 摘录：标题不含 login，命中必经消息内容
    const byContent = await store.search('login');
    expect(byContent).toHaveLength(1);
    expect(byContent[0]!.snippet).toContain('Login');
    // 多命中按 updatedAt 倒序（b 后更新排前）：a 命中标题、b 命中 assistant 消息
    const multi = await store.search('登录');
    expect(multi.map((h) => h.id)).toEqual([b.id, a.id]);
    // 空查询 / 无命中
    expect(await store.search('   ')).toEqual([]);
    expect(await store.search('不存在的关键词')).toEqual([]);
  });

  it('search：tool 消息不参与检索；长内容 snippet 截断带省略号', async () => {
    const s = await store.create('t');
    await store.appendMessage(s.id, { id: 't1', role: 'tool', content: '秘密关键词 xyz', createdAt: 1 });
    expect(await store.search('xyz')).toEqual([]);
    const long = `前置填充${'A'.repeat(100)}命中点${'B'.repeat(100)}`;
    await store.appendMessage(s.id, { id: 'u1', role: 'user', content: long, createdAt: 2 });
    const hits = await store.search('命中点');
    expect(hits).toHaveLength(1);
    expect(hits[0]!.snippet).toContain('命中点');
    expect(hits[0]!.snippet.length).toBeLessThan(long.length);
    expect(hits[0]!.snippet.startsWith('…')).toBe(true);
    expect(hits[0]!.snippet.endsWith('…')).toBe(true);
  });

  it('branchFrom：复制 [0..节点] 消息与 todos 建分支，标题加「分支」，原会话不动', async () => {
    const s = await store.create('', 'expert-1');
    await store.appendMessage(s.id, { id: 'u1', role: 'user', content: 'q1', createdAt: 1 });
    await store.appendMessage(s.id, { id: 'a1', role: 'assistant', content: 'a1', createdAt: 2, toolCalls: [{ id: 'c1', name: 'edit', arguments: '{}' }] });
    await store.appendMessage(s.id, { id: 'u2', role: 'user', content: 'q2', createdAt: 3 });
    await store.appendMessage(s.id, { id: 'a2', role: 'assistant', content: 'a2', createdAt: 4 });
    await store.rename(s.id, '登录重构'); // 首条 user 消息会覆盖 create 标题，显式改回稳定值
    await store.updateTodos(s.id, [{ id: '1', content: 'todo', status: 'done' }]);
    await store.flush(s.id);

    // 从 a1 节点分叉：复制 u1 + a1（含节点本身），丢弃其后的 u2/a2
    const branch = await store.branchFrom(s.id, 'a1');
    expect(branch).not.toBeNull();
    expect(branch!.id).not.toBe(s.id);
    expect(branch!.title).toBe('登录重构 · 分支');
    expect(branch!.expertId).toBe('expert-1'); // 专家会话分叉仍是专家会话
    expect(branch!.messages.map((m) => m.id)).toEqual(['u1', 'a1']);
    expect(branch!.messageCount).toBe(2);
    expect(branch!.todos).toEqual([{ id: '1', content: 'todo', status: 'done' }]);

    // 原会话保持不动（时间旅行保留原时间线）
    const original = await store.get(s.id);
    expect(original!.messages.map((m) => m.id)).toEqual(['u1', 'a1', 'u2', 'a2']);
    expect(original!.title).toBe('登录重构');

    // 深拷贝独立：改分支的消息与 toolCalls 不会串改原会话缓存
    branch!.messages[1]!.content = '篡改';
    branch!.messages[1]!.toolCalls![0]!.name = '篡改';
    const after = await store.get(s.id);
    expect(after!.messages[1]!.content).toBe('a1');
    expect(after!.messages[1]!.toolCalls![0]!.name).toBe('edit');

    // 分支已落盘：新实例读盘可见
    const fresh = new SessionStore(join(dir, 'sessions'), 60_000);
    expect((await fresh.get(branch!.id))?.messages.map((m) => m.id)).toEqual(['u1', 'a1']);

    // 不存在会话 / 无效节点 → null
    expect(await store.branchFrom('no-such', 'a1')).toBeNull();
    expect(await store.branchFrom(s.id, 'nope')).toBeNull();
  });

  it('工作区隔离：create 绑定 workspacePath，list/search 按其过滤，旧会话（无字段）隐藏', async () => {
    const wsA = '/proj/alpha';
    const wsB = '/proj/beta';
    const a1 = await store.create('A1', undefined, wsA);
    const a2 = await store.create('A2', undefined, wsA);
    const b1 = await store.create('B1', undefined, wsB);
    // 首条 user 消息会把标题改写为内容前缀，a1/b1 标题变为「alpha 关键字」构成搜索命中。
    // flush:true 立即落盘、不排防抖——否则其后大量读操作（>debounceMs）会让防抖定时器在测试体
    // 中途触发 fire-and-forget 写，与 afterEach 的 rm(dir) 竞争导致 Windows rename EPERM（unhandled rejection）
    await store.appendMessage(a1.id, { id: 'u1', role: 'user', content: 'alpha 关键字', createdAt: 1 }, { flush: true });
    await store.appendMessage(b1.id, { id: 'u1', role: 'user', content: 'alpha 关键字', createdAt: 2 }, { flush: true });

    // 绑定值随 meta 落盘并可回读
    expect((await store.get(a1.id))?.workspacePath).toBe(wsA);

    // list 按工作区过滤（同毫秒创建借两侧 sort 消除顺序抖动）
    expect((await store.list(wsA)).map((m) => m.id).sort()).toEqual([a1.id, a2.id].sort());
    expect((await store.list(wsB)).map((m) => m.id)).toEqual([b1.id]);
    expect(await store.list()).toHaveLength(3); // 省略参数 = 不过滤（返回全部）

    // search 与 list 同源隔离
    expect((await store.search('alpha', wsA)).map((h) => h.id)).toEqual([a1.id]);
    expect((await store.search('alpha', wsB)).map((h) => h.id)).toEqual([b1.id]);
    expect(await store.search('alpha')).toHaveLength(2); // 省略参数 = 不过滤

    // 旧会话：磁盘上无 workspacePath 字段 → 不匹配任何工作区值（含 null）→ 隐藏
    const legacyId = 'legacy-1';
    await writeFile(
      join(dir, 'sessions', `${legacyId}.json`),
      JSON.stringify({ id: legacyId, title: '旧会话', createdAt: 0, updatedAt: 0, messageCount: 0, messages: [] }),
      'utf-8',
    );
    expect((await store.list(wsA)).some((m) => m.id === legacyId)).toBe(false);
    expect((await store.list(null)).some((m) => m.id === legacyId)).toBe(false);
    expect((await store.list()).some((m) => m.id === legacyId)).toBe(true);
    expect(await store.search('旧会话', wsA)).toHaveLength(0);
  });

  it('branchFrom 继承源会话 workspacePath（回溯分支留在同一工作区）', async () => {
    const ws = '/proj/gamma';
    const s = await store.create('源', undefined, ws);
    await store.appendMessage(s.id, { id: 'u1', role: 'user', content: 'q', createdAt: 1 });
    await store.appendMessage(s.id, { id: 'a1', role: 'assistant', content: 'a', createdAt: 2 });
    await store.flush(s.id);
    const branch = await store.branchFrom(s.id, 'a1');
    expect(branch!.workspacePath).toBe(ws);
    expect((await store.list(ws)).map((m) => m.id)).toContain(branch!.id);
  });
});
