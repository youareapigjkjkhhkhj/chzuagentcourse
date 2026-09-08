export type AgentRole = "user" | "assistant";

export type AgentMessageUiStatus = "streaming" | "done" | "cancelled" | "error";

export type AgentPersistedMessageStatus = "NORMAL" | "INTERRUPTED";

// hint 为流式过程中的运行提示 只存在于前端时间线 后端不落库
export type AgentBlockKind = "reasoning" | "answer" | "tool" | "hint";

export interface AgentSession {
  id: string;
  title: string;
  lastTime?: string;
  turns?: number;
}

// 后端回放的时间线块
export interface AgentBlock {
  kind: AgentBlockKind;
  at: string;
  text?: string | null;
  name?: string | null;
  displayName?: string | null;
  status?: "done" | "failed" | "interrupted" | null;
  result?: string | null;
}

// 前端时间线块 id 为客户端自增 open 为折叠面板展开态
export interface AgentBlockUI {
  id: number;
  kind: AgentBlockKind;
  at: string;
  text?: string;
  name?: string;
  displayName?: string;
  status?: "running" | "done" | "failed" | "interrupted";
  result?: string;
  open?: boolean;
  // 流式实测耗时 仅本次连接内可得 回放块无此二字段 行级不显示耗时
  startMs?: number;
  durationMs?: number;
}

export interface AgentMessage {
  id: string;
  role: AgentRole;
  content: string;
  thinking?: string;
  blocks?: AgentBlockUI[];
  status?: AgentMessageUiStatus;
  messageStatus?: AgentPersistedMessageStatus;
  createdAt?: string;
  // 轮次总耗时 流式收尾实测 回放由相邻 user/assistant createTime 差值补齐
  elapsedMs?: number;
}

export interface AgentMetaPayload {
  conversationId: string;
  taskId: string;
}

export interface AgentMessageDelta {
  type: string;
  delta: string;
}

export interface AgentToolProgress {
  name: string;
  displayName: string;
  status: "start" | "end";
  result?: string | null;
  ok?: boolean | null;
}

export interface AgentHintPayload {
  code: string;
  text: string;
}

export interface AgentCompletionPayload {
  messageId?: string | null;
  title?: string | null;
  messageStatus?: AgentPersistedMessageStatus;
}

// 引擎探活身份 /agent/v1/meta
export interface AgentEngineMeta {
  framework: string;
  model: string;
  maxIters: number;
  capabilities: string[];
  toolProvider: string;
  mcpConfigured: boolean;
}

// 原始帧抽屉逐条记录
export interface AgentRawFrame {
  id: number;
  ts: string;
  name: string;
  data: unknown;
}
