# EduAgentX · 多 Agent 互动课堂

输入一个主题（可附课件资料）→ 生成课件、讲稿与随堂测验 → AI 教师照着讲、AI 同学在讨论区发言、学生举手提问 → 导出 PPTX / HTML / PDF。

技术栈固定为 **Flask + Vue3 + SQLite**：文本模型走 OpenAI 兼容协议（DeepSeek / OpenAI / Qwen / Kimi / 自建均可），语音走火山引擎大模型语音。
浏览器只跟自己的 Flask 说话，任何厂商凭据都不出服务端。

> 当前进度：**P0 ~ P5 已交付**。首页输入主题 → 工作台六步任务卡实时跑完 → 12 页课程
> （大纲 / 讲稿 / 测验）落库，刷新还在 → 课堂页 AI 老师真讲课、AI 同学在讨论区发言、
> 学生举手提问（语音走火山引擎）→ 课件资料可上传检索 → 导出 PPTX / HTML / PDF，
> 带成本看板与预算、断点续跑、访问码、备份恢复。
> 计划与验收口径见 [`../项目文档/`](../项目文档)，工程规则见 [`../AGENTS.md`](../AGENTS.md)，
> 要往服务器上放请看 [部署文档](docs/部署文档.md) 与 [运维手册](docs/运维手册.md)。

---

## 5 分钟上手

前置：**Python 3.11+**、**Node.js 20+**、Git Bash 或 PowerShell（不装 GNU Make 也能跑，见「没有 make 怎么办」）。

### 1. 装依赖

```bash
cd 项目源码/backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt        # macOS/Linux: .venv/bin/pip

cd ../frontend
npm install
```

### 2. 生成配置

```bash
cd ../backend
cp .env.example .env
```

打开 `.env`，只需填三处（其余留空即可启动）：

| 变量 | 从哪来 | 不填会怎样 |
|------|--------|-----------|
| `SECRET_KEY` | `.venv/Scripts/python -c "import secrets; print(secrets.token_hex(32))"` | 会话与指纹盐退化，仅本地开发可接受 |
| `FERNET_KEY` | `.venv/Scripts/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` | **设置页保存 API Key 会报错**（Key 要加密落库） |
| `LLM_API_KEY` | 模型厂商控制台（模板里默认 DeepSeek） | 走 Mock Provider：界面能点，内容不是真的 |

`.env` 已在 `.gitignore` 里，**不要提交**。

### 3. 建库 + 灌种子

```bash
.venv/Scripts/python -m flask --app "app:create_app()" db upgrade
.venv/Scripts/python -m flask --app "app:create_app()" seed
```

种子会建 1 位主讲老师（沈老师）+ 3 位 AI 同学（林晓 / 陈默 / 苏雨）+ 3 个音色 + **2 门官方示例课**（机器学习入门 / 光合作用，各 12 页）；重复执行不会产生重复数据，也不会覆盖你改过的行。

### 4. 启动

```bash
cd ..                       # 回到「项目源码/」
bash scripts/dev.sh          # Git Bash / macOS / Linux
.\scripts\dev.ps1            # PowerShell（Windows）
```

- 前端 http://localhost:5173 —— 打开它
- 后端 http://localhost:5000/api/health —— 应当返回 `{"code":0,...,"status":"ok"}`
- Ctrl+C 同时停掉两个服务

进「设置」页给某个服务商填 Key，点**测试连接**：成功会显示 `✓ 已连接 · 320ms`，失败会显示具体原因（401 / 连不上 / 超时），不会只弹一句「操作成功」。

---

## 部署

一台干净机器上要能用起来，三条命令：

```bash
cp backend/.env.example backend/.env     # 填 SECRET_KEY / FERNET_KEY
docker compose up -d --build
open http://<机器IP>:5000                # docker compose ps 等它变成 healthy
```

要 TLS / 域名加 `--profile tls`（配 `docker/nginx.conf`）；不用 Docker 的物理机装法、
访问码怎么开、升级怎么回滚，都在 [docs/部署文档.md](docs/部署文档.md)；
日常的备份恢复、日志、审计、成本与排障在 [docs/运维手册.md](docs/运维手册.md)。

