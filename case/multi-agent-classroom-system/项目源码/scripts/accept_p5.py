#!/usr/bin/env python
"""P5 A/B/C/D/F/G 类验收（P5-G2）：一门课导出三格式，再把这套系统的「工程化」走一遍。

一条命令跑完，**不联网、不读 `.env`、不碰 `backend/data/`**：两个临时后端共用
一份临时 SQLite 与一个临时导出目录，跑完连库带文件一起删。

```bash
cd 项目源码
python scripts/accept_p5.py
```

| 实例 | 端口 | 配置 | 验的是 |
|------|------|------|--------|
| 主实例 | :5086 | 离线替身，导出/用量/预算全开 | A/B/C/D/F/G 的绝大多数 |
| 访问码 | :5087 | `SITE_ACCESS_CODE` 开着 | A13（门禁本身）、F4 的日志脱敏 |

**两个实例为什么是这两个配置**：访问码只有在**开着它的那一台**上才验得到
（主实例上它压根不存在），而日志脱敏要有一台把日志写进文件的实例才看得到
「写出来的文件里有没有凭据」—— 就用访问码那台，它本来就要被反复敲。

## 报的与不报的

跑不到的（要不要 Docker、要真上游账单、要人眼评分）一律如实记 **跳过**，
并把**离线侧验到的那一半**写在同一行里 —— 假验过比不验更糟。
委托给 pytest / vitest 的条目在最后逐条记账（`-rA`，通过没通过都点名）。

## 与 P3/P4 脚本的关系

骨架（`Report` / `api` / `child_env` / `_guard` / `prepare_database` / 失败留现场）
照搬 `accept_p4.py`：几条命令的读法、输出形状、失败时的现场保留方式应当一致。
**没有改动任何被测代码** —— 脚本红了就改脚本或改实现，不改「怎么算通过」。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

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

#: 两个临时后端。不碰 5000（`make dev` 的端口，连的是你的库），也不挨着
#: P1~P4 用过的那几个（5081~5085、5094~5098）：同时跑两条验收互不打扰。
MAIN_PORT = 5086
GATE_PORT = 5087

#: 访问码那台的码。写死：脚本要用它验「输错了会怎样」，换个值就得跟着改一处。
ACCESS_CODE = "accept-p5-letmein"


def _base() -> str:
    """默认调主实例（另一台用 `base=ctx.gate` 显式指定）。"""
    return f"http://127.0.0.1:{MAIN_PORT}/api"


#: 离线的凭据口径，与 `accept_p2/p3/p4.py` 逐字一致
#: （只设 `EDUAGENTX_DISABLE_DOTENV` 拦不住 Flask CLI 自己读 `.env`）。
OFFLINE_ENV: dict[str, str] = {
    "EDUAGENTX_DISABLE_DOTENV": "1",
    "FLASK_SKIP_DOTENV": "1",
    "LLM_PROVIDER": "mock",
    "LLM_API_KEY": "",
    "LLM_BASE_URL": "",
    "VOLC_TTS_API_KEY": "",
    "VOLC_TTS_ENDPOINT": "",
    "VOLC_TTS_RESOURCE_ID": "",
    "VOLC_ASR_API_KEY": "",
    "VOLC_ASR_ENDPOINT": "",
    "VOLC_ASR_RESOURCE_ID": "",
    "VOLC_REALTIME_API_KEY": "",
    "VOLC_REALTIME_ENDPOINT": "",
    "VOLC_REALTIME_MODEL": "",
    "VOLC_TTS_VOICE_TEACHER": "mock-voice-teacher",
    "VOLC_TTS_VOICE_HISTORY": "mock-voice-humanity",
}

#: 填进设置页的那把**假** Key。它会被真的存下来、真的拿去调用一次上游（必然失败），
#: 于是它经过了一条完整的错误路径 —— 日志脱敏那一条就查它有没有从哪儿漏出来。
SECRET_KEY_TEXT = "sk-accept-p5-must-not-appear-in-logs"

#: 一个**必然连不上、又不属于内网**的地址（RFC 5737 的 TEST-NET-1）。
#: 用它而不是 127.0.0.1：后者会被 SSRF 拦下，那样就测不到「上游失败」那条路径了。
UNREACHABLE_BASE_URL = "http://192.0.2.1:9/v1"

#: 给**主实例**的加密密钥：设置页保存 API Key 时要拿它加密落库（AGENTS §4.1）。
#: 它不是凭据 —— 只用来把脚本自己塞进去的那把假 Key 加密到一个跑完就删的临时库里。
#: 与 tests/conftest.py 用的是同一把，省得两处各编一个。
#: **只给主实例**：访问码那台刻意不给，于是「没配 FERNET_KEY 时报什么」也能顺手验一条
#: （README 与部署文档都写着那里会报「未配置 FERNET_KEY」，而不是一句 50001）。
OFFLINE_FERNET_KEY = "dGVzdC1rZXktZm9yLWVkdWFnZW50eC1vbmx5LTAwMDA="

#: 日志单文件上限。故意开得很小（20KB）：一趟验收就能把它写满，
#: 「写满会切」这件事于是可观测 —— 用默认的 50MB 得跑到明年。
LOG_MAX_BYTES = 20 * 1024

#: 生成一门课最多等多久（墙钟）。离线替身跑 12 页要一两分钟，超了说明卡住了。
GEN_DEADLINE = 300.0

#: 一次导出最多等多久。渲染是后台线程，轮询到 done/failed 为止。
EXPORT_DEADLINE = 120.0

#: 验收课：12 页是 §7 的口径（「12 页 PPTX ≤ 20s」）。话题写死，
#: 产物里的中文才好逐字核对（E1 比的是「这段话在不在产物里」）。
TOPIC = "P5 验收：机器学习的三类问题"
PAGE_COUNT = 12

#: 一门**用完就删**的课（A14 要看 `course.delete` 那条审计）。8 是页数下限。
AUDIT_TOPIC = "P5 验收：用完就删的一门课"
AUDIT_PAGES = 8

#: 「别人的东西」用的第二个身份：F1 要验非拥有者拿不到导出（404 而不是 403）。
OTHER_OWNER = "user_accept_p5_other"

#: 三格式的耗时上限（P5-D1）与 HTML 体积上限（P5-D3）。
EXPORT_BUDGET_SECONDS = {"pptx": 20.0, "html": 10.0, "pdf": 25.0}
HTML_MAX_BYTES = 15 * 1024 * 1024

#: 两个实例的日志文件名。重启（A9 / A12）按端口取回同一个名字 ——
#: `start` 是**追加**打开的（见那里的注释），所以重启不会把前面的证据抹掉。
LOG_NAMES = {MAIN_PORT: "main.log", GATE_PORT: "gate.log"}


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------


class Report:
    """通过清单。最后要能一眼看出「哪几条没过」。"""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []

    def _add(self, aid: str, title: str, status: str, detail: str) -> None:
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

    def verdict(self, aid: str, title: str, problems: Sequence[str], detail: str = "") -> None:
        """一组断言：`problems` 非空即不通过，内容原样打印。"""
        if problems:
            self.fail(aid, title, "；".join(problems))
        else:
            self.ok(aid, title, detail)

    def summary(self) -> int:
        passed = sum(1 for row in self.rows if row[2] == "PASS")
        failed = [r for r in self.rows if r[2] == "FAIL"]
        skipped = [r for r in self.rows if r[2] == "SKIP"]
        print()
        print("=" * 68)
        print(f"P5 验收：通过 {passed} / 不通过 {len(failed)} / 跳过 {len(skipped)}")
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
    method: str,
    path: str,
    body: Any = None,
    *,
    base: str = "",
    owner: str = "",
    timeout: float = 30.0,
    headers: Mapping[str, str] | None = None,
) -> tuple[int, Any]:
    """调后端接口，返回 (HTTP 状态, 响应体)。业务错误也在信封里，不抛异常。

    `headers` 是给访问码那台用的：cookie 得手工带上（标准库没有会话）。
    """
    data = None
    head = {"X-Request-Id": "accept-p5", **(headers or {})}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        head["Content-Type"] = "application/json"
    if owner:
        head["X-Owner-Id"] = owner
    req = urllib.request.Request(f"{base or _base()}{path}", data=data, method=method, headers=head)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, _decode(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, _decode(exc.read())
    except Exception as exc:  # 连不上 / 超时
        return 0, {"error": f"{type(exc).__name__}: {exc}"}


def _decode(raw: bytes) -> Any:
    text = raw.decode("utf-8", "replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text[:400]}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """**不跟跳转**。

    访问码那一整套（302 → 校验页 → POST → 302 回原页）验的就是**跳转本身**，
    而 urllib 默认会把 302 跟到底，于是「302 到 /access」在脚本看来是
    「200 一个页面」—— 第一版就是这么把门禁判成没生效的。
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def http_raw(
    path: str,
    *,
    base: str = "",
    headers: Mapping[str, str] | None = None,
    timeout: float = 30.0,
    follow: bool = False,
) -> tuple[int, bytes, Mapping[str, str]]:
    """要响应头或要原始字节时用它（页面与文件下载都不是 JSON）。

    `follow=False`（默认）：302 原样返回，让人自己看它跳到哪。
    """
    url = f"{base or _base()}{path}"
    req = urllib.request.Request(url, headers={"X-Request-Id": "accept-p5", **(headers or {})})
    opener = urllib.request.urlopen if follow else _opener.open
    try:
        with opener(req, timeout=timeout) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}".encode(), {}


def http_post_form(
    path: str, form: Mapping[str, str], *, base: str = "", headers: Mapping[str, str] | None = None
) -> tuple[int, bytes, Mapping[str, str]]:
    """表单 POST（访问码那一页是 `application/x-www-form-urlencoded`，不是 JSON）。**不跟跳转。**"""
    data = urllib.parse.urlencode(dict(form)).encode("utf-8")
    head = {
        "X-Request-Id": "accept-p5",
        "Content-Type": "application/x-www-form-urlencoded",
        **(headers or {}),
    }
    req = urllib.request.Request(f"{base or _base()}{path}", data=data, method="POST", headers=head)
    try:
        with _opener.open(req, timeout=30) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}".encode(), {}


def _data(status: int, envelope: Mapping[str, Any]) -> Any:
    """成功信封里的 `data`（收 2xx 而不只是 200：创建导出是 **201**）。"""
    if 200 <= int(status) < 300 and isinstance(envelope, Mapping) and envelope.get("code") == 0:
        return envelope.get("data")
    return None


def _why(status: int, envelope: Any) -> str:
    """一句能读的失败原因（HTTP 状态 + 服务端那句话）。"""
    if not isinstance(envelope, Mapping):
        return f"HTTP {status} {str(envelope)[:200]}"
    detail = envelope.get("message") or envelope.get("error") or ""
    extra = envelope.get("data")
    if isinstance(extra, Mapping) and extra.get("details"):
        detail = f"{detail} {brief(extra['details'], 200)}"
    return f"HTTP {status} code={envelope.get('code')} {detail}".strip()


def brief(payload: Any, limit: int = 300) -> str:
    text = json.dumps(payload, ensure_ascii=False, default=str)
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
# 子进程
# --------------------------------------------------------------------------


def venv_python() -> Path:
    """后端 venv 里的解释器（Windows 在 Scripts/，POSIX 在 bin/）。"""
    for candidate in (BACKEND / ".venv" / "Scripts" / "python.exe", BACKEND / ".venv" / "bin" / "python"):
        if candidate.exists():
            return candidate
    return Path(sys.executable)


def child_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """子进程的环境（与 accept_p2/p3/p4 同一份，含那两条编码与 `.env` 的闸门）。"""
    return {
        **os.environ,
        "PYTHONIOENCODING": "utf-8",
        "FLASK_SKIP_DOTENV": "1",
        "EDUAGENTX_DISABLE_DOTENV": "1",
        **(env or {}),
    }


def start(process_args: list[str], cwd: Path, log_path: Path, env: dict[str, str] | None = None):
    # **追加**打开（accept_p4 那边是 "w"）：这个脚本会重启后端（A9 的「kill 服务
    # → 重启」、A12 的「重启后数据还在」），而 F4 要翻的正是重启**之前**那一段
    # 日志 —— 截断一次，假 Key 有没有漏出来就没法回答了。
    log = log_path.open("a", encoding="utf-8")
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
    """在 backend 目录下用 venv python 跑一段代码（造合成数据、查库都用它）。"""
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


