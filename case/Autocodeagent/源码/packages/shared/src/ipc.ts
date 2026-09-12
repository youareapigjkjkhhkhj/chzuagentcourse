/**
 * IPC 白名单通道与 payload 校验（AGENTS §23：IPC payload 必须 zod 校验）。
 * Main 侧用 parse() 校验，非法输入直接拒绝，不做猜测。
 */
import { z } from 'zod';
import type { ModelConfig } from './types';

export const IpcChannels = {
  sessionList: 'session:list',
  sessionGet: 'session:get',
  sessionCreate: 'session:create',
  sessionDelete: 'session:delete',
  /** 清空当前会话：移除全部消息与 todos、标题复位，保留会话壳（原地重开，非删会话） */
  sessionClear: 'session:clear',
  /** 消息操作：撤回/重发 = 截断该条及之后；删除 = 单条 */
  sessionTruncate: 'session:truncate',
  sessionDeleteMessage: 'session:delete-message',
  /** 侧栏会话搜索：标题 + 消息内容全文 grep（Main 侧执行，Renderer 无 fs） */
  sessionSearch: 'session:search',
  /** P2 3.3 节点回溯：回到某消息节点重来（逆序强制回滚 + 分叉新会话），复用 SessionMessagePayload */
  sessionRollback: 'session:rollback',
  agentAsk: 'agent:ask',
  agentAbort: 'agent:abort',
  permissionResolve: 'permission:resolve',
  modelConfigGet: 'config:model:get',
  modelConfigSet: 'config:model:set',
  modelConfigList: 'config:model:list',
  modelConfigActive: 'config:model:active',
  modelConfigRemove: 'config:model:remove',
  settingsGet: 'config:settings:get',
  settingsSet: 'config:settings:set',
  webConfigGet: 'config:web:get',
  webConfigSet: 'config:web:set',
  skillsList: 'skills:list',
  skillsGet: 'skills:get',
  skillsSave: 'skills:save',
  skillsSetEnabled: 'skills:set-enabled',
  skillsCreate: 'skills:create',
  skillsRemove: 'skills:remove',
  skillsImport: 'skills:import',
  mcpList: 'mcp:list',
  mcpUpsert: 'mcp:upsert',
  mcpRemove: 'mcp:remove',
  mcpSetEnabled: 'mcp:set-enabled',
  mcpSetAlwaysLoad: 'mcp:set-always-load',
  mcpReconnect: 'mcp:reconnect',
  mcpImport: 'mcp:import',
  expertList: 'expert:list',
  expertUpsert: 'expert:upsert',
  expertRemove: 'expert:remove',
  usageStats: 'usage:stats',
  usageRecords: 'usage:records',
  workspaceSelect: 'workspace:select',
  workspaceGet: 'workspace:get',
  workspaceRemove: 'workspace:remove',
  workspaceSetActive: 'workspace:set-active',
  workspaceTree: 'workspace:tree',
  workspaceFile: 'workspace:file',
  workspacePreview: 'workspace:preview',
  workspaceGit: 'workspace:git',
  diffList: 'diff:list',
  diffGet: 'diff:get',
  diffAccept: 'diff:accept',
  diffAcceptAll: 'diff:accept-all',
  diffRevert: 'diff:revert',
  streamEvent: 'stream:event',
} as const;

export type IpcChannel = (typeof IpcChannels)[keyof typeof IpcChannels];

export const SessionIdPayload = z.object({ id: z.string().min(1).max(128) });

/** 会话搜索关键词（侧栏搜索框） */
export const SessionSearchPayload = z.object({ query: z.string().min(1).max(128) });
export type SessionSearchInput = z.infer<typeof SessionSearchPayload>;

/** 消息级操作（撤回 / 重发 / 删除）：sessionId + 目标消息 id */
export const SessionMessagePayload = z.object({
  sessionId: z.string().min(1).max(128),
  messageId: z.string().min(1).max(128),
});

/** P7：新建会话（title 缺省 = 「新会话」；expertId 缺省 = 普通助理会话） */
export const SessionCreatePayload = z.object({
  title: z.string().max(128).optional(),
  expertId: z.string().min(1).max(128).optional(),
});
export type SessionCreateInput = z.infer<typeof SessionCreatePayload>;

