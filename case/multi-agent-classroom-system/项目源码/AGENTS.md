# EduAgentX 开发流程（项目源码/）

> 这份文件管**「一次改动怎么做」**：开工读什么、改完跑什么、什么时候提交、文档跟着谁改。
>
> 架构边界、硬约束、代码规模的判定标准在 **`../AGENTS.md`**（全项目规范，31 节）——本文件不重复它，只指路。
> 命令的完整清单在 `README.md`，本文件只说「什么时候**必须**跑哪条」。
>
> 适用目录：`项目源码/`。**代码注释与 Makefile 里写的 `AGENTS §x.y`，指的都是根目录那份 `../AGENTS.md`**
> （本文件只有 §0~§8，没有 `.y` 小节的编号）。下文里写「**根 §x**」的一律指 `../AGENTS.md`，裸 `§x` 指本文件。

---

## 0. 每次开工前（两分钟）

1. **确认现在在哪个阶段。** P0~P5 已交付（v1.1，2026-09-13），MVP = P0+P1+P2+P3；当前工作基本落在 P6 六个子项与已交付阶段的打磨上。里程碑状态见 `../项目文档/00-项目总览与里程碑.md`。
2. **只读根规范里跟这次改动有关的两节**：`../AGENTS.md` §4（硬约束 —— 密钥、`db_write`、服务端状态源、信封）与 §6/§10（代码规模、巨型文件）。不用每次从头读 693 行。
3. **侦察代码。** 先看改动落点的现有实现（`grep` + 读文件），再问「有没有现成能力可复用」（根 §11）。P0~P5 已经沉淀出 `providers/` 抽象、`db_write`、事件总线、`classroom/roster`、板书与课堂记录器等基础设施 —— **大多数需求不需要新写一层**。

> `../项目文档/P{n}-*.md` 既是任务书也是契约。要动的那块功能，先看它在那份文档里的验收条件是怎么写的 —— 那决定了这次改动「做到什么样才算完」。

---

## 1. 环境与启动

首次：

```bash
make setup        # 装前后端依赖 → 生成 backend/.env（已存在则不动）→ 建库 → 灌种子
```

之后：

```bash
make dev          # 后端 :5000 + 前端 :5173，Ctrl+C 一起停
```

| 你要做的事 | 命令 |
|---|---|
| 起前后端 | `make dev`（= `bash scripts/dev.sh`；PowerShell 用 `scripts/dev.ps1`） |
| 不给浏览器抢焦点（脚本里调） | `NO_OPEN=1 bash scripts/dev.sh` |
| 上次没关干净、端口被占 | `bash scripts/dev.sh --force`（先收掉占端口的老进程） |
| 换端口 | `BACKEND_PORT=5001 FRONTEND_PORT=5174 bash scripts/dev.sh` |
| 建库 / 迁移 | `make migrate`（= `flask db upgrade`）；回滚用 `flask db downgrade` |
| 灌种子 | `make seed` —— **幂等**，重复跑不产生重复数据，也不覆盖你改过的行 |
| 备份数据 | `make backup`（走在线备份 API 取一致快照，别用 `cp`，见 §7） |

三个必须知道的启动事实：

- **后端不自动重载。** `dev.sh` 用 `flask run` 且没开 `--reload`：**改完 `.py` 或 `.env` 要重启 dev.sh**，否则测的是旧代码。前端 Vite 有 HMR，改 `.vue` / `.ts` / `.css` 即时生效。
- **Vite 只绑 `[::1]`（IPv6）。** 访问与探测都用 `localhost:5173`；写 `127.0.0.1` 会连不上。Vite 把 `/api` 与 `/ws` 反代到后端，前端代码里一律用相对路径 `/api/...`。
- **探活**：`curl http://localhost:5000/api/health` 应返回 `{"code":0,...,"status":"ok"}`；`curl http://localhost:5173` 应返回 200。起进程与「能打开」是两件事，flask 要连库、vite 要预打包，各要几秒。

---

## 2. 一次改动的完整流程

1. **侦察**：定位要改的文件；先问「有没有更小的改法」（根 §12 最小修改原则）。
2. **划改动面**：写下这次要动哪几个文件。一次改动只做一件事 —— 如果侦察时冒出「顺手还能改 X」，那是下一次提交的事（根 §25 Diff 原则）。
3. **改**：优先在现有文件/函数里改，不新建文件；确实要建，先过根 §7（什么时候必须拆分）与根 §9（禁止无意义创建文件）。
4. **跑门禁**：按 §3 的对照表跑对应那几条。
5. **自检**：过一遍根 §27 的强制自检清单（架构 / 代码 / 正确性 / 安全 / 成本 / 测试 / Diff / 文档）。
6. **同步文档**：按 §6 的表改对应文档 —— 代码与文档不一致**视为缺陷**（根 §26）。
7. **提交**：按 §5 写提交信息。

