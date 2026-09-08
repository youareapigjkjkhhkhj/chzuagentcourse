# AI糖尿病辅助诊断系统

## 项目简介

AI糖尿病辅助诊断系统是一个基于深度学习的医学影像分析平台，专门用于糖尿病视网膜病变的早期筛查和诊断。系统通过先进的AI模型分析眼底图像，为医生提供辅助诊断建议，提高诊断效率和准确性。

## 主要功能

### 1. 用户管理
- **多角色支持**：支持管理员和医生两种用户角色
- **安全认证**：基于JWT的身份认证和授权机制
- **权限控制**：根据用户角色提供不同的功能访问权限

### 2. 图像分析
- **图像上传**：支持多种格式的眼底图像上传
- **AI模型分析**：集成ResNet、DenseNet和EfficientNet三种深度学习模型
- **实时分析**：快速处理图像并返回诊断结果
- **结果可视化**：直观展示病变区域和诊断置信度

### 3. 诊断报告
- **报告生成**：自动生成详细的诊断报告
- **报告管理**：查看、编辑和导出历史诊断报告
- **数据统计**：提供诊断数据的可视化统计和分析

### 4. AI医学助手
- **智能问答**：基于医学知识库的智能问答系统
- **诊断建议**：根据分析结果提供个性化的诊断建议
- **随访计划**：根据病情严重程度制定随访计划
- **术语解释**：提供医学术语的详细解释

### 5. 医学知识库
- **知识管理**：支持医学文章的创建、编辑和管理
- **智能搜索**：基于向量数据库的语义搜索功能
- **分类浏览**：按疾病类型、治疗方法等分类浏览知识
- **知识图谱**：构建医学知识之间的关联关系

### 6. 系统管理
- **模型管理**：管理和更新AI诊断模型
- **用户管理**：管理系统用户和权限
- **系统设置**：配置系统参数和阈值
- **操作日志**：记录和审计系统操作

## 技术架构

### 前端技术栈
- **React 18**：现代化的用户界面框架
- **TypeScript**：提供类型安全的JavaScript超集
- **Vite**：快速的构建工具和开发服务器
- **Tailwind CSS**：实用优先的CSS框架
- **Framer Motion**：流畅的动画库
- **React Router**：单页应用路由管理
- **Recharts**：数据可视化图表库

### 状态管理
- **React Context**：轻量级状态管理解决方案
- **自定义Hooks**：封装复杂逻辑，提高代码复用性

### UI/UX设计
- **响应式设计**：适配不同屏幕尺寸的设备
- **暗黑模式**：支持明暗主题切换
- **无障碍设计**：遵循WCAG无障碍设计指南
- **微交互**：精心设计的过渡动画和反馈效果

## 项目结构

```
src/
├── components/        # 可复用组件
│   ├── Navbar.tsx    # 顶部导航栏
│   └── Sidebar.tsx   # 侧边栏导航
├── contexts/         # React Context
│   └── authContext.ts # 认证上下文
├── hooks/            # 自定义Hooks
│   └── useTheme.ts   # 主题切换Hook
├── lib/              # 工具库
│   └── utils.ts      # 通用工具函数
├── mocks/            # 模拟数据
│   └── data.ts       # 模拟数据生成
├── pages/            # 页面组件
│   ├── Dashboard.tsx # 仪表盘
│   ├── ImageAnalysis.tsx # 图像分析
│   ├── AIAssistant.tsx # AI助手
│   └── KnowledgeBase.tsx # 知识库
├── types/            # TypeScript类型定义
│   └── index.ts      # 通用类型
├── App.tsx           # 根组件
├── main.tsx          # 应用入口
└── index.css         # 全局样式
```

## 本地开发

### 环境准备

- 安装 [Node.js](https://nodejs.org/en) (推荐版本 18.x 或更高)
- 安装 [pnpm](https://pnpm.io/installation) (推荐的包管理器)

### 操作步骤

1. 克隆项目
```sh
git clone [项目地址]
cd blindness/frotend
```

2. 安装依赖
```sh
pnpm install
```

3. 启动开发服务器
```sh
pnpm run dev
```

4. 在浏览器访问 http://localhost:3001

### 可用脚本

- `pnpm run dev` - 启动开发服务器
- `pnpm run build` - 构建生产版本
- `pnpm run preview` - 预览生产构建
- `pnpm run lint` - 运行代码检查

## 部署说明

### 构建生产版本

```sh
pnpm run build
```

构建产物将生成在 `dist` 目录中，可以部署到任何静态文件服务器。

### 环境变量配置

创建 `.env` 文件并配置以下变量：

```
VITE_API_URL=http://your-api-server.com
VITE_APP_TITLE=AI糖尿病辅助诊断系统
```

## 浏览器支持

- Chrome (推荐)
- Firefox
- Safari
- Edge

## 贡献指南

1. Fork 项目
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request

## 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。


**注意**：本系统仅用于辅助诊断，不能替代专业医生的诊断结果。所有诊断结果应由专业医生审核确认。