export const AskPayload = z.object({
  sessionId: z.string().min(1).max(128),
  message: z.string().min(1).max(20000),
  /** P4：/name 触发的技能名（正文作为高优先级指令注入） */
  skillName: z.string().min(1).max(64).optional(),
});

export const PermissionResolvePayload = z.object({
  requestId: z.string().min(1).max(128),
  allow: z.boolean(),
  remember: z.boolean(),
});

/** P2：审阅操作与只读浏览（均经 workspace jail，AGENTS §15/§23） */
export const ChangeIdPayload = z.object({ changeId: z.string().min(1).max(128) });

export const DiffListPayload = z.object({ sessionId: z.string().min(1).max(128) });

export const DiffAcceptAllPayload = z.object({ sessionId: z.string().min(1).max(128) });

export const WorkspaceFilePayload = z.object({ path: z.string().min(1).max(512) });

/** 多工作区：移除目录 / 切换活动目录 */
export const WorkspacePathPayload = z.object({ path: z.string().min(1).max(512) });

export const ModelConfigPayload = z.object({
  /** 新建时省略，编辑时必带（由 Main 端兼容处理） */
  id: z.string().min(1).max(64).optional(),
  name: z.string().min(1).max(64),
  provider: z.string().min(1).max(64),
  baseUrl: z.string().url(),
  model: z.string().min(1).max(128),
  apiKey: z.string().max(512),
  encrypted: z.boolean(),
  /** 高级参数默认不在 UI 暴露（对齐 Claude Code 等主流 Agent），省略时 Main 端补默认值 */
  temperature: z.number().min(0).max(2).optional(),
  maxTokens: z.number().int().min(1).max(200000).optional(),
  contextWindow: z.number().int().min(4000).max(1000000).optional(),
});

export type AskInput = z.infer<typeof AskPayload>;
export type ModelConfigInput = z.infer<typeof ModelConfigPayload>;

/** P3：应用设置更新（部分字段可选，省略即不修改） */
export const SettingsSetPayload = z.object({
  permissionMode: z.enum(['Plan', 'Ask', 'Auto']).optional(),
  execWhitelist: z.array(z.string().min(1).max(200)).max(50).optional(),
  disabledSkills: z.array(z.string().min(1).max(128)).max(200).optional(),
});
export type SettingsSetInput = z.infer<typeof SettingsSetPayload>;

/** 联网搜索配置更新：enabled/provider 存 settings；plainKey 加密存 KeyStore（省略=不改，空串=清除，非空=更新） */
export const WebConfigSetPayload = z.object({
  enabled: z.boolean().optional(),
  provider: z.enum(['tavily']).optional(),
  plainKey: z.string().max(512).optional(),
});
export type WebConfigSetInput = z.infer<typeof WebConfigSetPayload>;

/** P4：技能操作 payload */
export const SkillNamePayload = z.object({ name: z.string().min(1).max(64) });
export const SkillSavePayload = z.object({
  name: z.string().min(1).max(64),
  body: z.string().max(50000),
});
export const SkillEnabledPayload = z.object({
  name: z.string().min(1).max(64),
  enabled: z.boolean(),
});
/** 新增技能表单（原型同款：名称 + 来源 + 描述 + 正文） */
export const SkillCreatePayload = z.object({
  name: z.string().min(1).max(64),
  scope: z.enum(['global', 'project']),
  description: z.string().min(1).max(300),
  body: z.string().max(50000),
});
export type SkillCreateInput = z.infer<typeof SkillCreatePayload>;
/** 导入 ZIP 技能包：data = zip 二进制的 base64（上限约 10MB 原始） */
export const SkillImportPayload = z.object({
  data: z.string().min(1).max(14_000_000),
  scope: z.enum(['global', 'project']).optional(),
});
export type SkillImportInput = z.infer<typeof SkillImportPayload>;

/** P5：MCP 连接器 slug（工具挂载名需符合 function name 字符集） */
const mcpName = z.string().regex(/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,31}$/);

