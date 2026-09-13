/** window.agent 桥接类型（preload 通过 contextBridge 注入） */
import type {
  AppSettings,
  AskInput,
  ChangeSetView,
  DiffView,
  Expert,
  ExpertUpsertInput,
  GitInfo,
  McpServerView,
  McpUpsertInput,
  ModelConfig,
  ModelConfigInput,
  RollbackResult,
  SessionData,
  SessionMeta,
  SessionRunState,
  SessionSearchHit,
  SettingsSetInput,
  SkillMeta,
  StreamEvent,
  ToolRecord,
  TreeNode,
  UsageStats,
  WebConfigSetInput,
  WebConfigView,
  WorkspaceState,
} from '@agentbuddy/shared';

export interface IpcResult<T> {
  ok: boolean;
  data?: T;
  error?: string;
}

export interface AgentBridge {
  session: {
    list(): Promise<IpcResult<SessionMeta[]>>;
    get(id: string): Promise<IpcResult<SessionData | null>>;
    /** P7：expertId 缺省 = 普通助理会话 */
    create(title: string, expertId?: string): Promise<IpcResult<SessionData>>;
    delete(id: string): Promise<IpcResult<void>>;
    /** 清空当前会话：移除全部消息与 todos、标题复位，保留会话壳 */
    clear(id: string): Promise<IpcResult<void>>;
    /** 侧栏会话搜索：标题 + 消息内容全文 grep（Main 侧执行） */
    search(query: string): Promise<IpcResult<SessionSearchHit[]>>;
    /** P2 3.3 节点回溯：回到该消息节点重来（逆序回滚 + 分叉新会话） */
    rollback(sessionId: string, messageId: string): Promise<IpcResult<RollbackResult>>;
    /** 消息撤回 / 重发：删除该条及之后全部消息 */
    truncateFrom(sessionId: string, messageId: string): Promise<IpcResult<void>>;
    /** 删除单条消息 */
    deleteMessage(sessionId: string, messageId: string): Promise<IpcResult<void>>;
  };
  agent: {
    ask(payload: AskInput): Promise<IpcResult<void>>;
    abort(sessionId: string): Promise<IpcResult<boolean>>;
    /** 会话进行态：切换会话时对齐 busy / 恢复挂起权限卡 */
    state(sessionId: string): Promise<IpcResult<SessionRunState>>;
  };
  permission: {
    resolve(payload: { requestId: string; allow: boolean; remember: boolean }): Promise<IpcResult<boolean>>;
  };
  config: {
    getModel(): Promise<IpcResult<ModelConfig>>;
    setModel(config: ModelConfigInput): Promise<IpcResult<ModelConfig>>;
    listModels(): Promise<IpcResult<ModelConfig[]>>;
    setActive(id: string): Promise<IpcResult<void>>;
    removeModel(id: string): Promise<IpcResult<void>>;
    /** P3：应用设置（权限模式 + EXEC 白名单） */
    getSettings(): Promise<IpcResult<AppSettings>>;
    setSettings(patch: SettingsSetInput): Promise<IpcResult<AppSettings>>;
    /** 联网搜索：webfetch 内置零配置；websearch 开关 + Tavily key（Main 侧加密存 KeyStore，仅回掩码） */
    getWeb(): Promise<IpcResult<WebConfigView>>;
    setWeb(patch: WebConfigSetInput): Promise<IpcResult<WebConfigView>>;
  };
  workspace: {
    get(): Promise<IpcResult<WorkspaceState | null>>;
    select(): Promise<IpcResult<WorkspaceState | null>>;
    /** 多工作区：移除关联目录 / 切换活动目录 */
    remove(path: string): Promise<IpcResult<WorkspaceState>>;
    setActive(path: string): Promise<IpcResult<WorkspaceState>>;
    tree(): Promise<IpcResult<TreeNode[]>>;
    file(path: string): Promise<IpcResult<string>>;
    /** 预览读取：base64 + mime（渲染端按格式分流渲染） */
    preview(path: string): Promise<IpcResult<{ base64: string; mime: string; size: number }>>;
    git(): Promise<IpcResult<GitInfo | null>>;
  };
  diff: {
    list(sessionId: string): Promise<IpcResult<ChangeSetView[]>>;
    get(changeId: string): Promise<IpcResult<DiffView>>;
    accept(changeId: string): Promise<IpcResult<ChangeSetView>>;
    acceptAll(sessionId: string): Promise<IpcResult<number>>;
    revert(changeId: string): Promise<IpcResult<ChangeSetView>>;
  };
  /** P4 Skills */
  skills: {
    list(): Promise<IpcResult<SkillMeta[]>>;
    get(name: string): Promise<IpcResult<{ meta: SkillMeta; body: string; raw: string } | null>>;
    save(name: string, body: string): Promise<IpcResult<SkillMeta>>;
    setEnabled(name: string, enabled: boolean): Promise<IpcResult<void>>;
    create(input: { name: string; scope: 'global' | 'project'; description: string; body: string }): Promise<IpcResult<SkillMeta>>;
    remove(name: string): Promise<IpcResult<void>>;
    importZip(dataBase64: string, scope: 'global' | 'project'): Promise<IpcResult<SkillMeta[]>>;
  };
  /** P5 MCP 连接器 */
  mcp: {
    list(): Promise<IpcResult<McpServerView[]>>;
    upsert(input: McpUpsertInput): Promise<IpcResult<McpServerView[]>>;
    remove(name: string): Promise<IpcResult<McpServerView[]>>;
    setEnabled(name: string, enabled: boolean): Promise<IpcResult<McpServerView[]>>;
    setAlwaysLoad(name: string, alwaysLoad: boolean): Promise<IpcResult<McpServerView[]>>;
    reconnect(name: string): Promise<IpcResult<McpServerView[]>>;
    importJson(text: string): Promise<IpcResult<{ imported: string[]; views: McpServerView[] }>>;
  };
  /** P7 专家团 */
  expert: {
    list(): Promise<IpcResult<Expert[]>>;
    upsert(input: ExpertUpsertInput): Promise<IpcResult<Expert>>;
    remove(id: string): Promise<IpcResult<void>>;
  };
  /** P6 用量统计 */
  usage: {
    stats(days?: number): Promise<IpcResult<UsageStats>>;
    records(filter?: { sessionId?: string; tool?: string }): Promise<IpcResult<ToolRecord[]>>;
  };
  onStream(callback: (event: StreamEvent) => void): () => void;
}

export function agent(): AgentBridge {
  const bridge = (window as unknown as { agent?: AgentBridge }).agent;
  if (!bridge) throw new Error('agent 桥接未初始化（需在 Electron 环境运行）');
  return bridge;
}
