# EduAgentX —— 工程入口（P0 §6）
#
# 所有命令都假设工作目录是「项目源码/」。
#
# Windows 上没有装 GNU Make 的话，scripts/ 下有等价入口：
#   make dev       ≈  .\scripts\dev.ps1      （bash: bash scripts/dev.sh）
#   make accept    ≈  依次跑 scripts\accept_p0.py 到 accept_p5.py
#   make accept-p1 ≈  python scripts\accept_p1.py （P1-G2，离线桩）
#   make accept-p2 ≈  python scripts\accept_p2.py （P2-G2，离线 Mock，三个实例）
#   make accept-p3 ≈  python scripts\accept_p3.py （P3-G2，无头 WS 课堂，三个实例）
#   make accept-p4 ≈  python scripts\accept_p4.py （P4-G2，材料与工作台，两个实例）
#   make accept-p5 ≈  python scripts\accept_p5.py （P5-G2，导出/看板/续跑/访问码，两个实例）
#   make up / down ≈  docker compose up -d --build / down（要 Docker，与 make 无关）
#   make test      ≈  python scripts\test.py （或直接看 README 里的两条 pytest/vitest）
# 不装 make 不影响验收 —— 几份 accept 脚本都不依赖本文件。

SHELL := /bin/bash

# Windows venv 的 python 在 Scripts/，POSIX 在 bin/
ifeq ($(OS),Windows_NT)
VENV_PY := .venv/Scripts/python.exe
else
VENV_PY := .venv/bin/python
endif
# 同一条路径的两个写法：PY 供根目录用，$(VENV_PY) 供已经 cd backend 的配方用
PY := backend/$(VENV_PY)

# app:create_app() 里的括号必须引起来：交给 shell 时 `(` 会被当成子 shell 语法
FLASK := $(PY) -m flask --app "app:create_app()"
NPM := npm

.PHONY: help setup env dev seed migrate clean-exports up down logs ps backup restore deps-audit ci test test-back test-front lint build accept accept-p0 accept-p1 accept-p2 accept-p3 accept-p4 accept-p5 clean

help:
	@echo "setup      安装前后端依赖，建库、灌种子（首次上手跑这个）"
	@echo "env        从 .env.example 生成 backend/.env（已存在就不动）"
	@echo "dev        同时启动后端 :5000 与前端 :5173"
	@echo "seed       灌入内置角色/音色/示例课程（幂等）"
	@echo "migrate    执行数据库迁移到最新版本"
	@echo "clean-exports  删掉过期的导出产物与记录（挂在 cron 上，P5-C1）"
	@echo "up         docker compose 起容器（P5-A11；要 TLS 加 PROFILE=tls）"
	@echo "down       停掉容器（数据留在 backend/data，不动）"
	@echo "logs       跟容器日志"
	@echo "ps         看容器状态与健康检查结果"
	@echo "backup     打一份备份（库 + 材料 + 音频 + 导出产物，P5-C3）"
	@echo "restore    从备份恢复（先打印预告，确认要加 --yes）"
	@echo "deps-audit 依赖漏洞扫描（pip-audit / npm audit，P5-F5，需要联网）"
	@echo "ci         一键跑完：lint + 前后端测试 + 五套离线验收（P5-G2）"
	@echo "test       后端 pytest + 前端 vitest"
	@echo "lint       ruff + mypy + eslint + vue-tsc"
	@echo "build      前端生产构建"
	@echo "accept     跑 P0 + P1 + P2 + P3 + P4 + P5 六套验收，输出通过清单"
	@echo "accept-p0  只跑 P0（A 类 11 条，用你本机的库）"
	@echo "accept-p1  只跑 P1（离线桩，临时库，不联网、不动你的数据）"
	@echo "accept-p2  只跑 P2（离线 Mock，三个实例：正常 / 半配 / 关语音）"
	@echo "accept-p3  只跑 P3（无头 WS 课堂，三个实例：正常 / 心跳 1s / 关推送）"
	@echo "accept-p4  只跑 P4（材料与工作台，两个实例：材料开 / MATERIAL_ENABLED=false）"
	@echo "accept-p5  只跑 P5（导出三格式 + 看板 + 预算 + 续跑 + 访问码 + 审计 + 备份演练）"

# .env 只有一份（backend/.env），`make dev` 与 docker compose 用的是它。
# 已经有就**不动它**：那里面是真 Key，覆盖一次就没了。
env:
	@test -f backend/.env || (cp backend/.env.example backend/.env && echo "已生成 backend/.env —— 请填入密钥")

setup:
	$(PY) -m pip install -r backend/requirements.txt
	cd frontend && $(NPM) install
	$(MAKE) env
	@echo "填好 backend/.env 的密钥后，接着跑：make migrate && make seed"
	cd backend && $(FLASK) db upgrade
	$(MAKE) seed

dev:
	bash scripts/dev.sh

seed:
	cd backend && $(FLASK) seed

migrate:
	cd backend && $(FLASK) db upgrade

