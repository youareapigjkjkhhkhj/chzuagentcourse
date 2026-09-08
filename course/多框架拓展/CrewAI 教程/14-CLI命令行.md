# 14 - CLI 命令行

本篇目标：掌握 CrewAI 的 **CLI 命令行工具**——创建、运行、训练、测试、重放、管理 Crew 和 Flow。

## 14.1 基本结构

```bash
crewai <command> [options]
```

## 14.2 命令总览

| 命令 | 用途 |
|------|------|
| `crewai create` | 创建新的 crew / flow / tool / skill / template |
| `crewai run` | 运行 crew 或 flow |
| `crewai train` | 训练 crew |
| `crewai test` | 测试 crew 性能 |
| `crewai replay` | 从特定任务重放 |
| `crewai log-tasks-outputs` | 查看任务输出日志 |
| `crewai version` | 查看版本 |
| `crewai tool` | 管理工具 |
| `crewai skill` | 管理技能 |
| `crewai template` | 管理模板 |

## 14.3 `crewai create` — 创建项目

```bash
# 创建 crew（JSON-first，推荐）
crewai create crew my_crew

# 创建 crew（经典 YAML）
crewai create crew my_crew --classic

# 创建 flow
crewai create flow my_flow

# 创建自定义工具
crewai create tool my_tool

# 创建技能
crewai create skill my_skill

# 从远程模板创建
crewai create template my_template
```

### 创建 Skill 的细节

在 crew 项目内（有 `pyproject.toml` 时）创建于 `./skills/`：

```bash
crewai create skill code-review
# → ./skills/code-review/SKILL.md
```

在项目外创建（`--no-project` 标志在当前目录创建）：

```bash
crewai create skill code-review --no-project
# → ./code-review/SKILL.md
```

### 创建 Tool 的细节

```bash
crewai create tool my_custom_tool
# 脚手架一个自定义工具仓库
```

### 模板

```bash
# 添加远程项目模板到当前目录
crewai create template my_template

# 指定输出目录
crewai create template my_template --output-dir ./custom_dir
```

## 14.4 `crewai run` — 运行

```bash
# 运行项目（自动检测 crew.jsonc / crew.json）
crewai run
```

`crewai run` 自动：
1. 检测 `crew.jsonc` 或 `crew.json`
2. 加载引用的 Agent 文件（`agents/*.jsonc`）
3. 提示缺失的占位值
4. 启动 Crew

## 14.5 `crewai train` — 训练

```bash
# 训练 5 次迭代（默认）
crewai train

# 指定迭代次数
crewai train -n 10

# 指定训练数据文件
crewai train -n 10 -f my_training_data.pkl
```

参数：

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `-n, --n-iterations` | 训练迭代次数 | 5 |
| `-f, --filename` | 训练数据文件路径 | `trained_agents_data.pkl` |

## 14.6 `crewai test` — 测试

```bash
# 测试 2 次迭代（默认）
crewai test

# 指定迭代次数和模型
crewai test -n 5 -m gpt-4o

# 短格式
crewai test -n 5 -m gpt-4o-mini
```

参数：

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `-n, --n-iterations` | 迭代次数 | 2 |
| `-m, --model` | 评估模型 | `gpt-4o-mini` |

> ⚠️ 当前测试仅支持 OpenAI 提供商。

`crewai test` 结束后输出**性能指标表格**，展示每个 Task 和整体 Crew 的评分。

## 14.7 `crewai replay` — 重放

```bash
# 从特定任务重放 crew 执行
crewai replay -t <task_id>
```

参数：

| 选项 | 说明 |
|------|------|
| `-t, --task-id` | 从哪个任务 ID 开始重放 |

## 14.8 `crewai log-tasks-outputs` — 日志

```bash
# 查看任务输出日志
crewai log-tasks-outputs
```

## 14.9 `crewai version` — 版本

```bash
# 查看版本
crewai version

# 同时查看 tools 版本
crewai version --tools
```

## 14.10 Resource Group 命令

CrewAI 将资源操作分组：

```bash
# 工具管理
crewai tool install
crewai tool uninstall
crewai tool list

# 技能管理
crewai skill publish
crewai skill install
crewai skill list

# 模板管理
crewai template list
crewai template add
```

## 14.11 已弃用的别名

以下旧命令仍可用，但会有黄色弃用警告：

```bash
# 旧写法（弃用）
crewai create crew my_crew

# 推荐新写法
crewai create crew my_crew
```

旧的 snake_case 标志已隐藏但兼容：

```bash
# flag 别名（旧）
--n_iterations
# 推荐 kebab-case
--n-iterations
```

## 关键 CLI 速查

| 你需要 | 命令 |
|--------|------|
| 创建 crew | `crewai create crew name` |
| 创建 flow | `crewai create flow name` |
| 创建 skill | `crewai create skill name` |
| 运行项目 | `crewai run` |
| 训练 | `crewai train -n 5` |
| 测试 | `crewai test -n 3 -m gpt-4o-mini` |
| 重放 | `crewai replay -t <task_id>` |
| 版本 | `crewai version` |

## 下一步

→ [15-测试与训练.md](15-测试与训练.md)：深入了解 Crew 的测试指标与训练机制。
