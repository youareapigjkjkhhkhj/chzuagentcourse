/**
 * IPC 注册：白名单通道 + zod 校验（AGENTS §23）。
 * 非法入参直接拒绝并返回错误信息，不做猜测。
 */
import { dialog, ipcMain, type BrowserWindow } from 'electron';
import { randomUUID } from 'node:crypto';
import { ConfigStore, ExpertStore, gitInfo, readWorkspaceFile, readWorkspaceFileBase64, SessionStore, workspaceTree, Workspace, type KeyStore, type McpPool, type SkillHub, type UsageStore } from '@agent-core/agent-core';
import {
  AskPayload,
  ChangeIdPayload,
  DiffAcceptAllPayload,
  DiffListPayload,
  ExpertIdPayload,
  ExpertUpsertPayload,
  IpcChannels,
  maskKey,
  McpEnabledPayload,
  McpImportPayload,
  McpNamePayload,
  McpUpsertPayload,
  ModelConfigPayload,
  PermissionResolvePayload,
  SessionCreatePayload,
  SessionIdPayload,
  SessionMessagePayload,
  SessionSearchPayload,
  SettingsSetPayload,
  SkillCreatePayload,
  SkillEnabledPayload,
  SkillImportPayload,
  SkillNamePayload,
  SkillSavePayload,
  UsageRecordsPayload,
  UsageStatsPayload,
  validatePayload,
  WebConfigSetPayload,
  WorkspacePathPayload,
  WorkspaceFilePayload,
  type ModelConfig,
  type WebConfigView,
} from '@agentbuddy/shared';
import { ChatService } from './chatService';

export interface IpcContext {
  window: BrowserWindow;
  sessions: SessionStore;
  configs: ConfigStore;
  chat: ChatService;
  workspace: Workspace;
  skills: SkillHub;
  /** P5：MCP 连接池 */
  mcp: McpPool;
  /** P7：专家存储 */
  experts: ExpertStore;
  /** P6：密钥密文存储 + 用量/执行记录 */
  keys: KeyStore;
  usage: UsageStore;
}

