/**
 * 领域类型：会话 / 消息 / 模型配置 / LLM 归一化结果。
 * 三层（Main / Preload / Renderer）共用，不含任何 Node 依赖。
 */

export type Role = 'user' | 'assistant' | 'tool' | 'system';

/** 风险等级（技术方案 §4.2 权限矩阵列） */
export type Risk = 'READ' | 'WRITE' | 'EXEC' | 'NETWORK' | 'DANGEROUS';

/** 权限模式（P3 §4.2 决策矩阵行：Plan 只读 / Ask 逐次确认 / Auto 白名单自动） */
export type PermissionMode = 'Plan' | 'Ask' | 'Auto';

/** 应用级设置（P3：持久化于 config.json；DANGEROUS 授权永不持久，§4.2） */
export interface AppSettings {
  /** 工作区默认权限（盾牌菜单三档） */
  permissionMode: PermissionMode;
  /** Auto 模式 EXEC 低风险白名单（正则源串；空 = 内置默认清单） */
  execWhitelist: string[];
  /** P4：禁用技能名清单（未列出 = 启用） */
  disabledSkills: string[];
  /** 联网搜索（websearch）非密钥配置；apiKey 单独加密存于 KeyStore（id='websearch'） */
  websearch: WebSearchSettings;
}

/** 联网搜索设置（webfetch 内置零配置；websearch 需开启并配置 Tavily key 方注入） */
export interface WebSearchSettings {
  enabled: boolean;
  provider: 'tavily';
}

/** 联网搜索配置视图（含密钥状态、不含明文；供设置页展示，Main 侧组装） */
export interface WebConfigView {
  enabled: boolean;
  provider: 'tavily';
  hasKey: boolean;
  keyMask?: string;
}

/** assistant 消息携带的工具调用（arguments 保留原始 JSON 串，§17 流结束后一次性 parse） */
export interface StoredToolCall {
  id: string;
  name: string;
  arguments: string;
}

/** 多模态图片（user 消息附带）：mime + 不含 data: 前缀的 base64 正文 */
export interface ChatImage {
  mime: string;
  dataBase64: string;
}

export interface ChatMessage {
  id: string;
  role: Role;
  content: string;
  /** 多模态：user 消息附带的图片（随会话落盘 + 回放；toWire 时组装为 image_url content 分片） */
  images?: ChatImage[];
  /** 推理模型思维链（reasoning_content）：仅前端 live 展示，不落盘、不进下一轮 wire 历史 */
  reasoning?: string;
  /** unix ms */
  createdAt: number;
  /** assistant：本轮发起的工具调用 */
  toolCalls?: StoredToolCall[];
  /** tool：对应的 tool_call id（消息 id 与之相同，便于 UI live 与落盘一致） */
  toolCallId?: string;
  /** tool：Trace 卡片元数据 */
  toolName?: string;
  toolArgs?: string;
  toolOk?: boolean;
  toolMs?: number;
  /** tool：write/edit/bash 产生的变更集 id（P2 审阅链路，回放时恢复 [查看 Diff]） */
  toolChangeId?: string;
}

export interface SessionMeta {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messageCount: number;
  /** P7：绑定的专家 id（专家会话专属；ask 时自动套用其人设与工具/技能限定） */
  expertId?: string;
  /** 会话所属工作区：创建时的活动根目录绝对路径（null = 无工作区时创建）。
   * 侧栏 / 搜索按当前活动工作区过滤——切换文件夹即切换历史（对齐主流 Agent 的项目级会话隔离）。
   * 本次改动前的旧会话无此字段（undefined），不匹配任何工作区值，默认隐藏（文件保留在磁盘）。 */
  workspacePath?: string | null;
}

export interface SessionData extends SessionMeta {
  messages: ChatMessage[];
  /** P4：todo_write 清单随会话落盘，回放恢复 Checklist */
  todos?: TodoItem[];
}

