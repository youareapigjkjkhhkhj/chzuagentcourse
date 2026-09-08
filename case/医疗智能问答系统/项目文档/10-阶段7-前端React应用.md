# 10 - 阶段7：前端 React 应用

## 目标

基于 React + TypeScript + Tailwind CSS 构建前端 SPA，对接后端 API。

## 1. 技术栈

| 依赖 | 版本 | 用途 |
|------|------|------|
| react | 18.3 | UI 框架 |
| react-router-dom | 7.3 | 客户端路由 |
| vite | 6.2 | 构建工具 |
| tailwindcss | 3.4 | 原子化 CSS |
| typescript | 5.7 | 类型安全 |
| recharts | 2.15 | 图表库 |
| zod | 3.24 | 数据验证 |
| sonner | 2.0 | Toast 通知 |

## 2. 项目结构

```
frotend/src/
├── main.tsx              # 入口：BrowserRouter + Toaster
├── App.tsx               # 路由配置
├── index.css             # 全局样式（Tailwind）
├── pages/                # 页面组件
│   ├── Home.tsx          # 首页
│   ├── Login.tsx         # 登录页
│   ├── Register.tsx      # 注册页
│   ├── Dashboard.tsx     # 仪表盘
│   ├── AIAssistant.tsx   # AI 问答
│   ├── ImageAnalysis.tsx # 图像分析
│   ├── ReportList.tsx    # 报告列表
│   ├── ReportDetail.tsx  # 报告详情
│   ├── KnowledgeBaseList.tsx     # 知识库列表
│   ├── DocumentManagement.tsx    # 文档管理
│   ├── KnowledgeBaseSettings.tsx # 知识库设置
│   ├── ModelManager.tsx          # 模型管理
│   ├── SystemSettings.tsx        # 系统设置
│   ├── UserManagement.tsx        # 用户管理
│   ├── Profile.tsx               # 个人中心
│   └── ChatHistory.tsx           # 聊天历史
├── components/           # 通用组件
├── contexts/             # React Context
│   ├── AuthContext.tsx   # 认证状态
│   ├── ModelContext.tsx  # 模型配置
│   └── KBContext.tsx     # 知识库状态
├── services/             # API 调用层
├── hooks/                # 自定义 Hooks
├── types/                # TypeScript 类型
└── lib/                  # 工具函数
```

## 3. 路由配置

`App.tsx` 定义所有路由：

| 路径 | 页面 | 权限 |
|------|------|------|
| `/` | Home | 公开 |
| `/login` | Login | 公开 |
| `/register` | Register | 公开 |
| `/dashboard` | Dashboard | 登录 |
| `/ai-assistant` | AIAssistant | 登录 |
| `/analysis` | ImageAnalysis | 登录 |
| `/reports` | ReportList | 登录 |
| `/reports/:id` | ReportDetail | 登录 |
| `/knowledge` | KnowledgeBaseList | 登录 |
| `/knowledge/:kbId` | DocumentManagement | 登录 |
| `/knowledge-settings` | KnowledgeBaseSettings | admin |
| `/models` | ModelManager | admin |
| `/settings` | SystemSettings | admin |
| `/users` | UserManagement | admin |
| `/profile` | Profile | 登录 |
| `/chat-history` | ChatHistory | 登录 |

## 4. 路由守卫

```tsx
// PrivateRoute.tsx
function PrivateRoute({ children, requiredRole }) {
    const { user, token } = useAuth();

    if (!token) return <Navigate to="/login" />;
    if (requiredRole && user?.role !== requiredRole) return <Navigate to="/" />;

    return children;
}
```

## 5. SSE 流式解析

`AIAssistant` 页面中解析 SSE 流：

```typescript
const response = await fetch('/api/chat/send-stream', {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, model_id, knowledge_base_id })
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const text = decoder.decode(value);
    // 解析 SSE: "data: {...}"
    const lines = text.split('\n');
    for (const line of lines) {
        if (line.startsWith('data: ')) {
            const data = JSON.parse(line.slice(6));
            if (data.type === 'token') {
                setResponse(prev => prev + data.content);
            }
        }
    }
}
```

## 6. Context 状态管理

| Context | 职责 |
|---------|------|
| `AuthContext` | Token、用户信息、登录/登出 |
| `ModelContext` | 可用模型列表、当前选中模型 |
| `KBContext` | 知识库列表、当前选中知识库 |

## 7. 开发与构建

```bash
# 开发
pnpm dev          # 启动 Vite dev server (port 3000)

# 构建
pnpm build        # 输出到 dist/static/

# 注意：前端开发服务器会代理 /api 到后端 localhost:5000
```

## 关键文件

| 文件 | 说明 |
|------|------|
| `src/App.tsx` | 路由配置 |
| `src/main.tsx` | 应用入口 |
| `src/contexts/` | 状态管理 Context |
| `src/services/` | API 调用封装 |
| `package.json` | 依赖配置 |
| `vite.config.ts` | Vite 配置 |
