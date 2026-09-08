/**
 * Electron Main 入口：窗口创建、存储初始化、IPC 注册、退出落盘。
 * 安全基线：contextIsolation / sandbox 开启，Renderer 无 Node 能力。
 */
import { app, BrowserWindow, dialog, Menu, protocol, shell, type MenuItemConstructorOptions } from 'electron';
import { extname, join } from 'node:path';
import { homedir } from 'node:os';
import { cp, access, readFile } from 'node:fs/promises';
import { ConfigStore, ExpertStore, KeyStore, McpConfigStore, McpPool, SessionStore, SkillHub, UsageStore, Workspace } from '@agent-core/agent-core';
import { IpcChannels, type McpServerView } from '@agentbuddy/shared';
import { ChatService } from './chatService';
import { registerIpc } from './ipc';
import { createKeyVault } from './keyVault';

/** 预览自定义协议 abp://ws/<工作区相对路径>：只读服务工作区文件，让 HTML 预览的相对
 * css/js/图片按真实目录结构加载（srcdoc 无 base URL 会丢样式）。standard 使 URL 具备
 * host/pathname 与相对解析能力；secure+supportFetchAPI 支持页面内 fetch / module 脚本。必须在 app ready 前注册。 */
protocol.registerSchemesAsPrivileged([
  { scheme: 'abp', privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true } },
]);

/** abp 协议 MIME 映射（按扩展名）；未列出回落 octet-stream */
const ABP_MIME: Record<string, string> = {
  html: 'text/html; charset=utf-8', htm: 'text/html; charset=utf-8',
  css: 'text/css; charset=utf-8', js: 'text/javascript; charset=utf-8', mjs: 'text/javascript; charset=utf-8',
  json: 'application/json; charset=utf-8', map: 'application/json; charset=utf-8', txt: 'text/plain; charset=utf-8',
  svg: 'image/svg+xml', png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif',
  webp: 'image/webp', ico: 'image/x-icon', bmp: 'image/bmp', avif: 'image/avif',
  woff: 'font/woff', woff2: 'font/woff2', ttf: 'font/ttf', otf: 'font/otf',
  mp4: 'video/mp4', webm: 'video/webm', mp3: 'audio/mpeg', wav: 'audio/wav', pdf: 'application/pdf',
};

async function createWindow(): Promise<void> {
  // 数据目录对齐主流 Agent（~/.claude、~/.codex）：用户主目录下的 .AgentBuddy
  const dataDir = join(homedir(), '.AgentBuddy');

  // 一次性迁移：旧版存于 Electron userData，新目录不存在时拷入（不删旧目录）
  const legacyDir = join(app.getPath('userData'), 'data');
  try {
    await access(dataDir);
  } catch {
    try {
      await access(legacyDir);
      await cp(legacyDir, dataDir, { recursive: true });
    } catch {
      /* 旧目录不存在则首次全新初始化 */
    }
  }

  const sessions = new SessionStore(join(dataDir, 'sessions'));
  const configs = new ConfigStore(dataDir);
  const workspace = new Workspace(dataDir);
  await sessions.init();
  await configs.init();
  await workspace.init();

  // abp 协议 handler：abp://ws/<相对路径> → workspace jail 解析 → 只读返回。
  // ACAO:* 让 HTML 内 module 脚本 / crossorigin 资源可跨（沙箱 iframe 的 opaque 源）加载。
  protocol.handle('abp', async (req) => {
    try {
      const rel = decodeURIComponent(new URL(req.url).pathname).replace(/^\/+/, '');
      const abs = await workspace.resolvePath(rel);
      const buf = await readFile(abs);
      const mime = ABP_MIME[extname(abs).slice(1).toLowerCase()] ?? 'application/octet-stream';
      // 用 byteOffset/length 视图避免 Node Buffer 池化导致的多余字节
      const body = new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength);
      return new Response(body, {
        headers: { 'content-type': mime, 'cache-control': 'no-store', 'access-control-allow-origin': '*' },
      });
    } catch {
      return new Response('Not Found', { status: 404 });
    }
  });

  // P4：两级技能（全局 ~/.AgentBuddy/skills + 项目 <ws>/.AgentBuddy/skills）
  const skills = new SkillHub({
    globalDir: join(dataDir, 'skills'),
    projectDir: () => workspace.activePath(),
    getDisabled: () => configs.getSettings().then((s) => s.disabledSkills),
    setDisabled: async (disabledSkills) => {
      await configs.setSettings({ disabledSkills });
    },
  });
  await skills.seed(); // 首次启动播种内置示例（/review /test），已存在不覆盖

  // P5：MCP 连接池（~/.AgentBuddy/mcp.json）；状态变化经 stream:event 广播（§18）
  // 窗口未就绪前广播暂存为空操作，窗口创建后绑定真实发送器（连接异步完成，不会丢状态）
  let emitMcp: (views: McpServerView[]) => void = () => undefined;
  const mcp = new McpPool({
    store: new McpConfigStore(join(dataDir, 'mcp.json')),
    onViews: (views) => emitMcp(views),
  });

  // P6：密钥密文存储（safeStorage，keys.json 无明文）+ 用量/执行记录（usage.jsonl / records.jsonl）
  const keys = new KeyStore(join(dataDir, 'keys.json'), createKeyVault());
  const usage = new UsageStore(dataDir);
  await keys.migrate(configs); // P0 明文一次性迁出，迁后 config.json 不再含 apiKey 明文

  // P7：专家团（~/.AgentBuddy/experts.json），会话绑定 expertId 后 ask 自动套用
  const experts = new ExpertStore(dataDir);
  await experts.init();

  const chat = new ChatService(sessions, configs, workspace, dataDir, skills, mcp, experts, {
    getKey: (id) => keys.get(id),
    usage,
  });

  const window = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 900,
    minHeight: 600,
    title: 'AgentBuddy',
    backgroundColor: '#faf6ef',
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true,
      preload: join(__dirname, 'preload.cjs'),
    },
  });

  // 外链一律走系统浏览器，Renderer 无导航能力
  window.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith('https:') || url.startsWith('http:')) void shell.openExternal(url);
    return { action: 'deny' };
  });
  window.webContents.on('will-navigate', (e) => e.preventDefault());

  registerIpc({ window, sessions, configs, chat, workspace, skills, mcp, experts, keys, usage });

  emitMcp = (views) => {
    if (!window.isDestroyed()) window.webContents.send(IpcChannels.streamEvent, { type: 'mcp', servers: views });
  };
  void mcp.init(); // 启用中的连接器异步连接，不阻塞窗口加载

  Menu.setApplicationMenu(buildMenu(window, dataDir));

  if (process.env['VITE_DEV_SERVER_URL']) {
    await window.loadURL(process.env['VITE_DEV_SERVER_URL']);
  } else {
    await window.loadFile(join(__dirname, '../renderer/index.html'));
  }

  let flushed = false;
  app.on('before-quit', (e) => {
    // before-quit 不等待异步：拦截退出，会话落盘 + MCP 连接全部收尾后再真正退出（否则关窗丢最后一段消息）
    if (flushed) return;
    e.preventDefault();
    void sessions
      .flushAll()
      .then(() => mcp.closeAll())
      .finally(() => {
        flushed = true;
        app.quit();
      });
  });
}

