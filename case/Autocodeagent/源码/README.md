# AgentBuddy 源码

本地轻量编程代理。当前处于 **P0：应用壳与流式聊天**（见 `../项目阶段规划/`）。

## 结构

```
源码/
├── packages/
│   ├── shared/          # 类型 + zod IPC schema（三层共用）
│   └── agent-core/      # llm（OpenAI 兼容流式适配）· store（会话/配置持久化）
└── apps/
    └── desktop/         # Electron 壳 + Vue3 Renderer
```

## 开发

```bash
npm install
npm run typecheck     # 三包类型检查
npm run test          # agent-core 单测（vitest）
npm run dev           # 启动桌面应用（vite 渲染进程 + electron 主进程）
```

## 安全基线（P0 已执行）

- `contextIsolation: true`、`nodeIntegration: false`、`sandbox: true`
- Renderer 无 Node 能力，一切经 `preload` 白名单 + zod 校验
- API Key 仅掩码展示（P6 迁入 safeStorage）；日志不输出密钥
