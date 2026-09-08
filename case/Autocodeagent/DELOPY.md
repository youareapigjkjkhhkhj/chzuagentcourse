# AgentBuddy 部署打包指南

## 项目概述

AgentBuddy 是基于 Electron + Vue 3 + TypeScript 的本地编程代理工具。本文档指导如何将项目构建并打包为 Windows 可执行文件（.exe）。

## 项目结构

```
源码/
├── packages/
│   ├── shared/          # 共享类型定义
│   └── agent-core/      # Agent 核心运行时
└── apps/
    └── desktop/         # Electron 应用
```

## 前提条件

- Node.js 20+ 
- npm 9+
- Windows 操作系统（打包 .exe 需要 Windows 环境）

## 一、安装依赖

```bash
cd 源码
npm install
```

## 二、开发构建

### 类型检查

```bash
npm run typecheck
```

### 运行测试

```bash
npm run test
```

### 开发模式运行

```bash
npm run dev
```

### 生产构建

```bash
npm run build
```

构建产物输出到 `apps/desktop/dist/` 目录：

```
dist/
├── main/
│   ├── index.cjs       # Main 进程
│   └── preload.cjs     # Preload 脚本
└── renderer/
    ├── index.html      # 入口 HTML
    └── assets/         # 静态资源（JS/CSS）
```

## 三、打包为 Windows 可执行文件

项目使用 `electron-packager` 进行打包（更稳定，避免 electron-builder 的文件锁定问题）。

### 打包命令

```bash
cd 源码/apps/desktop

# 设置镜像源（加速下载）
set ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/

# 打包
npx electron-packager . AgentBuddy --platform=win32 --arch=x64 --overwrite --out=./release --ignore="(release|node_modules|\.git)" --asar
```

### 打包产物

```
release/
└── AgentBuddy-win32-x64/
    ├── AgentBuddy.exe          # 主程序（约 188MB）
    ├── resources/
    │   └── app.asar            # 应用代码包
    └── ... (其他 Electron 运行时文件)
```

### 使用方式

直接运行 `AgentBuddy.exe` 即可启动应用，无需安装。

## 四、打包流程图

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  安装依赖   │ ──▶ │  生产构建   │ ──▶ │  应用打包   │
│ npm install │     │ npm run build│     │ electron-   │
└─────────────┘     └─────────────┘     │ builder     │
                                        └──────┬──────┘
                                               │
                                               ▼
                                        ┌─────────────┐
                                        │ release/    │
                                        │ *.exe       │
                                        └─────────────┘
```

## 五、环境变量配置

打包时如需嵌入 API Key 等配置，可使用环境变量：

```bash
# 构建时注入配置
set API_KEY=your_api_key
set LLM_PROVIDER=openai
npm run build
```

或在项目根目录创建 `.env` 文件：

```env
API_KEY=your_api_key
LLM_PROVIDER=openai
DEFAULT_MODEL=gpt-4
```

> 注意：敏感信息不应提交到代码仓库。

## 六、常见问题

### 1. 构建失败：找不到模块

```bash
# 清理依赖重新安装
rm -rf node_modules
npm install
```

### 2. 打包后图标不显示

- 确保 `build/icon.ico` 存在且格式正确
- 图标尺寸建议：256x256 像素
- 可在线转换 PNG 到 ICO：https://convertico.com/

### 3. 打包后 IPC 通信异常

检查 `src/main/index.ts` 中的 `webPreferences.preload` 路径是否正确：

```ts
preload: join(__dirname, 'preload.cjs')
```

打包后 `__dirname` 指向 asar 包内的路径。

### 4. 安装包体积过大

可通过以下方式优化：

- 启用 asar 打包（electron-builder 默认开启）
- 排除开发依赖：`"files": ["dist/**/*", "!node_modules/**/test/**"]`
- 使用 `electron-builder` 的 `compression` 选项

### 5. 签名与安全

生产环境建议：

1. 购买代码签名证书
2. 配置 ` CSC_LINK` 和 `CSC_KEY_PASSWORD` 环境变量
3. 在 `package.json` 的 `build.win.signingHashAlgorithms` 配置签名算法

## 七、发布清单

- [ ] 版本号更新（package.json）
- [ ] 变更日志编写
- [ ] 图标文件准备
- [ ] 测试打包产物运行
- [ ] 安装测试（全新环境）
- [ ] 代码签名（可选）
- [ ] 上传发布

## 八、快速开始

### 方式 1：使用 bat 文件（推荐）

双击 `build.bat`，自动完成所有步骤。

### 方式 2：手动命令

```bash
cd 源码/apps/desktop

# 1. 安装依赖
npm install

# 2. 设置镜像源（可选，加速下载）
set ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/

# 3. 安装精确版本 electron
npm install electron@33.4.11 --save-dev --save-exact

# 4. 安装打包工具
npm install --save-dev electron-packager

# 5. 构建
npm run build

# 6. 打包
npx electron-packager . AgentBuddy --platform=win32 --arch=x64 --overwrite --out=./release --ignore="(release|node_modules|\.git)" --asar

# 7. 运行
release\AgentBuddy-win32-x64\AgentBuddy.exe
```

## 参考资料

- [electron-builder 官方文档](https://www.electron.build/)
- [electron-forge 官方文档](https://www.electronforge.io/)
- [Electron 官方打包指南](https://www.electronjs.org/docs/latest/tutorial/tutorial-packaging)