> **测试写多少**：本项目不追求穷尽式单测。可点出来的功能优先，测试覆盖「端点契约 + 会被回归踩坏的核心路径」即可（根 §23）。新的验收条件优先表达为 `scripts/accept_p{n}.py` 里的一条断言，而不是散落的单测。

---

## 3. 门禁：什么时候跑哪条

| 你改了 | 最少要跑 |
|---|---|
| 任意代码 | `make lint` |
| 后端逻辑 / 服务 / 模型 | `python scripts/test.py --back`（= `pytest`） |
| 前端组件 / store / 工具 | `python scripts/test.py --front`（= `vitest run`） |
| 接口 / WS 事件 / 设置项 | `pytest tests/contract`，并逐条对照该阶段文档的验收表 |
| 某阶段的功能本身 | `python scripts/accept_p{n}.py`（n = 该功能所属阶段） |
| 准备提交 | `make ci` |

- **`make lint`** = `ruff` + `mypy app` + 前端 `vue-tsc` + `eslint`，一条命令覆盖四样，别漏跑单独某一半。
- **`make test`** = 后端 `pytest` + 前端 `vitest run`。
- **`make ci`** = `lint` + `test` + `accept-p1 ~ accept-p5`。**全程离线、用替身与临时库、不碰你本机的服务与数据**，所以任何时刻都能跑，是提交前的标准动作。
- **`accept_p0` 不在 `ci` 里**：P0 的验收要对着跑起来的服务探活（`/api/health`、设置页 Provider 测试连接），跑之前确保 `make dev` 起着 —— 它也会自己拉起服务（已在跑的就复用，跑完关掉）。
- **红了先分清是谁的**：`git stash` 后重跑一次，能区分「我改坏的」与「本来就红的」。

---

## 4. 验收脚本怎么用

六套 `scripts/accept_p0.py ~ accept_p5.py`，一条命令跑完对应阶段的 A 类验收（多数还含 B/C/D/E/F/G 里能自动化的部分）：

```bash
python scripts/accept_p0.py            # 对着已启动的本机前后端（没起就自己拉，跑完关）
python scripts/accept_p0.py --offline  # 不发起任何真实模型调用（A5a/A5b 记跳过）
python scripts/accept_p1.py            # 离线桩：另起后端连临时库，不联网、没 Key 照样跑
python scripts/accept_p1.py --keep     # 保留临时库/日志/进程，用来查看失败现场
```

规则（踩过坑之后定的，别绕开）：

- **p1~p5 全程离线，且不碰你的 :5000。** 脚本自己设 `EDUAGENTX_DISABLE_DOTENV=1` 与 `FLASK_SKIP_DOTENV=1`（**两个都要**：Flask CLI 会自己读 `.env`，只设一个会漏），用替身 Provider 与 `%TEMP%/eduagentx-p{n}-*` 下的临时库，后端另起在 508x~509x（p1 `:5098`、p2 `:5094~5096`、p3 `:5081~5083`、p4 `:5084/5085`、p5 `:5086/5087`）—— 断网、没 Key 照样跑得完，不写你的 `app.db`，也不占用正在 `make dev` 的端口。
- **临时目录默认跑完就删**，`--keep` 才留。红了才留、绿了自己删 —— 这台机器堆过 38166 个 / 8.95GB（2026-09-13 清过一次）。
- **「跳过」≠ 通过。** 需要真模型才能量的项（D 类性能、E 类人工评分）会明确记「跳过」并说明原因。读到跳过要问清楚为什么，不要当成绿。
- **不许为了让验收过而放宽断言。** 验收条件写在阶段文档里，脚本是它的翻译；改脚本等于改契约 —— 要改，先改 `../项目文档/P{n}-*.md` 的验收表并说明理由。
- **不许把真模型塞进验收。** 需要真实 LLM / TTS / ASR 的部分走用户手点或冒烟测试。

---

## 5. 提交与 Diff 规范

提交信息：`类型: 中文一句话说清改了什么、为什么`。类型沿用仓库现有习惯：

| 前缀 | 用在 |
|---|---|
| `add:` | 新功能、新文件 |
| `update:` | 已有功能的调整 |
| `fix:` | 修 Bug |
| `docs:` | 只动文档 |
| `chore:` | 依赖、脚本、构建、清理 |

例：`fix: 板书多行文字按 tspan 分行，超长按行截断`