两条**不要改**的：`gunicorn.conf.py` 里的 `worker_class = "gevent"`（SSE/WS 是长连接）
与 `workers = 1`（SQLite 单写者 + 课堂在线名单在进程内存里）。理由写在文件开头。

---

## 验收

```bash
python scripts/accept_p0.py     # P0：A 类 11 条
python scripts/accept_p1.py     # P1-G2：A/B/C 类 30+ 条，离线桩，不联网也不需要 Key
python scripts/accept_p2.py     # P2-G2：语音三条链路，离线 Mock，三个实例
python scripts/accept_p3.py     # P3-G2：无头 WS 课堂，十二页课从头走到下课
python scripts/accept_p4.py     # P4-G2：材料解析与工作台对话
python scripts/accept_p5.py     # P5-G2：导出三格式 + 看板 + 续跑 + 访问码 + 备份演练
python scripts/test.py          # 前后端全部测试
```

P1 ~ P5 那几套**都不碰你的数据**：各自起后端连临时库（跑完删掉），
模型/语音/材料全走离线替身 —— 断网、没 Key 照样跑得完。

`accept_p0.py` 会自己拉起服务（已经在跑的就复用），跑完关掉；**不改你的数据** —— 它试写的假 Key 会挑「未配置且没存过 Key」的空卡，验完按原值还原。

`accept_p1.py` 连碰都不碰你那个库：它另起一个后端（:5098）连临时库（跑完删掉），并以 `LLM_PROVIDER=mock` 运行 —— 每页都出自离线桩的固定产出，**断网、没 Key 照样跑得完**。它真生成四五门课来验：12 页端到端、SSE 帧序、大纲暂停后删页、单页重写、取消、404/400/409、重启修正、越权 404。要真模型才能量的（D 类性能、E 类人工评分）会明确记「跳过」并说明原因，不假装通过。

其余验收项对应的命令：

| 项 | 命令 | 说明 |
|----|------|------|
| B1~B3 接口契约 | `cd backend && .venv/Scripts/python -m pytest tests/contract` | 信封 / 错误码 / 40201 都有断言 |
| C1 库里无明文 Key | `grep -a -c "sk-" backend/data/eduagentx.db` | 期望 `0`（密文里也不该出现 Key 的形状） |
| C2 迁移双向 | `cd backend && .venv/Scripts/python -m flask --app "app:create_app()" db downgrade` 再 `... db upgrade` | |
| C3 WAL | `python -c "import sqlite3;print(sqlite3.connect('backend/data/eduagentx.db').execute('PRAGMA journal_mode').fetchone()[0])"` | 期望 `wal` |
| D1 health P95 | 见下方代码块 | 目标 < 50ms |
| D2 首屏 TTI | 见下方 Lighthouse 代码块（需本机有 Chrome） | 桌面目标 ≤ 1.5s，实测 `0.7s` |
| D3 产物体积 | `cd frontend && npm run build`，再 `ls -l dist/assets/*.js` | gzip 后 ≤ 800KB |
| E1 静态检查 | `cd backend && .venv/Scripts/python -m ruff check . && .venv/Scripts/python -m mypy app`；`cd frontend && npm run lint && npm run typecheck` | 零错误 |
| E2 覆盖率 | `cd backend && .venv/Scripts/python -m pytest --cov=app --cov-report=term-missing` | 目标 ≥ 60% |
| F1~F3 安全 | 见下方「安全基线」；契约测试与 `tests/unit/test_config.py`（扫代码里的硬编码端点）盯着 | |

D1 采样（后端要先跑起来）：

```bash
python -c "
import http.client, time
c = http.client.HTTPConnection('127.0.0.1', 5000)      # 直连 IP：走 keep-alive，且绕开代理
xs = []
for _ in range(100):
    t = time.perf_counter()
    c.request('GET', '/api/health'); c.getresponse().read()
    xs.append((time.perf_counter() - t) * 1000)
xs.sort()
print(f'P50 {xs[49]:.1f}ms  P95 {xs[94]:.1f}ms  max {xs[-1]:.1f}ms')
"
```

