# P4 · Skills 体系

> 周期参考：3–5 天 ｜ 前置：P1（可与 P3 / P5 并行）｜ 产出：两级技能资产 + `/` 命令 + 计划可见性

## 阶段目标

让用户的经验以 Markdown 形式沉淀并复用：全局 / 项目两级技能、目录注入系统提示、斜杠命令触发；同时交付 `todo` 工具驱动的执行计划。

## 范围

**包含**：Skills 扫描与解析、目录注入、`/` 命令、管理页、todo 工具
**不包含**：可执行脚本式 Skill（明确不做，保持纯文本指令）

## 工作分解

| # | 任务 | 说明 |
| --- | --- | --- |
| 1 | 两级扫描 | `~/.AgentBuddy/skills/`（全局）+ `<workspace>/.AgentBuddy/skills/`（项目）；同名时项目覆盖全局 |
| 2 | frontmatter 解析 | `SKILL.md` 的 `name / description` 经 zod 校验；解析失败的技能跳过并提示，不阻塞启动 |
| 3 | 目录注入 | 已启用技能的 name + description 摘要进系统提示（第④层）；正文不进上下文，模型需要时用 `read` 自取 |
| 4 | `/` 命令 | 输入框 `/name` → 技能正文追加为高优先级指令再进 Loop；输入 `/` 弹出技能菜单 |
| 5 | 启用开关 | 技能级启用 / 禁用，即时反映到下一次上下文组装 |
| 6 | Skills 管理页 | 卡片式：名称、描述、来源徽标（全局 / 项目）、状态开关、触发方式、查看 / 编辑 `SKILL.md` |
| 7 | `todo` 工具 | `todo_write` 维护任务清单（内存态，随会话落盘）；`onPlanStep` 事件驱动中栏 Plan Checklist |
| 8 | 内置示例技能 | 随包附带 `/review`、`/test` 两个示例 `SKILL.md` |

## 验收条件（已验收 ✓：164 passed | 1 skipped，typecheck 零错误，build 过，/review 真模型冒烟过）

- [x] 《设计方案》成功标准 2：添加项目级自定义技能，覆盖全局同名，`/name` 可触发（skills.test 同名覆盖 + ChatView skillName 链路）
- [x] 禁用某技能后，新回合的系统提示中不再出现其摘要（settings.disabledSkills → catalog 过滤）
- [x] 项目级与全局同名技能并存时，生效的是项目级（管理页来源徽标正确）
- [x] `/review` 触发后，模型回复明显遵循技能正文的审查清单（smoke.real /review 断言总体结论/四节/优先修复）
- [x] 长任务中模型主动维护 todo 清单，中栏 Checklist 实时更新勾选状态（todo_write → plan 事件 + session.todos 落盘回放）
- [x] 畸形 `SKILL.md`（缺 frontmatter / 非法字段）不导致启动失败，管理页显示告警（扫描跳过 + warning 徽标/告警条）
- [x] 单测：frontmatter 解析、同名覆盖优先级、`/` 命令注入位置（skills.test + todoTool.test + context.test）

## 交付检查点（已完成 ✓）

真模型冒烟 1 次：`/review` 触发代码审查，检查清单输出符合技能正文约束（2026-08-29，gpt-5-mini，2 tests passed）。

## 实现要点归档（P4）

| 层 | 关键点 |
| --- | --- |
| agent-core/skills.ts | 两级扫描（全局 `~/.AgentBuddy/skills` + 项目 `<ws>/.AgentBuddy/skills`）、frontmatter zod、同名项目覆盖、SkillHub（seed/list/get/save/setEnabled/catalog）、save 路径 jail |
| 上下文 | ④层仅 name+description 摘要进系统提示；`/name` 正文作当轮高优先级指令（目录之后追加，不落历史） |
| todo_write | 风险 READ 全模式免询问；全量覆盖入参校验；ctx.onTodos 回调 → Loop 统一发 plan 事件 + SessionStore.updateTodos 防抖落盘 |
| IPC（§23） | skills:list / get / save / set-enabled，AskPayload 增 skillName；disabledSkills 持久化 settings |
| 渲染端 | SkillsView 卡片管理页（徽标/开关/告警/全文编辑弹层）；ComposerCard `/` 菜单；ChatView `/name` 触发校验；Checklist 勾选态 + 回放恢复 |
| 内置示例 | /review /test 首次启动播种到全局目录，已存在不覆盖 |
| 新增/删除（原型对齐） | SkillHub.create（表单→frontmatter 组装、slug 校验、同范围查重、项目级需工作区）/ remove（路径仅两级根内 + 清理禁用残留）；IPC skills:create / skills:remove；SkillsView「新增技能」表单弹窗 + 卡片删除按钮（二次确认）；168 passed \| 2 skipped |
| ZIP 导入（原型对齐） | 零依赖解包（zip.ts：EOCD→中央目录，stored/deflate，CP437 文件名 + 反斜杠归一，体积护栏防炸弹）；importZip 整目录解包（references/scripts 附属保持结构落盘、二进制保真）、顶层 SKILL.md 识别（嵌套视为参考文件）、成员路径 jail 防 zip-slip、全量校验原子落盘、包内/同范围查重；IPC skills:import（base64，zod 限 14MB）；真实 Compress-Archive 包字节级验证；181 passed \| 2 skipped |