/** 应用菜单（中文，替换 Electron 默认英文菜单）：文件 / 编辑 / 转到 / 视图 / 窗口 / 帮助。
 * 导航与新建/打开动作经 stream:event 下发 { type:'nav', view }（§18 事件驱动），Renderer 路由；
 * 编辑菜单必须保留 role（否则复制/粘贴/撤销在输入框失效）。 */
function buildMenu(window: BrowserWindow, dataDir: string): Menu {
  const nav = (view: string): void => {
    if (!window.isDestroyed()) window.webContents.send(IpcChannels.streamEvent, { type: 'nav', view });
  };
  const template: MenuItemConstructorOptions[] = [
    {
      label: '文件',
      submenu: [
        { label: '新建会话', accelerator: 'CmdOrCtrl+N', click: () => nav('new-session') },
        { label: '打开工作区…', accelerator: 'CmdOrCtrl+O', click: () => nav('pick-workspace') },
        { type: 'separator' },
        { role: 'quit', label: '退出 AgentBuddy' },
      ],
    },
    {
      label: '编辑',
      submenu: [
        { role: 'undo', label: '撤销' },
        { role: 'redo', label: '重做' },
        { type: 'separator' },
        { role: 'cut', label: '剪切' },
        { role: 'copy', label: '复制' },
        { role: 'paste', label: '粘贴' },
        { role: 'selectAll', label: '全选' },
      ],
    },
    {
      label: '转到',
      submenu: [
        { label: 'AI 助理', accelerator: 'CmdOrCtrl+1', click: () => nav('assistant') },
        { label: '专家团', accelerator: 'CmdOrCtrl+2', click: () => nav('experts') },
        { label: '技能 Skills', accelerator: 'CmdOrCtrl+3', click: () => nav('skills') },
        { label: 'MCP 连接器', accelerator: 'CmdOrCtrl+4', click: () => nav('mcp') },
        { label: '模型配置', accelerator: 'CmdOrCtrl+5', click: () => nav('models') },
        { label: '用量统计', accelerator: 'CmdOrCtrl+6', click: () => nav('usage') },
      ],
    },
    {
      label: '视图',
      submenu: [
        { role: 'reload', label: '重新加载' },
        { role: 'forceReload', label: '强制重新加载' },
        { role: 'toggleDevTools', label: '开发者工具' },
        { type: 'separator' },
        { role: 'resetZoom', label: '实际大小' },
        { role: 'zoomIn', label: '放大' },
        { role: 'zoomOut', label: '缩小' },
        { type: 'separator' },
        { role: 'togglefullscreen', label: '全屏切换' },
      ],
    },
    {
      label: '窗口',
      submenu: [
        { role: 'minimize', label: '最小化' },
        { role: 'close', label: '关闭窗口' },
      ],
    },
    {
      label: '帮助',
      submenu: [
        {
          label: '关于 AgentBuddy',
          click: () => {
            void dialog.showMessageBox(window, {
              type: 'info',
              title: '关于 AgentBuddy',
              message: `AgentBuddy v${app.getVersion()}`,
              detail: `本地轻量的通用 AI 助理\n数据目录：${dataDir}`,
              buttons: ['知道了'],
            });
          },
        },
        { label: '打开数据目录', click: () => void shell.openPath(dataDir) },
      ],
    },
  ];
  return Menu.buildFromTemplate(template);
}

void app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