/** 会话搜索命中条目（session:search 响应）：snippet = 消息内首个命中位置的上下文摘录 */
export interface SessionSearchHit {
  id: string;
  title: string;
  expertId?: string;
  updatedAt: number;
  snippet: string;
}

/** P2 3.3 节点回溯结果：branchSessionId = 从该节点分叉的新会话；restored = 实际回滚的变更集数 */
export interface RollbackResult {
  branchSessionId: string;
  restored: number;
}

export interface ModelConfig {
  /** 多模型配置列表中的唯一标识（新建时由 Main 生成） */
  id: string;
  name: string;
  provider: string;
  baseUrl: string;
  model: string;
  apiKey: string;
  /** P6 接入 safeStorage 后的过渡字段：true = apiKey 已迁出 config.json（密文在 keys.json） */
  encrypted: boolean;
  /** P6：Renderer 专用掩码视图（sk-••••8F2A 形态）；Main 内部模型对象不含该字段 */
  apiKeyMask?: string;
  temperature: number;
  maxTokens: number;
  /** 模型上下文上限（token 预算 = 该值 − 8k，§4.3） */
  contextWindow: number;
}

/** 厂商差异归一后的 LLM 响应（见技术方案 §4.4） */
export interface NormalizedLLMResponse {
  message: ChatMessage;
  /** P1 Agent Loop 起使用：流结束后按 index 归一的 tool_calls */
  toolCalls?: StoredToolCall[];
  usage: NormalizedUsage;
  finishReason: 'stop' | 'length' | 'tool_calls' | 'content_filter' | 'unknown';
}

export interface NormalizedUsage {
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  /** 命中 Prompt Cache 的输入 Token（跨厂商归一，见技术方案 §4.7） */
  cacheReadTokens: number;
}

/** wire content 分片（多模态）：文本 or 图片（OpenAI 兼容 image_url，url 为 data:<mime>;base64,<正文>） */
export type WireContentPart =
  | { type: 'text'; text: string }
  | { type: 'image_url'; image_url: { url: string } };

/** 发给 LLM 的 wire 消息（OpenAI 兼容格式） */
export interface LlmWireMessage {
  role: Role;
  /** 纯文本 or 多模态分片数组（user 带图时）；assistant/tool 恒为 string | null */
  content: string | WireContentPart[] | null;
  tool_calls?: Array<{ id: string; type: 'function'; function: { name: string; arguments: string } }>;
  tool_call_id?: string;
}

/** 工具 function-calling schema（OpenAI 格式） */
export interface LlmToolSchema {
  type: 'function';
  function: { name: string; description: string; parameters: Record<string, unknown> };
}

export type StreamEvent =
  | { type: 'token'; sessionId: string; messageId: string; delta: string }
  /** 推理模型思维链增量（reasoning_content）：前端灰色「思考过程」区展示，与正式回答分离 */
  | { type: 'reasoning'; sessionId: string; messageId: string; delta: string }
  | { type: 'done'; sessionId: string; messageId: string; usage: NormalizedUsage }
  | { type: 'interrupted'; sessionId: string }
  | { type: 'error'; sessionId: string; message: string }
  | { type: 'tool_start'; sessionId: string; callId: string; name: string; argsSummary: string; risk: Risk }
  | { type: 'tool_result'; sessionId: string; callId: string; ok: boolean; ms: number; summary: string }
  | { type: 'permission_request'; sessionId: string; requestId: string; callId: string; name: string; risk: Risk; detail: string }
  | { type: 'diff_ready'; sessionId: string; callId: string; changeId: string }
  | { type: 'plan'; sessionId: string; todos: TodoItem[] }
  | { type: 'mcp'; servers: McpServerView[] }
  /** 非致命提醒（如 MCP 工具超额丢弃）：UI 琥珀横幅展示，不打断回合 */
  | { type: 'notice'; sessionId: string; message: string }
  /** 会话标题异步更新（首轮后 LLM 自动命名）：侧栏据此刷新 */
  | { type: 'title'; sessionId: string; title: string }
  /** 应用菜单导航广播（无 sessionId）：view = 目标视图名，或 new-session / pick-workspace 动作 */
  | { type: 'nav'; view: string };