export function registerIpc(ctx: IpcContext): void {
  const { window, sessions, configs, chat, workspace, skills, mcp, experts, keys, usage } = ctx;
  const emit = (event: unknown) => {
    if (!window.isDestroyed()) window.webContents.send(IpcChannels.streamEvent, event);
  };

  // P6：模型配置下发一律掩码化 —— apiKey 清空，仅提供尾 4 位掩码；明文只在 Main 内部解密使用
  const masked = async (m: ModelConfig): Promise<ModelConfig> => {
    const plain = (await keys.get(m.id)) || m.apiKey;
    return { ...m, apiKey: '', apiKeyMask: plain ? maskKey(plain) : undefined };
  };

  // 联网搜索配置视图：enabled/provider 取自 settings，密钥状态取自 KeyStore（id='websearch'），仅下发掩码
  const webView = async (): Promise<WebConfigView> => {
    const s = await configs.getSettings();
    const plain = await keys.get('websearch');
    return { enabled: s.websearch.enabled, provider: s.websearch.provider, hasKey: !!plain, keyMask: plain ? maskKey(plain) : undefined };
  };

  const handle = (channel: string, fn: (...args: unknown[]) => unknown) => {
    ipcMain.handle(channel, async (_e, ...args) => {
      try {
        return { ok: true, data: await fn(...args) };
      } catch (err) {
        return { ok: false, error: err instanceof Error ? err.message : String(err) };
      }
    });
  };

  // 会话按活动工作区隔离（切换文件夹 = 切换历史）；旧会话（无 workspacePath）不匹配 → 隐藏
  handle(IpcChannels.sessionList, () => sessions.list(workspace.activePath()));

  handle(IpcChannels.sessionGet, (raw) => {
    const v = validatePayload(SessionIdPayload, raw, IpcChannels.sessionGet);
    if (!v.ok) throw new Error(v.error);
    return sessions.get(v.value.id);
  });

  handle(IpcChannels.sessionCreate, (raw) => {
    const v = validatePayload(SessionCreatePayload, raw ?? {}, IpcChannels.sessionCreate);
    if (!v.ok) throw new Error(v.error);
    return sessions.create(v.value.title ?? '', v.value.expertId, workspace.activePath());
  });

  handle(IpcChannels.sessionDelete, (raw) => {
    const v = validatePayload(SessionIdPayload, raw, IpcChannels.sessionDelete);
    if (!v.ok) throw new Error(v.error);
    return sessions.delete(v.value.id);
  });

  // 侧栏会话搜索：标题 + 消息内容 grep（Main 侧 fs，Renderer 无文件系统访问）
  handle(IpcChannels.sessionSearch, (raw) => {
    const v = validatePayload(SessionSearchPayload, raw, IpcChannels.sessionSearch);
    if (!v.ok) throw new Error(v.error);
    return sessions.search(v.value.query, workspace.activePath());
  });

  // 消息级操作：生成中拒绝（runTurn 持有 live 消息副本，边删边写会复活已删消息）
  handle(IpcChannels.sessionTruncate, (raw) => {
    const v = validatePayload(SessionMessagePayload, raw, IpcChannels.sessionTruncate);
    if (!v.ok) throw new Error(v.error);
    if (chat.isBusy(v.value.sessionId)) throw new Error('该会话正在生成中，请先停止再操作消息');
    return sessions.truncateFrom(v.value.sessionId, v.value.messageId).then(() => undefined);
  });

  handle(IpcChannels.sessionDeleteMessage, (raw) => {
    const v = validatePayload(SessionMessagePayload, raw, IpcChannels.sessionDeleteMessage);
    if (!v.ok) throw new Error(v.error);
    if (chat.isBusy(v.value.sessionId)) throw new Error('该会话正在生成中，请先停止再操作消息');
    return sessions.deleteMessage(v.value.sessionId, v.value.messageId).then(() => undefined);
  });

  // P2 3.3 节点回溯：生成中拒绝（回滚改写工作区 + 分叉会话，会与 runTurn 竞争同一 live 副本）
  handle(IpcChannels.sessionRollback, (raw) => {
    const v = validatePayload(SessionMessagePayload, raw, IpcChannels.sessionRollback);
    if (!v.ok) throw new Error(v.error);
    if (chat.isBusy(v.value.sessionId)) throw new Error('该会话正在生成中，请先停止再回溯');
    return chat.rollbackToNode(v.value.sessionId, v.value.messageId);
  });

  handle(IpcChannels.agentAsk, (raw) => {
    const v = validatePayload(AskPayload, raw, IpcChannels.agentAsk);
    if (!v.ok) throw new Error(v.error);
    return chat.ask(v.value.sessionId, v.value.message, emit, v.value.skillName);
  });

  handle(IpcChannels.agentAbort, (raw) => {
    const v = validatePayload(SessionIdPayload, raw, IpcChannels.agentAbort);
    if (!v.ok) throw new Error(v.error);
    return chat.abort(v.value.id);
  });

  handle(IpcChannels.permissionResolve, (raw) => {
    const v = validatePayload(PermissionResolvePayload, raw, IpcChannels.permissionResolve);
    if (!v.ok) throw new Error(v.error);
    return chat.resolvePermission(v.value.requestId, v.value.allow, v.value.remember);
  });

  handle(IpcChannels.modelConfigGet, async () => masked(await configs.get()));

  handle(IpcChannels.modelConfigSet, async (raw) => {
    const v = validatePayload(ModelConfigPayload, raw, IpcChannels.modelConfigSet);
    if (!v.ok) throw new Error(v.error);
    // 编辑已有配置时保留原高级参数；新建时生成 id 并自动激活（新增即用，对话框下拉立即可见）
    const base = v.value.id ? await configs.list().then((ms) => ms.find((m) => m.id === v.value.id)) : undefined;
    const plainKey = v.value.apiKey ?? '';
    // P6：密钥落 keys.json 密文；config.json 永远不存明文（空串 = 保留原 Key 不改）
    const saved = await configs.upsert({
      ...base,
      ...v.value,
      id: v.value.id ?? randomUUID(),
      apiKey: '',
      encrypted: plainKey ? true : base?.encrypted ?? false,
      temperature: v.value.temperature ?? base?.temperature ?? 0.2,
      maxTokens: v.value.maxTokens ?? base?.maxTokens ?? 8192,
      contextWindow: v.value.contextWindow ?? base?.contextWindow ?? 128000,
    });
    if (plainKey) await keys.set(saved.id, plainKey);
    if (!v.value.id) await configs.setActive(saved.id);
    return masked(saved);
  });

  handle(IpcChannels.modelConfigList, async () => {
    const list = await configs.list();
    return Promise.all(list.map((m) => masked(m)));
  });

  handle(IpcChannels.modelConfigActive, (raw) => {
    const v = validatePayload(SessionIdPayload, raw, IpcChannels.modelConfigActive);
    if (!v.ok) throw new Error(v.error);
    return configs.setActive(v.value.id);
  });

  handle(IpcChannels.modelConfigRemove, async (raw) => {
    const v = validatePayload(SessionIdPayload, raw, IpcChannels.modelConfigRemove);
    if (!v.ok) throw new Error(v.error);
    await keys.remove(v.value.id); // 同步清除密文，避免 keys.json 残留孤儿条目
    return configs.remove(v.value.id);
  });

  /* ── P6 用量统计：聚合视图 + 执行记录筛选 ── */
  handle(IpcChannels.usageStats, (raw) => {
    const v = validatePayload(UsageStatsPayload, raw, IpcChannels.usageStats);
    if (!v.ok) throw new Error(v.error);
    return usage.stats(v.value.days);
  });

  handle(IpcChannels.usageRecords, (raw) => {
    const v = validatePayload(UsageRecordsPayload, raw, IpcChannels.usageRecords);
    if (!v.ok) throw new Error(v.error);
    return usage.records(v.value);
  });

  /* ── P3 应用设置：模式 + EXEC 白名单 ── */
  handle(IpcChannels.settingsGet, () => configs.getSettings());

  handle(IpcChannels.settingsSet, (raw) => {
    const v = validatePayload(SettingsSetPayload, raw, IpcChannels.settingsSet);
    if (!v.ok) throw new Error(v.error);
    return configs.setSettings(v.value);
  });

  /* ── 联网搜索：webfetch 内置零配置；websearch 开关 + Tavily key（加密存 KeyStore） ── */
  handle(IpcChannels.webConfigGet, () => webView());

  handle(IpcChannels.webConfigSet, async (raw) => {
    const v = validatePayload(WebConfigSetPayload, raw, IpcChannels.webConfigSet);
    if (!v.ok) throw new Error(v.error);
    const cur = (await configs.getSettings()).websearch;
    await configs.setSettings({ websearch: { enabled: v.value.enabled ?? cur.enabled, provider: v.value.provider ?? cur.provider } });
    // plainKey 省略 = 不改；空串 = 清除；非空 = 加密落 KeyStore（config.json 永不存明文）
    if (v.value.plainKey !== undefined) {
      if (v.value.plainKey) await keys.set('websearch', v.value.plainKey);
      else await keys.remove('websearch');
    }
    return webView();
  });

  /* ── P4 Skills：两级扫描 / 正文读写 / 启停 ── */
  handle(IpcChannels.skillsList, () => skills.list());

  handle(IpcChannels.skillsGet, (raw) => {
    const v = validatePayload(SkillNamePayload, raw, IpcChannels.skillsGet);
    if (!v.ok) throw new Error(v.error);
    return skills.get(v.value.name);
  });

  handle(IpcChannels.skillsSave, (raw) => {
    const v = validatePayload(SkillSavePayload, raw, IpcChannels.skillsSave);
    if (!v.ok) throw new Error(v.error);
    return skills.save(v.value.name, v.value.body);
  });

  handle(IpcChannels.skillsSetEnabled, (raw) => {
    const v = validatePayload(SkillEnabledPayload, raw, IpcChannels.skillsSetEnabled);
    if (!v.ok) throw new Error(v.error);
    return skills.setEnabled(v.value.name, v.value.enabled);
  });

  handle(IpcChannels.skillsCreate, (raw) => {
    const v = validatePayload(SkillCreatePayload, raw, IpcChannels.skillsCreate);
    if (!v.ok) throw new Error(v.error);
    return skills.create(v.value);
  });

  handle(IpcChannels.skillsRemove, (raw) => {
    const v = validatePayload(SkillNamePayload, raw, IpcChannels.skillsRemove);
    if (!v.ok) throw new Error(v.error);
    return skills.remove(v.value.name);
  });

  handle(IpcChannels.skillsImport, (raw) => {
    const v = validatePayload(SkillImportPayload, raw, IpcChannels.skillsImport);
    if (!v.ok) throw new Error(v.error);
    return skills.importZip(Buffer.from(v.value.data, 'base64'), v.value.scope ?? 'global');
  });

  /* ── P5 MCP：视图 / 表单增改 / 删除 / 启停 / 重连 / JSON 导入 ── */
  handle(IpcChannels.mcpList, () => mcp.views());

  handle(IpcChannels.mcpUpsert, async (raw) => {
    const v = validatePayload(McpUpsertPayload, raw, IpcChannels.mcpUpsert);
    if (!v.ok) throw new Error(v.error);
    await mcp.upsert(v.value);
    return mcp.views();
  });

  handle(IpcChannels.mcpRemove, async (raw) => {
    const v = validatePayload(McpNamePayload, raw, IpcChannels.mcpRemove);
    if (!v.ok) throw new Error(v.error);
    await mcp.remove(v.value.name);
    return mcp.views();
  });

  handle(IpcChannels.mcpSetEnabled, async (raw) => {
    const v = validatePayload(McpEnabledPayload, raw, IpcChannels.mcpSetEnabled);
    if (!v.ok) throw new Error(v.error);
    await mcp.setEnabled(v.value.name, v.value.enabled);
    return mcp.views();
  });

  handle(IpcChannels.mcpReconnect, async (raw) => {
    const v = validatePayload(McpNamePayload, raw, IpcChannels.mcpReconnect);
    if (!v.ok) throw new Error(v.error);
    await mcp.reconnect(v.value.name);
    return mcp.views();
  });

  handle(IpcChannels.mcpImport, async (raw) => {
    const v = validatePayload(McpImportPayload, raw, IpcChannels.mcpImport);
    if (!v.ok) throw new Error(v.error);
    const imported = await mcp.importJson(v.value.text);
    return { imported: imported.map((c) => c.name), views: mcp.views() };
  });

  /* ── P7 专家团：清单 / 新增编辑 / 删除（存储层同 schema 复核，§23） ── */
  handle(IpcChannels.expertList, () => experts.list());

  handle(IpcChannels.expertUpsert, (raw) => {
    const v = validatePayload(ExpertUpsertPayload, raw, IpcChannels.expertUpsert);
    if (!v.ok) throw new Error(v.error);
    return experts.upsert(v.value);
  });

  handle(IpcChannels.expertRemove, (raw) => {
    const v = validatePayload(ExpertIdPayload, raw, IpcChannels.expertRemove);
    if (!v.ok) throw new Error(v.error);
    return experts.remove(v.value.id);
  });

  handle(IpcChannels.workspaceGet, () => workspace.state());

  handle(IpcChannels.workspaceRemove, (raw) => {
    const v = validatePayload(WorkspacePathPayload, raw, IpcChannels.workspaceRemove);
    if (!v.ok) throw new Error(v.error);
    return workspace.remove(v.value.path);
  });

  handle(IpcChannels.workspaceSetActive, (raw) => {
    const v = validatePayload(WorkspacePathPayload, raw, IpcChannels.workspaceSetActive);
    if (!v.ok) throw new Error(v.error);
    return workspace.setActive(v.value.path);
  });

  handle(IpcChannels.workspaceTree, () => {
    const { roots, active } = workspace.state();
    if (roots.length === 0) throw new Error('未选择工作区目录');
    return workspaceTree(roots, active);
  });

  handle(IpcChannels.workspaceFile, (raw) => {
    const v = validatePayload(WorkspaceFilePayload, raw, IpcChannels.workspaceFile);
    if (!v.ok) throw new Error(v.error);
    const { roots, active } = workspace.state();
    if (roots.length === 0) throw new Error('未选择工作区目录');
    return readWorkspaceFile(roots, active, v.value.path);
  });

  handle(IpcChannels.workspacePreview, (raw) => {
    const v = validatePayload(WorkspaceFilePayload, raw, IpcChannels.workspacePreview);
    if (!v.ok) throw new Error(v.error);
    const { roots, active } = workspace.state();
    if (roots.length === 0) throw new Error('未选择工作区目录');
    return readWorkspaceFileBase64(roots, active, v.value.path);
  });

  handle(IpcChannels.workspaceGit, () => {
    const root = workspace.activePath();
    if (!root) return null;
    return gitInfo(root);
  });

  /* ── P2 审阅：清单 / Diff / 接受 / 撤销 ── */
  handle(IpcChannels.diffList, (raw) => {
    const v = validatePayload(DiffListPayload, raw, IpcChannels.diffList);
    if (!v.ok) throw new Error(v.error);
    return chat.listChanges(v.value.sessionId);
  });

  handle(IpcChannels.diffGet, (raw) => {
    const v = validatePayload(ChangeIdPayload, raw, IpcChannels.diffGet);
    if (!v.ok) throw new Error(v.error);
    return chat.getDiff(v.value.changeId);
  });

  handle(IpcChannels.diffAccept, (raw) => {
    const v = validatePayload(ChangeIdPayload, raw, IpcChannels.diffAccept);
    if (!v.ok) throw new Error(v.error);
    return chat.acceptChange(v.value.changeId);
  });

  handle(IpcChannels.diffAcceptAll, (raw) => {
    const v = validatePayload(DiffAcceptAllPayload, raw, IpcChannels.diffAcceptAll);
    if (!v.ok) throw new Error(v.error);
    return chat.acceptAll(v.value.sessionId);
  });

  handle(IpcChannels.diffRevert, (raw) => {
    const v = validatePayload(ChangeIdPayload, raw, IpcChannels.diffRevert);
    if (!v.ok) throw new Error(v.error);
    return chat.revertChange(v.value.changeId);
  });

  handle(IpcChannels.workspaceSelect, async () => {
    const result = await dialog.showOpenDialog(window, {
      properties: ['openDirectory', 'multiSelections'],
      title: '选择工作区目录（可多选关联）',
    });
    if (result.canceled || result.filePaths.length === 0) return null;
    // 多工作区：逐个关联，最后一个选中的作为活动目录
    let state = workspace.state();
    for (const p of result.filePaths) state = await workspace.open(p);
    return state;
  });
}
