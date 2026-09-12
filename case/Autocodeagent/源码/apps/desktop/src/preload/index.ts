/**
 * Preload：纯白名单透传，零第三方依赖（沙箱环境不允许 require 外部包）。
 * 所有入参校验在 Main 侧用 zod 完成（见 main/ipc.ts）。
 */
import { contextBridge, ipcRenderer } from 'electron';
import type {
  AskInput,
  ExpertUpsertInput,
  IpcChannel,
  McpUpsertInput,
  ModelConfigInput,
  ModelConfig,
  SettingsSetInput,
  StreamEvent,
  WebConfigSetInput,
} from '@agentbuddy/shared';

const invoke = (channel: IpcChannel, ...args: unknown[]) => ipcRenderer.invoke(channel, ...args);

const api = {
  session: {
    list: () => invoke('session:list'),
    get: (id: string) => invoke('session:get', { id }),
    /** P7：expertId 缺省 = 普通助理会话 */
    create: (title: string, expertId?: string) => invoke('session:create', { title, ...(expertId ? { expertId } : {}) }),
    delete: (id: string) => invoke('session:delete', { id }),
    /** 清空当前会话：移除全部消息与 todos、标题复位，保留会话壳 */
    clear: (id: string) => invoke('session:clear', { id }),
    /** 侧栏会话搜索：标题 + 消息内容全文 grep */
    search: (query: string) => invoke('session:search', { query }),
    /** P2 3.3 节点回溯：回到该消息节点重来（逆序回滚 + 分叉新会话） */
    rollback: (sessionId: string, messageId: string) => invoke('session:rollback', { sessionId, messageId }),
    /** 消息撤回 / 重发：删除该条及之后全部消息 */
    truncateFrom: (sessionId: string, messageId: string) => invoke('session:truncate', { sessionId, messageId }),
    /** 删除单条消息 */
    deleteMessage: (sessionId: string, messageId: string) => invoke('session:delete-message', { sessionId, messageId }),
  },
  agent: {
    ask: (payload: AskInput) => invoke('agent:ask', payload),
    abort: (sessionId: string) => invoke('agent:abort', { id: sessionId }),
  },
  permission: {
    resolve: (payload: { requestId: string; allow: boolean; remember: boolean }) => invoke('permission:resolve', payload),
  },
  config: {
    getModel: () => invoke('config:model:get'),
    setModel: (config: ModelConfigInput) => invoke('config:model:set', config),
    listModels: () => invoke('config:model:list') as Promise<{ ok: boolean; data?: ModelConfig[]; error?: string }>,
    setActive: (id: string) => invoke('config:model:active', { id }),
    removeModel: (id: string) => invoke('config:model:remove', { id }),
    getSettings: () => invoke('config:settings:get'),
    setSettings: (patch: SettingsSetInput) => invoke('config:settings:set', patch),
    /** 联网搜索：webfetch 内置零配置；websearch 开关 + Tavily key（加密存 KeyStore，仅回掩码） */
    getWeb: () => invoke('config:web:get'),
    setWeb: (patch: WebConfigSetInput) => invoke('config:web:set', patch),
  },
  workspace: {
    get: () => invoke('workspace:get'),
    select: () => invoke('workspace:select'),
    remove: (path: string) => invoke('workspace:remove', { path }),
    setActive: (path: string) => invoke('workspace:set-active', { path }),
    tree: () => invoke('workspace:tree'),
    file: (path: string) => invoke('workspace:file', { path }),
    preview: (path: string) => invoke('workspace:preview', { path }),
    git: () => invoke('workspace:git'),
  },
  /** P2 审阅：清单 / Diff 视图 / 接受 / 一键全部接受 / 撤销 */
  diff: {
    list: (sessionId: string) => invoke('diff:list', { sessionId }),
    get: (changeId: string) => invoke('diff:get', { changeId }),
    accept: (changeId: string) => invoke('diff:accept', { changeId }),
    acceptAll: (sessionId: string) => invoke('diff:accept-all', { sessionId }),
    revert: (changeId: string) => invoke('diff:revert', { changeId }),
  },
  /** P4 Skills：两级清单 / 正文读写 / 启停 / 新增删除 / ZIP 导入 */
  skills: {
    list: () => invoke('skills:list'),
    get: (name: string) => invoke('skills:get', { name }),
    save: (name: string, body: string) => invoke('skills:save', { name, body }),
    setEnabled: (name: string, enabled: boolean) => invoke('skills:set-enabled', { name, enabled }),
    create: (input: { name: string; scope: 'global' | 'project'; description: string; body: string }) =>
      invoke('skills:create', input),
    remove: (name: string) => invoke('skills:remove', { name }),
    importZip: (dataBase64: string, scope: 'global' | 'project') =>
      invoke('skills:import', { data: dataBase64, scope }),
  },
  /** P5 MCP：视图 / 表单增改 / 删除 / 启停 / 重连 / JSON 导入 */
  mcp: {
    list: () => invoke('mcp:list'),
    upsert: (input: McpUpsertInput) => invoke('mcp:upsert', input),
    remove: (name: string) => invoke('mcp:remove', { name }),
    setEnabled: (name: string, enabled: boolean) => invoke('mcp:set-enabled', { name, enabled }),
    setAlwaysLoad: (name: string, alwaysLoad: boolean) => invoke('mcp:set-always-load', { name, alwaysLoad }),
    reconnect: (name: string) => invoke('mcp:reconnect', { name }),
    importJson: (text: string) => invoke('mcp:import', { text }),
  },
  /** P7 专家团：清单 / 新增编辑 / 删除 */
  expert: {
    list: () => invoke('expert:list'),
    upsert: (input: ExpertUpsertInput) => invoke('expert:upsert', input),
    remove: (id: string) => invoke('expert:remove', { id }),
  },
  /** P6 用量统计：聚合视图（可限定近 N 天）+ 执行记录筛选 */
  usage: {
    stats: (days?: number) => invoke('usage:stats', days === undefined ? {} : { days }),
    records: (filter?: { sessionId?: string; tool?: string }) => invoke('usage:records', filter ?? {}),
  },
  /** 事件驱动：Main → Renderer 单向流（AGENTS §18） */
  onStream: (callback: (event: StreamEvent) => void) => {
    const listener = (_e: unknown, event: StreamEvent) => callback(event);
    ipcRenderer.on('stream:event', listener);
    return () => ipcRenderer.removeListener('stream:event', listener);
  },
};

contextBridge.exposeInMainWorld('agent', api);