/**
 * 会话进行态快照（切换会话时前端据此对齐 busy / 恢复权限卡）：
 * busy = 后端是否仍在为该会话跑 runTurn；pending = 挂起中的权限询问——
 * permission_request 是一次性事件，切走会话即被 sessionId 过滤丢弃且不重发，故须主动查回才能重画权限卡。
 */
export interface SessionRunState {
  busy: boolean;
  pending: { requestId: string; callId: string; name: string; risk: Risk; detail: string } | null;
}

/* ── P2 审阅 / Diff 视图类型（三层共用，无 Node 依赖） ── */

export type ReviewStatus = 'pending' | 'accepted' | 'reverted';
export type EntryKind = 'modified' | 'created' | 'deleted' | 'renamed';

/** 变更条目（路径为工作区相对路径，展示用） */
export interface ChangeEntryView {
  kind: EntryKind;
  from: string;
  to?: string;
}

/** 会话审阅清单条目（diff:list 响应） */
export interface ChangeSetView {
  changeId: string;
  sessionId: string;
  status: ReviewStatus;
  createdAt: number;
  entries: ChangeEntryView[];
  /** git 整树快照（bash 等无文件清单场景） */
  isGitSnapshot: boolean;
}

/** 单行差异：ctx 上下文 / del 删除（旧侧行号）/ add 新增（新侧行号） */
export interface DiffLine {
  kind: 'ctx' | 'del' | 'add';
  text: string;
  oldNo?: number;
  newNo?: number;
}

/** 单文件 Diff（diff:get 响应内的文件单元） */
export interface FileDiff {
  path: string;
  kind: EntryKind;
  insertions: number;
  deletions: number;
  lines: DiffLine[];
}

/** 完整 Diff 视图（diff:get 响应） */
export interface DiffView {
  changeId: string;
  status: ReviewStatus;
  createdAt: number;
  /** git 整树快照时无逐文件明细，仅支持整体撤销 */
  isGitSnapshot: boolean;
  files: FileDiff[];
}

/** 文件树节点（workspace:tree 响应） */
export interface TreeNode {
  name: string;
  /** 相对工作区路径 */
  path: string;
  dir: boolean;
  children?: TreeNode[];
}

/** 工作区条目（@ 提及菜单：文件夹 + 文件） */
export interface WorkspaceEntry {
  path: string;
  dir: boolean;
}

/** 多工作区状态：roots = 已关联目录清单；active = 当前活动目录（相对路径解析 / 命令 cwd / git 归属） */
export interface WorkspaceState {
  roots: string[];
  active: string | null;
}

/** git 信息（workspace:git 响应，非 git 仓库返回 null） */
export interface GitInfo {
  branch: string;
  dirty: number;
}

/* ── P4 Skills / Todo 类型 ── */

/** 技能元数据（管理页 + 系统提示目录注入） */
export interface SkillMeta {
  name: string;
  description: string;
  /** 来源：全局 ~/.AgentBuddy/skills / 项目 <ws>/.AgentBuddy/skills */
  source: 'global' | 'project';
  /** SKILL.md 绝对路径（查看 / 编辑） */
  path: string;
  enabled: boolean;
  /** 畸形告警（缺 frontmatter / 非法字段）；存在则不参与注入与触发 */
  warning?: string;
}

/** todo_write 任务项（随会话落盘 + 中栏 Checklist） */
export interface TodoItem {
  id: string;
  content: string;
  status: 'pending' | 'in_progress' | 'done' | 'cancelled';
}

/* ── P6 用量统计 / 执行记录类型 ── */

/** 单次 LLM 响应归一用量落盘条目（usage.jsonl 一行） */
export interface UsageEntry {
  ts: number;
  sessionId: string;
  model: string;
  provider: string;
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  cacheReadTokens: number;
}