> 别用 `urllib.request.urlopen('http://localhost:5000/...')` 采样：它会读系统代理设置、
> 且 `localhost` 可能先解析到 `::1`，在部分 Windows 机器上每次请求要多花 ~2 秒等待，
> 量出来的是客户端的坑，不是后端的延迟（同机 curl 只有 ~0.2s）。本机实测：
> `P50 2.9ms / P95 25.1ms / max 28.6ms`（判定 PASS，目标 P95 < 50ms）。

D2 采样（要先 `npm run build`，再 `npm run preview`；需要本机装了 Chrome）：

```bash
cd frontend && npm run build && npm run preview &   # preview 默认 4173
npx lighthouse http://localhost:4173/ --only-categories=performance --preset=desktop \
  --chrome-flags="--headless=new" --output=json --output-path=lh.json --quiet
python -c "import json;a=json.load(open('lh.json'))['audits'];print(a['interactive']['displayValue'])"
```

> 本机实测（Lighthouse 13.4.1，desktop preset，simulate 节流）：
> `TTI 0.7s`、LCP `0.7s`、TBT `0ms`、CLS `0`、性能分 `100` —— 判定 PASS（目标 ≤ 1.5s）。
>
> 顺带跑了更严的 **mobile preset**（4× CPU 降速 + slow-4G 模拟）：TTI `3.1s`、LCP `3.1s`、
> 性能分 `92`。目标是按桌面端定的（这是给老师上课用的桌面 Web 应用），移动端这一档没有过线，
> 但也**不在 P0 验收范围内**；真要过，得从首屏包体积入手（`IndexView` 那块 336KB→90KB gzip）。
> `vite preview` 只监听 `::1`，所以命令里写 `localhost` 而不是 `127.0.0.1`。

---

## 目录结构

```
项目源码/
├── backend/
│   ├── app/
│   │   ├── api/            # 蓝图：health / settings（含服务商与音色）/ courses / generation /
│   │   │                   #   agents / voice / materials / workbench / classroom / exports /
│   │   │                   #   usage（只做取参 → 调 service → 包信封）
│   │   ├── common/         # 信封与错误、日志脱敏与轮转、加密、SSRF 校验、写队列、任务器、
│   │   │                   #   access.py = 站点访问码门禁；site.py = 托管前端产物（P5）
│   │   ├── models/         # Provider / VoiceProfile / AgentRole / Course / GenJob / GenStep /
│   │   │                   #   Material / Export / ModelCall / DailyUsage / Budget / AuditLog（Key 只进不出）
│   │   ├── providers/      # LLM / TTS / ASR / Realtime 抽象 + mock + 火山与 OpenAI 兼容实现
│   │   │                   #   llm/fixture.py = 离线课程桩（各期验收与示例课演示靠它）
│   │   ├── services/       # provider_registry / provider_admin / settings / audit / backup
│   │   │                   #   generation/ = 生成管线（intake · pipeline · schema · prompts · filter · events）
│   │   │                   #   courses/    = 课程读写（store 是页面与 DSL 的唯一事实来源）
│   │   │                   #   classroom/  = 课堂运行时（P3）；voice/（P2）；materials/（P4）
│   │   │                   #   exports/    = IR → PPTX/HTML/PDF + 队列 + 一次性下载（P5）
│   │   │                   #   usage/      = 用量埋点 · 聚合 · 定价 · 预算（P5）
│   │   ├── seeds/          # 内置音色、课堂角色、示例课程
│   │   ├── templates/      # access.html（访问码校验页，后端渲染：那一刻前端产物正被它挡着）
│   │   └── config.py       # 所有厂商凭据 / 端点 / 音色 ID 都从这里读 .env
│   ├── migrations/         # Alembic
│   ├── tests/              # unit（不联网）+ contract（接口契约）
│   ├── data/               # 全部状态：SQLite · 上传 · 材料 · 音频 · 导出 · 备份（gitignore）
│   └── gunicorn.conf.py    # 生产入口（gevent / workers=1，理由见文件头）
├── frontend/
│   └── src/
│       ├── api/            # axios 实例：注入 X-Request-Id、解包信封、40304 跳校验页
│       ├── components/     # AppHeader / ProviderCard / ProviderFormDrawer / CapabilityPanel
│       │                   #   CostBoard · BudgetEditor · PricingEditor（P5 成本）
│       │                   #   workbench/ = 任务卡 · 时间线 · 大纲树 · 页面编辑 · 导出 · 材料 · 对话
│       │                   #   classroom/ = 讲台 · 讨论区 · 随堂测验；home/ = 主题输入 · 课程卡
│       ├── styles/         # tokens.css：原型设计令牌 + TDesign 主题覆盖
│       ├── stores/         # Pinia：settings（服务商/音色/生成参数/预算）/ courses / user
│       └── views/          # 首页 / 工作台 / 课堂演示 / 课堂记录 / 设置（含成本看板）
├── docs/                   # 部署文档 · 运维手册
├── docker/                 # entrypoint.sh · nginx.conf（TLS 档的示例）
├── Dockerfile · docker-compose.yml · .dockerignore
└── scripts/                # dev.sh · dev.ps1 · test.py · accept_p0.py ~ accept_p5.py
```