/** 新增 / 编辑连接器表单（常规通道；JSON 导入走 McpImportPayload） */
export const McpUpsertPayload = z
  .object({
    name: mcpName,
    type: z.enum(['stdio', 'http', 'sse']),
    command: z.string().max(512).optional(),
    args: z.array(z.string().max(1024)).max(64).optional(),
    env: z.record(z.string().max(1024)).optional(),
    url: z.string().max(2048).optional(),
    headers: z.record(z.string().max(1024)).optional(),
    description: z.string().max(300).optional(),
    enabled: z.boolean(),
    /** 强制常驻：跳过按需加载分流 */
    alwaysLoad: z.boolean().optional(),
    /** 上传图标 data URL（≈100KB 原图），仅接受 image 类型 */
    icon: z.string().max(150_000).optional(),
  })
  .superRefine((v, c) => {
    if (v.type === 'stdio' && !v.command) {
      c.addIssue({ code: z.ZodIssueCode.custom, path: ['command'], message: 'stdio 类型必填启动命令' });
    }
    if (v.type !== 'stdio' && !v.url) {
      c.addIssue({ code: z.ZodIssueCode.custom, path: ['url'], message: `${v.type} 类型必填端点 URL` });
    }
    if (v.env && Object.keys(v.env).length > 32) {
      c.addIssue({ code: z.ZodIssueCode.custom, path: ['env'], message: '环境变量最多 32 个' });
    }
    if (v.icon !== undefined && !v.icon.startsWith('data:image/')) {
      c.addIssue({ code: z.ZodIssueCode.custom, path: ['icon'], message: '图标必须为 data:image/* 格式' });
    }
  });
export type McpUpsertInput = z.infer<typeof McpUpsertPayload>;

export const McpNamePayload = z.object({ name: mcpName });
export const McpEnabledPayload = z.object({ name: mcpName, enabled: z.boolean() });
export const McpAlwaysLoadPayload = z.object({ name: mcpName, alwaysLoad: z.boolean() });
/** JSON 粘贴导入：兼容 {"mcpServers": {...}} 与内层对象（Claude Desktop / Cursor 格式） */
export const McpImportPayload = z.object({ text: z.string().min(1).max(100_000) });

/** P7：专家新增 / 编辑表单（id 缺省 = 新建；Logo 与 MCP 图标同款 data:image/* 校验） */
export const ExpertUpsertPayload = z
  .object({
    id: z.string().min(1).max(128).optional(),
    name: z.string().min(1).max(64),
    emoji: z.string().min(1).max(16),
    logo: z.string().max(150_000).optional(),
    description: z.string().max(300),
    tags: z.array(z.string().min(1).max(32)).max(8),
    persona: z.string().max(20000),
    tools: z.array(z.string().min(1).max(64)).max(40),
    skills: z.array(z.string().min(1).max(64)).max(20),
  })
  .superRefine((v, c) => {
    if (v.logo !== undefined && !v.logo.startsWith('data:image/')) {
      c.addIssue({ code: z.ZodIssueCode.custom, path: ['logo'], message: 'Logo 必须为 data:image/* 格式' });
    }
  });
export type ExpertUpsertInput = z.infer<typeof ExpertUpsertPayload>;

export const ExpertIdPayload = z.object({ id: z.string().min(1).max(128) });

/** P6：用量统计范围（缺省 = 全量；days = 近 N 天） */
export const UsageStatsPayload = z.object({ days: z.number().int().min(1).max(365).optional() });
export type UsageStatsInput = z.infer<typeof UsageStatsPayload>;

/** P6：执行记录筛选（会话 × 工具组合，缺省 = 不限） */
export const UsageRecordsPayload = z.object({
  sessionId: z.string().min(1).max(128).optional(),
  tool: z.string().min(1).max(128).optional(),
});
export type UsageRecordsInput = z.infer<typeof UsageRecordsPayload>;

/** 供 Main 侧统一校验：返回 ok 或带通道名的错误信息 */
export function validatePayload<T>(
  schema: z.ZodType<T>,
  data: unknown,
  channel: IpcChannel,
): { ok: true; value: T } | { ok: false; error: string } {
  const result = schema.safeParse(data);
  if (result.success) return { ok: true, value: result.data };
  return { ok: false, error: `[${channel}] 参数非法: ${result.error.issues[0]?.message ?? '未知'}` };
}

export type { ModelConfig };