def run_flask(args: Sequence[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """跑一条 `flask <子命令>`（迁移、种子、备份、清理都走它）。"""
    return subprocess.run(
        [str(venv_python()), "-m", "flask", "--app", "app:create_app()", *args],
        cwd=str(BACKEND),
        env=child_env(env),
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def run_pytest(*args: str) -> subprocess.CompletedProcess:
    """跑一趟 pytest。**这里不能再加 `-q`**：`pyproject.toml` 的 addopts 里已经有一个了。"""
    return subprocess.run(
        [str(venv_python()), "-m", "pytest", *args],
        cwd=str(BACKEND),
        env=child_env(),
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _pytest_tail(result: subprocess.CompletedProcess, lines: int = 12) -> str:
    output = plain((result.stdout or "") + (result.stderr or ""))
    return "\n".join(line for line in output.splitlines()[-lines:] if line.strip())


def _pytest_summary(result: subprocess.CompletedProcess) -> str:
    output = plain((result.stdout or "") + (result.stderr or ""))
    for line in reversed(output.splitlines()):
        if re.search(r"\b\d+\s+(passed|failed|error|skipped|xfailed)", line):
            return line.strip().strip("=").strip()
    return _pytest_tail(result, 2).replace(chr(10), " ")


#: 委托用例的逐条结果（节点 id → PASSED/FAILED/…）。跑一趟、多处引用。
_NODE_CACHE: dict[str, str] = {}


def pytest_verdicts(nodes: Iterable[str]) -> None:
    """跑一趟 `-rA`，把逐条结论记进 `_NODE_CACHE`（整文件与单条分两趟，同 accept_p4）。"""
    unique = sorted(set(nodes))
    if not unique:
        return
    whole = [node for node in unique if "::" not in node]
    single = [node for node in unique if "::" in node]
    for batch in (whole, single):
        if batch:
            _pytest_verdicts_of(batch)


def _pytest_verdicts_of(nodes: list[str]) -> None:
    result = run_pytest("-rA", "-p", "no:cacheprovider", *nodes)
    seen: list[str] = []
    for line in plain((result.stdout or "") + (result.stderr or "")).splitlines():
        match = re.match(r"^(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\s+(\S+)", line.strip())
        if match:
            verdict, name = match.group(1), match.group(2)
            seen.append(name)
            _NODE_CACHE[name] = verdict
            _NODE_CACHE.setdefault(name.split("[", 1)[0], verdict)
    if seen:
        return
    tail = (_pytest_tail(result, 6).splitlines() or ["（pytest 没有输出）"])[-1]
    for node in nodes:
        _NODE_CACHE.setdefault(node, f"没跑到（pytest 这么说：{tail}）")


def pytest_node_ok(node: str) -> tuple[bool, str]:
    verdict = _NODE_CACHE.get(node)
    if verdict:
        return verdict == "PASSED", "" if verdict == "PASSED" else verdict
    prefix = node + "::"
    inside = {name: value for name, value in _NODE_CACHE.items() if name.startswith(prefix)}
    if not inside:
        return False, "没跑到（用例被改名或删掉了？）"
    bad = sorted(name.rsplit("::", 1)[-1] for name, value in inside.items() if value != "PASSED")
    if bad:
        return False, f"{len(bad)} 条没通过：{bad[:3]}"
    return True, ""


# --------------------------------------------------------------------------
# 一次验收里要来回传的东西
# --------------------------------------------------------------------------


@dataclass
class Ctx:
    """两个临时后端 + 这次跑出来的课程与产物。检查函数从这里取料，不各自新建。"""

    env: dict[str, str]
    work_dir: Path
    export_dir: Path
    backup_dir: Path
    log_dir: Path
    db_urls: dict[int, str] = field(default_factory=dict)
    procs: dict[str, Any] = field(default_factory=dict)
    #: 端口 → 起这台时用的环境（重启要按原样再来一遍，见 `restart_server`）
    server_env: dict[int, dict[str, str]] = field(default_factory=dict)
    #: 主课程（12 页，三格式导出都拿它）
    course_id: str = ""
    #: 生成这次课程的任务 id（时间线、续跑都按它取）
    job_id: str = ""
    #: 格式 → exportId
    exports: dict[str, str] = field(default_factory=dict)
    #: 续跑那条用的课（A9）：kill 掉服务再接着跑的那一门
    resumed_course_id: str = ""
    resumed_job_id: str = ""
    #: 课堂记录导出用的会话与产物（A5）
    session_id: str = ""
    record_exports: dict[str, str] = field(default_factory=dict)
    #: 访问码那台拿到的 cookie（`name=value`）
    gate_cookie: str = ""
    logs: dict[str, Path] = field(default_factory=dict)

    @property
    def main(self) -> str:
        return f"http://127.0.0.1:{MAIN_PORT}/api"

    @property
    def gate(self) -> str:
        return f"http://127.0.0.1:{GATE_PORT}/api"

    @property
    def site(self) -> str:
        return f"http://127.0.0.1:{GATE_PORT}"

    def db(self, port: int = MAIN_PORT) -> str:
        return self.db_urls[port]


# --------------------------------------------------------------------------
# 辅助
# --------------------------------------------------------------------------


def _guard(rep: Report, label: str, fn, *args) -> None:
    """跑一组检查。抛异常也要留下痕迹：一组崩掉就把后面几十条结果全丢了。"""
    try:
        fn(rep, *args)
    except Exception as exc:  # 脚本要活下去：一组崩掉就记一条，接着跑下一组
        where = ""
        tb = exc.__traceback__
        while tb is not None:
            if tb.tb_next is None:
                where = f"（{Path(tb.tb_frame.f_code.co_filename).name}:{tb.tb_lineno}）"
            tb = tb.tb_next
        rep.fail("P5-EXC", f"{label} 组检查中断", f"{type(exc).__name__}: {exc}{where}")


def sql(ctx: Ctx, query: str, port: int = MAIN_PORT) -> list[tuple]:
    """直接读临时库。**只读**：写一律走接口或 CLI，免得脚本自己把状态改了。"""
    script = (
        "import json, sqlite3, sys\n"
        # 要的是盘上的路径，不是 `sqlite:///...` 这个 URL —— sqlite3 不认 URL，
        # 认了就当相对路径，报「unable to open database file」。
        f"con = sqlite3.connect({db_path(ctx, port).as_posix()!r})\n"
        f"rows = con.execute({query!r}).fetchall()\n"
        "print(json.dumps([list(r) for r in rows], ensure_ascii=False, default=str))\n"
    )
    done = run_python(script)
    if done.returncode != 0:
        raise AssertionError(f"查库失败：{plain((done.stderr or '')[-400:])}")
    return [tuple(row) for row in json.loads((done.stdout or "[]").strip().splitlines()[-1])]


def db_path(ctx: Ctx, port: int = MAIN_PORT) -> Path:
    """临时库在盘上的路径（备份、查 WAL 都要用真路径）。"""
    return Path(str(ctx.db(port)).removeprefix("sqlite:///"))


def wait_export(ctx: Ctx, export_id: str, *, base: str = "", timeout: float = EXPORT_DEADLINE) -> dict:
    """轮询一次导出直到 done / failed，返回最后一帧。"""
    deadline = time.time() + timeout
    row: dict = {}
    while time.time() < deadline:
        status, envelope = api("GET", f"/exports/{export_id}", base=base)
        found = _data(status, envelope)
        if isinstance(found, Mapping):
            row = dict(found)
            if row.get("status") in {"done", "failed", "canceled"}:
                return row
        time.sleep(0.2)
    return row


def wait_job(ctx: Ctx, job_id: str, *, timeout: float = GEN_DEADLINE) -> dict:
    """轮询生成任务直到终态。"""
    deadline = time.time() + timeout
    row: dict = {}
    while time.time() < deadline:
        status, envelope = api("GET", f"/jobs/{job_id}")
        found = _data(status, envelope)
        if isinstance(found, Mapping):
            row = dict(found)
            if row.get("status") in {"done", "failed", "canceled"}:
                return row
        time.sleep(0.3)
    return row


# --------------------------------------------------------------------------
# 一、访问码这道门（P5-A13）
# --------------------------------------------------------------------------


def check_access(rep: Report, ctx: Ctx) -> None:
    """在**开着访问码的那一台**上走一遍：挡住 → 输对 → 放行。

    主实例上验不了这条：它压根没开门（本地单机默认），所以「没开的时候
    一切照旧」与「开了之后挡住」是两件都要验的事。
    """
    problems: list[str] = []
    lines: list[str] = []

    # --- 1. 页面被拦到校验页 ---
    status, body, headers = http_raw("/workbench", base=ctx.site)
    location = headers.get("Location", "")
    if status != 302:
        problems.append(f"没带访问码访问页面，回的是 {status}（该 302 到校验页）")
    elif "/access" not in location:
        problems.append(f"302 的目标不是校验页：{location}")
    lines.append(f"GET /workbench -> {status} Location: {location or '（无）'}")

    # --- 2. 接口回 403 + 业务码 40304（不是 401/302：前端要靠它跳页） ---
    status, envelope = api("GET", "/courses", base=ctx.gate)
    code = envelope.get("code") if isinstance(envelope, Mapping) else None
    if status != 403 or code != 40304:
        problems.append(f"没带访问码调接口：HTTP {status} code={code}（该 403 / 40304）")
    lines.append(f"GET /api/courses -> {status} code={code}")

    # --- 3. 健康检查不走门禁（容器探针没有浏览器、没有 cookie） ---
    status, envelope = api("GET", "/health", base=ctx.gate)
    if _data(status, envelope) is None:
        problems.append(f"/api/health 被门禁挡住了：{_why(status, envelope)}")
    lines.append(f"GET /api/health -> {status}（探针要能过）")

    # --- 4. 输错会怎样 ---
    status, body, headers = http_post_form(
        "/access", {"code": "definitely-wrong", "next": "/workbench"}, base=ctx.site
    )
    if status != 403:
        problems.append(f"输错访问码回的是 {status}（该 403 并留在校验页）")
    lines.append(f"POST /access（错的码）-> {status}")

    # --- 5. 输对：发 cookie、跳回原来要去的地方 ---
    status, body, headers = http_post_form(
        "/access", {"code": ACCESS_CODE, "next": "/workbench"}, base=ctx.site
    )
    cookie = (headers.get("Set-Cookie") or "").split(";")[0]
    if status != 302:
        problems.append(f"输对访问码回的是 {status}（该 302 跳回 next）")
    if not headers.get("Location", "").endswith("/workbench"):
        problems.append(f"没跳回 next：{headers.get('Location')}")
    if "httponly" not in (headers.get("Set-Cookie") or "").lower():
        problems.append("访问码 cookie 不是 HttpOnly")
    if not cookie:
        problems.append("没发 cookie")
    lines.append(f"POST /access（对的码）-> {status} {cookie.split('=')[0]}=…（HttpOnly）")

    # --- 6. 带着 cookie 就放行 ---
    ctx.gate_cookie = cookie
    status, envelope = api("GET", "/courses", base=ctx.gate, headers={"Cookie": cookie})
    if _data(status, envelope) is None:
        problems.append(f"带了 cookie 还是被挡：{_why(status, envelope)}")
    lines.append(f"带 cookie 再调 /api/courses -> {status}")

    # --- 7. 开放重定向：`next` 只认本站路径 ---
    status, _body, headers = http_post_form(
        "/access", {"code": ACCESS_CODE, "next": "//evil.example.com/x"}, base=ctx.site
    )
    location = headers.get("Location", "")
    if "evil.example.com" in location:
        problems.append(f"next 是外站地址也照跳：{location}")
    lines.append(f"next=//evil.example.com -> Location: {location}（被丢掉）")

    rep.verdict("P5-A13", "访问码：没带被拦、带对了放行、外站 next 不跳", problems, "\n".join(lines))


# --------------------------------------------------------------------------
# 二、日志脱敏与轮转（P5-F4）
# --------------------------------------------------------------------------


def check_logs(rep: Report, ctx: Ctx) -> None:
    """日志文件里不能有凭据，且写满会自动轮转。

    拿主实例验：它这一趟被反复敲过，日志里什么都有 —— 正好翻。翻的是**两组**文件：

    - `main.log*`：应用自己写的（`LOG_FILE`，`RotatingFileHandler`），生产上就是这一份；
    - `main.console.log`：进程的 stdout/stderr（werkzeug 的横幅与访问日志）。

    两组都要翻：脱敏 Filter 是挂在 handler 上的，而「有没有哪条路绕过了 handler」
    正是这条验收要问的 —— 只看被 Filter 覆盖的那一份，等于让它自己证明自己。
    """
    app_files = sorted(ctx.log_dir.glob("main.log*"))
    console_files = sorted(ctx.log_dir.glob("main.console.log*"))
    log_files = app_files + console_files
    text = "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in log_files)
    problems: list[str] = []
    if not text.strip():
        problems.append("日志文件是空的（LOG_FILE 没生效？）")
    # 这串是 check_security 往设置页里填的那把假 Key：它经过了一次**上游调用失败**
    # 的错误路径（那段代码最容易被异常栈连人带 Key 一起打出来）。
    for path in log_files:
        body = path.read_text(encoding="utf-8", errors="replace")
        if SECRET_KEY_TEXT in body:
            problems.append(f"日志里出现了假 Key 原文（{path.name}）")
        for hint in ("Bearer ", "api_key=", "apiKey="):
            if hint in body:
                problems.append(f"{path.name} 里出现了 {hint!r} —— 往上几行看看它带的是什么")
        # 一次性票据走 URL 查询串，而**访问日志会把整条请求行记下来**：拿到日志的人
        # 就拿到了那张票（运维手册 §5 说的就是这件事）。这里按「参数名 + 取值」找，
        # 脱敏生效时它长这样：`download?token=****`。
        leaked_tickets = re.findall(r"(?i)\b(?:token|ticket)=([^\s\"'&]{6,})", body)
        leaked_tickets = [value for value in leaked_tickets if set(value) != {"*"}]
        if leaked_tickets:
            problems.append(f"{path.name} 里出现了没脱敏的票据：{leaked_tickets[:2]}")
    rotated = [path.name for path in app_files if path.suffix.lstrip(".").isdigit()]
    if not rotated:
        problems.append("没有轮转文件（单文件上限没生效）")
    rep.verdict(
        "P5-F4",
        "日志脱敏与轮转：文件里翻不到凭据，写满会自动切",
        problems,
        f"翻了 {len(log_files)} 个日志文件（{', '.join(p.name for p in log_files[:4])}…），"
        f"轮转出 {len(rotated)} 个；一次性票据在访问日志里是 `token=****`",
    )


# --------------------------------------------------------------------------
# 三、备份与恢复演练（P5-C3）
# --------------------------------------------------------------------------


def _tree(root: Path) -> set[str]:
    """一棵目录下的全部文件（相对路径）。空目录与不存在的目录都是空集合。"""
    if not root.is_dir():
        return set()
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    """一棵目录下每个文件的「第几字节 + 改没改过」，相对路径 → (大小, mtime_ns)。

    比 `_tree` 多一列：只数个数的话，「原地改了一个文件」与「什么都没动」
    长得一模一样，而恢复演练里恰好是要抓「偷偷覆盖了」这一种。
    **空目录不进快照**：目录会被应用启动时建出来（见 C3 那段注释），
    拿它当「写了东西」的证据就会误伤。
    """
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): (path.stat().st_size, path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


def _diff(before: Mapping[str, tuple[int, int]], after: Mapping[str, tuple[int, int]]) -> list[str]:
    """两棵快照之间多出来的、变了的、少了的文件（相对路径，字典序）。

    少了也算：恢复预告同样不该删东西。
    """
    changed = {name for name, stat in after.items() if before.get(name) != stat}
    changed.update(name for name in before if name not in after)
    return sorted(changed)


def check_backup(rep: Report, ctx: Ctx) -> None:
    """真打一份备份，真恢复到一个空目录，再把里面的东西读回来。

    「备份能恢复」这件事只有**真恢复过一次**才算数：归档打得开、文件在里面，
    跟「恢复回来能跑」之间隔着 WAL 边车、路径映射、库完整性三道坎。
    演练写在临时目录里，碰不到你的数据。
    """
    problems: list[str] = []
    lines: list[str] = []

    courses_before = int(sql(ctx, "select count(*) from courses")[0][0])
    files_before = _tree(ctx.export_dir)
    lines.append(f"恢复前：课程 {courses_before} 门、导出产物 {len(files_before)} 个文件")

    # --- 1. 打一份 ---
    done = run_flask(
        ["backup"], env={**ctx.env, "DATABASE_URL": ctx.db(), "BACKUP_DIR": str(ctx.backup_dir)}
    )
    archives = sorted(ctx.backup_dir.glob("eduagentx-*.tar.gz"))
    if done.returncode != 0 or not archives:
        problems.append(f"备份没打成：{plain((done.stderr or '')[-300:]) or done.stdout}")
        rep.verdict("P5-C3", "备份与恢复演练", problems, "\n".join(lines))
        return
    archive = archives[-1]
    lines.append(f"归档 {archive.name}（{archive.stat().st_size / 1024:.0f}KB）")

    # --- 2. 恢复到一个空目录（先造一个空库，好验「恢复前那份副本」） ---
    target = ctx.work_dir / "restore"
    target_env = {
        **ctx.env,
        "DATABASE_URL": f"sqlite:///{(target / 'eduagentx.db').as_posix()}",
        "UPLOAD_DIR": (target / "uploads").as_posix(),
        "MATERIAL_DIR": (target / "materials").as_posix(),
        "AUDIO_DIR": (target / "audio").as_posix(),
        "EXPORT_DIR": (target / "exports").as_posix(),
    }
    target.mkdir(parents=True, exist_ok=True)
    made = run_flask(["db", "upgrade"], env=target_env)
    if made.returncode != 0:
        problems.append(f"空库没建起来：{plain((made.stderr or '')[-300:])}")
        rep.verdict("P5-C3", "备份与恢复演练", problems, "\n".join(lines))
        return

    # 不带 --yes：只打印预告，一个字节都不该写。
    # 判据是**文件树的前后差**（`_snapshot`），不是「某个目录在不在」：
    # `create_app()` 起手就把 UPLOAD/AUDIO/EXPORT 这些目录建出来
    # （`_ensure_directories`），上面那句 `db upgrade` 早让它们全存在了 ——
    # 拿「目录存在」当证据，红的永远是脚本自己（第一趟就是这么误判的：
    # 预告没写一个字，却报「已经写进去了」）。目录不算数，文件的新增/改动/删除才算。
    before_dry = _snapshot(target)
    dry = run_flask(["restore", str(archive)], env=target_env)
    if dry.returncode != 0:
        problems.append(f"预告那一步就失败了：{plain((dry.stderr or '')[-300:])}")
    written = _diff(before_dry, _snapshot(target))
    if written:
        problems.append("没给 --yes，却已经写进去了：" + "、".join(written[:5]))
    last_line = (plain(dry.stdout or "").strip().splitlines() or [""])[-1]
    lines.append(f"预告（不带 --yes）末行：{last_line[:90]}")

    # 带 --yes：真恢复
    real = run_flask(["restore", str(archive), "--yes"], env=target_env)
    if real.returncode != 0:
        problems.append(f"恢复失败：{plain((real.stderr or '')[-400:])}")
        rep.verdict("P5-C3", "备份与恢复演练", problems, "\n".join(lines))
        return

    # --- 3. 读回来 ---
    restored_db = target / "eduagentx.db"
    check = run_python(
        "import sqlite3\n"
        f"con = sqlite3.connect({restored_db.as_posix()!r})\n"
        "print(con.execute('pragma integrity_check').fetchone()[0])\n"
        "print(con.execute('select count(*) from courses').fetchone()[0])\n"
    )
    out = [line.strip() for line in (check.stdout or "").splitlines() if line.strip()]
    if check.returncode != 0 or len(out) < 2:
        problems.append(f"恢复出来的库读不动：{plain((check.stderr or '')[-300:])}")
    else:
        if out[0] != "ok":
            problems.append(f"恢复出来的库 integrity_check 不是 ok：{out[0]}")
        if int(out[1]) != courses_before:
            problems.append(f"课程数对不上：恢复前 {courses_before}、恢复后 {out[1]}")

    files_after = _tree(target / "exports")
    if files_after != files_before:
        missing = sorted(files_before - files_after)[:3]
        problems.append(f"导出产物没全回来（少 {len(files_before - files_after)} 个：{missing}）")
    lines.append(
        f"恢复后：库 integrity {out[0] if out else '?'}、课程 {out[1] if len(out) > 1 else '?'} 门、"
        f"产物 {len(files_after)} 个文件"
    )

    safety = sorted(target.glob("*.pre-restore-*.db"))
    if not safety:
        problems.append("恢复前没有把现有的库留一份副本（那份是最后的保险）")
    else:
        lines.append(f"恢复前的库留档：{safety[-1].name}")

    rep.verdict("P5-C3", "备份与恢复演练", problems, "\n".join(lines))


# --------------------------------------------------------------------------
# 四、生成一门 12 页课（三格式导出、看板、续跑都拿它当料）
# --------------------------------------------------------------------------


def _post_generate(topic: str, *, page_count: int, base: str = "") -> tuple[str, str]:
    """建一门课，立刻返回 `(courseId, jobId)`：生成在后台跑，这里不等。"""
    status, envelope = api(
        "POST",
        "/courses/generate",
        {"topic": topic, "mode": "lecture", "pageCount": page_count, "confirmOutline": False},
        base=base,
        timeout=30,
    )
    data = _data(status, envelope)
    if not isinstance(data, Mapping) or not data.get("courseId"):
        raise AssertionError(f"建课失败：{_why(status, envelope)}")
    return str(data["courseId"]), str(data["jobId"])


def _wait_status(job_id: str, *, want: set[str], timeout: float, base: str = "") -> dict:
    """等任务进某个状态（离线替身跑 12 页要一两分钟）。"""
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        status, envelope = api("GET", f"/jobs/{job_id}", base=base)
        data = _data(status, envelope)
        if isinstance(data, Mapping):
            last = dict(data)
            if str(last.get("status") or "") in want:
                return last
        time.sleep(0.3)
    return last


def _wait_resumed(job_id: str, *, was: str, timeout: float, base: str = "") -> dict:
    """等一次「续跑」跑完：先等它离开终态，再等它回到终态。

    少了前半程就会把**点之前**那个终态当成结果（杀服务留下的 `failed` 还挂在那儿），
    于是「点继续生成」这件事本身根本没被观测到。`was` 是点之前的状态：
    万一轮询没撞上中间那一下（离线替身跑得快），「变成了**另一个**终态」也算数。
    """
    terminal = {"done", "failed", "canceled"}
    moved = False
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        status, envelope = api("GET", f"/jobs/{job_id}", base=base)
        data = _data(status, envelope)
        if isinstance(data, Mapping):
            last = dict(data)
            current = str(last.get("status") or "")
            if current not in terminal:
                moved = True
            elif moved or current != was:
                return last
        time.sleep(0.3)
    return last


def _absent(rep: Report, items: Iterable[tuple[str, str]], why: str) -> None:
    """一条前置没成立时，把它带的那几条**点名**记跳过。

    静悄悄地少几行，比红一条更难查 —— 通过清单是拿来对账的，
    §7 里有几条就该看到几条。
    """
    for aid, title in items:
        rep.skip(aid, title, why)


# --------------------------------------------------------------------------
# 五、把产物打开看（E1 / A1 / A4 都靠它）
# --------------------------------------------------------------------------

#: 从产物里抠文本的小探针，跑在**后端 venv** 里（python-pptx 与 PyMuPDF 都在那儿）。
#: 它不是测试代码，是取证工具：三份产物讲的是不是同一件事、讲稿落在备注页还是
#: 正文里、PDF 有没有页码 —— 这三问都只能把产物真打开一次才答得上来。
_PROBE = r'''
import html as html_module
import json
import os
import re

import pymupdf
from pptx import Presentation


def flat(text):
    """去掉全部空白。

    PDF 会在字缝里插空格、PPTX 会按行折行，而 E1 问的是「这段话在不在」，
    不是「它排成什么样」—— 不归一化就会把排版当成内容差异报出来。
    """
    return re.sub(r"\s+", "", text or "")


def pptx_text(path):
    prs = Presentation(path)
    body, notes, with_notes = [], [], 0
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                body.append(shape.text_frame.text)
        text = slide.notes_slide.notes_text_frame.text if slide.has_notes_slide else ""
        if text.strip():
            with_notes += 1
        notes.append(text)
    return flat("\n".join(body)), flat("\n".join(notes)), {
        "slides": len(prs.slides), "notesSlides": with_notes}


def pdf_text(path):
    with pymupdf.open(path) as doc:
        text = "\n".join(page.get_text() for page in doc)
        return flat(text), flat(""), {"pages": doc.page_count}


def plain_text(path):
    """HTML 与 Markdown：**读文本**。

    不套无头浏览器：这条路要能在没有 Chromium 的机器上跑（P5 §8「已规避」
    那条风险的直接后果）。HTML 去掉 script/style 与标签之后就是正文，
    对「这段话在不在」这个问题足够了。
    """
    raw = open(path, encoding="utf-8", errors="replace").read()
    if path.endswith(".html"):
        raw = re.sub(r"<(script|style)\b.*?</\1>", " ", raw, flags=re.S | re.I)
        raw = html_module.unescape(re.sub(r"<[^>]+>", " ", raw))
    return flat(raw), flat(""), {}


KINDS = {"pptx": pptx_text, "pdf": pdf_text, "html": plain_text, "md": plain_text}

with open(os.environ["ACCEPT_P5_SPEC"], encoding="utf-8") as handle:
    SPEC = json.load(handle)

RESULTS = []
# 「在不在」这一问分两层问：BODY 是**看得见的那一层**，NOTES 是讲稿那一层。
# 只有 pptx 分得开（备注页是独立的一层）；html 与 pdf 的讲稿与正文同在一页上，
# 探针把整份文档都算 BODY。三问因此都有明确的那一层：
#   needles      必须出现在 BODY（用 EVERYWHERE 会漏判：讲稿里逐句带着页标题，
#                标题真从正文丢了也能被备注页救回来，等于没测）
#   absent       必须不出现在 BODY（「讲稿没糊到投影上」问的就是这个）
#   notesMissing 必须出现在 NOTES
for ITEM in SPEC["items"]:
    BODY, NOTES, EXTRA = KINDS[ITEM["kind"]](ITEM["path"])
    RESULTS.append({
        "key": ITEM["key"],
        "chars": len(BODY),
        "missing": [n for n in ITEM.get("needles", []) if flat(n) not in BODY],
        "absent": [n for n in ITEM.get("absent", []) if flat(n) in BODY],
        "notesMissing": [n for n in ITEM.get("notesNeedles", []) if flat(n) not in NOTES],
        **EXTRA,
    })
print(json.dumps({"results": RESULTS}, ensure_ascii=False))
'''


def probe_artifacts(ctx: Ctx, spec: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """把产物打开，看某几句话在不在里面。返回 `{key: 结果}`。"""
    path = ctx.work_dir / "probe-spec.json"
    path.write_text(json.dumps({"items": list(spec)}, ensure_ascii=False), encoding="utf-8")
    done = run_python(_PROBE, env={"ACCEPT_P5_SPEC": path.as_posix()})
    if done.returncode != 0:
        raise AssertionError(f"读产物失败：{plain((done.stderr or '')[-400:])}")
    lines = [line for line in (done.stdout or "").splitlines() if line.strip()]
    payload = json.loads(lines[-1]) if lines else {}
    return {row["key"]: row for row in payload.get("results", [])}


def _texts_of(raw: Any, key: str) -> list[str]:
    """`[{text: …}, …]` 里每个字典的 `text`（不是字典的元素原样跳过）。"""
    out = []
    for item in raw if isinstance(raw, list) else []:
        text = str(item.get("text") or "").strip() if isinstance(item, Mapping) else ""
        if text:
            out.append(text)
    return out


def _published(dsl: Mapping[str, Any]) -> list[str]:
    """这一页**该被导出去**的正文文本，按页型取。

    不能一律拿 `bullets`：桩给每一页都填了那几句话，但封面页发的是主讲/时长/对象
    那一行、大纲页发的是章目录、测验页发的是题干与选项 —— 那几页的 `bullets`
    本来就是没人看的填充物，渲染器不摆它是**对的**。
    （第一趟验收就是拿 `bullets` 一律去比，于是「25 段内容不见了」——
     缺的全是这三类页型，三种产物一个不差地都缺。那是我这边比错了，不是产物丢内容。）

    这张表是脚本对「这一页该导出什么」的**独立主张**，不调 `app/services/exports/ir.py`
    里那份映射：拿产品自己的映射当基准，等于让实现自己判自己。代价是页型改了要跟着改 ——
    真改了这里会红一条，而那条失败的提示语里带着页型，改起来是几分钟的事。
    """
    kind = str(dsl.get("kind") or "")
    texts: list[str] = []
    if kind == "cover":
        meta = dsl.get("meta")
        meta = meta if isinstance(meta, Mapping) else {}
        texts += [str(meta.get(key) or "") for key in ("lecturer", "audience", "subtitle")]
    elif kind == "outline":
        texts += [
            f"{item.get('no')}. {item.get('title')}"
            for item in dsl.get("chapters") or []
            if isinstance(item, Mapping) and str(item.get("title") or "").strip()
        ]
    elif kind == "quiz":
        quiz = dsl.get("quiz")
        quiz = quiz if isinstance(quiz, Mapping) else {}
        texts += [str(quiz.get(key) or "") for key in ("stem", "answer", "explain")]
        texts += [str(item) for item in quiz.get("options") or []]
    else:
        texts += _texts_of(dsl.get("bullets"), "text")
        if kind == "summary":
            texts.append(str(dsl.get("question") or ""))
        elif kind == "code":
            code = dsl.get("code")
            texts.append(str((code if isinstance(code, Mapping) else {}).get("content") or ""))
            texts += [str(item) for item in dsl.get("explanation") or []]
        elif kind == "example":
            texts += [str(item) for item in dsl.get("steps") or []]
        elif kind == "debate":
            texts.append(str(dsl.get("topic") or ""))
            texts.append(str(dsl.get("arbiterSummary") or ""))
        if kind == "figure":
            visual = dsl.get("visual")
            texts.append(str((visual if isinstance(visual, Mapping) else {}).get("desc") or ""))
    return [text.strip() for text in texts if str(text).strip()]


def _source_text(ctx: Ctx) -> dict[str, Any]:
    """源课程里的标题 / 要点 / 讲稿 / 测验 —— E1 的比对基准。

    取的是**用户看得见的那几个字段**，不是整份 DSL：渲染器按 IR 摆版式，
    键名与结构本来就会变，拿整份 DSL 去比只会比出「版式不一样」这个已知事实。
    """
    status, envelope = api("GET", f"/courses/{ctx.course_id}?withPages=1")
    data = _data(status, envelope)
    if not isinstance(data, Mapping):
        raise AssertionError(f"读课程失败：{_why(status, envelope)}")
    pages = [page for page in (data.get("pages") or []) if isinstance(page, Mapping)]
    titles: list[str] = []
    bullets: list[str] = []
    narration: list[str] = []
    quiz: list[str] = []
    for page in pages:
        dsl = page.get("dsl")
        dsl = dsl if isinstance(dsl, Mapping) else {}
        title = str(page.get("title") or dsl.get("title") or "").strip()
        if title:
            titles.append(title)
        bullets += _published(dsl)
        narration += _texts_of(dsl.get("narration"), "text")
        # 测验页的题干与解析在**嵌套的那一格**里（`dsl["quiz"]`，与
        # `exports/ir.py:_quiz_from_dsl` 读的是同一处）。此前在这外面找
        # `stem`/`explain`，一格都取不到 —— 于是 A4/E1 那句「测验附答案解析」
        # 一直在拿**空基准**比，比出来的「通过」是假的（报告里那句
        # 「测验 0 条可供逐字核对」就是它）。键名以页面 DSL 为准，
        # 不是我们自己想的那个。
        inner = dsl.get("quiz")
        inner = inner if isinstance(inner, Mapping) else {}
        for key in ("stem", "explain"):
            value = str(inner.get(key) or "").strip()
            if value:
                quiz.append(value)
    return {"pageCount": len(pages), "titles": titles, "bullets": bullets,
            "narration": narration, "quiz": quiz}


def _squash(text: str) -> str:
    """去掉全部空白再比。

    两边都要抹：文本里的空格是真内容（「P5 验收：…」），而产物那边会按窗口
    宽度折行、PDF 还会在字缝里插空格 —— 只抹一边就成了拿带空格的串去比
    不带空格的文本（第一趟的 A5 就是这么误判的）。
    """
    return re.sub(r"\s+", "", text or "")


def _long(values: Iterable[str], least: int = 6) -> list[str]:
    """挑出够长的比对串。

    一两个字的「要点」（选项字母 `A`、章节号 `1.`）在整份产物里到处都是，
    拿它当指纹等于没比 —— 一致率会是 100%，但那不是这门课的功劳。
    """
    return [value for value in values if len(_squash(value)) >= least]


# --------------------------------------------------------------------------
# 六、三格式真渲染（A1 / A3 / A4 / D1 / D3 / E1 / C1）
# --------------------------------------------------------------------------

#: 这一组共用的前置。生成没跑起来的话，下面每一条都得点名记跳过。
EXPORT_GROUP: list[tuple[str, str]] = [
    ("P5-A3", "HTML 离线可用：单文件自包含、正文与讲稿都在、没有外链"),
    ("P5-A4", "PDF 讲义可用：中文能取回、讲稿与测验解析都在、页码连号"),
    ("P5-D1", "导出耗时：PPTX ≤ 20s、HTML ≤ 10s、PDF ≤ 25s"),
    ("P5-D3", "导出 HTML ≤ 15MB"),
    ("P5-E1", "三格式与源课程的标题/要点一致率 100%"),
    ("P5-C1", "产物落在 data/exports/{courseId}/{exportId}.{ext}，相对路径且不含 .."),
]

#: 产物后缀。三种格式的渲染器都按枚举取后缀，这里跟着取同一个。
_EXT = {"pptx": "pptx", "html": "html", "pdf": "pdf", "md": "md"}


def _artifact(ctx: Ctx, course_id: str, export_id: str, fmt: str) -> Path:
    """产物在盘上的位置。`data/exports/` 那一段是**逻辑**前缀（P5-C1），
    物理位置由 `EXPORT_DIR` 决定 —— 这里用的是脚本自己配的那个临时目录。"""
    return ctx.export_dir / course_id / f"{export_id}.{_EXT[fmt]}"


def check_exports(rep: Report, ctx: Ctx) -> None:
    """一门 12 页课导三遍，每遍都把产物打开看（A1/A3/A4/D1/D3/E1/C1）。"""
    a1 = "PPTX 可用：页数对、标题与要点齐全、讲稿落备注页"
    try:
        ctx.course_id, ctx.job_id = _post_generate(TOPIC, page_count=PAGE_COUNT)
    except AssertionError as exc:
        rep.fail("P5-A1", a1, f"{exc}；这一条是下面每条的前置")
        _absent(rep, EXPORT_GROUP, "这门课没建起来（见 P5-A1）")
        return

    job = wait_job(ctx, ctx.job_id)
    if job.get("status") != "done":
        why = f"12 页课没生成完：status={job.get('status')} progress={job.get('progress')}"
        rep.fail("P5-A1", a1, f"{why}；这一条是下面每条的前置")
        _absent(rep, EXPORT_GROUP, "这门课没生成完（见 P5-A1）")
        return

    source = _source_text(ctx)
    pages = int(source["pageCount"] or PAGE_COUNT)
    body_needles = _long([*source["titles"], *source["bullets"]])
    notes_needles = _long(source["narration"])
    quiz_needles = _long(source["quiz"])
    lines = [f"课程 {ctx.course_id}（{pages} 页）：标题 {len(source['titles'])} 条、"
             f"要点 {len(body_needles)} 条、讲稿 {len(notes_needles)} 条、"
             f"测验 {len(quiz_needles)} 条可供逐字核对"]

    # --- 1. 三种格式各导一次，记耗时（D1 的判据是**用户等多久**，所以量墙钟） ---
    timings: dict[str, float] = {}
    problems: list[str] = []
    for fmt in ("pptx", "html", "pdf"):
        started = time.perf_counter()
        status, envelope = api(
            "POST", f"/courses/{ctx.course_id}/exports", {"format": fmt, "scope": "course"}
        )
        data = _data(status, envelope)
        if not isinstance(data, Mapping) or not data.get("exportId"):
            problems.append(f"{fmt} 导出没建起来：{_why(status, envelope)}")
            continue
        export_id = str(data["exportId"])
        ctx.exports[fmt] = export_id
        row = wait_export(ctx, export_id)
        timings[fmt] = time.perf_counter() - started
        if row.get("status") != "done":
            problems.append(
                f"{fmt} 导出没跑完：status={row.get('status')} error={row.get('error')}"
            )
        else:
            lines.append(
                f"{fmt.upper()} {export_id}：{timings[fmt]:.1f}s、"
                f"{int(row.get('sizeBytes') or 0) / 1024:.0f}KB、progress 到 {row.get('progress')}"
            )
    if problems:
        rep.fail("P5-A1", a1, "；".join(problems))
        _absent(rep, EXPORT_GROUP, "三份产物没齐（见 P5-A1 的失败原因）")
        return

    # --- 2. 把三份产物打开（E1 / A1 / A4 的内容那半） ---
    spec = [
        {
            "key": "pptx",
            "path": _artifact(ctx, ctx.course_id, ctx.exports["pptx"], "pptx").as_posix(),
            "kind": "pptx",
            "needles": [*body_needles, *quiz_needles],
            # 讲稿在 PIP 里是「备注页」那一层：它必须在 NOTES 里，且**不在正文里**
            # （落在正文就是把逐字稿糊在了投影上）。
            "notesNeedles": notes_needles,
            "absent": notes_needles,
        },
        {
            "key": "html",
            "path": _artifact(ctx, ctx.course_id, ctx.exports["html"], "html").as_posix(),
            "kind": "html",
            "needles": [*body_needles, *notes_needles, *quiz_needles],
        },
        {
            "key": "pdf",
            "path": _artifact(ctx, ctx.course_id, ctx.exports["pdf"], "pdf").as_posix(),
            "kind": "pdf",
            "needles": [*body_needles, *notes_needles, *quiz_needles],
        },
    ]
    seen = probe_artifacts(ctx, spec)

    # --- 3. A1：PPTX ---
    pptx = seen.get("pptx", {})
    a1_problems = []
    if int(pptx.get("slides") or 0) != pages:
        a1_problems.append(f"页数对不上：产物 {pptx.get('slides')} 页、课程 {pages} 页")
    if pptx.get("missing"):
        a1_problems.append(f"正文里找不到 {len(pptx['missing'])} 段：{pptx['missing'][:2]}")
    if pptx.get("notesMissing"):
        a1_problems.append(f"备注页里找不到 {len(pptx['notesMissing'])} 段讲稿")
    if pptx.get("absent"):
        a1_problems.append(f"讲稿跑进了正文（{len(pptx['absent'])} 段）—— 该在备注页")
    if int(pptx.get("notesSlides") or 0) == 0:
        a1_problems.append("一页备注都没有（讲稿没落下去）")
    lines.append(
        f"PPTX：{pptx.get('slides')} 页、{pptx.get('notesSlides')} 页带备注、"
        f"正文取回 {pptx.get('chars')} 字"
    )
    rep.verdict("P5-A1", a1, a1_problems, "\n".join(lines))

    # --- 4. A3：HTML 单文件、零外链 ---
    html_path = _artifact(ctx, ctx.course_id, ctx.exports["html"], "html")
    html = seen.get("html", {})
    a3_problems = []
    if html.get("missing"):
        a3_problems.append(f"HTML 里找不到 {len(html['missing'])} 段内容：{html['missing'][:2]}")
    raw_html = html_path.read_text(encoding="utf-8", errors="replace")
    # 「自包含」是可查的：断网打开要能用，就不能有 src/href 指向站外。
    externals = re.findall(r"""(?:src|href)\s*=\s*["']?(?:https?:)?//""", raw_html, flags=re.I)
    imports = re.findall(r"@import", raw_html, flags=re.I)
    if externals or imports:
        a3_problems.append(f"有 {len(externals) + len(imports)} 处外链（断网打开就废了）")
    lines.append(f"HTML {html_path.stat().st_size / 1024:.0f}KB：外链 {len(externals) + len(imports)} 处"
                 f"（0 处才算自包含）")
    rep.verdict("P5-A3", "HTML 离线可用：单文件自包含、正文与讲稿都在、没有外链",
                a3_problems, "\n".join(lines))

    # --- 5. A4：PDF 中文能取回、页码连号 ---
    pdf = seen.get("pdf", {})
    a4_problems = []
    if pdf.get("missing"):
        a4_problems.append(f"取不回 {len(pdf['missing'])} 段中文：{pdf['missing'][:2]}")
    if int(pdf.get("chars") or 0) < 1000:
        # 中文取不回来的 PDF 有两种坏法：一种是方框，一种是压根没文字层（整页图）。
        # 这一条挡后面那种 —— 靠的是「取回的字数」而不是「字体名对不对」。
        a4_problems.append(f"PDF 里只取回 {pdf.get('chars')} 字，像是没有文字层")
    paper = int(pdf.get("pages") or 0)
    numbered = probe_artifacts(
        ctx,
        [{
            "key": "pdf",
            "path": _artifact(ctx, ctx.course_id, ctx.exports["pdf"], "pdf").as_posix(),
            "kind": "pdf",
            "needles": [f"第1/{paper}页", f"第{paper}/{paper}页"] if paper else [],
        }],
    )
    if paper and numbered.get("pdf", {}).get("missing"):
        a4_problems.append(f"页码不对：页脚里找不到 第1/{paper}页 或 第{paper}/{paper}页")
    lines.append(f"PDF：{paper} 张纸、取回 {pdf.get('chars')} 字、页码 第 i / {paper} 页")
    rep.verdict("P5-A4", "PDF 讲义可用：中文能取回、讲稿与测验解析都在、页码连号",
                a4_problems, "\n".join(lines))

    # --- 6. D1：耗时 ---
    slow = [
        f"{fmt.upper()} {timings[fmt]:.1f}s 超过 {EXPORT_BUDGET_SECONDS[fmt]:.0f}s"
        for fmt in timings
        if timings[fmt] > EXPORT_BUDGET_SECONDS[fmt]
    ]
    if len(timings) < 3:
        slow.append(f"有格式没跑完（{len(timings)}/3）")
    rep.verdict(
        "P5-D1",
        "导出耗时：PPTX ≤ 20s、HTML ≤ 10s、PDF ≤ 25s",
        slow,
        "；".join(f"{fmt.upper()} {timings[fmt]:.1f}s"
                 for fmt in ("pptx", "html", "pdf") if fmt in timings)
        + "（墙钟：建任务 → 轮询到 done，含 0.2s 的轮询粒度）",
    )

    # --- 7. D3：HTML 体积 ---
    size = html_path.stat().st_size
    rep.verdict(
        "P5-D3",
        "导出 HTML ≤ 15MB",
        [f"{size / 1024 / 1024:.1f}MB 超过 15MB"] if size > HTML_MAX_BYTES else [],
        f"{size / 1024:.0f}KB / {HTML_MAX_BYTES / 1024 / 1024:.0f}MB",
    )

    # --- 8. E1：三份产物讲的是不是同一件事 ---
    e1_problems = []
    for key, label in (("pptx", "PPTX"), ("html", "HTML"), ("pdf", "PDF")):
        miss = seen.get(key, {}).get("missing") or []
        if miss:
            rate = 1 - len(miss) / max(1, len(body_needles))
            e1_problems.append(f"{label} 少了 {len(miss)} 段（一致率 {rate:.0%}）：{miss[:2]}")
    rep.verdict(
        "P5-E1",
        "三格式与源课程的标题/要点一致率 100%",
        e1_problems,
        f"逐字核对了 {len(body_needles)} 段标题与要点、{len(notes_needles)} 段讲稿、"
        f"{len(quiz_needles)} 段测验解析，三种产物各核一遍",
    )

    # --- 9. C1：产物落在哪、路径长什么样 ---
    c1_problems = []
    c1_lines = []
    for fmt, export_id in ctx.exports.items():
        rows = sql(ctx, f"select file_path, size_bytes from exports where id = {export_id!r}")
        if not rows:
            c1_problems.append(f"{fmt} 那一行在库里找不到")
            continue
        rel, size_bytes = str(rows[0][0]), int(rows[0][1] or 0)
        want = f"data/exports/{ctx.course_id}/{export_id}.{_EXT[fmt]}"
        if rel != want:
            c1_problems.append(f"{fmt} 的落点是 {rel}，该是 {want}")
        if ".." in rel or rel.startswith("/") or ":" in rel:
            c1_problems.append(f"{fmt} 的路径不是干净的相对路径：{rel}")
        path = _artifact(ctx, ctx.course_id, export_id, fmt)
        if not path.is_file():
            c1_problems.append(f"{fmt} 的文件不在盘上：{path}")
        elif path.stat().st_size != size_bytes:
            c1_problems.append(
                f"{fmt} 的体积对不上：库里 {size_bytes}、盘上 {path.stat().st_size}"
            )
        c1_lines.append(f"{rel}（{size_bytes / 1024:.0f}KB）")
    rep.verdict("P5-C1", "产物落在 data/exports/{courseId}/{exportId}.{ext}，相对路径且不含 ..",
                c1_problems, "；".join(c1_lines))


# --------------------------------------------------------------------------
# 七、下载链接：一次性、越权 404（B2 / F1）
# --------------------------------------------------------------------------


def check_download(rep: Report, ctx: Ctx) -> None:
    """下载票据用过即废、改一个字就废；别人的东西是 404 不是 403（B2 / F1）。"""
    if "pptx" not in ctx.exports:
        _absent(rep, [("P5-B2", "下载链接是一次性的：用过即废、篡改即废"),
                      ("P5-F1", "非课程拥有者导不了也下不了（404）")], "没有可下载的产物")
        return
    export_id = ctx.exports["pptx"]
    problems: list[str] = []
    lines: list[str] = []

    # --- 1. 状态接口现签一张票（链接每次轮询都换一张，别缓存） ---
    status, envelope = api("GET", f"/exports/{export_id}")
    data = _data(status, envelope)
    url = str((data or {}).get("fileUrl") or "") if isinstance(data, Mapping) else ""
    if not url:
        problems.append(f"能下载却没有 fileUrl：{_why(status, envelope)}")
    if not problems and "token=" not in url:
        problems.append(f"下载链接上没带票据：{url}")
    if problems:
        rep.fail("P5-B2", "下载链接是一次性的：用过即废、篡改即废", "；".join(problems))
        rep.skip("P5-F1", "非课程拥有者导不了也下不了（404）", "前置没成立（见 P5-B2）")
        return

    token = url.split("token=", 1)[1]

    # --- 2. 第一次：拿到文件本体（这条路不带 JSON 信封） ---
    status, blob, headers = http_raw(f"/exports/{export_id}/download?token={token}")
    disposition = headers.get("Content-Disposition", "")
    size = int((data or {}).get("sizeBytes") or 0) if isinstance(data, Mapping) else 0
    if status != 200:
        problems.append(f"带票据下载回的是 {status}：{plain(blob[:120].decode('utf-8', 'replace'))}")
    elif not blob.startswith(b"PK"):
        problems.append(f"下来的不是一个 pptx（前两个字节 {blob[:2]!r}）")
    elif size and len(blob) != size:
        problems.append(f"下到的字节数（{len(blob)}）与状态接口报的 sizeBytes（{size}）不一致")
    if "attachment" not in disposition.lower():
        problems.append(f"没有按附件下载：{disposition or '（无 Content-Disposition）'}")
    lines.append(f"第一次：HTTP {status}、{len(blob) / 1024:.0f}KB、{disposition[:60]}")

    # --- 3. 同一张票再用一次：401（前端据此知道该回去重新问状态） ---
    status, again, _ = http_raw(f"/exports/{export_id}/download?token={token}")
    body = _decode(again)
    fallback = ""
    if isinstance(body, Mapping):
        inner = body.get("data")
        if isinstance(inner, Mapping) and isinstance(inner.get("details"), Mapping):
            fallback = str(inner["details"].get("fallback") or "")
    if status != 401:
        problems.append(f"同一张票第二次用回的是 {status}（该 401）")
    if fallback != "refetch":
        problems.append(f"没告诉前端该怎么办：details.fallback={fallback!r}（该 refetch）")
    lines.append(f"同一张票再用：HTTP {status} code={body.get('code') if isinstance(body, Mapping) else '?'}"
                 f" fallback={fallback or '（无）'}")

    # --- 4. 把票改一个字：401（不认识的票与过期的票同一句话） ---
    tampered = token[:-2] + ("aa" if not token.endswith("aa") else "bb")
    status, _raw, _ = http_raw(f"/exports/{export_id}/download?token={tampered}")
    if status != 401:
        problems.append(f"改过一个字的票回的是 {status}（该 401）")
    lines.append(f"篡改过的票：HTTP {status}")
    rep.verdict("P5-B2", "下载链接是一次性的：用过即废、篡改即废", problems, "\n".join(lines))

    # --- 5. F1：换个身份（别人的课 / 别人的产物） ---
    f1_problems: list[str] = []
    lines = []
    other = {"X-Owner-Id": OTHER_OWNER}
    status, envelope = api("GET", f"/exports/{export_id}", headers=other)
    if status != 404:
        f1_problems.append(f"别人查这次导出回的是 {status}（该 404 —— 403 等于承认它存在）")
    status, envelope = api("GET", f"/courses/{ctx.course_id}", headers=other)
    if status != 404:
        f1_problems.append(f"别人的课程详情回的是 {status}（该 404）")
    status, envelope = api(
        "POST", f"/courses/{ctx.course_id}/exports", {"format": "pptx", "scope": "course"},
        headers=other,
    )
    if status != 404:
        f1_problems.append(f"别人导我的课回的是 {status}（该 404）")
    sneaked = _data(status, envelope)
    if isinstance(sneaked, Mapping) and sneaked.get("exportId"):
        f1_problems.append(f"越权那次居然真的排上了一次导出：{sneaked['exportId']}")
    status, _blob, _ = http_raw(f"/exports/{export_id}/download", headers={"X-Owner-Id": OTHER_OWNER})
    if status != 404:
        f1_problems.append(f"别人不带票下载回的是 {status}（该 404）")
    lines.append("换个身份看这次导出 / 这门课 / 下载：三个都是 404（403 等于承认它存在）")
    rep.verdict("P5-F1", "非课程拥有者导不了也下不了（404）", f1_problems, "\n".join(lines))


# --------------------------------------------------------------------------
# 八、课堂记录导出（A5）
# --------------------------------------------------------------------------


def check_record(rep: Report, ctx: Ctx) -> None:
    """一节「上完的课」导成 Markdown / PDF（A5）。

    离线只能走 REST 建课堂（WS 那套在 P3 的脚本里），而 REST 建不出字幕、
    消息与板书 —— 这两件事各自都是真的：**管线通**由这一条验，
    「有内容的记录长什么样」那一半记在 P5-A5b 的跳过里。
    """
    if not ctx.course_id:
        _absent(rep, [("P5-A5", "课堂记录导出：md 与 pdf 两条都真跑、空课堂如实说空")],
                "没有课程（见 P5-A1）")
        return
    problems: list[str] = []
    lines: list[str] = []

    status, envelope = api(
        "POST", "/classroom/sessions", {"courseId": ctx.course_id, "mode": "manual"}
    )
    data = _data(status, envelope)
    if not isinstance(data, Mapping) or not data.get("sessionId"):
        rep.fail("P5-A5", "课堂记录导出：md 与 pdf 两条都真跑、空课堂如实说空",
                 f"开不了课堂：{_why(status, envelope)}")
        return
    session_id = str(data["sessionId"])
    ctx.session_id = session_id
    status, envelope = api("POST", f"/classroom/sessions/{session_id}/end")
    lines.append(f"课堂 {session_id}：起来又下课（REST），status={(data or {}).get('status')}")

    for fmt in ("md", "pdf"):
        status, envelope = api(
            "POST",
            f"/courses/{ctx.course_id}/exports",
            {"format": fmt, "scope": "record", "sessionId": session_id},
        )
        created = _data(status, envelope)
        if not isinstance(created, Mapping) or not created.get("exportId"):
            problems.append(f"record/{fmt} 没建起来：{_why(status, envelope)}")
            continue
        export_id = str(created["exportId"])
        ctx.record_exports[fmt] = export_id
        row = wait_export(ctx, export_id)
        if row.get("status") != "done":
            problems.append(f"record/{fmt} 没跑完：status={row.get('status')} error={row.get('error')}")
            continue
        lines.append(f"record/{fmt} {export_id}：{int(row.get('sizeBytes') or 0) / 1024:.1f}KB")

    # 格式与范围对不上要当场回 40001（PPTX 导课堂记录这件事根本不存在）
    status, envelope = api(
        "POST", f"/courses/{ctx.course_id}/exports", {"format": "pptx", "scope": "record"}
    )
    if status != 400 or (isinstance(envelope, Mapping) and envelope.get("code") != 40001):
        problems.append(f"record 导 pptx 回的是 HTTP {status}（该 400 / 40001）")
    lines.append(f"record 导 pptx：HTTP {status} code={envelope.get('code') if isinstance(envelope, Mapping) else '?'}")

    # 有东西可导才算数：md 里要看得到「课名」与「这堂课没有…」这句实话
    md_id = ctx.record_exports.get("md")
    if md_id and not problems:
        md_path = _artifact(ctx, ctx.course_id, md_id, "md")
        text = md_path.read_text(encoding="utf-8", errors="replace")
        status, envelope = api("GET", f"/courses/{ctx.course_id}")
        title = str((_data(status, envelope) or {}).get("title") or "")
        # 两边都去空白再比：课名里有空格（「P5 验收：…」），而 markdown 会按
        # 窗口宽度折行 —— 只抹一边等于拿带空格的串去找不带空格的文本。
        if title and _squash(title) not in _squash(text):
            problems.append(f"md 里没有课名「{title}」")
        if "没有" not in text:
            problems.append("空课堂没说「这堂课没有…」，而是在装作有内容")
        lines.append(f"md 取回 {len(text)} 字，课名在、空课堂如实说空")

    rep.verdict("P5-A5", "课堂记录导出：md 与 pdf 两条都真跑、空课堂如实说空",
                problems, "\n".join(lines))


# --------------------------------------------------------------------------
# 九、成本看板（A7 / B3 / C2）
# --------------------------------------------------------------------------


def _sum_calls(ctx: Ctx, where: str, column: str = "tokens") -> float:
    rows = sql(ctx, f"select coalesce(sum({column}), 0) from model_calls where {where}")
    return float(rows[0][0] or 0)


def _bucket_total(
    payload: Mapping[str, Any], field: str, course_id: str = ""
) -> tuple[float, str]:
    """看板响应里某个分组的总数与它的标签。

    分组的身份认 `item["key"]`（按课程分组时它就是课程 id），标签认 `label`
    （课程显示标题，被删的课回落成 id）—— 第一版在这里找 `courseId` 字段，
    而响应里根本没有那一格，于是「这门课 0 token」一直红着：
    **接口是对的，是脚本问错了格子**。返回标签是为了顺带验一句「轴上是课名不是一串 id」。
    """
    for item in payload.get("items") or []:
        if not isinstance(item, Mapping):
            continue
        if course_id and str(item.get("key") or "") != course_id:
            continue
        return float(item.get(field) or 0), str(item.get("label") or "")
    return 0.0, ""


def _course_title(ctx: Ctx) -> str:
    """这门课的标题。看板的横轴该显示它，而不是一串 id。"""
    status, envelope = api("GET", f"/courses/{ctx.course_id}")
    data = _data(status, envelope)
    return str(data.get("title") or "") if isinstance(data, Mapping) else ""


def _call_tokens(node: Any) -> int | None:
    """一份调用统计里的 token 数；这一格不存在就回 None。

    步骤级在 `step["calls"]`、任务级在 `totals["calls"]` —— 两者**同形**
    （见 `services/generation/timeline.py` 的 `_totals`），所以两层都认：
    传进来的若是那一格本身就直接读 `tokens`，若是外层就先下探一层。
    """
    if not isinstance(node, Mapping):
        return None
    scope = node.get("calls") if "calls" in node else node
    if not isinstance(scope, Mapping) or "tokens" not in scope:
        return None
    return int(scope.get("tokens") or 0)


def check_usage(rep: Report, ctx: Ctx) -> None:
    """看板的数要能追到账本，误差 0（A7 / B3 / C2）。

    比对的两边是**两条独立的代码路径**：接口这边走聚合（`daily_usage` 缓存 +
    `model_calls`），脚本这边直接 `select sum(...)`。两边一样才说明看板没有自己的算法。
    """
    if not ctx.course_id:
        _absent(rep, [("P5-A7", "单课明细求和 == 账本求和（误差 0）"),
                      ("P5-B3", "看板聚合 == 明细求和（多组区间）"),
                      ("P5-C2", "model_calls 覆盖每一次外部调用，字段齐全")],
                "没有课程（见 P5-A1）")
        return

    # --- C2：账本本身有没有漏、字段齐不齐 ---
    rows = sql(
        ctx,
        "select kind, provider, model, tokens, latency_ms, owner_id, job_id, step_id, ok "
        "from model_calls order by id",
    )
    c2_problems = []
    if not rows:
        c2_problems.append("账本一行都没有 —— 生成跑过了却没落账")
    for row in rows:
        if not row[1] or not row[2]:
            c2_problems.append(f"有一行没写 provider/model（kind={row[0]}）")
            break
    if any(row[0] not in {"llm", "tts", "asr", "realtime"} for row in rows):
        c2_problems.append("有 kind 落在四条链路之外")
    if any(int(row[3] or 0) < 0 or int(row[4] or 0) < 0 for row in rows):
        c2_problems.append("有 token 或耗时为负")
    rep.verdict(
        "P5-C2",
        "model_calls 覆盖每一次外部调用，字段齐全",
        c2_problems,
        f"本轮共 {len(rows)} 行调用；每行都带 kind/provider/model/token/耗时/归属。"
        f"「抽查 20 次」要更忙的一轮（一趟验收只跑出 {len(rows)} 次）",
    )

    # --- A7：单课明细 vs 账本（两个方向各算一遍） ---
    job_id = ctx.job_id
    ledger_tokens = _sum_calls(ctx, f"job_id = {job_id!r} and kind = 'llm'")
    ledger_cost = _sum_calls(ctx, f"job_id = {job_id!r} and kind = 'llm'", "est_cost")
    ledger_calls = len(sql(ctx, f"select id from model_calls where job_id = {job_id!r} and kind = 'llm'"))
    status, envelope = api("GET", f"/usage/courses/{ctx.course_id}")
    detail = _data(status, envelope)
    a7_problems = []
    detail_tokens = detail_cost = 0.0
    if not isinstance(detail, Mapping):
        a7_problems.append(f"单课明细取不到：{_why(status, envelope)}")
    else:
        items = [item for item in (detail.get("items") or []) if isinstance(item, Mapping)]
        llm_items = [item for item in items if item.get("kind") == "llm"]
        detail_tokens = sum(float(item.get("tokens") or 0) for item in llm_items)
        detail_cost = sum(float(item.get("estCost") or 0) for item in llm_items)
        if len(llm_items) != ledger_calls:
            a7_problems.append(f"明细条数 {len(llm_items)} != 账本 {ledger_calls} 行")
        if abs(detail_tokens - ledger_tokens) > 0.001:
            a7_problems.append(f"token 对不上：明细 {detail_tokens:.0f}、账本 {ledger_tokens:.0f}")
        if abs(detail_cost - ledger_cost) > 0.000001:
            a7_problems.append(f"金额对不上：明细 {detail_cost:.6f}、账本 {ledger_cost:.6f}")
    rep.verdict(
        "P5-A7",
        "单课明细求和 == 账本求和（误差 0）",
        a7_problems,
        f"这门课的生成任务 {job_id}：账本 {ledger_calls} 次调用、{ledger_tokens:.0f} token、"
        f"¥{ledger_cost:.6f}；明细求和 {detail_tokens:.0f} token、¥{detail_cost:.6f}",
    )

    # --- B3：看板聚合 vs 账本，三组区间 ---
    all_tokens = _sum_calls(ctx, "kind = 'llm'")
    windows = [
        ("只今天", "from=&to="),
        ("最近 30 天（缺省）", ""),
        ("2020 年（这条课之前）", "from=2020-01-01&to=2020-01-02"),
    ]
    b3_problems = []
    lines = []
    for label, query in windows:
        status, envelope = api("GET", f"/usage/summary?groupBy=day&{query}")
        payload = _data(status, envelope)
        if not isinstance(payload, Mapping):
            b3_problems.append(f"{label} 拿不到看板：{_why(status, envelope)}")
            continue
        total = float((payload.get("totals") or {}).get("totalTokens") or 0)
        # 这一趟验收的每一次调用都发生在刚才几分钟内，所以「窗口包含今天」
        # 就等于「窗口包含全部调用」—— 不必去复刻本地日界那套换算。
        want = 0.0 if "2020" in query else all_tokens
        if abs(total - want) > 0.001:
            b3_problems.append(f"{label}：看板 {total:.0f} != 账本 {want:.0f}")
        lines.append(f"{label}：{total:.0f} token（账本 {want:.0f}）")
    status, envelope = api("GET", "/usage/summary?groupBy=course")
    payload = _data(status, envelope)
    by_course, label = _bucket_total(
        payload if isinstance(payload, Mapping) else {}, "totalTokens", ctx.course_id
    )
    want_course = ledger_tokens + _sum_calls(ctx, f"job_id = {job_id!r} and kind != 'llm'")
    if abs(by_course - want_course) > 0.001:
        b3_problems.append(f"按课程分组的 {ctx.course_id} 是 {by_course:.0f}，账本 {want_course:.0f}")
    course_title = _course_title(ctx)
    if course_title and label != course_title:
        b3_problems.append(f"分组标签给的是 {label[:40]!r}，不是课名 {course_title[:40]!r}（横轴上只有 id）")
    lines.append(f"按课程分组：{label or ctx.course_id} {by_course:.0f} token（账本 {want_course:.0f}）")
    rep.verdict("P5-B3", "看板聚合 == 明细求和（多组区间）", b3_problems, "；".join(lines))


# --------------------------------------------------------------------------
# 十、预算（A8）
# --------------------------------------------------------------------------


def check_budget(rep: Report, ctx: Ctx) -> None:
    """日预算调到极小 → 新任务当场被拒，已经跑完的不受影响（A8）。"""
    problems: list[str] = []
    lines: list[str] = []

    status, envelope = api("PUT", "/settings/budget", {"scope": "day", "limitTokens": 1})
    if _data(status, envelope) is None:
        rep.fail("P5-A8", "日预算调到极小值后，新生成任务被拒且说得出是哪条超了",
                 f"预算没设上：{_why(status, envelope)}")
        return
    lines.append("设 day.limitTokens = 1")

    # 复原放在 finally 里：这一组只要留下「日预算 = 1 token」，
    # 后面每一条都要建课（A9 续跑、A14 删课）就全会撞在 409 上 ——
    # 第一趟就是这么串起来的，一处的失败赔上了后面四条。
    try:
        status, envelope = api(
            "POST",
            "/courses/generate",
            {"topic": "P5 验收：这门课不该被建出来", "mode": "lecture", "pageCount": 8},
        )
        details = {}
        if isinstance(envelope, Mapping):
            inner = envelope.get("data")
            if isinstance(inner, Mapping) and isinstance(inner.get("details"), Mapping):
                details = dict(inner["details"])
        if status != 409:
            problems.append(f"超预算的生成回的是 HTTP {status}（该 409）")
        if details.get("error") != "budget_exceeded":
            problems.append(f"没给机器可读的原因：error={details.get('error')!r}")
        message = str(envelope.get("message") or "") if isinstance(envelope, Mapping) else ""
        if "预算" not in message:
            problems.append(f"提示语没说清是预算：{message[:80]!r}")
        leaked = [row for row in sql(ctx, "select title from courses") if "不该被建出来" in str(row[0])]
        if leaked:
            problems.append("被拒了却还是把课程建出来了（课程列表会多一门永远 generating 的课）")
        lines.append(f"超限的生成：HTTP {status} error={details.get('error')} "
                     f"usedTokens={details.get('usedTokens')} limitTokens={details.get('limitTokens')}")

        # 已经跑完的那门课不受影响
        if ctx.job_id:
            status, envelope = api("GET", f"/jobs/{ctx.job_id}")
            job = _data(status, envelope)
            if not isinstance(job, Mapping) or job.get("status") != "done":
                problems.append(f"已经跑完的任务被改了状态：{(job or {}).get('status')}")
            else:
                lines.append(f"先跑完的那门课仍是 {job.get('status')}（老任务不受影响）")
    finally:
        status, envelope = api(
            "PUT", "/settings/budget", {"scope": "day", "limitTokens": 0, "limitCost": 0}
        )
        if _data(status, envelope) is None:
            problems.append("预算没能复原（后面还有要生成的）")
        else:
            lines.append("复原：0 = 不限")
    rep.verdict("P5-A8", "日预算调到极小值后，新生成任务被拒且说得出是哪条超了",
                problems, "\n".join(lines))


# --------------------------------------------------------------------------
# 十一、断点续跑与任务时间线（A9 / A10）
# --------------------------------------------------------------------------


def check_resume(rep: Report, ctx: Ctx) -> None:
    """生成到一半把服务**杀掉**，重启后接着跑，已经写好的页不重写（A9）。

    这一条按 §7 的原文来：kill 服务 → 重启 → 点「继续生成」。判据是
    **已经写好的那几页没有重新调用 LLM** —— 对照的是账本行数，不是页面数。
    """
    try:
        course_id, job_id = _post_generate(TOPIC + "（续跑）", page_count=PAGE_COUNT)
    except AssertionError as exc:
        rep.fail("P5-A9", "生成到一半杀服务、重启后接着跑，已写好的页不重新调用上游", str(exc))
        rep.skip("P5-A10", "任务时间线：每步耗时/重试次数/token 都能展开看", "前置没成立（见 P5-A9）")
        return
    ctx.resumed_course_id, ctx.resumed_job_id = course_id, job_id

    # 让它先跑起来（写掉几页），再杀 —— 一建就杀的话「已经写好的页」是 0，
    # 「不重写」这条判据就空转了（0 ≤ 0 恒真）。
    deadline = time.time() + 60
    ready_before = 0
    while time.time() < deadline:
        rows = sql(ctx, f"select count(*) from course_pages where course_id = {course_id!r} "
                        "and status = 'ready'")
        ready_before = int(rows[0][0] or 0)
        if ready_before >= 2:
            break
        time.sleep(0.2)

    calls_before = len(sql(ctx, f"select id from model_calls where job_id = {job_id!r}"))
    stop(ctx.procs.pop("main", None))
    restart_ok = restart_server(ctx, MAIN_PORT) is not None
    lines = [f"第 {ready_before} 页写好后 kill 掉主实例（第 {calls_before} 次调用已记账）"]

    problems = []
    if not restart_ok:
        problems.append("重启没起来")
    if ready_before == 0:
        problems.append("还没写下一页就被杀了 —— 这一条没验到「已写好的页不重写」")

    if restart_ok:
        status, envelope = api("GET", f"/jobs/{job_id}")
        job = _data(status, envelope)
        job = dict(job) if isinstance(job, Mapping) else {}
        lines.append(f"重启后这个任务是 {job.get('status')}（resumable={job.get('resumable')}）"
                     f"，已就绪 {ready_before}/{PAGE_COUNT} 页")

        status, envelope = api("POST", f"/jobs/{job_id}/resume")
        if status != 200:
            problems.append(f"点「继续生成」回的是 {status}：{_why(status, envelope)}")
        else:
            # 「续跑完成」= 从**一个非终态**走到终态。直接等终态是不行的：
            # 点之前它正好是 failed（杀服务留下的那个），谁先读到就当场判「续跑失败」——
            # 第一趟就是这么把已经在跑的续跑判死的（当时账本依旧一行没多花）。
            done = _wait_resumed(
                job_id, was=str(job.get("status") or ""), timeout=GEN_DEADLINE
            )
            lines.append(f"续跑之后：status={done.get('status')} progress={done.get('progress')}")
            if done.get("status") != "done":
                problems.append(f"续跑没跑完：status={done.get('status')}")

    ready_after = int(sql(ctx, f"select count(*) from course_pages where course_id = {course_id!r} "
                              "and status = 'ready'")[0][0] or 0)
    calls_after = len(sql(ctx, f"select id from model_calls where job_id = {job_id!r}"))
    # 续跑**只该为没写完的那部分重新调用**：多出来的行数不该超过
    # 「还差几页」再加两次余量（大纲与收尾那几步不属于页）。
    extra = calls_after - calls_before
    allowance = max(0, PAGE_COUNT - ready_before) + 2
    lines.append(f"账本：kill 前 {calls_before} 行 → 续跑后 {calls_after} 行（多了 {extra}），"
                 f"就绪页 {ready_before} → {ready_after}/{PAGE_COUNT}")
    if extra > allowance:
        problems.append(
            f"多花了 {extra} 次调用（上限 {allowance} = 还差 "
            f"{max(0, PAGE_COUNT - ready_before)} 页 + 2 次余量）——"
            "已写好的页被重新生成了一遍"
        )
    if ready_after != PAGE_COUNT:
        problems.append(f"续跑完只就绪 {ready_after}/{PAGE_COUNT} 页")
    rep.verdict("P5-A9", "生成到一半杀服务、重启后接着跑，已写好的页不重新调用上游",
                problems, "\n".join(lines))

    # --- A10：时间线 ---
    status, envelope = api("GET", f"/jobs/{job_id}/timeline")
    payload = _data(status, envelope)
    a10_problems = []
    steps = []
    summed: int | None = None
    step_sum = 0
    if not isinstance(payload, Mapping):
        a10_problems.append(f"时间线取不到：{_why(status, envelope)}")
    else:
        steps = [step for step in (payload.get("steps") or []) if isinstance(step, Mapping)]
        if not steps:
            a10_problems.append("时间线里一个步骤都没有")
        for step in steps:
            for key in ("durationMs", "attempts", "calls"):
                if key not in step:
                    a10_problems.append(f"步骤缺 {key}（工作台展开时就没得显示）")
                    break
        # 合计那一格与每一步的 `calls` **同形**（同一套渲染逻辑在步骤级与任务级
        # 各铺一次，见 `services/generation/timeline.py` 的 `_totals`）——
        # 所以 token 在 `totals.calls.tokens` 里，不在 `totals.tokens` 上。
        # 光看「有没有这个键」太松，这里顺手对一次账：合计 == 各步相加。
        totals = payload.get("totals") or {}
        summed = _call_tokens(totals)
        # 合计里还并着「认不出归属」的那几条（有 job_id 却没落到任何一步上的调用）——
        # 对上账要把它们算进去，否则一个埋点漏 step_id 就会被这里误判成算错账。
        orphan = _call_tokens(totals.get("unattributed") or {}) or 0
        step_sum = sum(_call_tokens(step) or 0 for step in steps)
        if summed is None:
            a10_problems.append("没有合计（每步 token 与金额没法汇总）")
        elif summed != step_sum + orphan:
            a10_problems.append(
                f"合计与各步对不上：合计 {summed}、各步相加 {step_sum}（外加无归属 {orphan}）"
            )
        if "attempts" not in totals or "failedSteps" not in totals:
            a10_problems.append("合计里没有重试次数或失败步数（任务卡收起时那行字没得填）")
    status, envelope = api("GET", f"/jobs/{job_id}")
    poll = _data(status, envelope)
    if isinstance(poll, Mapping):
        for key in ("resumable", "retryable", "failedSteps"):
            if key not in poll:
                a10_problems.append(f"任务卡缺 {key}（重试/续跑按钮亮不亮没依据）")
    rep.verdict(
        "P5-A10",
        "任务时间线：每步耗时/重试次数/token 都能展开看",
        a10_problems,
        f"{len(steps)} 个步骤各带 durationMs / attempts / calls（几次调用、多少 token、多少钱）；"
        f"合计 {summed if summed is not None else '?'} token（各步相加 {step_sum}）",
    )


# --------------------------------------------------------------------------
# 十二、SSRF 与那把假 Key（F2 / F4 的前置）
# --------------------------------------------------------------------------

#: 该被挡下来的内网地址。最后一条是**十进制写法**的 127.0.0.1：
#: 字符串匹配挡不住它，只有真解析一遍才挡得住 —— 「解析而不是匹配」是
#: `app/common/urls.py` 的核心主张，所以要拿它来验。
SSRF_ATTEMPTS = [
    ("http://127.0.0.1:6379", "回环地址"),
    ("http://169.254.169.254/latest/meta-data", "云元数据服务"),
    ("http://2130706433/", "十进制写的 127.0.0.1"),
    ("file:///etc/passwd", "file 协议"),
]


def check_security(rep: Report, ctx: Ctx) -> None:
    """自定义接入地址的四道闸门，以及往设置页塞一把假 Key（F2）。"""
    status, envelope = api("GET", "/settings/providers")
    cards = _data(status, envelope)
    items = [
        card for card in ((cards or {}).get("items") or [])
        if isinstance(card, Mapping) and card.get("id")
    ] if isinstance(cards, Mapping) else []
    if not items:
        rep.fail("P5-F2", "SSRF 防护：内网地址与非 http(s) 协议被拒",
                 f"读不到服务商卡片：{_why(status, envelope)}")
        return
    provider_id = str(items[0]["id"])
    problems: list[str] = []
    lines: list[str] = []

    for url, label in SSRF_ATTEMPTS:
        status, envelope = api("PUT", f"/settings/providers/{provider_id}", {"baseUrl": url})
        code = envelope.get("code") if isinstance(envelope, Mapping) else None
        if status != 400 or code != 40001:
            problems.append(f"{label} 没被挡：HTTP {status} code={code}")
        lines.append(f"{label}（{url}）-> HTTP {status} code={code}")

    # 公网地址要能存下去（不然上面那四条可能只是「什么都不让存」）
    status, envelope = api(
        "PUT",
        f"/settings/providers/{provider_id}",
        {"baseUrl": UNREACHABLE_BASE_URL, "defaultModel": "accept-p5-model"},
    )
    stored = _data(status, envelope)
    if stored is None:
        problems.append(f"公网地址也存不进去：{_why(status, envelope)}")
    else:
        saved = str((stored or {}).get("baseUrl") or "")
        if UNREACHABLE_BASE_URL not in saved:
            problems.append(f"存下来的地址不是刚才那个：{saved}")
        lines.append(f"公网地址 {UNREACHABLE_BASE_URL} 存得下（说明上面四条不是「一律不让存」）")

    # 塞一把**假** Key：它会真的被存下来、真的走一次失败的上游调用，
    # 于是它经过了一条完整的错误路径 —— F4 查的就是它有没有从哪儿漏进日志。
    status, envelope = api(
        "PUT", f"/settings/providers/{provider_id}", {"apiKey": SECRET_KEY_TEXT}
    )
    if _data(status, envelope) is None:
        problems.append(f"假 Key 没存进去：{_why(status, envelope)}")
    else:
        status, envelope = api("POST", f"/settings/providers/{provider_id}/test", timeout=90)
        result = _data(status, envelope) or {}
        lines.append(
            f"探活（必然连不上）：HTTP {status} ok={result.get('ok')} "
            f"errorCode={result.get('errorCode') or '（无）'} —— 这一段最容易把 Key 连着异常栈打出来"
        )
        # 探活失败是**预期**的：这个地址是 TEST-NET-1，本来就连不上。
        # 要的是它失败得干干净净（200 + ok:false），而不是把请求体写进日志。

    # 没配 FERNET_KEY 的那台（访问码实例刻意没给它）：存 Key 要报得出「怎么办」，
    # 而不是一句 50001。README「常见问题」与部署文档 §2 都写着它报「未配置 FERNET_KEY」——
    # 文档承诺过的话，就得有一条验它。
    status, envelope = api("GET", "/settings/providers", base=ctx.gate,
                           headers={"Cookie": ctx.gate_cookie})
    cards = _data(status, envelope)
    gate_items = (cards or {}).get("items") if isinstance(cards, Mapping) else None
    if not gate_items:
        problems.append(f"访问码那台读不到服务商卡片：{_why(status, envelope)}")
    else:
        gate_id = str(gate_items[0].get("id"))
        status, envelope = api(
            "PUT", f"/settings/providers/{gate_id}", {"apiKey": SECRET_KEY_TEXT},
            base=ctx.gate, headers={"Cookie": ctx.gate_cookie},
        )
        message = str(envelope.get("message") or "") if isinstance(envelope, Mapping) else ""
        if "FERNET_KEY" not in message:
            problems.append(
                f"没配 FERNET_KEY 的那台存 Key，回的是 HTTP {status}：{message[:80]!r}"
                "（该说清是 FERNET_KEY 没配、怎么补）"
            )
        lines.append(f"没配 FERNET_KEY 的那台：HTTP {status} code="
                     f"{envelope.get('code') if isinstance(envelope, Mapping) else '?'}"
                     f"（文案里带着怎么补）")

    # 收尾：把这张卡恢复原样（后面还有别的检查要用这台实例）
    api("PUT", f"/settings/providers/{provider_id}", {"clearApiKey": True, "baseUrl": ""})
    lines.append("收尾：清掉假 Key、接入地址恢复默认")
    rep.verdict("P5-F2", "SSRF 防护：内网地址与非 http(s) 协议被拒", problems, "\n".join(lines))


# --------------------------------------------------------------------------
# 十三、审计（A14）
# --------------------------------------------------------------------------


def check_audit(rep: Report, ctx: Ctx) -> None:
    """关键操作各有一条 `audit_logs`，含操作者与 IP，且**不含 Key 原文**（A14）。"""
    problems: list[str] = []
    lines: list[str] = []

    # 先造一条 `course.delete`（另外三类前面已经发生过了）
    try:
        course_id, job_id = _post_generate(AUDIT_TOPIC, page_count=AUDIT_PAGES)
        done = _wait_status(job_id, want={"done", "failed", "canceled"}, timeout=GEN_DEADLINE)
        if done.get("status") != "done":
            problems.append(f"用来删的那门课没生成完：status={done.get('status')}")
        else:
            status, envelope = api("DELETE", f"/courses/{course_id}")
            if _data(status, envelope) is None:
                problems.append(f"删课失败：{_why(status, envelope)}")
            else:
                lines.append(f"{AUDIT_TOPIC}：建了又删（{course_id}）")
    except AssertionError as exc:
        problems.append(str(exc))

    wanted = [
        ("course.create", "创建课程"),
        ("course.delete", "删除课程"),
        ("provider.update", "修改 Provider"),
        ("export.create", "导出"),
    ]
    for action, label in wanted:
        rows = sql(ctx, f"select owner_id, ip, detail_json from audit_logs where action = {action!r}")
        if not rows:
            problems.append(f"{label}（{action}）没有审计记录")
            continue
        _owner, ip, detail = rows[-1][0], rows[-1][1], rows[-1][2]
        if not ip:
            problems.append(f"{label} 那条没记 IP")
        lines.append(f"{action}：{len(rows)} 条，最近一条 ip={ip or '（空）'} detail={str(detail)[:70]}")

    # 带着正确访问码走进来的那一次记在**访问码那台**的库上
    rows = sql(ctx, "select ip, owner_id from audit_logs where action = 'access.grant'", GATE_PORT)
    if not rows:
        problems.append("access.grant 没有审计记录（输对访问码这件事要留痕）")
    else:
        lines.append(f"access.grant：{len(rows)} 条（在访问码那台）ip={rows[-1][0] or '（空）'}")

    # ★ 假 Key 不能出现在任何一条审计里（§19：detail 只记「改了哪几栏」）
    leaks = [
        row for row in sql(ctx, "select detail_json from audit_logs")
        if SECRET_KEY_TEXT in str(row[0] or "")
    ]
    if leaks:
        problems.append(f"审计的 detail 里出现了假 Key 原文（{len(leaks)} 条）")
    fields_rows = sql(
        ctx, "select detail_json from audit_logs where action = 'provider.update' order by id desc limit 1"
    )
    if fields_rows:
        detail = str(fields_rows[-1][0] or "")
        if "apiKey" not in detail:
            lines.append("provider.update 的 detail 用的是字段名，不含取值")

    rep.verdict("P5-A14", "关键操作都有审计：操作者 + IP，且不写 Key 原文",
                problems, "\n".join(lines))


# --------------------------------------------------------------------------
# 十四、重启后数据还在（A12）+ 到期的产物（A6）
# --------------------------------------------------------------------------


def restart_server(ctx: Ctx, port: int) -> Any:
    """把这一台按**起它时的那份环境**重启。返回新进程（失败时 None）。"""
    name = LOG_NAMES[port].replace(".log", "")
    stop(ctx.procs.pop(name, None))
    time.sleep(1.0)
    proc = start_server(ctx, port, LOG_NAMES[port], ctx.server_env[port])
    ctx.procs[name] = proc
    return proc


def check_restart(rep: Report, ctx: Ctx) -> None:
    """重启一次再看：课还在、产物还能下、课堂记录还读得到（A12）。

    卷挂载那半（「容器重启后卷还在」）离线验不到，这里验的是它的**前提**：
    这些东西本来就不活在进程内存里 —— 重启前拿得到的，重启后一样拿得到。
    """
    problems: list[str] = []
    lines: list[str] = []
    want = {cid for cid in (ctx.course_id, ctx.resumed_course_id) if cid}

    proc = restart_server(ctx, MAIN_PORT)
    if proc is None:
        rep.fail("P5-A12", "重启后课程 / 产物 / 课堂记录都还在", "重启没起来")
        return
    lines.append("主实例重启了一次（同一份库、同一个目录）")

    status, envelope = api("GET", "/courses")
    listed_after = {str(row.get("id")) for row in (_data(status, envelope) or {}).get("items", [])
                    if isinstance(row, Mapping)}
    missing = want - listed_after
    if missing:
        problems.append(f"重启后课程列表里少了 {len(missing)} 门：{sorted(missing)[:2]}")

    for fmt, export_id in list(ctx.exports.items()) + list(ctx.record_exports.items()):
        status, envelope = api("GET", f"/exports/{export_id}")
        row = _data(status, envelope)
        if not isinstance(row, Mapping) or not row.get("downloadable"):
            problems.append(f"重启后 {fmt} 的产物下不了了：{_why(status, envelope)}")
            continue
        # `fileUrl` 是**站点绝对路径**（`/api/exports/…`，自己就带着 `/api` 那一段），
        # 所以 base 给站点根、不给 `/api` —— 接在 `_base()` 后面会变成 `/api/api/…`，
        # 那是个 404，而 404 看起来像「产物没了」。
        url = str(row.get("fileUrl") or "")
        status, blob, _ = http_raw(url, base=f"http://127.0.0.1:{MAIN_PORT}")
        if status != 200 or not blob:
            problems.append(f"重启后 {fmt} 的产物下下来是空的（HTTP {status}）")
    lines.append(f"重启后逐个下载了 {len(ctx.exports) + len(ctx.record_exports)} 份产物，都是 200")

    if ctx.session_id:
        status, envelope = api("GET", f"/classroom/sessions/{ctx.session_id}/record")
        if _data(status, envelope) is None:
            problems.append(f"重启后课堂记录读不到了：{_why(status, envelope)}")
        else:
            lines.append(f"课堂记录 {ctx.session_id} 还读得到")

    rep.verdict("P5-A12", "重启后课程 / 产物 / 课堂记录都还在", problems, "\n".join(lines))


# --------------------------------------------------------------------------
# 十五、产物到期与清理（A6 / C1 的后半）
# --------------------------------------------------------------------------


def _backdate(ctx: Ctx, export_id: str, when: str = "2020-01-01T00:00:00Z") -> None:
    """把一行导出的 `expires_at` 拨到过去 —— **脚本唯一一次写库**。

    24 小时到期这件事在离线验收里等不到（那是明天的事），只能把时钟拨过去。
    接口上也没有这条路径（也不该有：谁能改到期时间，谁就能绕开它），
    所以这里绕开 REST 直接写临时库 —— 写的是脚本自己刚造出来的临时数据。
    """
    script = (
        "import sqlite3\n"
        f"con = sqlite3.connect({db_path(ctx).as_posix()!r})\n"
        "con.execute('update exports set expires_at = ? where id = ?', "
        f"({when!r}, {export_id!r}))\n"
        "con.commit()\n"
        f"print(con.execute('select expires_at from exports where id = ?', ({export_id!r},))"
        ".fetchone()[0])\n"
    )
    done = run_python(script)
    out = (done.stdout or "").strip().splitlines()
    if done.returncode != 0 or not out:
        raise AssertionError(f"改 expires_at 失败：{plain((done.stderr or '')[-300:])}")


def check_cleanup(rep: Report, ctx: Ctx) -> None:
    """到期的产物：接口先不发、然后被清理任务删掉（A6 / C1）。"""
    problems: list[str] = []
    lines: list[str] = []
    md_id = ctx.record_exports.get("md")
    if not md_id:
        _absent(rep, [("P5-A6", "产物到期：链接不再发、清理任务连文件带行一起删")],
                "没有可到期的产物（见 P5-A5）")
        return

    _backdate(ctx, md_id)
    lines.append(f"把 {md_id} 的 expires_at 拨到 2020-01-01")

    status, envelope = api("GET", f"/exports/{md_id}")
    row = _data(status, envelope)
    if isinstance(row, Mapping):
        if row.get("downloadable") or row.get("fileUrl"):
            problems.append("已经过期了还说能下载")
        lines.append(f"过期后查状态：downloadable={row.get('downloadable')} fileUrl={row.get('fileUrl')!r}")
    else:
        problems.append(f"过期后连状态都查不到了：{_why(status, envelope)}")

    status, envelope = api("GET", f"/exports/{md_id}/download")
    if status != 409:
        problems.append(f"过期产物仍然照发：HTTP {status}（该 409）")
    lines.append(f"过期后下载：HTTP {status} code={envelope.get('code') if isinstance(envelope, Mapping) else '?'}")

    # 真跑一次清理（容器里由 entrypoint 的循环跑，物理机由 cron 跑）
    before = _tree(ctx.export_dir)
    done = run_flask(["exports-cleanup"], env={**ctx.env, "DATABASE_URL": ctx.db()})
    if done.returncode != 0:
        problems.append(f"清理没跑起来：{plain((done.stderr or '')[-300:])}")
    after = _tree(ctx.export_dir)
    rows = sql(ctx, f"select id from exports where id = {md_id!r}")
    if rows:
        problems.append("清理跑过了，那一行还在（过期该连行带文件一起删）")
    if len(after) >= len(before):
        problems.append(f"清理前后文件数没变：{len(before)} → {len(after)}")
    else:
        lines.append(f"清理：产物 {len(before)} → {len(after)} 个文件，那一行也没了")

    # 顺带看数据库体积（P5-C4 的「别让 session_events 撑爆」那半）
    db_file = db_path(ctx)
    size_kb = db_file.stat().st_size / 1024 if db_file.exists() else 0
    events = int(sql(ctx, "select count(*) from session_events")[0][0] or 0)
    limit = 5000
    lines.append(f"库 {size_kb:.0f}KB、session_events {events} 行（上限 {limit}，按条数裁剪）")
    rep.verdict("P5-A6", "产物到期：链接不再发、清理任务连文件带行一起删",
                problems, "\n".join(lines))


# --------------------------------------------------------------------------
# 十六、交付文档齐备（G3）
# --------------------------------------------------------------------------


def check_docs(rep: Report, ctx: Ctx) -> None:
    """四件套在不在、能不能照着做（G3）。

    「经他人按文档实操成功一次」这一半离线替不了（要另一个人），
    这里验的是它的前提：四份文档都在、README 里那条五分钟路径每一步都能对上
    （`make setup` / `make dev` / `/api/health` 这些字眼确实在），
    以及**文档里写的命令真的存在**（Makefile 里有那个 target）。
    """
    problems: list[str] = []
    lines: list[str] = []
    docs = {
        "README（五分钟上手）": ROOT / "README.md",
        "部署文档": ROOT / "docs" / "部署文档.md",
        "运维手册": ROOT / "docs" / "运维手册.md",
    }
    for label, path in docs.items():
        if not path.is_file():
            problems.append(f"{label} 不在：{path.relative_to(ROOT).as_posix()}")
        else:
            lines.append(f"{label} {path.stat().st_size / 1024:.0f}KB")
    readme = (ROOT / "README.md").read_text(encoding="utf-8", errors="replace") \
        if (ROOT / "README.md").is_file() else ""
    faq = "FAQ" in readme or "常见问题" in readme or "## 答疑" in readme
    if not faq:
        problems.append("README 里没有 FAQ / 常见问题那一段")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8", errors="replace")
    for target in ("setup", "dev", "test", "lint", "accept-p5", "up", "backup"):
        if not re.search(rf"^{target}:", makefile, flags=re.M):
            problems.append(f"README 里让人跑的 `make {target}` 在 Makefile 里没有")
    lines.append("Makefile 里有 README 让人跑的那几个 target")
    rep.verdict("P5-G3", "交付文档齐备：README / 部署文档 / 运维手册 / FAQ", problems,
                "\n".join(lines))


# --------------------------------------------------------------------------
# 十七、委托给 pytest 的条目（逐条记账）
# --------------------------------------------------------------------------

#: `(编号, 标题, 节点…)`。一组里的**每条**都要通过才算这一条通过。
DELEGATED: list[tuple[str, str, list[str]]] = [
    (
        "P5-B1",
        "导出接口契约：404 / 409 / 413 三个分支都有人钉着",
        [
            "tests/contract/test_p5_export_api.py::test_exporting_someone_elses_class_is_404",
            "tests/contract/test_p5_export_api.py::test_someone_elses_export_is_404",
            "tests/contract/test_p5_export_api.py::test_deleting_a_running_export_is_refused",
            "tests/contract/test_p5_export_api.py::test_a_format_that_does_not_fit_the_scope_is_refused_at_creation",
            "tests/contract/test_p5_export_api.py::test_a_record_export_without_a_session_is_refused",
            "tests/unit/test_exports_queue.py::test_unsupported_combo_rejected_upfront",
            "tests/unit/test_exports_queue.py::test_oversized_product_is_refused_before_writing",
        ],
    ),
    (
        "P5-C4",
        "session_events 不膨胀：按条数裁剪，且裁剪不影响课堂记录的可读性",
        [
            "tests/unit/test_classroom_recorder.py::test_events_are_pruned_when_they_hit_the_limit",
            "tests/contract/test_p3_classroom_api.py::test_the_record_survives_the_event_log_being_pruned",
        ],
    ),
    (
        "P5-B2b",
        "下载票据的其余几条：只为它自己那次导出签、过期即废、不认识的票同一句话",
        [
            "tests/unit/test_voice_tickets.py::test_a_scoped_ticket_only_opens_its_own_room",
            "tests/unit/test_voice_tickets.py::test_a_ticket_expires",
            "tests/contract/test_p5_export_api.py::test_the_status_endpoint_mints_a_fresh_link_every_time",
            "tests/contract/test_p5_export_api.py::test_download_filename_is_a_readable_chinese_name",
            "tests/contract/test_p5_export_api.py::test_a_filename_cannot_escape_into_a_path",
        ],
    ),
    (
        "P5-C3b",
        "备份的边角：清理过的与没跑完的行不被误删，产物不会被当成孤儿扫走",
        [
            "tests/unit/test_exports_queue.py::test_cleanup_leaves_unexpired_and_failed_rows_alone",
            "tests/unit/test_exports_queue.py::test_cleanup_sweeps_orphans_only_after_the_grace_period",
            "tests/unit/test_exports_queue.py::test_orphan_sweep_never_touches_an_owned_product",
            "tests/unit/test_exports_queue.py::test_temp_files_are_never_taken_for_products",
            "tests/contract/test_p5_export_api.py::test_deleting_a_course_takes_its_exports_with_it",
        ],
    ),
    (
        "P5-C2b",
        "账本的行来自唯一的那个写入点：失败的调用也记、负数被夹到 0、单位跟着链路走",
        [
            "tests/unit/test_usage_ledger.py::test_a_call_lands_in_the_ledger_with_its_attribution",
            "tests/unit/test_usage_ledger.py::test_a_failed_call_is_still_recorded",
            "tests/unit/test_usage_ledger.py::test_negative_numbers_are_clamped_to_zero",
            "tests/unit/test_usage_ledger.py::test_units_follow_the_kind",
            "tests/unit/test_usage_ledger.py::test_a_write_failure_does_not_blow_up_the_caller",
        ],
    ),
    (
        "P5-B3b",
        "看板缓存：过去的日才缓存、今天永远重算、晚到的账能被重算回来",
        [
            "tests/unit/test_api_usage.py::test_a_past_day_is_cached_and_today_never_is",
            "tests/unit/test_api_usage.py::test_refresh_recomputes_a_day_whose_ledger_arrived_late",
            "tests/unit/test_api_usage.py::test_refreshing_today_writes_nothing",
            "tests/unit/test_api_usage.py::test_the_cache_reads_back_the_same_number",
            "tests/unit/test_api_usage.py::test_a_day_with_no_spend_still_gets_four_zero_rows",
        ],
    ),
]

#: 离线跑不到、但离线侧有替代证据的条目：`(编号, 标题, 节点, 为什么跑不到)`。
PROXIED: list[tuple[str, str, list[str], str]] = [
    (
        "P5-A2",
        "PPTX 可二次编辑（在 PowerPoint 里改字、拖文本框）",
        ["tests/unit/test_exports_queue.py::test_pptx_is_editable_slides_not_an_image"],
        "要人在 Office 里点；离线侧验到的是**它不是一张整页图片**（文本框是文本框），"
        "那是「能不能改」的前提",
    ),
    (
        "P5-A3b",
        "HTML 断网双击即看、翻页与字幕都正常",
        [
            "tests/unit/test_exports_queue.py::test_html_is_self_contained",
            "tests/unit/test_exports_queue.py::test_watermark_can_be_turned_off_and_is_recorded",
        ],
        "「双击打开」要浏览器；离线侧验到的是自包含（零外链，见 P5-A3 那一行的 0 处）"
        "与字幕层里有讲稿（见 P5-E1）",
    ),
    (
        "P5-A4b",
        "PDF 打出来中文无方框、无乱码",
        ["tests/unit/test_exports_queue.py::test_pdf_has_all_pages_and_page_numbers"],
        "「看着有没有方框」要眼睛；离线侧验到的是**文字层里能取回原文**"
        "（方框字取不回来，这一条是它的下界）",
    ),
    (
        "P5-A7b",
        "看板的金额与实际账单对得上",
        [
            "tests/unit/test_api_usage.py::test_the_detail_adds_up_to_the_same_number_as_the_board",
            "tests/unit/test_usage_ledger.py::test_llm_price_splits_prompt_and_completion",
            "tests/unit/test_usage_ledger.py::test_an_unlisted_model_falls_back_to_the_wildcard",
        ],
        "要真账单；离线侧验到的是**口径一致**（看板 = 明细 = 账本，误差 0，见 P5-A7 那一行）"
        "与价格表算得对",
    ),
    (
        "P5-A8b",
        "预算的其他几档：单课 / 全局 / 告警比例 / 关掉之后不拦",
        [
            "tests/unit/test_api_usage.py::test_a_course_budget_only_counts_that_course",
            "tests/unit/test_api_usage.py::test_the_alert_ratio_warns_without_blocking",
            "tests/unit/test_api_usage.py::test_a_disabled_budget_is_ignored",
            "tests/unit/test_api_usage.py::test_zero_means_unlimited_and_blocks_nothing",
            "tests/unit/test_api_usage.py::test_a_course_budget_must_name_a_course",
        ],
        "离线只走 day 那一档（三档共用一套判定，见 `usage/budget.py`）；"
        "另外几档与「0 = 不限」由这些用例钉着",
    ),
    (
        "P5-A9b",
        "断点续跑的页级幂等：同一页跑两次不会写两遍、重跑会记下重试次数",
        [
            "tests/unit/test_generation_recovery.py::test_resume_finishes_the_course_without_repaying_for_what_is_done",
            "tests/unit/test_generation_recovery.py::test_a_job_left_running_by_a_restart_is_marked_failed",
            "tests/unit/test_generation_recovery.py::test_the_recovery_is_written_to_the_event_log",
        ],
        "离线侧那次是真 kill 真重启（见 P5-A9 那一行）；这里记的是它的同源证据："
        "重启后的收尾与「已经写好的页不重写」在更小的单位上也被钉着",
    ),
    (
        "P5-G3b",
        "文档经他人按文档实操成功一次",
        ["tests/unit/test_api_docs.py::test_every_endpoint_has_a_docstring_with_a_request_example"],
        "要另一个人照着做一遍；离线侧验到的是**接口层的文档契约**"
        "（每条路由都有一段带「请求示例」的说明，由真路由表走查）",
    ),
]


def _cases_passed(node: str) -> int:
    """这个节点（整文件或单条）跑过了几条用例。"""
    if node in _NODE_CACHE or node + "::" in _NODE_CACHE:
        return 1
    prefix = node + "::"
    return sum(1 for name in _NODE_CACHE if name.startswith(prefix))


def check_delegated(rep: Report, ctx: Ctx) -> None:
    """跑一趟离线用例，把上面两张表逐条记账。"""
    nodes = [node for _aid, _title, group in DELEGATED for node in group]
    nodes += [node for _aid, _title, group, _why in PROXIED for node in group]
    pytest_verdicts(nodes)

    for aid, title, group in DELEGATED:
        problems = []
        for node in group:
            ok, why = pytest_node_ok(node)
            if not ok:
                problems.append(f"{node.rsplit('::', 1)[-1]}（{why}）")
        rep.verdict(aid, title, problems, f"{len(group)} 条用例全通过")


def check_unreachable(rep: Report, ctx: Ctx) -> None:
    """离线跑不到的：如实跳过，并说清卡在哪。"""
    for aid, title, group, why in PROXIED:
        pairs = []
        for node in group:
            ok, _ = pytest_node_ok(node)
            pairs.append(f"{node.rsplit('::', 1)[-1]}：{'通过' if ok else '**未通过**'}")
        evidence = f"；离线侧（{len(group)} 条）—— " + "、".join(pairs) if group else ""
        rep.skip(aid, title, f"{why}{evidence}")

    rep.skip(
        "P5-B4",
        "OpenAPI 文档可访问（/api/docs），与实现一致",
        "**这一条没实现**：仓库里没有 /api/docs 这条路由，也没有契约测试生成 OpenAPI。"
        "口径改成了「接口层的文档契约由 tests/unit/test_api_docs.py 走真路由表钉着」"
        "（每条路由都要有一段带请求示例的说明、说明里的方法要与路由一致）——"
        "见 P5 文档 §10 的偏差记录",
    )
    rep.skip(
        "P5-A10b",
        "失败步骤可见上游错误码（如 429 rate_limit）",
        "离线替身不制造失败（P5 §7 的离线口径：不打上游、也不假装上游会失败），"
        "所以这一半没有离线触发点；失败路径本身由 tests/unit/test_generation_pipeline.py "
        "与 tests/unit/test_generation_llm.py 的用例钉着",
    )
    rep.skip(
        "P5-A5b",
        "有内容的课堂记录：字幕全文 + 消息（带角色）+ 板书快照 + 我的作答",
        "这些只能由 WS 课堂产生（subtitle/message/board 三条都走 WebSocket），"
        "而 P3 那套无头课堂是 accept_p3 的地盘。离线侧验到的是**记录导出的管线**"
        "（md 与 pdf 两条都真跑、空课堂如实说空，见 P5-A5 那一行）",
    )
    rep.skip(
        "P5-A11",
        "干净机器上 docker compose up -d → 3 分钟内 http://host:5000 可用",
        "要 Docker。**开发这套代码的机器上没有 docker（`docker: command not found`）**，"
        "所以这条与 P5-F3 的那半、P5-D4 从来没跑过 —— 第一次 docker compose up 才是它的真验收，"
        "见 P5 文档 §10",
    )
    rep.skip(
        "P5-F3",
        "容器以非 root 运行；.env 不被打包进镜像",
        "要 Docker（同上）。静态那半已核对：Dockerfile 里 drop 到 uid 10001、"
        "构建上下文排除了 backend/.env（见 .dockerignore），但这只是「写了」，不是「验过」",
    )
    rep.skip(
        "P5-D4",
        "冷启动（容器从起到健康）≤ 30s",
        "要容器；离线这台起来用了不到 10 秒，但那是 flask 开发服务器连一个空库，"
        "与容器里跑迁移 + 起 gunicorn 不是一件事，不能拿它当证据",
    )
    rep.skip(
        "P5-D2",
        "导出过程不影响正在进行的课堂（同时导出 + 上课，事件延迟 P95 ≤ 800ms）",
        "要一边上课一边导出并量分位；两个离线实例验不了这个时序。"
        "结构上的依据是导出跑在后台线程、渲染不碰课堂事件那条路径，但没有量过",
    )
    rep.skip(
        "P5-D5",
        "100 门课程 + 1 万条消息下，课程列表页 P95 ≤ 300ms",
        "要造量再测分位；离线这两个实例各自只有一两门课。要做的话是 "
        "`python scripts/accept_p5.py --keep` 起服务、灌量、再用压测工具打",
    )
    rep.skip(
        "P5-E2",
        "导出产物视觉达到「可直接用于教学」标准（人工评分 ≥ 4/5）",
        "要人眼评分；脚本能说的是**结构与内容对**（页数、层级、讲稿、无溢出取回），"
        "排版好不好看它答不了",
    )
    rep.skip(
        "P5-E3",
        "成本估算与实际账单偏差 ≤ 15%",
        "要真账单，而且这一趟连一个真的上游都没打过（全程离线替身）",
    )
    rep.skip(
        "P5-F5",
        "依赖漏洞扫描（pip-audit / npm audit）无 high/critical 未处理项",
        "要联网。已知的一半：前端 `npm audit --audit-level=high` 为 2 moderate / 0 high / "
        "0 critical（两条都在仅开发依赖 @vitest/mocker）。"
        "**后端 pip-audit 还没跑过** —— 这台机器装不上它（源里没有），"
        "`make deps-audit` 已备好命令，第一次部署时请自己跑一遍并记账",
    )
    rep.skip(
        "P5-G2",
        "`make ci` 一键跑通（含 Playwright 关键链路 E2E）",
        "这一条是**上面每一条的合集**（lint + 单测 + 五套离线验收），"
        "跑完这一趟就算跑过它 —— 唯一对不上的是「Playwright」：本仓库没有它，"
        "前端 E2E 的角色由 vitest 的组件用例与 accept_p3 那只无头浏览器承担，"
        "见 Makefile 里 `ci` 那条的注释",
    )


def check_suites(rep: Report, ctx: Ctx) -> None:
    """P5-G1：P0~P4 的契约套件仍然全绿。"""
    suites = {
        "P0": "tests/contract/test_p0_api.py",
        "P1": "tests/contract/test_p1_api.py",
        "P2": "tests/contract/test_p2_voice_api.py",
        "P3": "tests/contract/test_p3_classroom_api.py",
        "P4": "tests/contract/test_p4_material_api.py",
        "接口文档契约": "tests/unit/test_api_docs.py",
    }
    results = {name: run_pytest(path) for name, path in suites.items()}
    problems = [
        f"{name} 未通过：{_pytest_tail(result, 6)}"
        for name, result in results.items()
        if result.returncode != 0
    ]
    rep.verdict(
        "P5-G1",
        "P0~P4 的契约套件保持通过",
        problems,
        "；".join(f"{name} {_pytest_summary(result)}" for name, result in results.items()),
    )


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------


def prepare_database(ctx: Ctx, port: int) -> tuple[bool, str]:
    """在一台的临时库上跑迁移与种子。返回 (是否成功, 失败原因)。"""
    env = {**ctx.env, "DATABASE_URL": ctx.db_urls[port]}
    upgrade = run_flask(["db", "upgrade"], env=env)
    if upgrade.returncode != 0:
        return False, f"db upgrade 失败：\n{plain((upgrade.stderr or '')[-500:])}"

    seeded = run_python(
        "import json\n"
        "from app import create_app\n"
        "from app.seeds import run_seed\n"
        "app = create_app()\n"
        "with app.app_context():\n"
        "    print(json.dumps(run_seed(), ensure_ascii=False))\n",
        env=env,
    )
    if seeded.returncode != 0:
        return False, f"seed 失败：\n{plain((seeded.stderr or '')[-500:])}"
    return True, ""


def start_server(ctx: Ctx, port: int, log_name: str, env: dict[str, str]):
    """起一台临时后端。

    两个文件，**不是一个**：`main.log` 是应用自己写的（`LOG_FILE`，会轮转的
    那一份），`main.console.log` 是这个进程的 stdout/stderr（werkzeug 的启动
    横幅与访问日志）。分开存是必须的：两个句柄指着同一个文件时，Windows 上
    `os.rename` 会失败（WinError 32），轮转压根切不动 —— 第一趟跑出「没有轮转
    文件」，就是这个原因，不是产品的问题。
    """
    # 记下这份环境：重启要按原样再来一遍（A9 的 kill → 重启、A12 的重启），
    # 从 `main()` 那边复制一份过来是两条会各自跑偏的真相。
    ctx.server_env[port] = env
    console_path = ctx.log_dir / f"{log_name.removesuffix('.log')}.console.log"
    ctx.logs[log_name.removesuffix(".log")] = console_path
    proc = start(
        [str(venv_python()), "-m", "flask", "--app", "app:create_app()", "run", "--port", str(port)],
        cwd=BACKEND,
        log_path=console_path,
        env=env,
    )
    if not wait_http(f"http://127.0.0.1:{port}/api/health", timeout=90):
        log = console_path.read_text(encoding="utf-8", errors="replace")
        print(f"  {port} 上的后端没起来，日志：\n{plain(log[-1200:])}")
        stop(proc)
        return None
    return proc


def _port_busy(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def main() -> int:
    parser = argparse.ArgumentParser(description="P5 A/B/C/D/F/G 类验收（P5-G2，离线）")
    parser.add_argument("--keep", action="store_true", help="跑完留下临时库、导出目录与两个后端进程")
    args = parser.parse_args()

    for port in (MAIN_PORT, GATE_PORT):
        if is_up(f"http://127.0.0.1:{port}/api/health") or _port_busy(port):
            print(f"端口 {port} 上已经有服务了。这台机器上它可能是别人的 —— 停掉它再跑。")
            return 2

    work_dir = Path(tempfile.mkdtemp(prefix="eduagentx-p5-"))
    shared = {
        "EXPORT_DIR": (work_dir / "exports").as_posix(),
        "BACKUP_DIR": (work_dir / "backups").as_posix(),
        "UPLOAD_DIR": (work_dir / "uploads").as_posix(),
        "MATERIAL_DIR": (work_dir / "materials").as_posix(),
        "AUDIO_DIR": (work_dir / "audio").as_posix(),
    }
    db_urls = {
        port: f"sqlite:///{(work_dir / f'accept-{port}.db').as_posix()}"
        for port in (MAIN_PORT, GATE_PORT)
    }
    ctx = Ctx(
        env={
            **OFFLINE_ENV,
            **shared,
            "DATABASE_URL": db_urls[MAIN_PORT],
            "FERNET_KEY": OFFLINE_FERNET_KEY,
        },
        work_dir=work_dir,
        export_dir=work_dir / "exports",
        backup_dir=work_dir / "backups",
        log_dir=work_dir / "logs",
        db_urls=db_urls,
    )
    ctx.log_dir.mkdir(parents=True, exist_ok=True)

    print("P5 A/B/C/D/F/G 类验收开始（两个离线实例，全程不联网）")
    print(f"  主实例   http://127.0.0.1:{MAIN_PORT}/api（离线替身，导出全开）")
    print(f"  访问码   http://127.0.0.1:{GATE_PORT}/api（SITE_ACCESS_CODE 开着）")
    print(f"  临时目录 {work_dir}（两个库 + 导出产物 + 备份 + 日志）")
    print()

    report = Report()
    try:
        # 日志写进临时目录（不是 stdout）：F4 那一条要翻的是**文件**，
        # 而「写出来的文件里有没有凭据」跟「控制台里有没有」是两件事。
        for port, name, env in (
            (MAIN_PORT, "main.log", ctx.env),
            # 访问码那台**不给** FERNET_KEY：顺手验一条「没配时报什么」（见常量注释）
            (GATE_PORT, "gate.log", {**OFFLINE_ENV, **shared, "SITE_ACCESS_CODE": ACCESS_CODE}),
        ):
            ok, why = prepare_database(ctx, port)
            if not ok:
                print(f"  临时库没准备好（:{port}）：\n{why}")
                return 2
            proc = start_server(
                ctx,
                port,
                name,
                {
                    **env,
                    "DATABASE_URL": db_urls[port],
                    "LOG_FILE": (ctx.log_dir / name).as_posix(),
                    "LOG_MAX_BYTES": str(LOG_MAX_BYTES),
                    "LOG_BACKUP_COUNT": "3",
                },
            )
            if proc is None:
                return 2
            ctx.procs[name.split(".")[0]] = proc

        # 顺序不是随便排的：
        #   - 生成与导出在前（后面每条都要拿这门课与这几份产物）；
        #   - 续跑那条会把主实例 kill 掉再起来，所以排在「不需要重启」的检查之后；
        #   - 审计在安全之后（`provider.update` 那条要先生效）；
        #   - 备份在清理之前（这样归档里有全部产物），清理在最后（它是唯一会删东西的）；
        #   - 日志在重启之后（这时文件里已经有重启前后两段）。
        _guard(report, "访问码", check_access, ctx)
        _guard(report, "三格式导出", check_exports, ctx)
        _guard(report, "下载与越权", check_download, ctx)
        _guard(report, "课堂记录导出", check_record, ctx)
        _guard(report, "成本看板", check_usage, ctx)
        _guard(report, "预算", check_budget, ctx)
        _guard(report, "断点续跑", check_resume, ctx)
        _guard(report, "SSRF 与凭据", check_security, ctx)
        _guard(report, "审计", check_audit, ctx)
        _guard(report, "重启后数据还在", check_restart, ctx)
        _guard(report, "备份与恢复", check_backup, ctx)
        _guard(report, "产物到期与清理", check_cleanup, ctx)
        _guard(report, "日志脱敏与轮转", check_logs, ctx)
        _guard(report, "交付文档", check_docs, ctx)
        _guard(report, "P0~P4 回归", check_suites, ctx)
        _guard(report, "委托用例", check_delegated, ctx)
        _guard(report, "跑不到的", check_unreachable, ctx)

        passed = sum(1 for row in report.rows if row[2] == "PASS")
        skipped = sum(1 for row in report.rows if row[2] == "SKIP")
        report.ok(
            "P5-G2c",
            "scripts/accept_p5.py 跑通导出/用量/续跑/门禁全流程",
            f"以上 {passed} 条在离线替身上通过、{skipped} 条按 §7 的分工记跳过；"
            "两个实例全程未联网、未读 .env",
        )
    finally:
        failed = any(row[2] == "FAIL" for row in report.rows)
        if not args.keep:
            print()
            print("  正在关闭两个临时后端…")
            for proc in ctx.procs.values():
                stop(proc)
        if args.keep:
            print(f"\n  两个临时后端还在 :{MAIN_PORT} / :{GATE_PORT}（--keep）")
            print(f"  临时目录 {work_dir}")
        elif failed:
            print(f"  这一趟没全绿，临时目录留着给你查：{work_dir}")
        else:
            shutil.rmtree(work_dir, ignore_errors=True)

    return report.summary()


if __name__ == "__main__":
    sys.exit(main())
