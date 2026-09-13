<div align="center">
  <img src="chzu.png" alt="滁州学院 CHUZHOU UNIVERSITY" width="480">

  # CHZU 智能体开发训练营实战

  **滁州学院 · 智能体开发训练营教学资源库**

  *Agentic 时代 —— 从 AI 使用者到 AI 架构师*

  [![License](https://img.shields.io/badge/License-仅限学习研究非商用-green.svg)](#五版权与使用许可)
  [![Copyright](https://img.shields.io/badge/Copyright-©%20滁州学院-green.svg)](#五版权与使用许可)
</div>

---

## 一、仓库简介

本仓库为**滁州学院智能体开发训练营**的官方教学资源库，收录训练营全部课程资料、实战案例与配套文档，覆盖 Dify / LangChain / LangGraph / 多智能体框架（AgentScope、AutoGen、CrewAI、LlamaIndex）、大模型微调及企业级 Agent 工程实践等内容，供本校师生教学、学习、复现与二次开发使用。

## 二、目录结构

```
├── chzu.png                                  # 滁州学院校徽
├── Agentic时代_从AI使用者到AI架构师.pptx       # 训练营总述课件
├── 智能体训练营课程方案_v2.docx                # 训练营课程方案
├── 练习/                                      # 训练营配套练习
├── case/                                      # 实战案例（项目文档 + 源码 + 部署参考）
│   ├── Agentic供应链运营平台
│   ├── AI Agricultural Assistant              # AgriGPT 智慧农业助手
│   ├── AI Wardrobe                            # AI 衣柜（Java 微服务 + Spring AI）
│   ├── Autocodeagent                          # AgentBuddy 智能编码桌面端
│   ├── E-commerce-Smart-Agent                 # 灵犀客服（电商智能客服）
│   ├── JOB                                    # CareerAgent 多智能体求职与职业发展
│   ├── LLM-Wiki-Platform                      # LLM 知识管理平台
│   ├── multi-agent-classroom-system           # EduAgentX 多智能体课堂教学系统
│   ├── ragent                                 # 生产级 Java RAG 平台
│   ├── 企业级智能数据分析系统                   # ChatBI 智能问数
│   ├── 医疗智能问答系统                        # 医疗 RAG 问答 + 影像分析
│   ├── 智能笔记助手
│   └── 研究报告生成器
└── course/                                    # 课程资料
    ├── Dify 平台开发 / Dify平台综合项目
    ├── LangChain 教程 / LangGraph 教程 / Langgraph全版
    ├── 多框架拓展（AgentScope / AutoGen / CrewAI / LlamaIndex）
    ├── 模型训练与微调
    ├── 技术文档（Git / Linux / Docker / K8s / 中间件 / SpringBoot / Vue3 等）
    ├── 课程大纲
    └── PPT
```

> 每个含代码的实战案例均配套《可拓展创新方向.md》，提供可直接落地的扩展创新点（含方向总览表、模块级改动方案与 MVP 实施路线），适合用于课程创新、学科竞赛与毕业设计选题。

## 三、内容速览

| 模块 | 内容说明 |
| :--- | :--- |
| 平台搭建 | Dify 部署与插件开发（Text2SQL、database、文档提取等实验） |
| 框架基础 | LangChain v1.0、LangGraph 从基础到进阶（RAG、多智能体、多模态） |
| 框架拓展 | AgentScope / AutoGen / CrewAI / LlamaIndex 系列教程 |
| 模型微调 | 医疗大模型全流程实战（SFT / LoRA / QLoRA / DPO / PPO） |
| 实战案例 | 覆盖电商客服、医疗问答、供应链、求职助手、课堂教学等真实项目 |
| 技术文档 | Git、Docker、K8s、Redis、MQ、Nginx、SpringBoot3 + MyBatisPlus、Vue3 等 |

## 四、使用说明

1. 各案例目录内均含《项目文档》（设计方案、README），部分含《部署参考》，请按对应文档启动项目。
2. 建议先阅读 `Agentic时代_从AI使用者到AI架构师.pptx`，总览训练营知识脉络后再进入各模块学习。
3. 出于安全考虑，仓库内**不含**任何真实密钥与环境配置（`.env`、`api.txt` 等），各项目仅保留 `.env.example` 示例文件，运行前请自行补齐配置。
4. 参考环境要求：Docker（含 docker-compose）、Python 3.11+、Node.js 22+、Java 17+ 等，具体以各项目文档为准。

## 五、版权与使用许可

<div align="center">

**版权归属：滁州学院（© 2026 CHUZHOU UNIVERSITY，All Rights Reserved）**

</div>

### 5.1 授权范围（允许）

- 个人学习、课程教学、学术研究等**非商业用途**；
- 在非商业前提下下载、复制、修改本仓库内容用于学习实践；
- 引用、转载本仓库内容时，**须注明出处**，格式建议为：

  > 来源：滁州学院智能体开发训练营（https://gitee.com/woaitonghui_admin/chzuagentcourse）

### 5.2 禁止事项

- **任何形式的商业用途**，包括但不限于：出售本仓库内容、用于付费课程或商业培训、集成进商业产品或付费服务；
- 删除、遮挡或篡改本仓库的版权声明与出处标识；
- 未经滁州学院书面许可的营利性二次分发。

### 5.3 第三方资源说明

仓库内引用的开源框架、第三方行业报告 / 白皮书（PDF）等资料，其著作权归各自权利人所有，本仓库仅用于教学目的收录，如涉及授权问题请联系相应权利人。

### 5.4 授权咨询

如需商业授权或合作，请通过本仓库 Gitee Issues 或滁州学院相关部门联系。

## 六、免责声明

本仓库内容仅供教学与学习交流使用，不构成任何形式的技术保证或商业承诺。使用者应自行评估并承担使用风险，因使用本仓库内容产生的任何直接或间接损失，滁州学院不承担相应责任。

---

<div align="center">

**滁州学院 · 智能体开发训练营**

Copyright © 2026 CHUZHOU UNIVERSITY. All Rights Reserved.

</div>
