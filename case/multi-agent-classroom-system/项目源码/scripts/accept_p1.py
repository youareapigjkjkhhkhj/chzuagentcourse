#!/usr/bin/env python
"""P1 A/B/C 类验收（P1-G2）：用离线桩跑通「主题 → 一门能上课的课」。

    python scripts/accept_p1.py            # 跑全部
    python scripts/accept_p1.py --keep     # 跑完留下临时库、日志与后端进程

三条原则（与 accept_p0 相同，理由见那份脚本）：

1. **不改你的数据。** 这份脚本会真的生成四五门课 —— 在 backend/data/ 上跑
   一遍，你的课程列表里就会多出几门「验收课」。所以它**自己起一个后端**，
   而且那个后端连的是临时库（`DATABASE_URL` 指到 tempfile 里）；:5000 上
   那个（连你自己库的）它连碰都不碰。
2. **不联网。** 后端以 `LLM_PROVIDER=mock` 启动：每一页都出自
   `app/providers/llm/fixture.py` 的固定产出，且同一输入永远同一输出。
   这台机器断网、没 Key，照样跑得完（P1-G2）。

   `LLM_PROVIDER=mock` 只钉住了大模型那一路。生成流水线从 P2 起还有
   `tts` 步骤，而**Flask CLI 自己会读 `backend/.env`** —— 环境变量里
   给的值它会照用，但没给的（火山那三组 Key 与接入地址）它会从 `.env`
   补上。于是这台机器上一跑验收，`tts` 步骤就真去合成音频、真花钱了，
   而「不联网」这四个字是这份脚本对使用者的承诺。所以下面除了
   `LLM_PROVIDER=mock`，还会把 `LLM_*`/`VOLC_*` 全部显式清空，并给子进程
   `FLASK_SKIP_DOTENV=1`（连 Flask CLI 那一层也堵上）。谁要是在这里
   「顺手」删掉几行，请先想一遍这句承诺。
3. **说得出为什么。** 每条不通过都打印实际收到的响应；跑不到的条目
   （要真模型的性能项、要人打分的质量项）明确跳过并说明原因，
   而不是假装通过。

跑不到的与跑得到的分界，就是 P1 §7 自己的分界：

    A（功能）/ B（接口）/ C（数据）  → 离线桩可验，脚本逐条查
    D（性能）/ E（质量人工分）       → 要真模型，记跳过并附上离线侧的数字
    F（安全）/ G（回归）             → 能脚本化的那几条照查，其余指向用例
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Mapping, Sequence

#: Windows 控制台是 GBK，而生成的课程标题里全是中文、日志里还夹着 ✓。
#: 默认行为是直接 UnicodeEncodeError 崩掉 —— 验收脚本不该死在打印上。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(errors="replace")

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def plain(text: str) -> str:
    """去掉 ANSI 颜色码：报错详情里混着转义序列没法读。"""
    return _ANSI.sub("", text or "")


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"

#: 验收用的临时后端。刻意不用 5000：那是 `make dev` 的端口，连的是你的库。
TEMP_PORT = 5098
#: P1-C5 的「重启」要再起一个实例，用另一个端口（同一个临时库）。
RESTART_PORT = 5097

#: 由 main() 赋值的接口前缀（脚本要等临时后端起来才知道自己该调谁）。
API = ""

#: 终态事件：收到它们这条流就该结束了（§4.1）。
TERMINAL_EVENTS = frozenset({"job.done", "job.failed", "job.canceled"})

#: 大纲确认点。它不是终态 —— 流在暂停时还开着，只是没有更多帧了。
PAUSE_EVENTS = frozenset({"job.paused"})

#: 主线课程（P1-A1 的主题，§7 各处用的都是这一门）。
TOPIC = "机器学习入门"
PAGE_COUNT = 12

#: P1-A7 重写的那一页、P1-A11 人工编辑的那一页、P1-C2 存特殊字符的那一页。
REWRITE_PAGE = 7
EDIT_PAGE = 5
UNICODE_PAGE = 9

#: P1-C2 用的字符：公式、上下标、emoji、全角标点、箭头。逐字节比回来才算无损。
UNICODE_BEATS = (
    "公式 η 与学习率 α 的关系：x ← x − η∇f(x)",
    "下标 x₁ x₂ 与上标 x² x³ 都要原样存住",
    "emoji 🎯🧪 与全角标点：，「」？——以及箭头 → ≤ ≥",
)

#: 「断网失败」这一支不拔网线，改为跑已覆盖该映射的用例（不联网）。
FAILURE_TESTS = [
    "tests/unit/test_generation_pipeline.py::test_an_unconfigured_generation_fails_the_first_step",
    "tests/contract/test_p1_api.py::test_a_failed_page_shows_up_in_the_tree_and_can_be_retried",
]

#: P1-F2 的敏感词路径。
SENSITIVE_TESTS = [
    "tests/unit/test_generation_pipeline.py::test_a_sensitive_page_is_regenerated_once_and_audited",
    "tests/unit/test_generation_pipeline.py::test_a_page_that_stays_sensitive_is_not_published",
]

#: P1-F4 的「生成结束后线程数回落」。
LEAK_TESTS = ["tests/unit/test_common_tasks.py::test_threads_do_not_grow_with_the_number_of_jobs"]

#: 真的会调模型的四步。`tts`（P1 里是 skipped）与 `assemble`（只重建 DSL）
#: 不调模型，它们的记账里没有 model/tokens 是**对的** —— 拿它们去撞 P1-B4
#: 只会把一条正确的实现报成缺陷。
LLM_STEPS = frozenset({"parse", "outline", "write", "quiz"})


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------


class Report:
    """通过清单。最后要能一眼看出「哪几条没过」。"""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []

    def _add(self, aid: str, title: str, status: str, detail: str) -> None:
        # 详情里可能嵌着 pytest/npm 的原始输出（带 ANSI 颜色码），统一在这里清洗
        detail = plain(detail)
        self.rows.append((aid, title, status, detail))
        label = {"PASS": "通过", "FAIL": "不通过", "SKIP": "跳过"}[status]
        print(f"  [{label}] {aid} {title}")
        if detail:
            for line in detail.splitlines():
                print(f"         {line}")

    def ok(self, aid: str, title: str, detail: str = "") -> None:
        self._add(aid, title, "PASS", detail)

    def fail(self, aid: str, title: str, detail: str = "") -> None:
        self._add(aid, title, "FAIL", detail)

    def skip(self, aid: str, title: str, detail: str = "") -> None:
        self._add(aid, title, "SKIP", detail)

    def summary(self) -> int:
        passed = sum(1 for row in self.rows if row[2] == "PASS")
        failed = [r for r in self.rows if r[2] == "FAIL"]
        skipped = [r for r in self.rows if r[2] == "SKIP"]
        print()
        print("=" * 68)
        print(f"P1 验收：通过 {passed} / 不通过 {len(failed)} / 跳过 {len(skipped)}")
        for aid, title, _, detail in failed:
            print(f"  ✗ {aid} {title}")
            if detail:
                print(f"      {detail.splitlines()[0]}")
        for aid, title, _, detail in skipped:
            print(f"  - {aid} {title}（{detail.splitlines()[0] if detail else '未说明'}）")
        print("=" * 68)
        return 1 if failed else 0


# --------------------------------------------------------------------------
# HTTP（只用标准库：脚本要能被系统 python 直接跑起来）
# --------------------------------------------------------------------------


def api(
    method: str, path: str, body: Any = None, timeout: float = 30.0, owner: str = ""
) -> tuple[int, dict]:
    """调后端接口，返回 (HTTP 状态, 信封)。业务错误也在信封里，不抛异常。

    `owner` 是 P1-F3 用的：`X-Owner-Id` 头一换，「当前用户」就变成另一个人。
    它不是鉴权（能改请求头就能冒充），是本地会话期留给越权用例的一道缝。
    """
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json", "X-Request-Id": "accept-p1"}
    if owner:
        headers["X-Owner-Id"] = owner
    req = urllib.request.Request(f"{API}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"raw": raw[:400]}
    except Exception as exc:  # 连不上 / 超时
        return 0, {"error": f"{type(exc).__name__}: {exc}"}


def _data(status: int, envelope: dict) -> Any:
    return envelope.get("data") if status == 200 and envelope.get("code") == 0 else None


def brief(payload: Any, limit: int = 300) -> str:
    text = json.dumps(payload, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"


def is_up(url: str, timeout: float = 5.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status < 500
    except Exception:
        return False


def wait_http(url: str, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status < 500:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


# --------------------------------------------------------------------------
# SSE
# --------------------------------------------------------------------------


def open_stream(
    job_id: str,
    *,
    timeout: float = 300.0,
    stop_at: frozenset[str] = TERMINAL_EVENTS,
    base: str = "",
) -> tuple[list[dict], dict]:
    """订阅一条 SSE 直到终态（或 `stop_at` 里的某帧），返回 (帧列表, 响应头)。

    帧按 SSE 的写法解析：`id:` 给 seq、`event:` 给名字、`data:` 给 JSON，
    空行分隔一帧；以 `:` 开头的行是注释 —— 心跳 `: ping` 与开场那句 `: ok`
    都走这里，它们不是事件。

    这条流既是「看进度」也是「等结果」：任务跑完时最后一帧一定是终态，
    收到就可以断开（浏览器那边也要主动 close，见 SSE 路由的注释）。
    """
    req = urllib.request.Request(
        f"{base or API}/courses/generate/{job_id}/stream",
        headers={"Accept": "text/event-stream", "X-Request-Id": "accept-p1"},
    )
    frames: list[dict] = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        headers = {key.lower(): value for key, value in resp.headers.items()}
        pending: dict[str, str] = {}
        for raw in resp:
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if not line:
                if pending.get("event"):
                    frames.append(_frame(pending))
                    if pending["event"] in stop_at:
                        break
                pending = {}
                continue
            if line.startswith(":"):
                continue
            name, _, value = line.partition(":")
            pending[name.strip()] = value[1:] if value.startswith(" ") else value
    return frames, headers


def _frame(pending: Mapping[str, str]) -> dict:
    try:
        data = json.loads(pending.get("data") or "{}")
    except json.JSONDecodeError:  # 帧坏了也要留下痕迹，而不是丢掉它
        data = {"raw": pending.get("data", "")}
    return {"seq": int(pending.get("id") or 0), "event": pending["event"], "data": data}


# --------------------------------------------------------------------------
# 进程管理
# --------------------------------------------------------------------------


def venv_python() -> Path:
    for rel in ("Scripts/python.exe", "bin/python"):
        candidate = BACKEND / ".venv" / rel
        if candidate.exists():
            return candidate
    sys.exit("找不到虚拟环境。先建：python -m venv backend/.venv 然后 pip install -r backend/requirements.txt")


def npx() -> str:
    return shutil.which("npx") or shutil.which("npx.cmd") or "npx"


def child_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """子进程的环境。

    `PYTHONIOENCODING=utf-8` 是必需的，不是讲究：子进程的输出进了管道，
    Python 就按**本地编码**（中文 Windows 上是 GBK）写字节，而我们按 UTF-8 读 ——
    一门课的主题、每一句讲稿都会变成乱码，断言「清洗后的主题还是不是原来那句」
    于是永远为假。这类失败看着像业务 bug，其实是编码。

    两个 `*_DOTENV` 是「不联网」那条承诺的守卫，别删：

    * `EDUAGENTX_DISABLE_DOTENV=1` 关掉应用自己那一次 `load_dotenv`；
    * `FLASK_SKIP_DOTENV=1` 关掉 **Flask CLI 自己**那一次 —— 后端是用
      `python -m flask run` 起的（还有 `db upgrade`），CLI 在建 app 之前
      就会把 `backend/.env` 读进环境。这个坑实测踩过一次：三个验收实例
      全被 `.env` 喂成了「真配」，本该报 40201 的半配实例发起了一次真的
      上游连接（详见 accept_p2.py 的 `OFFLINE_ENV`）。
    """
    return {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "FLASK_SKIP_DOTENV": "1",
        "EDUAGENTX_DISABLE_DOTENV": "1",
        **(env or {}),
    }


def start(process_args: list[str], cwd: Path, log_path: Path, env: dict[str, str] | None = None):
    log = log_path.open("w", encoding="utf-8")
    return subprocess.Popen(
        process_args, cwd=str(cwd), env=child_env(env),
        stdout=log, stderr=subprocess.STDOUT,
    )


def stop(proc) -> None:
    """停掉我们启动的服务（含它的子进程；Windows 上 terminate 杀不干净）。"""
    if proc is None or proc.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, check=False)
    else:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def run_python(code: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """在 backend 目录下用 venv python 跑一段代码（读临时库、灌种子都用它）。"""
    return subprocess.run(
        [str(venv_python()), "-c", code],
        cwd=str(BACKEND),
        env=child_env(env),
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def run_pytest(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(venv_python()), "-m", "pytest", "-q", *args],
        cwd=str(BACKEND),
        env=child_env(),
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _pytest_tail(result: subprocess.CompletedProcess, lines: int = 12) -> str:
    """pytest 输出里最后几行才有「几个通过几个失败」。"""
    output = plain((result.stdout or "") + (result.stderr or ""))
    return "\n".join(line for line in output.splitlines()[-lines:] if line.strip())


# --------------------------------------------------------------------------
# 一次验收里要来回传的东西
# --------------------------------------------------------------------------


@dataclass
class Ctx:
    """临时后端 + 这次跑出来的几门课。检查函数从这里取料，不各自新建。"""

    env: dict[str, str]
    work_dir: Path
    course_id: str = ""      # 主线课程：12 页、每章一测验（A1/A5/A6/A7/A10/A11/B1/B2/B4/C1/C2/C4）
    job_id: str = ""
    elapsed_ms: int = 0      # P1-B1 要的那个耗时
    frames: list[dict] = field(default_factory=list)   # 主线课程的 SSE 帧
    stream_headers: dict = field(default_factory=dict)
    job: dict = field(default_factory=dict)
    detail: dict = field(default_factory=dict)         # 主线课程详情（含 pages）
    paused_course: str = ""  # 停在大纲确认点的那门
    seminar_course: str = "" # 研讨模式那门
    cancel_course: str = ""  # 取消那一门


# --------------------------------------------------------------------------
# 辅助
# --------------------------------------------------------------------------


def _post_generate(topic: str, **options: Any) -> tuple[int, Any]:
    """POST 一个生成任务，返回 (耗时毫秒, 响应 data)。耗时是 P1-B1 的判据。"""
    started = time.perf_counter()
    status, envelope = api("POST", "/courses/generate", {"topic": topic, **options}, timeout=30)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return elapsed_ms, _data(status, envelope)


def _wait_done(job_id: str, timeout: float = 180.0) -> dict:
    """轮询兜底接口直到任务进终态（SSE 之外的第二个状态源，P1 §4）。"""
    deadline = time.time() + timeout
    payload: dict = {}
    while time.time() < deadline:
        status, envelope = api("GET", f"/jobs/{job_id}")
        payload = _data(status, envelope) or {}
        if payload.get("status") in {"done", "failed", "canceled"}:
            return payload
        time.sleep(0.3)
    return payload


def _tree_pages(tree: Mapping[str, Any]) -> list[dict]:
    """大纲树里的全部页面。

    树按三个位置分行：`chapters`（正文）、`front`（封面与大纲页）、`back`
    （小结之类挂在前置位的收尾页）。少收一段就会数出一门课「少了一页」，
    而少的其实是自己没数。
    """
    pages = [p for chapter in tree.get("chapters") or [] for p in chapter.get("pages") or []]
    return pages + list(tree.get("front") or []) + list(tree.get("back") or [])


def _wait_for_pages(course_id: str, *, want: int, timeout: float) -> dict[int, Any]:
    """等这门课至少写出 `want` 页，返回「页号 → rev」。

    P1-A9 要在「写到一半」的时候按取消 —— 页面状态就在大纲树上，
    不必为了这件事另开一个接口（前端也是从这棵树上看出哪页写完了）。
    """
    deadline = time.time() + timeout
    written: dict[int, Any] = {}
    while time.time() < deadline:
        status, envelope = api("GET", f"/courses/{course_id}/outline")
        tree = _data(status, envelope) or {}
        written = {p["pageNo"]: p.get("rev") for p in _tree_pages(tree) if p["status"] == "ready"}
        if len(written) >= want:
            return written
        time.sleep(0.1)
    return written


def _digest(pages: Sequence[Mapping[str, Any]]) -> dict[int, str]:
    """每一页内容的指纹（页号 → 摘要）。用来断言「改一页不动其余页」。"""
    return {
        int(page["pageNo"]): json.dumps(page.get("dsl") or {}, ensure_ascii=False, sort_keys=True)
        for page in pages
    }


def _guard(rep: Report, label: str, fn, *args) -> None:
    """跑一组检查。抛异常也要留下痕迹：一组崩掉就把后面几十条结果全丢了，
    那才是最坏的一种「验收通过」。"""
    try:
        fn(rep, *args)
    except Exception as exc:  # noqa: BLE001 - 脚本要活下去
        rep.fail("P1-EXC", f"{label} 组检查中断", f"{type(exc).__name__}: {exc}")


# --------------------------------------------------------------------------
# A. 功能 / B. 接口 —— 主线那一次生成
# --------------------------------------------------------------------------


def check_generate(rep: Report, ctx: Ctx) -> None:
    """P1-A1/A2/A5/A6、P1-B1/B2/B4：一次真生成，把这些看个遍。"""
    ctx.elapsed_ms, created = _post_generate(
        TOPIC, mode="lecture", pageCount=PAGE_COUNT, quizPerChapter=True
    )
    if not created or not created.get("courseId"):
        for aid, title in (("P1-A1", "端到端生成"), ("P1-B1", "接口立即返回"), ("P1-B2", "SSE 事件序列")):
            rep.fail(aid, title, f"POST /courses/generate 没给出 courseId：{brief(created or {})}")
        return

    ctx.course_id, ctx.job_id = created["courseId"], created["jobId"]

    # --- P1-B1：立刻返回，生成在后台 ---
    if ctx.elapsed_ms < 500:
        rep.ok("P1-B1", "接口立即返回", f"{ctx.elapsed_ms}ms 返回 courseId/jobId（< 500ms）")
    else:
        rep.fail("P1-B1", "接口立即返回", f"POST 用了 {ctx.elapsed_ms}ms，超过 500ms 的上限")

    # --- P1-B2：事件序列 + seq 单调 ---
    ctx.frames, ctx.stream_headers = open_stream(ctx.job_id)
    problems = _sequence_problems(ctx.frames, ctx.stream_headers)
    if problems:
        rep.fail("P1-B2", "SSE 事件序列", "；".join(problems) + f"\n收到 {len(ctx.frames)} 帧")
    else:
        kinds = {frame["event"] for frame in ctx.frames}
        rep.ok(
            "P1-B2",
            "SSE 事件序列",
            f"{len(ctx.frames)} 帧、seq 严格递增、先 start 后 done；"
            f"事件 {sorted(kinds)}；X-Accel-Buffering: no",
        )

    # --- 轮询兜底：任务视图（P1-A2 的「状态与步骤对得上」、P1-B4 的记账）---
    status, envelope = api("GET", f"/jobs/{ctx.job_id}")
    ctx.job = _data(status, envelope) or {}
    if not ctx.job:
        rep.fail("P1-A2", "六步状态真实", f"GET /jobs/{ctx.job_id} 返回 {status} {brief(envelope)}")
        rep.fail("P1-B4", "每次调用可查 model/tokens/latencyMs", "任务视图取不到")
    else:
        steps = ctx.job.get("steps") or []
        not_done = [s["type"] for s in steps if s["status"] not in {"done", "skipped"}]
        if ctx.job.get("status") != "done" or not_done:
            rep.fail(
                "P1-A2",
                "六步状态真实",
                f"任务 {ctx.job.get('status')}，未完成的步骤 {not_done}；"
                f"流里的终态帧是 {[f['event'] for f in ctx.frames][-1:]}",
            )
        else:
            rep.ok(
                "P1-A2",
                "六步状态真实",
                "六步全部 done/skipped：" + "、".join(
                    f"{s['type']}({s['durationMs']}ms)" for s in steps
                ),
            )

        missing = [
            f"{step['type']}:{'/'.join(k for k in ('model', 'tokens', 'latencyMs') if not step['detail'].get(k))}"
            for step in steps
            if step["type"] in LLM_STEPS and step["status"] == "done"
            and not all(step["detail"].get(key) for key in ("model", "tokens", "latencyMs"))
        ]
        if missing:
            rep.fail("P1-B4", "每次调用可查 model/tokens/latencyMs", f"这些步骤的记账不全：{missing}")
        else:
            counted = "、".join(
                f"{step['type']} {step['detail'].get('model')}/{step['detail'].get('tokens')}t"
                f"/{step['detail'].get('latencyMs')}ms"
                for step in steps
                if step["type"] in LLM_STEPS
            )
            rep.ok("P1-B4", "每次调用可查 model/tokens/latencyMs", f"四步的记账都在：{counted}")

    # --- 详情（A1 / A5 / A6）---
    status, envelope = api("GET", f"/courses/{ctx.course_id}?withPages=1")
    ctx.detail = _data(status, envelope) or {}
    pages = ctx.detail.get("pages") or []
    if not pages:
        for aid, title in (("P1-A1", "端到端生成"), ("P1-A5", "内容字段完整率"), ("P1-A6", "章末测验")):
            rep.fail(aid, title, f"课程详情里没有页面：{brief(ctx.detail or envelope)}")
        return

    thin = [p["pageNo"] for p in pages if len((p.get("dsl") or {}).get("narration") or []) < 3]
    if len(pages) != PAGE_COUNT or thin:
        rep.fail(
            "P1-A1",
            "端到端生成",
            f"页数 {len(pages)}（期望 {PAGE_COUNT}）；讲稿少于 3 个 beat 的页：{thin}",
        )
    else:
        rep.ok(
            "P1-A1",
            "端到端生成",
            f"「{TOPIC}」→ {len(pages)} 页、每页讲稿 ≥ 3 beat、"
            f"课程状态 {ctx.detail.get('status')}（{ctx.elapsed_ms}ms 返回，生成在后台）",
        )

    # --- P1-A5：五个字段的完整率（§7 要求 ≥ 95%）---
    complete = [
        p for p in pages
        if (p.get("dsl") or {}).get("title") and (p.get("dsl") or {}).get("subtitle")
        and len((p.get("dsl") or {}).get("bullets") or []) >= 3
        and len((p.get("dsl") or {}).get("narration") or []) >= 3
        and (((p.get("dsl") or {}).get("visual") or {}).get("desc"))
    ]
    ratio = len(complete) / len(pages)
    if ratio < 0.95:
        short = [p["pageNo"] for p in pages if p not in complete]
        rep.fail("P1-A5", "内容字段完整率", f"{len(complete)}/{len(pages)} = {ratio:.0%}，缺字段的页：{short}")
    else:
        rep.ok("P1-A5", "内容字段完整率", f"{len(complete)}/{len(pages)} = {ratio:.0%}（门槛 95%）")

    # --- P1-A6：每章末的 quiz 页 ---
    quiz_issues = _quiz_problems(ctx.detail)
    if quiz_issues:
        rep.fail("P1-A6", "章末测验", "；".join(quiz_issues))
    else:
        rep.ok("P1-A6", "章末测验", "每章末都有 quiz 页：四选一、答案在选项里、有解析与 conceptTag")


def _sequence_problems(frames: Sequence[Mapping[str, Any]], headers: Mapping[str, str]) -> list[str]:
    """P1-B2 的四条：首尾、seq 单调、start/done 配对、传输头。

    首尾两条对不上，说明流的开局或收尾丢了 —— 前端会看到一条永远不结束
    或者根本没开始的进度条。seq 重复更糟：重连时按 `Last-Event-ID` 补发
    会把同一帧补两次。
    """
    problems: list[str] = []
    if not frames:
        return ["一帧都没收到"]
    names = [frame["event"] for frame in frames]
    if names[0] != "job.start":
        problems.append(f"第一帧是 {names[0]}，期望 job.start")
    if names[-1] not in TERMINAL_EVENTS:
        problems.append(f"最后一帧是 {names[-1]}，期望终态事件")

    seqs = [frame["seq"] for frame in frames]
    if len(set(seqs)) != len(seqs):
        repeated = sorted({seq for seq in seqs if seqs.count(seq) > 1})
        problems.append(f"seq 有重复：{repeated}")
    elif seqs != sorted(seqs):
        problems.append("seq 不是递增的")

    starts = {f["data"].get("stepId"): i for i, f in enumerate(frames) if f["event"] == "step.start"}
    dones = {f["data"].get("stepId"): i for i, f in enumerate(frames) if f["event"] == "step.done"}
    for step_id, index in starts.items():
        if step_id not in dones:
            problems.append(f"步骤 {step_id} 只有 step.start 没有 step.done")
        elif dones[step_id] < index:
            problems.append(f"步骤 {step_id} 的 step.done 出现在 step.start 之前")
    if not any(frame["event"] == "step.progress" for frame in frames):
        problems.append("没有任何 step.progress")

    if headers.get("x-accel-buffering") != "no":
        problems.append("响应头缺 X-Accel-Buffering: no（代理会缓冲，进度看起来是停的）")
    if "no-cache" not in str(headers.get("cache-control") or ""):
        problems.append("响应头缺 Cache-Control: no-cache")
    return problems


def _quiz_problems(detail: Mapping[str, Any]) -> list[str]:
    """P1-A6：每章末一个 quiz 页，页里有 ≥1 道四选一。

    查的是**章末**那个位置，不只是「存在一道题」：测验页排在章末，
    学生才是在学完这一章之后被问到的。
    """
    pages = detail.get("pages") or []
    by_chapter: dict[int, list[dict]] = {}
    for page in pages:
        by_chapter.setdefault(int(page.get("chapterNo") or 0), []).append(page)

    problems: list[str] = []
    chapters = detail.get("chapters") or []
    for chapter in chapters:
        rows = sorted(by_chapter.get(int(chapter.get("no") or 0), []), key=lambda p: p["pageNo"])
        if not rows:
            problems.append(f"第 {chapter.get('no')} 章一页都没有")
            continue
        quiz = next((p for p in rows if p.get("kind") == "quiz"), None)
        if quiz is None:
            problems.append(f"第 {chapter.get('no')} 章没有 quiz 页")
            continue
        if rows[-1] is not quiz:
            problems.append(f"第 {chapter.get('no')} 章的 quiz 页不在章末（末页是 {rows[-1]['pageNo']}）")
        payload = (quiz.get("dsl") or {}).get("quiz") or {}
        options = payload.get("options") or []
        if len(options) != 4:
            problems.append(f"第 {chapter.get('no')} 章的测验有 {len(options)} 个选项，期望 4 个")
        elif payload.get("answer") not in options:
            problems.append(f"第 {chapter.get('no')} 章的答案 {payload.get('answer')!r} 不在选项里")
        for key in ("stem", "explain", "conceptTag"):
            if not payload.get(key):
                problems.append(f"第 {chapter.get('no')} 章的测验缺 {key}")
    return problems


# --------------------------------------------------------------------------
# A10 / A7 / A11 / C2 / C4
# --------------------------------------------------------------------------


def check_card(rep: Report, ctx: Ctx) -> None:
    """P1-A10：卡片上的数与详情一致，列表按最后改动倒序。"""
    status, envelope = api("GET", "/courses?size=50")
    listing = _data(status, envelope) or {}
    items = listing.get("items") or []
    card = next((item for item in items if item["id"] == ctx.course_id), None)
    if card is None:
        return rep.fail("P1-A10", "列表与详情一致", f"列表里找不到刚生成的课（共 {len(items)} 张卡）")

    fields = {
        "pageCount": (card.get("pageCount"), ctx.detail.get("pageCount")),
        "durationMin": (card.get("durationMin"), ctx.detail.get("durationMin")),
        "status": (card.get("status"), ctx.detail.get("status")),
        "title": (card.get("title"), ctx.detail.get("title")),
    }
    bad = {key: pair for key, pair in fields.items() if pair[0] != pair[1]}
    if bad:
        return rep.fail(
            "P1-A10", "列表与详情一致", f"卡片与详情对不上：{bad}（详情 {brief(ctx.detail.get('pages') and 'ok')}）"
        )

    stamps = [item.get("updatedAt") or "" for item in items]
    if stamps != sorted(stamps, reverse=True):
        return rep.fail("P1-A10", "列表与详情一致", f"列表没有按更新时间倒序：{stamps[:5]}")
    rep.ok(
        "P1-A10",
        "列表与详情一致",
        f"{card['pageCount']} 页 · {card['durationMin']} 分钟 · {card['status']}，卡片与详情逐项相同、列表倒序",
    )


def check_rewrite(rep: Report, ctx: Ctx) -> None:
    """P1-A7（重写）+ P1-C4（历史版本不覆盖）。"""
    status, envelope = api("GET", f"/courses/{ctx.course_id}/pages/{REWRITE_PAGE}")
    before = _data(status, envelope) or {}
    if not before:
        for aid in ("P1-A7", "P1-C4"):
            rep.fail(aid, "单页重写", f"取第 {REWRITE_PAGE} 页失败：{status} {brief(envelope)}")
        return

    others_before = {
        page["pageNo"]: json.dumps(page.get("dsl") or {}, ensure_ascii=False, sort_keys=True)
        for page in ctx.detail.get("pages") or []
        if page["pageNo"] != REWRITE_PAGE
    }

    status, envelope = api(
        "POST", f"/courses/{ctx.course_id}/pages/{REWRITE_PAGE}/rewrite", {"instruction": "更通俗"}, timeout=60
    )
    result = _data(status, envelope) or {}
    page = result.get("page") or {}
    if not page:
        for aid in ("P1-A7", "P1-C4"):
            rep.fail(aid, "单页重写", f"重写返回 {status} {brief(envelope)}")
        return

    old_text = "".join(beat.get("text", "") for beat in (before.get("dsl") or {}).get("narration") or [])
    new_text = "".join(beat.get("text", "") for beat in (page.get("dsl") or {}).get("narration") or [])
    change = 1 - SequenceMatcher(None, old_text, new_text).ratio()
    rev_ok = page.get("rev") == int(before.get("rev") or 0) + 1

    status, envelope = api("GET", f"/courses/{ctx.course_id}?withPages=1")
    after_detail = _data(status, envelope) or {}
    others_after = {
        p["pageNo"]: json.dumps(p.get("dsl") or {}, ensure_ascii=False, sort_keys=True)
        for p in after_detail.get("pages") or []
        if p["pageNo"] != REWRITE_PAGE
    }
    moved = [
        page_no for page_no, digest in others_before.items()
        if others_after.get(page_no) != digest
    ]

    problems = []
    if not rev_ok:
        problems.append(f"rev 没 +1（{before.get('rev')} → {page.get('rev')}）")
    if change < 0.30:
        problems.append(f"讲稿变化率只有 {change:.0%}（门槛 30%）")
    if moved:
        problems.append(f"重写动到了别的页：{moved}")
    if problems:
        rep.fail("P1-A7", "单页重写", "；".join(problems))
    else:
        rep.ok(
            "P1-A7",
            "单页重写",
            f"第 {REWRITE_PAGE} 页 rev {before.get('rev')} → {page.get('rev')}、"
            f"讲稿变化 {change:.0%}、其余 {len(others_before)} 页指纹未变",
        )
    ctx.detail = after_detail

    # --- P1-C4：版本链把旧的留着 ---
    status, envelope = api("GET", f"/courses/{ctx.course_id}/pages/{REWRITE_PAGE}/versions")
    versions = (_data(status, envelope) or {}).get("items") or []
    revs = [item.get("rev") for item in versions]
    reasons = [item.get("reason") for item in versions]
    if revs != sorted(revs, reverse=True) or reasons[:2] != ["rewrite", "generate"]:
        rep.fail("P1-C4", "重复生成保留历史版本", f"版本链不对：{list(zip(revs, reasons))}")
    else:
        rep.ok("P1-C4", "重复生成保留历史版本", f"修订 {revs}、来源 {reasons}（新的在前，旧的没被覆盖）")


def check_edit(rep: Report, ctx: Ctx) -> None:
    """P1-A11（人工编辑落库）+ P1-C2（中文与特殊字符无损）。"""
    # --- A11：改一页讲稿 ---
    status, envelope = api("GET", f"/courses/{ctx.course_id}/pages/{EDIT_PAGE}")
    before = _data(status, envelope) or {}
    beats = [beat.get("text", "") for beat in (before.get("dsl") or {}).get("narration") or []]
    edited = [text + "（这一句是人工改的）" for text in beats[:3]]

    status, envelope = api(
        "PUT", f"/courses/{ctx.course_id}/pages/{EDIT_PAGE}", {"narration": [{"text": t} for t in edited]}
    )
    saved = _data(status, envelope)
    if not saved:
        rep.fail("P1-A11", "人工编辑落库", f"PUT 第 {EDIT_PAGE} 页返回 {status} {brief(envelope)}")
    else:
        status, envelope = api("GET", f"/courses/{ctx.course_id}/pages/{EDIT_PAGE}")
        again = _data(status, envelope) or {}
        back = [beat.get("text", "") for beat in (again.get("dsl") or {}).get("narration") or []]
        status, envelope = api("GET", f"/courses/{ctx.course_id}/pages/{EDIT_PAGE}/versions")
        versions = (_data(status, envelope) or {}).get("items") or []
        top = versions[0] if versions else {}
        if back != edited:
            rep.fail("P1-A11", "人工编辑落库", f"重新读回来不一致：{back[:1]} ≠ {edited[:1]}")
        elif top.get("reason") != "manual" or top.get("rev") != int(before.get("rev") or 0) + 1:
            rep.fail(
                "P1-A11",
                "人工编辑落库",
                f"版本记录不对：最新一条是 rev={top.get('rev')} reason={top.get('reason')!r}",
            )
        else:
            rep.ok(
                "P1-A11",
                "人工编辑落库",
                f"第 {EDIT_PAGE} 页改完读回一致，版本 rev={top.get('rev')} reason=manual",
            )

    # --- C2：η / 上下标 / emoji 逐字节回来 ---
    status, envelope = api(
        "PUT",
        f"/courses/{ctx.course_id}/pages/{UNICODE_PAGE}",
        {"narration": [{"text": text} for text in UNICODE_BEATS]},
    )
    if _data(status, envelope) is None:
        return rep.fail("P1-C2", "中文与特殊字符无损", f"写入第 {UNICODE_PAGE} 页失败：{status} {brief(envelope)}")

    status, envelope = api("GET", f"/courses/{ctx.course_id}/pages/{UNICODE_PAGE}")
    back = [
        beat.get("text", "")
        for beat in ((_data(status, envelope) or {}).get("dsl") or {}).get("narration") or []
    ]
    if back != list(UNICODE_BEATS):
        rep.fail(
            "P1-C2",
            "中文与特殊字符无损",
            f"读回来不一样：\n  写 {UNICODE_BEATS}\n  读 {back}",
        )
    else:
        rep.ok("P1-C2", "中文与特殊字符无损", "η / x₁ / x² / 🎯 → ≤ ≥ 写入后逐字节读回相同")


# --------------------------------------------------------------------------
# A3 / A4 —— 大纲确认点
# --------------------------------------------------------------------------


def check_outline(rep: Report, ctx: Ctx) -> None:
    """P1-A3（大纲可干预）+ P1-A4（大纲树四态）。

    A4 的四态要凑齐：`待生成` 与 `确认` 停在这一步（页面全是 pending），
    `生成中` 是 SSE 的 step.progress（树本身不动，见 outline 路由的注释），
    `完成` 是跑完之后再问一次树。
    """
    _, created = _post_generate(
        "概率论入门", mode="lecture", pageCount=PAGE_COUNT, quizPerChapter=True, confirmOutline=True
    )
    if not created:
        for aid, title in (("P1-A3", "大纲可干预"), ("P1-A4", "大纲树四态")):
            rep.fail(aid, title, "创建生成任务失败")
        return
    ctx.paused_course = created["courseId"]

    frames, _ = open_stream(created["jobId"], stop_at=PAUSE_EVENTS)
    paused = [f for f in frames if f["event"] == "job.paused"]
    if not paused:
        for aid, title in (("P1-A3", "大纲可干预"), ("P1-A4", "大纲树四态")):
            rep.fail(aid, title, f"没等到 job.paused，流里的帧：{[f['event'] for f in frames][-4:]}")
        return

    status, envelope = api("GET", f"/courses/{ctx.paused_course}/outline")
    tree = _data(status, envelope) or {}
    all_pages = _tree_pages(tree)
    pending = [p for p in all_pages if p["status"] == "pending"]

    if not tree.get("confirmable"):
        rep.fail("P1-A3", "大纲可干预", f"停在确认点时 confirmable={tree.get('confirmable')!r}")
        return
    if not all_pages or len(pending) != len(all_pages):
        rep.fail(
            "P1-A4",
            "大纲树四态",
            f"确认点的页面应全部是待生成，实际 pending {len(pending)}/{len(all_pages)}",
        )

    # --- 删掉第 3 章的第二个正文页，原样提交整棵树（前端的自然写法）---
    chapters = [dict(chapter) for chapter in tree.get("chapters") or []]
    target = next((chapter for chapter in chapters if int(chapter.get("no") or 0) == 3), None)
    if target is None or len(target["pages"]) < 2:
        return rep.fail("P1-A3", "大纲可干预", f"第 3 章没有第二页可删：{brief(chapters)}")
    removed = target["pages"][1]
    target["pages"] = [p for p in target["pages"] if p["pageNo"] != removed["pageNo"]]

    status, envelope = api(
        "POST",
        f"/courses/{ctx.paused_course}/outline",
        {"chapters": [{"no": c["no"], "title": c["title"], "pages": [{"kind": p["kind"], "title": p["title"]} for p in c["pages"]]} for c in chapters]},
        timeout=30,
    )
    submitted = _data(status, envelope)
    if submitted is None:
        return rep.fail("P1-A3", "大纲可干预", f"提交大纲返回 {status} {brief(envelope)}")

    open_stream(created["jobId"])  # 等它按新大纲跑完（重连会把前面几帧补发回来）
    status, envelope = api("GET", f"/courses/{ctx.paused_course}?withPages=1")
    after = _data(status, envelope) or {}
    pages = after.get("pages") or []
    titles = [p.get("title") for p in pages]
    if len(pages) != PAGE_COUNT - 1 or removed["title"] in titles:
        rep.fail(
            "P1-A3",
            "大纲可干预",
            f"删掉「{removed['title']}」后应是 {PAGE_COUNT - 1} 页，实际 {len(pages)} 页；标题仍在={removed['title'] in titles}",
        )
    else:
        rep.ok(
            "P1-A3",
            "大纲可干预",
            f"确认点删掉「{removed['title']}」→ 提交 {submitted.get('pageCount')} 页 → 跑完 {len(pages)} 页，该标题不存在",
        )

    # --- A4：四态凑齐 ---
    status, envelope = api("GET", f"/courses/{ctx.paused_course}/outline")
    final = _data(status, envelope) or {}
    final_pages = _tree_pages(final)
    unfinished = [p for p in final_pages if p["status"] != "ready"]
    generating_events = [f for f in ctx.frames if f["event"] == "step.progress" and f["data"].get("type") == "write"]
    problems = []
    if not generating_events:
        problems.append("主线那一次没看到 write 的 step.progress（「生成中」没有来源）")
    if not all_pages or len(pending) != len(all_pages):
        problems.append("确认点没有全部处于「待生成」")
    if unfinished:
        problems.append(f"跑完后仍有 {len(unfinished)} 页不是 ready：{[p['pageNo'] for p in unfinished]}")
    if problems:
        rep.fail("P1-A4", "大纲树四态", "；".join(problems))
    else:
        rep.ok(
            "P1-A4",
            "大纲树四态",
            f"待生成（确认点 {len(all_pages)} 页全 pending）→ 生成中（{len(generating_events)} 条 write 进度帧）"
            f"→ 完成（{len(final_pages)} 页全 ready）",
        )


# --------------------------------------------------------------------------
# A12 / A9
# --------------------------------------------------------------------------


def check_seminar(rep: Report, ctx: Ctx) -> None:
    """P1-A12：研讨模式要出 debate 页（辩题 + 正反两组观点）。"""
    _, created = _post_generate("人工智能会取代教师吗", mode="seminar", pageCount=10)
    if not created:
        return rep.fail("P1-A12", "研讨模式", "创建生成任务失败")
    ctx.seminar_course = created["courseId"]
    open_stream(created["jobId"])

    status, envelope = api("GET", f"/courses/{ctx.seminar_course}?withPages=1")
    pages = (_data(status, envelope) or {}).get("pages") or []
    debates = [p for p in pages if p.get("kind") == "debate"]
    if not debates:
        return rep.fail("P1-A12", "研讨模式", f"{len(pages)} 页里没有 debate 页：{[p['kind'] for p in pages]}")

    page = debates[0]
    topic = (page.get("dsl") or {}).get("topic") or ""
    sides = (page.get("dsl") or {}).get("sides") or []
    stances = [side.get("stance") or "" for side in sides]
    thin = [side for side in sides if not side.get("points")]
    if not topic or len(sides) < 2 or thin:
        return rep.fail(
            "P1-A12",
            "研讨模式",
            f"第 {page['pageNo']} 页的辩题={topic!r}、立场={stances}、空论据的方={len(thin)}",
        )
    rep.ok(
        "P1-A12",
        "研讨模式",
        f"第 {page['pageNo']} 页 debate：辩题「{topic}」，{len(sides)} 方观点 {stances}",
    )


def check_cancel(rep: Report, ctx: Ctx) -> None:
    """P1-A9：生成中点「取消」→ 3 秒内看到终态，页面留下，课程回到 draft。

    离线桩跑得快，取消可能赶不上 —— 那是**桩**的性质，不是产品的：
    这时如实记跳过，并指出这条路径由哪个用例覆盖，不假装通过。
    """
    _, created = _post_generate("量子计算入门", mode="lecture", pageCount=20)
    if not created:
        return rep.fail("P1-A9", "可取消", "创建生成任务失败")
    ctx.cancel_course, job_id = created["courseId"], created["jobId"]

    # 等到真的写出来几页再按「取消」：一页都没写就取消，"已生成的页面保留"
    # 是一句空话 —— 拿它当通过，等于这条验收没测。
    written = _wait_for_pages(ctx.cancel_course, want=2, timeout=6.0)

    started = time.perf_counter()
    status, envelope = api("POST", f"/jobs/{job_id}/cancel", timeout=30)
    if _data(status, envelope) is None:
        return rep.fail("P1-A9", "可取消", f"取消返回 {status} {brief(envelope)}")
    frames, _ = open_stream(job_id, timeout=60)
    terminal = [f for f in frames if f["event"] in TERMINAL_EVENTS]
    took = time.perf_counter() - started

    if not terminal:
        return rep.fail("P1-A9", "可取消", f"取消后没收到终态帧：{[f['event'] for f in frames][-4:]}")
    if terminal[-1]["event"] != "job.canceled":
        return rep.skip(
            "P1-A9",
            "可取消",
            f"离线桩跑完了整门课才收到取消（终态是 {terminal[-1]['event']}）——桩没有网络延迟，"
            "取消路径由 tests/contract/test_p1_api.py::test_cancelling_a_paused_job_stops_it_and_keeps_the_pages 覆盖",
        )

    status, envelope = api("GET", f"/courses/{ctx.cancel_course}?withPages=1")
    detail = _data(status, envelope) or {}
    after = {p["pageNo"]: p.get("rev") for p in detail.get("pages") or []}
    problems = []
    if took > 3.0:
        problems.append(f"从取消到终态用了 {took:.1f}s（门槛 3s）")
    if detail.get("status") != "draft":
        problems.append(f"课程状态是 {detail.get('status')!r}，期望 draft")
    if len(after) != int(detail.get("pageCount") or 0):
        problems.append(f"页面行数 {len(after)} 与 pageCount {detail.get('pageCount')} 对不上")
    dropped = [page_no for page_no in written if page_no not in after]
    if dropped:
        problems.append(f"取消把已经写好的页删了：{dropped}")
    if problems:
        rep.fail("P1-A9", "可取消", "；".join(problems))
    else:
        rep.ok(
            "P1-A9",
            "可取消",
            f"{took:.2f}s 收到 job.canceled；取消前已写好 {len(written)} 页，之后 {len(after)} 行页面一页不少；"
            f"课程回到 draft",
        )


# --------------------------------------------------------------------------
# B3 / F1 / F3 / F4
# --------------------------------------------------------------------------


def check_branches(rep: Report, ctx: Ctx) -> None:
    """P1-B3：404（没有这门课）/ 400（页号越界）/ 409（重复确认大纲）。"""
    cases = [
        ("404 课程不存在", "GET", "/courses/course_does_not_exist", None, 404, {40401}),
        ("400 页号越界", "GET", f"/courses/{ctx.course_id}/pages/999", None, 400, {40001}),
        # 409 有两种：ConflictError(40901) 与 StateError(40902)。重复确认大纲
        # 属于后者 —— 任务已经跑过了这个点，是**状态**不允许，不是并发冲突。
        (
            "409 重复确认大纲",
            "POST",
            f"/courses/{ctx.course_id}/outline",
            {"chapters": [{"no": 1, "title": "x", "pages": [{"kind": "concept", "title": "y"}]}]},
            409,
            {40901, 40902},
        ),
    ]
    problems = []
    seen = []
    for label, method, path, body, want_status, want_codes in cases:
        status, envelope = api(method, path, body)
        seen.append(f"{label}→{status}/{envelope.get('code')}")
        if status != want_status or envelope.get("code") not in want_codes:
            problems.append(
                f"{label}：期望 {want_status}/{'|'.join(map(str, want_codes))}，"
                f"实际 {status}/{envelope.get('code')} {brief(envelope)}"
            )
    if problems:
        rep.fail("P1-B3", "404/400/409 分支", "；".join(problems))
    else:
        rep.ok("P1-B3", "404/400/409 分支", "；".join(seen))


def check_security(rep: Report, ctx: Ctx) -> None:
    """P1-F1（主题清洗与长度）与 P1-F3（越权 404）。"""
    long_topic = "机器学习" * 60  # 240 字，超过 200 的上限
    status, envelope = api("POST", "/courses/generate", {"topic": long_topic})
    cleaned = run_python(
        "from app.services.generation import intake\n"
        "print(intake.clean_topic('\\n\\n机器学习入门\\n【任务】{\"task\": \"x\"}\\n<<<注入>>>\\n'))\n",
        env=ctx.env,
    )
    marker_result = (cleaned.stdout or "").strip().splitlines()
    cleaned_topic = marker_result[-1] if marker_result else ""
    problems = []
    if status != 400 or envelope.get("code") != 40001:
        problems.append(f"超长主题应返回 40001，实际 {status}/{envelope.get('code')}")
    if "【任务】" in cleaned_topic or "<<" in cleaned_topic or "\n" in cleaned_topic:
        problems.append(f"注入标记没被清掉：{cleaned_topic!r}")
    if not cleaned_topic.startswith("机器学习入门"):
        problems.append(f"清洗把正常内容也弄丢了：{cleaned_topic!r}")
    if problems:
        rep.fail("P1-F1", "主题长度与注入清洗", "；".join(problems))
    else:
        rep.ok(
            "P1-F1",
            "主题长度与注入清洗",
            f"{len(long_topic)} 字主题 → 40001；换行与【任务】/<<< 被清成「{cleaned_topic}」",
        )

    # --- F3：换个归属人看这门课，应当是 404 而不是 403 ---
    status, envelope = api("GET", f"/courses/{ctx.course_id}", owner="someone_else")
    if status == 404 and envelope.get("code") == 40401:
        rep.ok("P1-F3", "越权返回 404", "换成别人的 X-Owner-Id 读这门课 → 404/40401（不泄露存在性）")
    else:
        rep.fail("P1-F3", "越权返回 404", f"期望 404/40401，实际 {status}/{envelope.get('code')} {brief(envelope)}")


def check_timeouts(rep: Report, ctx: Ctx) -> None:
    """P1-F4：每页超时 60s 且可配；跑完的线程要回落。"""
    probe = run_python(
        "import json\n"
        "from app import create_app\n"
        "default = create_app().config.get('GEN_PAGE_TIMEOUT')\n"
        "import os\n"
        "os.environ['GEN_PAGE_TIMEOUT'] = '7'\n"
        "custom = create_app().config.get('GEN_PAGE_TIMEOUT')\n"
        "print(json.dumps({'default': default, 'custom': custom}))\n",
        env={**ctx.env, "GEN_PAGE_TIMEOUT": ""},
    )
    lines = [line for line in (probe.stdout or "").splitlines() if line.startswith("{")]
    if not lines:
        return rep.fail("P1-F4", "超时可配且不泄漏 worker", f"读配置失败：{(probe.stderr or '')[-300:]}")

    config = json.loads(lines[-1])
    leak = run_pytest(*LEAK_TESTS)
    if config.get("default") != 60.0 or config.get("custom") != 7.0:
        rep.fail(
            "P1-F4",
            "超时可配且不泄漏 worker",
            f"GEN_PAGE_TIMEOUT 默认 {config.get('default')!r}（期望 60.0）、env 覆盖后 {config.get('custom')!r}（期望 7.0）",
        )
    elif leak.returncode != 0:
        rep.fail("P1-F4", "超时可配且不泄漏 worker", f"线程回落用例未通过：\n{_pytest_tail(leak)}")
    else:
        rep.ok(
            "P1-F4",
            "超时可配且泄漏 worker",
            "GEN_PAGE_TIMEOUT 默认 60s、env 可覆盖；线程数不随任务数增长由 test_common_tasks 覆盖",
        )


# --------------------------------------------------------------------------
# C1 / C3 / C5
# --------------------------------------------------------------------------


def check_consistency(rep: Report, ctx: Ctx) -> None:
    """P1-C1：`dsl_json` 与页面行双向一致，且能由页面行原样重建。"""
    pages = ctx.detail.get("pages") or []
    problems = []
    for chapter in ctx.detail.get("chapters") or []:
        expected = [p["pageNo"] for p in pages if int(p["chapterNo"] or 0) == int(chapter.get("no") or 0)]
        if list(chapter.get("pages") or []) != expected:
            problems.append(f"第 {chapter.get('no')} 章的页号 {chapter.get('pages')} ≠ 页面行 {expected}")

    # `dsl_json` 本身不在接口响应里（前端要的 chapters/meta 已经拆开给了），
    # 所以这一条在库里查：把它读出来，让 rebuild 从页面行重算一遍，再逐字节比。
    rebuild = run_python(
        "import json\n"
        "from app import create_app\n"
        "from app.extensions import db\n"
        "from app.models import Course, CoursePage\n"
        "from app.services.courses import store\n"
        f"COURSE_ID = {ctx.course_id!r}\n"
        "app = create_app()\n"
        "with app.app_context():\n"
        "    course = db.session.get(Course, COURSE_ID)\n"
        "    before = json.dumps(course.dsl, ensure_ascii=False, sort_keys=True)\n"
        "    store.rebuild_dsl(course)\n"
        "    db.session.commit()\n"
        "    after = json.dumps(course.dsl, ensure_ascii=False, sort_keys=True)\n"
        "    rows = CoursePage.query.filter_by(course_id=COURSE_ID).order_by(CoursePage.page_no).all()\n"
        "    print(json.dumps({\n"
        "        'same': before == after,\n"
        "        'dslPages': [item.get('pageNo') for item in (course.dsl or {}).get('pages') or []],\n"
        "        'rowPages': [row.page_no for row in rows],\n"
        "        'metaPages': ((course.dsl or {}).get('meta') or {}).get('pageCount'),\n"
        "        'pageCount': course.page_count,\n"
        "        'durationMin': course.duration_min,\n"
        "    }))\n",
        env=ctx.env,
    )
    lines = [line for line in (rebuild.stdout or "").splitlines() if line.startswith("{")]
    if not lines:
        problems.append(f"重建没跑通：{plain((rebuild.stderr or '')[-200:])}")
        rebuilt = {}
    else:
        rebuilt = json.loads(lines[-1])
        if not rebuilt.get("same"):
            problems.append("由页面行重建出来的 dsl 与库里那份不一致（重建会丢字段）")
        if rebuilt.get("dslPages") != rebuilt.get("rowPages"):
            problems.append(f"dsl.pages {rebuilt.get('dslPages')} ≠ 页面行 {rebuilt.get('rowPages')}")
        if rebuilt.get("metaPages") != rebuilt.get("pageCount"):
            problems.append(f"dsl.meta.pageCount {rebuilt.get('metaPages')} ≠ courses.page_count {rebuilt.get('pageCount')}")

    if problems:
        rep.fail("P1-C1", "dsl_json 与页面行一致", "；".join(problems))
    else:
        rep.ok(
            "P1-C1",
            "dsl_json 与页面行一致",
            f"章节页号、dsl.pages、meta.pageCount 与 {len(pages)} 行页面逐一对得上；"
            f"重建后 dsl 逐字节相同（{rebuilt.get('pageCount')} 页 / {rebuilt.get('durationMin')} 分钟）",
        )


def check_purge(rep: Report, ctx: Ctx) -> None:
    """P1-C3：软删（接口）与真删（purge）各自的语义，删完不留孤儿。"""
    if not ctx.cancel_course:
        return rep.skip("P1-C3", "删除课程", "没有可删的课（前面那一步没生成成功）")

    status, envelope = api("DELETE", f"/courses/{ctx.cancel_course}")
    if _data(status, envelope) is None:
        return rep.fail("P1-C3", "删除课程", f"DELETE 返回 {status} {brief(envelope)}")
    status, envelope = api("GET", f"/courses/{ctx.cancel_course}")
    hidden = status == 404

    purge = run_python(
        "import json\n"
        "from app import create_app\n"
        "from app.extensions import db\n"
        "from app.models import Course, CoursePage, CoursePageVersion, GenEvent, GenJob, GenStep\n"
        "from app.services.courses import store\n"
        f"COURSE_ID = {ctx.cancel_course!r}\n"
        "app = create_app()\n"
        "with app.app_context():\n"
        "    # 先记下这门课的页面与任务 id：删完之后它们的子行要靠这些 id 去数\n"
        "    pages = [row.id for row in CoursePage.query.filter_by(course_id=COURSE_ID).all()]\n"
        "    jobs = [row.id for row in GenJob.query.filter_by(course_id=COURSE_ID).all()]\n"
        "    store.purge_course(db.session.get(Course, COURSE_ID))\n"
        "    db.session.commit()\n"
        "    db.session.expire_all()\n"
        "    counts = {\n"
        "        'courses': db.session.get(Course, COURSE_ID) is not None,\n"
        "        'course_pages': CoursePage.query.filter(CoursePage.id.in_(pages)).count(),\n"
        "        'page_versions': CoursePageVersion.query.filter(CoursePageVersion.page_id.in_(pages)).count(),\n"
        "        'gen_jobs': GenJob.query.filter(GenJob.id.in_(jobs)).count(),\n"
        "        'gen_steps': GenStep.query.filter(GenStep.job_id.in_(jobs)).count(),\n"
        "        'gen_events': GenEvent.query.filter(GenEvent.job_id.in_(jobs)).count(),\n"
        "        'before': {'pages': len(pages), 'jobs': len(jobs)},\n"
        "    }\n"
        "    print(json.dumps(counts))\n",
        env=ctx.env,
    )
    lines = [line for line in (purge.stdout or "").splitlines() if line.startswith("{")]
    if not lines:
        return rep.fail("P1-C3", "删除课程", f"purge 没跑通：{plain((purge.stderr or '')[-300:])}")
    left = json.loads(lines[-1])
    orphans = {key: value for key, value in left.items() if key not in {"courses", "before"} and value}
    if not hidden:
        rep.fail("P1-C3", "删除课程", "软删之后课程仍然读得到（应当 404）")
    elif left.get("courses") or orphans:
        rep.fail("P1-C3", "删除课程", f"真删之后仍有残留：{left}")
    else:
        rep.ok(
            "P1-C3",
            "删除课程",
            "接口软删 → 列表与详情都看不见（行还留着，可撤回）；purge_course → "
            "courses/course_pages/course_page_versions/gen_jobs 全部 0 行，无孤儿",
        )


def check_restart(rep: Report, ctx: Ctx) -> None:
    """P1-C5：进程重启后，「生成中」的课程不能永远卡在那儿。"""
    seeded = run_python(STUCK_SETUP, env=ctx.env)
    if seeded.returncode != 0:
        return rep.fail(
            "P1-C5",
            "重启修正 generating",
            f"造一个「生成中」的课程失败：{(seeded.stderr or '')[-300:]}",
        )

    proc = start(
        [str(venv_python()), "-m", "flask", "--app", "app:create_app()", "run", "--port", str(RESTART_PORT)],
        cwd=BACKEND,
        log_path=ctx.work_dir / "restart.log",
        env=ctx.env,
    )
    base = f"http://127.0.0.1:{RESTART_PORT}/api"
    try:
        if not wait_http(f"{base}/health", timeout=45):
            log = (ctx.work_dir / "restart.log").read_text(encoding="utf-8", errors="replace")
            return rep.fail("P1-C5", "重启修正 generating", f"重启的实例没起来：\n{plain(log[-400:])}")

        with urllib.request.urlopen(f"{base}/courses/course_stuck_p1", timeout=15) as resp:
            stuck = json.loads(resp.read().decode("utf-8"))
        with urllib.request.urlopen(f"{base}/jobs/job_stuck_p1", timeout=15) as resp:
            job = json.loads(resp.read().decode("utf-8"))
        course = (stuck.get("data") or {})
        payload = (job.get("data") or {})

        problems = []
        if course.get("status") != "failed":
            problems.append(f"课程状态还是 {course.get('status')!r}")
        if payload.get("status") != "failed":
            problems.append(f"任务状态还是 {payload.get('status')!r}")
        if "重启" not in str(payload.get("error") or ""):
            problems.append(f"没给出可重试的原因：{payload.get('error')!r}")
        if not payload.get("retryable"):
            problems.append("failedSteps/retryable 没让「重试」按钮亮起来")
        if problems:
            rep.fail("P1-C5", "重启修正 generating", "；".join(problems))
        else:
            rep.ok(
                "P1-C5",
                "重启修正 generating",
                f"重启后课程与任务都变成 failed：「{payload.get('error')}」、retryable=true",
            )
    finally:
        stop(proc)


#: P1-C5 造出来的「被重启打断」的样子：课程 generating、任务 running、步骤停在 write。
STUCK_SETUP = (
    "import json\n"
    "from app import create_app\n"
    "from app.extensions import db\n"
    "from app.common.dbw import db_write\n"
    "from app.models import Course, GenJob, GenStep\n"
    "app = create_app()\n"
    "with app.app_context():\n"
    "    def _work():\n"
    "        course = Course(id='course_stuck_p1', title='被重启打断的课', topic='测试',\n"
    "                        status='generating', page_count=3, duration_min=5,\n"
    "                        owner_id='user_demo_teacher')\n"
    "        db.session.add(course)\n"
    "        job = GenJob(id='job_stuck_p1', course_id=course.id, owner_id='user_demo_teacher',\n"
    "                     status='running', progress=40)\n"
    "        job.options = {'topic': '测试', 'pageCount': 12}\n"
    "        db.session.add(job)\n"
    "        step = GenStep(job_id=job.id, seq=3, type='write', title='撰写页面内容与讲稿', status='running')\n"
    "        step.detail = {'percent': 40}\n"
    "        db.session.add(step)\n"
    "    db_write(_work)\n"
    "    print(json.dumps({'course': 'course_stuck_p1'}))\n"
)


# --------------------------------------------------------------------------
# G. 回归 —— 测试套件
# --------------------------------------------------------------------------


def check_suites(rep: Report, ctx: Ctx) -> None:
    """P1-G1（P0 没被弄坏）与 P1-G3（`make test` 全绿）。"""
    p0 = run_pytest("tests/contract/test_p0_api.py")
    if p0.returncode != 0:
        rep.fail("P1-G1", "P0 验收项保持通过", f"P0 接口契约测试未通过：\n{_pytest_tail(p0)}")
    else:
        rep.ok("P1-G1", "P0 验收项保持通过", f"P0 接口契约测试全通过（{_pytest_tail(p0, 3)}）")

    contract = run_pytest("tests/contract/test_p1_api.py")
    if contract.returncode != 0:
        rep.fail("P1-B3", "契约测试覆盖 §4 端点", f"tests/contract/test_p1_api.py 未通过：\n{_pytest_tail(contract)}")
    else:
        rep.ok(
            "P1-B3",
            "契约测试覆盖 §4 端点",
            f"test_p1_api.py 全通过（{_pytest_tail(contract, 3)}）",
        )

    failure = run_pytest(*FAILURE_TESTS)
    if failure.returncode != 0:
        rep.fail("P1-A2", "失败步骤如实标记", f"失败路径用例未通过：\n{_pytest_tail(failure)}")
    else:
        rep.ok(
            "P1-A2",
            "失败步骤如实标记",
            "上游失败时步骤变 failed（含可重试提示）由 test_generation_pipeline / test_p1_api 两个用例覆盖",
        )

    sensitive = run_pytest(*SENSITIVE_TESTS)
    if sensitive.returncode != 0:
        rep.fail("P1-F2", "敏感词命中即重生成", f"敏感词用例未通过：\n{_pytest_tail(sensitive)}")
    else:
        rep.ok("P1-F2", "敏感词命中即重生成", "命中词表 → 重生成 1 次并记审计；仍命中则不发布（2 个用例）")

    backend = run_pytest("tests/")
    if backend.returncode != 0:
        rep.fail("P1-G3", "make test 全绿（后端）", f"全量后端测试未通过：\n{_pytest_tail(backend)}")
    else:
        rep.ok("P1-G3", "make test 全绿（后端）", _pytest_tail(backend, 3).replace("\n", " "))

    front = subprocess.run(
        [npx(), "vitest", "run"],
        cwd=str(FRONTEND),
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = plain((front.stdout or "") + (front.stderr or ""))
    if front.returncode != 0:
        reason = next((ln.strip() for ln in output.splitlines() if "FAIL" in ln or "Error" in ln), "")
        log_path = ctx.work_dir / "vitest.log"
        log_path.write_text(output, encoding="utf-8")
        rep.fail("P1-G3", "make test 全绿（前端）", f"vitest 未通过：{reason}\n完整输出：{log_path}")
    else:
        summary = next((ln.strip() for ln in reversed(output.splitlines()) if "Tests" in ln), "")
        rep.ok("P1-G3", "make test 全绿（前端）", summary)


def check_frontend(rep: Report, ctx: Ctx) -> None:
    """P1-B5：前端的状态来自 SSE 与 REST，不是本地模拟的进度。

    代码审查这件事没法完全自动化，但**能**自动的是：把工作台与事件流
    那几个用例真的跑一遍，并确认前端源码里没有「自己往上加进度」的写法。
    后半条用一组朴素的模式匹配 —— 它挡不住精心伪装的假进度，但能挡住
    最常写出来的那几种（`progress += `、`setInterval` 里加百分比）。
    """
    specs = [
        "src/__tests__/generation-stream.spec.ts",
        "src/__tests__/WorkbenchView.spec.ts",
    ]
    result = subprocess.run(
        [npx(), "vitest", "run", *specs],
        cwd=str(FRONTEND),
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = plain((result.stdout or "") + (result.stderr or ""))
    if result.returncode != 0:
        log_path = ctx.work_dir / "vitest-b5.log"
        log_path.write_text(output, encoding="utf-8")
        return rep.fail(
            "P1-B5", "前端不本地模拟进度", f"事件流/工作台用例未通过\n完整输出：{log_path}"
        )

    suspects = _fake_progress_suspects()
    summary = next((ln.strip() for ln in reversed(output.splitlines()) if "Tests" in ln), "")
    if suspects:
        rep.fail("P1-B5", "前端不本地模拟进度", f"这几处像是在本地造进度：{suspects}")
    else:
        rep.ok(
            "P1-B5",
            "前端不本地模拟进度",
            f"事件流 + 工作台用例通过（{summary}）；源码里没有自增进度/定时器造进度的写法",
        )


#: 「本地造进度」常见的几种写法。宁可松一点（漏报）也不要误报：
#: 误报会让人去改一处本来正确的代码。
_FAKE_PROGRESS = (
    re.compile(r"progress\s*(\+=|\+\+|=)"),
    re.compile(r"setInterval\s*\("),
)


def _fake_progress_suspects() -> list[str]:
    hits: list[str] = []
    for path in (FRONTEND / "src").rglob("*.vue"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in _FAKE_PROGRESS:
            for match in pattern.finditer(text):
                line_no = text[: match.start()].count("\n") + 1
                hits.append(f"{path.relative_to(FRONTEND)}:{line_no} {match.group(0)}")
    return hits[:5]


# --------------------------------------------------------------------------
# D / E —— 离线跑不了的那几条
# --------------------------------------------------------------------------


def check_uncheatable(rep: Report, ctx: Ctx) -> None:
    """D 与 E 里离线跑不动的部分：如实跳过，并说明卡在什么地方。"""
    rep.skip(
        "P1-D",
        "端到端/重写/并发耗时与 token 对账",
        f"要真实模型（本次 12 页由离线桩生成，{ctx.elapsed_ms}ms 只代表桩的速度）；"
        "接上真 Key 后按 §7 D 类逐条采样",
    )
    rep.skip("P1-E1~E4", "内容质量打分", "抽样人工评分（≥4 分），脚本给不出分；用真模型生成 2 门课 + 3 个主题后人工走查")
    rep.skip(
        "P1-E5",
        "页面要点重复度",
        "离线桩每一页的要点都是同一句模板换个标题（要点集合两两不重合，但骨架相同），"
        "这个数说明不了「内容注水」；P1-E5 要用真模型生成的两门课来算",
    )


# --------------------------------------------------------------------------
# 临时库与后端
# --------------------------------------------------------------------------


def prepare_database(ctx: Ctx) -> tuple[bool, str]:
    """在临时库上跑迁移与种子。返回 (是否成功, 失败原因)。"""
    upgrade = subprocess.run(
        [str(venv_python()), "-m", "flask", "--app", "app:create_app()", "db", "upgrade"],
        cwd=str(BACKEND), env=child_env(ctx.env),
        capture_output=True, check=False, text=True, encoding="utf-8", errors="replace",
    )
    if upgrade.returncode != 0:
        return False, f"db upgrade 失败：\n{plain((upgrade.stderr or '')[-500:])}"

    seeded = run_python(
        "import json\n"
        "from app import create_app\n"
        "from app.seeds import run_seed\n"
        "app = create_app()\n"
        "with app.app_context():\n"
        "    print(json.dumps(run_seed(), ensure_ascii=False))\n",
        env=ctx.env,
    )
    if seeded.returncode != 0:
        return False, f"seed 失败：\n{plain((seeded.stderr or '')[-500:])}"
    return True, ""


def check_seeds(rep: Report, ctx: Ctx) -> None:
    """P1-7 的两门示例课：离线演示的底座，顺手在这条新链路上验一遍。

    它们和生成出来的课走的是同一套渲染与同一套 `dsl_json`，所以这里查的
    是「形状一样」：页数一致、每页有 beat、封面能推出课程卡片。
    """
    probe = run_python(
        "import json\n"
        "from app import create_app\n"
        "from app.models import Course, CoursePage\n"
        "app = create_app()\n"
        "with app.app_context():\n"
        "    out = []\n"
        "    for course in Course.query.order_by(Course.id).all():\n"
        "        pages = CoursePage.query.filter_by(course_id=course.id).all()\n"
        "        out.append({'id': course.id, 'pages': len(pages), 'pageCount': course.page_count,\n"
        "                    'status': course.status, 'cover': bool(course.cover),\n"
        "                    'beats': all((p.dsl or {}).get('narration') for p in pages)})\n"
        "    print(json.dumps(out, ensure_ascii=False))\n",
        env=ctx.env,
    )
    lines = [line for line in (probe.stdout or "").splitlines() if line.startswith("[")]
    if not lines:
        return rep.fail("P1-A1", "示例课可用", f"读示例课失败：{plain((probe.stderr or '')[-300:])}")

    courses = json.loads(lines[-1])
    bad = [
        c for c in courses
        if not (c["cover"] and c["beats"] and c["pages"] >= 3 and c["pages"] == c["pageCount"])
    ]
    if len(courses) < 2 or bad:
        rep.fail("P1-A1", "示例课可用", f"示例课不完整：{bad or courses}")
    else:
        rep.ok(
            "P1-A1",
            "示例课可用（P1-7）",
            "、".join(f"{c['id']}（{c['pages']} 页 · {c['status']}）" for c in courses) + "，每页都有 beat、封面可推",
        )


def start_server(ctx: Ctx, port: int, log_name: str):
    proc = start(
        [str(venv_python()), "-m", "flask", "--app", "app:create_app()", "run", "--port", str(port)],
        cwd=BACKEND,
        log_path=ctx.work_dir / log_name,
        env=ctx.env,
    )
    if not wait_http(f"http://127.0.0.1:{port}/api/health", timeout=60):
        log = (ctx.work_dir / log_name).read_text(encoding="utf-8", errors="replace")
        print(f"  后端没起来，日志：\n{plain(log[-1200:])}")
        stop(proc)
        return None
    return proc


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="P1 A/B/C 类验收（P1-G2，离线桩）")
    parser.add_argument("--keep", action="store_true", help="跑完留下临时库、日志与后端进程")
    args = parser.parse_args()

    global API
    API = f"http://127.0.0.1:{TEMP_PORT}/api"

    if is_up(f"http://127.0.0.1:{TEMP_PORT}/api/health"):
        print(f"端口 {TEMP_PORT} 上已经有服务了。这台机器上它可能是别人的 —— 停掉它再跑。")
        return 2

    work_dir = Path(tempfile.mkdtemp(prefix="eduagentx-p1-"))
    ctx = Ctx(
        env={
            "DATABASE_URL": f"sqlite:///{(work_dir / 'accept.db').as_posix()}",
            # 离线桩：不联网、不读 Key、同一输入永远同一输出（P1-G2）
            "LLM_PROVIDER": "mock",
            "LLM_API_KEY": "",
            "LLM_BASE_URL": "",
            # 音频也不许落进 backend/data/：万一哪天有人把 VOICE_ENABLED 打开，
            # 合成的 mp3 也该跟着临时库一起被删掉（原则 1）
            "AUDIO_DIR": (work_dir / "audio").as_posix(),
            # 语音那三组是 P2 之后才进来的：生成流水线有 `tts` 步骤了，
            # 不清空就会真去调火山（见文件头第 2 条）。
            "VOICE_ENABLED": "false",
            "VOLC_TTS_API_KEY": "",
            "VOLC_TTS_ENDPOINT": "",
            "VOLC_TTS_RESOURCE_ID": "",
            "VOLC_ASR_API_KEY": "",
            "VOLC_ASR_ENDPOINT": "",
            "VOLC_ASR_RESOURCE_ID": "",
            "VOLC_REALTIME_API_KEY": "",
            "VOLC_REALTIME_ENDPOINT": "",
            "VOLC_REALTIME_MODEL": "",
        },
        work_dir=work_dir,
    )

    print("P1 A/B/C 类验收开始（离线桩，全程不联网）")
    print(f"  临时后端 http://127.0.0.1:{TEMP_PORT}/api")
    print(f"  临时库     {work_dir / 'accept.db'}")
    print()

    report = Report()
    server = None
    try:
        ok, why = prepare_database(ctx)
        if not ok:
            print(f"  临时库没准备好：\n{why}")
            return 2
        server = start_server(ctx, TEMP_PORT, "backend.log")
        if server is None:
            return 2

        _guard(report, "示例课", check_seeds, ctx)
        _guard(report, "生成流程", check_generate, ctx)
        _guard(report, "列表与详情", check_card, ctx)
        _guard(report, "单页重写", check_rewrite, ctx)
        _guard(report, "人工编辑", check_edit, ctx)
        _guard(report, "大纲确认", check_outline, ctx)
        _guard(report, "研讨模式", check_seminar, ctx)
        _guard(report, "取消", check_cancel, ctx)
        _guard(report, "错误分支", check_branches, ctx)
        _guard(report, "数据一致性", check_consistency, ctx)
        _guard(report, "删除课程", check_purge, ctx)
        _guard(report, "重启恢复", check_restart, ctx)
        _guard(report, "安全", check_security, ctx)
        _guard(report, "超时配置", check_timeouts, ctx)
        _guard(report, "前端", check_frontend, ctx)
        _guard(report, "离线跑不了的条目", check_uncheatable, ctx)
        _guard(report, "测试套件", check_suites, ctx)

        rep_skip = sum(1 for row in report.rows if row[2] == "SKIP")
        report.ok(
            "P1-G2",
            "Mock LLM 离线跑通全流程",
            f"以上 {len(report.rows)} 条检查全部在 LLM_PROVIDER=mock 上跑完（{rep_skip} 条按 §7 的分工记跳过）",
        )
    finally:
        if server is not None and not args.keep:
            print()
            print("  正在关闭临时后端…")
            stop(server)
        elif server is not None:
            print(f"\n  临时后端还在 :{TEMP_PORT}（--keep），临时库 {work_dir}")
        if not args.keep:
            shutil.rmtree(work_dir, ignore_errors=True)

    return report.summary()


if __name__ == "__main__":
    sys.exit(main())
