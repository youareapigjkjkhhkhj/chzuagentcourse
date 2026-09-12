# EduAgentX —— 工程入口（P0 §6）
#
# 所有命令都假设工作目录是「项目源码/」。
#
# Windows 上没有装 GNU Make 的话，scripts/ 下有等价入口：
#   make dev       ≈  .\scripts\dev.ps1      （bash: bash scripts/dev.sh）
#   make accept    ≈  python scripts\accept_p0.py 然后 python scripts\accept_p1.py
#   make accept-p1 ≈  python scripts\accept_p1.py （P1-G2，离线桩）
#   make test      ≈  python scripts\test.py （或直接看 README 里的两条 pytest/vitest）
# 不装 make 不影响验收 —— 两份 accept 脚本都不依赖本文件。

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

.PHONY: help setup dev seed migrate test test-back test-front lint build accept accept-p0 accept-p1 clean

help:
	@echo "setup      安装前后端依赖，建库、灌种子（首次上手跑这个）"
	@echo "dev        同时启动后端 :5000 与前端 :5173"
	@echo "seed       灌入内置角色/音色/示例课程（幂等）"
	@echo "migrate    执行数据库迁移到最新版本"
	@echo "test       后端 pytest + 前端 vitest"
	@echo "lint       ruff + mypy + eslint + vue-tsc"
	@echo "build      前端生产构建"
	@echo "accept     跑 P0 + P1 两套验收，输出通过清单"
	@echo "accept-p0  只跑 P0（A 类 11 条，用你本机的库）"
	@echo "accept-p1  只跑 P1（离线桩，临时库，不联网、不动你的数据）"

setup:
	$(PY) -m pip install -r backend/requirements.txt
	cd frontend && $(NPM) install
	@test -f backend/.env || (cp backend/.env.example backend/.env && echo "已生成 backend/.env —— 请填入密钥后重新执行")
	cd backend && $(FLASK) db upgrade
	$(MAKE) seed

dev:
	bash scripts/dev.sh

seed:
	cd backend && $(FLASK) seed

migrate:
	cd backend && $(FLASK) db upgrade

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

accept: accept-p0 accept-p1

accept-p0:
	$(PY) scripts/accept_p0.py

# 离线桩：自己起后端连临时库，不碰 :5000 那个、也不需要 Key（P1-G2）
accept-p1:
	$(PY) scripts/accept_p1.py

clean:
	rm -rf frontend/dist
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