---

## 配置项

`.env` 里**只需要**关心这几组，其余（超时、采样率、QPM）用默认值即可：

- **文本模型**：`LLM_PROVIDER`（deepseek/openai/qwen/kimi/custom）、`LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL`
  —— 这一组是「当前启用的服务商」的兜底配置；在设置页里改的会覆盖它（设置页改的是数据库）。
- **语音（火山引擎）**：`VOLC_TTS_*`（大模型 TTS 2.0，双向流式）、`VOLC_REALTIME_*`（端到端实时语音）、`VOLC_ASR_*`（流式识别）
  —— 三套是**互不通用**的三条链路，音色 ID 也不通用（TTS 2.0 的音色来自 `_uranus_bigtts` 池，实时语音来自 `_jupiter_bigtts` 池）。填错池子会被上游以 `InvalidSpeaker` 拒绝。
  —— P0 阶段这三个适配器是骨架：凭据填了也只会如实回「还在 P2 接通」，绝不会假装能用。
- **生成默认值**：`DEFAULT_PAGE_COUNT`、`DEFAULT_CLASSMATE_COUNT`；其余参数在设置页里改。

改完 `.env` 要重启后端。

---

## 安全基线（AGENTS.md §4.1 / §24）

- **凭据只在服务端**：前端代码、网络面板、日志里都拿不到 Key；接口只回 `sk-****1234` 这样的掩码，连密文都不返回（有契约测试盯着）。
- **落库加密**：API Key 用 Fernet 加密后写入 `api_key_enc`，读明文必须显式走 `reveal_api_key()`。
- **浏览器不直连厂商**：前端所有请求都打自己的 Flask（开发态走 Vite 代理）。
- **上传**：扩展名与 MIME 白名单 + 魔数校验 + 大小上限 + 文件名安全化 + 独立存储目录。
- **SSRF**：自定义 `base_url` 过协议白名单（只允许 http/https）与内网网段黑名单（127./10./172.16-31./192.168./169.254. 等），域名会真的解析一遍。
- **越权**：资源接口一律校验 `owner_id`，越权按 404 处理（不泄露「存在但无权限」）。
- **日志**：不打印 Key 原文（含异常栈）、完整提示词、材料正文、音频帧。
- **隐私**：语音默认不落盘；学习行为数据默认只存本地。

---

## 常见问题

**没有 make 怎么办？** Makefile 只是入口别名，Windows 上用 `scripts/` 下的等价脚本即可：