- **一次提交一件事。** 禁止「功能新增 + 大规模重构 + 格式化」混在一条（根 §25）。
- **提交前看 `git status`。** 这个仓库可能有多会话并行的改动（例如样式分离）。只 `git add` 你这次动过的文件，**别 `git add -A`**。
- **不提交**：`.env`、`backend/data/*.db*`（含 `-wal` / `-shm`）、`data/exports/`、`%TEMP%` 下的任何东西、任何真实密钥。提交前 `git diff --cached` 扫一眼有没有密钥字面量。

---

## 6. 文档同步（改了就得跟着改）

`../AGENTS.md` §26：代码与文档不一致视为缺陷。

| 改了什么 | 同步改 |
|---|---|
| 接口 / WS 事件 / 事件载荷 | `../项目文档/P{n}-*.md` 里的接口表或事件表 |
| 数据表 / 字段 / 索引 | 该阶段文档的数据模型章节 |
| 验收条件 | 该阶段文档的验收表 |
| 启动方式 / 环境变量 / 常用命令 | `README.md`（含「常见问题」那节） |
| 阶段完成 | `../项目文档/00-项目总览与里程碑.md` 的里程碑状态 |
| 开发流程本身 | 本文件与 `../AGENTS.md` |

前端 `src/types/` 与后端 Schema 是**同一份契约的两半**，改一边必须跟着改另一边（例如给 `presence` 事件加字段）。

---

## 7. 常见坑（本机都踩过）

- **端口被占**：上次 `dev.sh` 没关干净。`bash scripts/dev.sh --force`，或换 `BACKEND_PORT` / `FRONTEND_PORT`。
- **Vite 连不上**：它只绑 `[::1]`，用 `localhost` 而不是 `127.0.0.1`。
- **改了 `.py` 没生效**：后端没有 reloader，重启 `dev.sh`。
- **离线脚本仍读了 `.env`**：`EDUAGENTX_DISABLE_DOTENV=1` 与 `FLASK_SKIP_DOTENV=1` 缺一不可。
- **上传音频被拒**（`只接受 pcm / wav 音频，收到 'json'`）：在 axios 实例上写死了 `Content-Type: application/json`，`FormData` 被 JSON 序列化了。**别在实例上设 Content-Type**，让浏览器自己带 boundary。
- **Windows 控制台中文乱码**：先 `chcp 65001`（GBK 控制台打印中文会抛 `UnicodeEncodeError`）；写文件显式 `encoding='utf-8'`。
- **别 `cp` 数据库**：SQLite 开了 WAL，`cp app.db` 会丢 `-wal` 里的数据。用 `make backup`。
- **TDesign 样式顺序**：`tdesign-vue-next/es/style/index.css` 必须在 `tokens.css` **之前**引入，否则设计令牌被覆盖。
- **`%TEMP%` 堆积**：验收脚本的临时目录默认自删；用了 `--keep` 的记得自己清。
- **新增依赖**：Python 加进 `backend/requirements.txt`，前端加进 `frontend/package.json`，并说明用途（根 §20 依赖控制）。

---

## 8. 十条不可协商的硬约束（摘要，详见 `../AGENTS.md` §4）

1. **密钥只在服务端**：`.env` 或加密后的 `providers.api_key_enc`；代码里不出现任何密钥 / 端点 / 音色 ID 字面量；浏览器侧不得出现厂商凭据。
2. **所有写操作走 `common/dbw.py` 的 `db_write(fn)`**，禁止裸写会话（SQLite 单写者）；高频写批量提交；迁移必须可 downgrade。
3. **服务端是唯一状态源**：课堂状态、生成进度、页号、beat 位置只能由 SSE / WS 事件驱动，前端不许本地推进或模拟进度。
4. **LLM 输出必须过 JSON Schema 校验**：失败重试一次（带错误回喂），仍失败标该页 `failed`，**不阻塞整课**。
5. **讲稿必须 beat 化**（`narration: [{beatId, text, estSec}]`）；材料模式输出必须带 `sources`，且 `quote` 能在对应 chunk 原文中匹配。
6. **每一笔外部调用（LLM / TTS / ASR / 实时语音）都必须写 `model_calls`**（provider / model / tokens / latency / ok / error_code）—— P5 成本看板的唯一数据源，漏记即不可信。
7. **所有接口返回统一信封** `{code, message, data, requestId}`；上游失败映射为明确业务码 + 可读原因 + 降级策略，**禁止裸抛 500**。
8. **语音链路任何失败都必须带 `fallback` 字段**，前端不得自行猜测降级路径。
9. **业务代码禁止直接 import 厂商 SDK**，一律走 `providers/` registry。
10. **禁止任何静默修改课程的行为** —— Skill 调用必须在前端可见。

违反即返工。