/** 单次工具调用落盘条目（records.jsonl 一行） */
export interface ToolRecord {
  ts: number;
  sessionId: string;
  tool: string;
  target: string;
  risk: Risk;
  ok: boolean;
  ms: number;
}

/** 用量聚合视图（usage:stats 响应） */
export interface UsageStats {
  totals: {
    /** 输入 + 输出 */
    tokens: number;
    promptTokens: number;
    completionTokens: number;
    /** 估算费用（美元，按模型单价累加） */
    cost: number;
    /** 工具调用次数 */
    calls: number;
    /** 去重会话数 */
    sessions: number;
    /** 缓存命中率 %（prompt 为 0 时 = 0，不报错） */
    cacheHitRate: number;
    cacheReadTokens: number;
  };
  /** 近 7 日柱状图（MM-DD） */
  daily: Array<{ day: string; tokens: number }>;
  /** 工具调用分布（降序） */
  byTool: Array<{ tool: string; count: number }>;
  /** 按模型消耗 */
  byModel: Array<{
    model: string;
    provider: string;
    reqs: number;
    input: number;
    output: number;
    cacheRead: number;
    cost: number;
  }>;
}

/* ── P7 专家团类型 ── */

/**
 * 专家配置（持久化于 ~/.AgentBuddy/experts.json）：
 * 人设 + 绑定的工具/Skills 子集；会话经 SessionMeta.expertId 绑定后，
 * ask 每轮自动注入 persona 并限定工具下发与技能目录（agent-core 只消费数据，不知道存储/UI）。
 */
export interface Expert {
  id: string;
  name: string;
  /** 头像 Emoji（未上传 Logo 时展示） */
  emoji: string;
  /** 上传的 Logo（data URL，≤100KB 原图；与 MCP 连接器图标同款校验） */
  logo?: string;
  description: string;
  /** 能力标签（卡片展示） */
  tags: string[];
  /** 人设 / System Prompt 追加段（空 = 不注入） */
  persona: string;
  /** 绑定工具：内置工具名（read/glob/grep/edit/write/bash）或 'mcp:连接器名'；空 = 全部可用 */
  tools: string[];
  /** 绑定技能名（目录只下发这些；空 = 全部启用技能） */
  skills: string[];
  createdAt: number;
  updatedAt: number;
}

/* ── P5 MCP 连接器类型 ── */

/** 传输类型：stdio / http（Streamable HTTP，主流网关默认）/ sse（旧版兼容） */
export type McpTransportType = 'stdio' | 'http' | 'sse';

export type McpStatus = 'connected' | 'connecting' | 'offline' | 'disabled';

/** 连接器配置（持久化于 ~/.AgentBuddy/mcp.json 的 mcpServers） */
export interface McpServerConfig {
  name: string;
  type: McpTransportType;
  command?: string;
  args?: string[];
  /** 支持 ${VAR} 占位符：连接时从系统环境变量注入；值不落盘、不进日志 */
  env?: Record<string, string>;
  url?: string;
  /** http/sse 自定义请求头（鉴权等；值支持 ${VAR} 占位，连接时解析注入，不进日志） */
  headers?: Record<string, string>;
  description?: string;
  enabled: boolean;
  /** 强制常驻：即使 MCP schema 合计超阈值也全量下发工具参数，跳过按需检索（默认 false = 参与按需分流） */
  alwaysLoad?: boolean;
  /** 上传的图标（data URL，≤100KB 原图） */
  icon?: string;
}

export interface McpToolView {
  name: string;
  description: string;
}

/** 管理页卡片视图：配置 + 运行时状态 */
export interface McpServerView {
  config: McpServerConfig;
  status: McpStatus;
  tools: McpToolView[];
  error?: string;
  /** 该连接器工具当前处于 deferred 按需模式（未常驻参数定义，需 search_tools 检索后方可调用） */
  onDemand?: boolean;
}