| make 目标 | 等价命令 |
|-----------|---------|
| `make dev` | `bash scripts/dev.sh` 或 `.\scripts\dev.ps1` |
| `make test` | `python scripts/test.py` |
| `make seed` | `cd backend && .venv/Scripts/python -m flask --app "app:create_app()" seed` |
| `make migrate` | `cd backend && .venv/Scripts/python -m flask --app "app:create_app()" db upgrade` |
| `make lint` / `make build` | 见上方验收表 E1 / D3 |
| `make accept` | 依次跑 `scripts/accept_p0.py` ~ `accept_p5.py` |
| `make accept-p1` … `accept-p5` | `python scripts/accept_pN.py`（都是离线实例，不需要 Key） |
| `make env` | `cp backend/.env.example backend/.env` |
| `make up` / `make down` | `docker compose up -d --build` / `down`（要 Docker；`PROFILE=tls` 带上 nginx） |
| `make backup` / `make restore` | `cd backend && .venv/Scripts/python -m flask --app "app:create_app()" backup`，恢复见运维手册 |
| `make clean-exports` | `cd backend && .venv/Scripts/python -m flask --app "app:create_app()" exports-cleanup` |
| `make deps-audit` | 见运维手册 §8（**要联网**） |

**PowerShell 说「禁止运行脚本」**：`powershell -ExecutionPolicy Bypass -File scripts\dev.ps1`，或一次性放开当前用户：`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`。

**端口被占用**：`BACKEND_PORT=5001 FRONTEND_PORT=5174 bash scripts/dev.sh`（PowerShell 用 `-BackendPort 5001 -FrontendPort 5174`）。

**「测试连接」返回 40201**：这是「还没配齐」，不是网络问题。40201 的 message 会说缺哪几栏 —— 空卡通常缺 API Key、接入地址、模型名三样，填齐再测。

**Key 是对的但探活失败**：看返回的 `errorCode` —— `unauthorized`（Key 无效/无权限）、`network`（连不上，多半是地址写错）、`timeout`（超时）。`error` 字段是上游原话，已脱敏。

**保存 Key 报「未配置 FERNET_KEY」**：按上面第 2 步生成一个填进 `.env`，重启后端。

**改了样式但页面没变**：确认 `src/main.ts` 里 `tdesign-vue-next/es/style/index.css` 仍在自有 `tokens.css` **之前**引入 —— 顺序反了，`--td-*` 覆盖就失效。

**Windows 控制台中文乱码**：`chcp 65001` 切到 UTF-8 代码页再跑命令。CLI 的输出只用中文与 ASCII，正是为了这个。

**想放到局域网上给同事用**：开访问码（`SITE_ACCESS_CODE`），否则知道地址的人都能用。它是一张门禁卡（共用一个码），不是账号体系 —— 细节与风控见 [部署文档 §2](docs/部署文档.md)。

**页面打开是空的，端口 5000 上只有 API**：开发机上没跑过 `npm run build` 时后端**只提供 API**，这是设计如此（见 `backend/app/common/site.py` 第 1 条）。跑一次 `make build` 再重启。

**数据在哪 / 怎么备份**：全部状态在 `backend/data/`。别 `cp` 那个 `.db` —— WAL 下拷出来的是「看着正常、其实少一截」的文件。用 `make backup`（SQLite 在线备份 API）与 `make restore`：[运维手册 §3](docs/运维手册.md)。

---

## 想要真效果，需要两样东西

1. **可用的文本模型 Key** —— 课程生成要走真模型才有真内容。没 Key 也**跑得动**：
   `.env` 里留空或 `LLM_PROVIDER=mock`，离线桩产出固定但结构完整的内容，
   验收与演示都够用；
2. **火山语音的音色 ID** —— 填进 `.env` 的 `VOLC_TTS_VOICE_*` / `VOLC_REALTIME_VOICE_*`，
   重启后端。设置页会显示「已配置 / 未配置」，没填时调用如实返回 `40201`（还没配齐），
   不会假装出声。三套语音链路（TTS 2.0 / 实时语音 / 流式识别）的音色池**互不通用**，
   填错池子会被上游以 `InvalidSpeaker` 拒绝 —— 见「配置项」那节。

## 下一步

P6（扩展能力）的计划见 [`../项目文档/P6-扩展能力.md`](../项目文档/P6-扩展能力.md)。