# 导出产物是**到期即删**（P5-C1）：这一步不做，`data/exports/` 只会一直涨。
# 仓库里没有常驻调度器，所以由部署方挂一条定时任务调它：
#   物理机：0 * * * * cd <项目>/项目源码 && make clean-exports
#   容器：docker compose exec -T app flask exports-cleanup
#         （容器里 entrypoint.sh 默认已经挂了一条一小时的循环，不用再配）
clean-exports:
	cd backend && $(FLASK) exports-cleanup

# --- 部署（P5 §6 / A11 / A12 / C3）---

# 起容器前先确保 .env 在：compose 找不到它会直接报错，
# 而那句报错与「密钥没配」看起来是两回事。
up: env
	docker compose up -d --build $(if $(PROFILE),--profile $(PROFILE),)
	@echo "起来了。看状态：make ps ；跟日志：make logs"
	@echo "首次起容器会自动跑迁移；要灌种子就 SEED_ON_START=1（见 docker-compose.yml）"

down:
	docker compose --profile tls down

logs:
	docker compose logs -f --tail=100 app

ps:
	docker compose ps

# 备份走的是后端自己的 CLI（P5-C3）：它比「在宿主机上 cp 数据目录」多两件事 ——
# SQLite 用在线备份 API 取一致快照、四类文件按逻辑名归档（换机器也恢复得回来）。
# 容器在跑的时候可以直接 `docker compose exec -T app flask backup`。
backup:
	cd backend && $(FLASK) backup

# 恢复默认只打印预告。真要恢复：make restore FILE=... ARGS=--yes
restore:
	cd backend && $(FLASK) restore "$(FILE)" $(ARGS)

# 依赖漏洞扫描（P5-F5）。**需要联网**，所以不挂在 test / accept 里：
# 那两条按 AGENTS §23 是必须离线的。
#
# 两个坑，都写在这儿省得下次再踩：
#   1. npm 的漏洞库接口只在官方 registry 上有。走镜像源会得到
#      `[NOT_IMPLEMENTED] /-/npm/v1/security/*` —— 看着像报错，
#      其实是这个源没实现那个接口。所以这里显式指定 registry。
#   2. pip-audit 要自己装（它不在 requirements.txt 里：那是运行时依赖清单，
#      而这是运维工具）。装不上多半是当前源里没有这个包。
deps-audit:
	cd frontend && $(NPM) audit --audit-level=high --registry=https://registry.npmjs.org
	cd backend && $(VENV_PY) -m pip_audit --skip-editable || \
		echo "没装 pip-audit：$(VENV_PY) -m pip install pip-audit 之后再来一次"

# 一条命令跑完「代码是好的」这件事（P5-G2）。**不包含 accept-p0**：
# 它用的是你本机那个库（虽然不改数据），而 ci 的口径是「随便在哪台机器上跑都成立」。
#
# P5 §7 的 G2 写的是「lint + 单测 + 契约 + E2E（Playwright）」。本仓库没有 Playwright：
# 前端的 E2E 角色由 vitest 的组件用例（真实点击与路由）与 accept_p3 那台**无头浏览器**
# （用脚本假浏览器把 12 页课从头走到下课）承担 —— 两者都在下面这条链上。
ci: lint test accept-p1 accept-p2 accept-p3 accept-p4 accept-p5

test: test-back test-front

test-back:
	cd backend && $(VENV_PY) -m pytest

test-front:
	cd frontend && $(NPM) run test

lint:
	cd backend && $(VENV_PY) -m ruff check .
	cd backend && $(VENV_PY) -m mypy app
	cd frontend && $(NPM) run typecheck
	cd frontend && $(NPM) run lint

build:
	cd frontend && $(NPM) run build

accept: accept-p0 accept-p1 accept-p2 accept-p3 accept-p4 accept-p5

accept-p0:
	$(PY) scripts/accept_p0.py

# 离线桩：自己起后端连临时库，不碰 :5000 那个、也不需要 Key（P1-G2）
accept-p1:
	$(PY) scripts/accept_p1.py

# 离线 Mock：自己起三个后端（正常 / 半配 / 关语音）连同一个临时库，
# 合成与识别全走 Mock，一条上游请求都不发（P2-G2）
accept-p2:
	$(PY) scripts/accept_p2.py

# 无头课堂：自己起三个后端（正常 / 心跳 1s 判死 4s / 关推送）各自连临时库，
# 用一只脚本假浏览器把 12 页课从头走到下课，模型与语音全走离线替身（P3-G2）
accept-p3:
	$(PY) scripts/accept_p3.py

# 材料与工作台：自己起两个后端（材料开 / MATERIAL_ENABLED=false）各自连临时库，
# 材料解析、检索、溯源全走离线替身，样例来自 samples/materials（P4-G2）
accept-p4:
	$(PY) scripts/accept_p4.py

# 导出与工程化：自己起两个后端（正常 / 开了访问码）各自连临时库，
# 三种产物真渲染、下载链接真过期、备份真恢复一次（P5-G2 / C3）
accept-p5:
	$(PY) scripts/accept_p5.py

clean:
	rm -rf frontend/dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
