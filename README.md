# CHZU 智能体开发训练营实战

> 从 AI 使用者到 AI 架构师 —— 智能体开发训练营的实战资料仓库

本仓库收录智能体开发训练营的全部课程资料与实战案例，涵盖 Dify / LangChain / LangGraph / 多智能体框架（AgentScope、AutoGen、CrewAI、LlamaIndex）、模型微调以及企业级 Agent 工程实践等内容，供学员学习、复现与二次开发。

## 目录结构

```
├── Agentic时代_从AI使用者到AI架构师.pptx   # 训练营总述课件
├── 智能体训练营课程方案_v2.docx              # 训练营课程方案
├── case/         # 实战案例（学生项目：项目文档 + 源码 + 部署参考）
│   ├── Agentic供应链运营平台
│   ├── AI Agricultural Assistant
│   ├── AI Wardrobe                # AI 衣柜（多模块 Java 微服务）
│   ├── Autocodeagent              # 智能编码桌面端项目
│   ├── E-commerce-Smart-Agent     # 灵犀客服
│   ├── LLM-Wiki-Platform          # LLM 知识库平台
│   ├── multi-agent-classroom-system   # EduAgentX 多智能体课堂
│   ├── ragent
│   ├── 企业级智能数据分析系统
│   ├── 医疗智能问答系统
│   ├── 智能笔记助手
│   ├── 研究报告生成器
│   └── 模型微调实战等更多……
└── course/       # 课程资料（分框架教程、配套 PPT/实验、课程大纲、技术文档）
    ├── Dify 平台开发 / Dify平台综合项目
    ├── LangChain 教程 / LangGraph 教程 / Langgraph全版
    ├── 多框架拓展（AgentScope / AutoGen / CrewAI / LlamaIndex）
    ├── 模型训练与微调
    ├── 技术文档（Git / Linux / Docker / K8s / 中间件 / SpringBoot / Vue3…）
    ├── 课程大纲
    └── PPT
```

## 内容速览

| 模块 | 说明 |
| --- | --- |
| 平台搭建 | Dify 部署与插件开发（Text2SQL、database、文档提取等实验） |
| 框架基础 | LangChain v1.0、LangGraph 从基础到进阶（RAG、多智能体、多模态） |
| 框架拓展 | AgentScope / AutoGen / CrewAI / LlamaIndex 十六讲式教程 |
| 模型微调 | 医疗大模型全流程实战（SFT / LoRA / QLoRA / DPO / PPO） |
| 实战案例 | 覆盖电商客服、医疗问答、供应链、课堂多智能体等真实项目 |
| 技术文档 | Git、Docker、K8s、Redis、MQ、Nginx、SpringBoot3 + MyBatisPlus、Vue3 等 |

## 使用说明

- 各案例目录内均含 `项目文档`（设计方案、README），部分含 `部署参考`，请按对应文档启动。
- 训练营以「代码即 Agent 底座」理念，建议结合 `Agentic时代_从AI使用者到AI架构师.pptx` 总览全营知识脉络。

> ⚠️ 本仓库为教学用途。出于安全考虑，**真实密钥/环境配置（.env、api.txt 等）不入库**，各项目仅保留 `.env.example` 等示例配置，运行前请自行补齐配置。

## 环境要求（参考）

Docker（含 docker-compose）、Python 3.11+、Node.js 22+、Java 17+ 等 —— 具体以各项目文档为准。
