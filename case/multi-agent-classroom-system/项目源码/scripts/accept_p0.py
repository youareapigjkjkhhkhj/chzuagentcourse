#!/usr/bin/env python
"""P0 A 类验收（P0-G2）：一条命令跑完 A1~A9 并输出通过清单。

    python scripts/accept_p0.py            # 跑全部
    python scripts/accept_p0.py --offline  # 跳过大模型探活（不产生任何外网请求）

三条原则：

1. **不改你的数据。** 每个写操作都先记下原值，验完立刻还原 —— 包括
   服务商启用状态、语音语速、生成参数。A4 / A5b 要试写一个假 Key，专门挑
   「未配置**且没存过 Key**」的那张卡，绝不覆盖你已经填好的真 Key
   （明文取不回来）；试写时按卡片自己报的 `missing` 把缺的字段补齐
   （空卡缺接入地址与模型名是产品如实告知，不是缺陷），验完按原值还原。
2. **A9 不在你的库上做。** 「删库重建」会在一个临时 DATABASE_URL 上跑
   完整的 upgrade + seed + 启动流程，语义等价但不碰 backend/data/。
3. **说得出为什么。** 每条不通过都打印实际收到的响应；跳过的条目说明
   跳过的原因，而不是假装通过。

服务没起的话本脚本会自己拉起（:5000 后端 / :5173 前端），跑完再关掉；
已经在跑的则复用、不动它。
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
from pathlib import Path
from typing import Any

#: Windows 控制台是 GBK，而 npm/flask 的输出里有 ✓ 之类的字符。
#: 默认行为是直接 UnicodeEncodeError 崩掉 —— 验收脚本不该死在打印上。
#: errors="replace" 让无法转换的字符变成 ?，中文本身仍按控制台编码正常显示。
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

BACKEND_PORT = 5000
FRONTEND_PORT = 5173
API = f"http://localhost:{BACKEND_PORT}/api"
WEB = f"http://localhost:{FRONTEND_PORT}"

#: A4 试写用的假 Key：形状像真的（sk- 开头、后 4 位可辨认），但一看就知道是测试值。
FAKE_KEY = "sk-acceptance-p0-0000000000001234"

#: 「断网」这一支不支持真的拔网线，改为跑两个已覆盖该映射的单元测试（不联网）。
TIMEOUT_TESTS = [
    "tests/unit/test_llm_openai_compatible.py::test_test_never_raises_on_timeout",
    "tests/contract/test_p0_api.py::test_probe_reports_a_timeout",
]


# --------------------------------------------------------------------------
# 输出
# --------------------------------------------------------------------------


class Report:
    """通过清单。最后要能一眼看出「哪几条没过」。"""

    def __init__(self) -> None:
        self.rows: list[tuple[str, str, str, str]] = []

    def _add(self, aid: str, title: str, status: str, detail: str) -> None:
        # 详情里可能嵌着 npm/pytest 的原始输出（带 ANSI 颜色码），统一在这里清洗，
        # 免得每个调用点都要记得处理一遍
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
        print(f"P0 A 类验收：通过 {passed} / 不通过 {len(failed)} / 跳过 {len(skipped)}")
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


def api(method: str, path: str, body: Any = None, timeout: float = 30.0) -> tuple[int, dict]:
    """调后端接口，返回 (HTTP 状态, 信封)。业务错误也在信封里，不抛异常。"""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "X-Request-Id": "accept-p0"},
    )
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


def is_up(url: str, timeout: float = 5.0) -> bool:
    """这个地址现在有没有人在服务（用来决定「复用」还是「自己起一个」）。"""
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


def brief(payload: Any, limit: int = 300) -> str:
    text = json.dumps(payload, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"


def _data(status: int, envelope: dict) -> Any:
    return envelope.get("data") if status == 200 and envelope.get("code") == 0 else None


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


def start(process_args: list[str], cwd: Path, log_path: Path, env: dict[str, str] | None = None):
    log = log_path.open("w", encoding="utf-8")
    merged = {**os.environ, **(env or {})}
    return subprocess.Popen(process_args, cwd=str(cwd), env=merged, stdout=log, stderr=subprocess.STDOUT)


def stop(proc) -> None:
    """停掉我们启动的服务（含它的子进程；Windows 上 terminate 杀不干净 node）。"""
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
    """在 backend 目录下用 venv python 跑一段代码（读库、跑种子都用它）。"""
    return subprocess.run(
        [str(venv_python()), "-c", code],
        cwd=str(BACKEND),
        env={**os.environ, **(env or {})},
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


# --------------------------------------------------------------------------
# A1~A9
# --------------------------------------------------------------------------


def check_a1(rep: Report) -> None:
    """一条命令启动前后端：两个地址都要 200，且健康检查说 ok。"""
    status, envelope = api("GET", "/health")
    health = _data(status, envelope)
    if health is None:
        return rep.fail("P0-A1", "启动前后端", f"GET {API}/health 返回 {status} {brief(envelope)}")
    if health.get("status") != "ok":
        return rep.fail("P0-A1", "启动前后端", f"health.status={health.get('status')!r}，期望 'ok'")

    try:
        with urllib.request.urlopen(WEB, timeout=10) as resp:
            web_status = resp.status
            has_app = b'id="app"' in resp.read()
    except Exception as exc:
        return rep.fail("P0-A1", "启动前后端", f"GET {WEB} 失败：{type(exc).__name__}: {exc}")
    if web_status != 200 or not has_app:
        return rep.fail("P0-A1", "启动前后端", f"{WEB} 返回 {web_status}，挂载点 id=app 存在={has_app}")

    rep.ok(
        "P0-A1",
        "启动前后端",
        f"{API}/health → 200 status=ok；{WEB} → 200（db={health.get('db')}）",
    )


def check_a2(rep: Report) -> None:
    """顶栏四页导航可跳转且不白屏。

    HTTP 层只能证明「四个地址都回得来同一个 SPA 外壳」——「点了之后有内容、
    控制台不报错」是浏览器里的事。这里跑前端自己的 App.spec 作为证据：
    它在 jsdom 里真的挂载了四个页面，并断言 `console.error` 零调用。
    真实浏览器仍建议人工点一遍（见 README 的验收说明）。
    """
    result = subprocess.run(
        [npx(), "vitest", "run", "src/__tests__/App.spec.ts"],
        cwd=str(FRONTEND),
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    output = plain((result.stdout or "") + (result.stderr or ""))
    summary = next((ln for ln in reversed(output.splitlines()) if "Tests" in ln and "passed" in ln), "")
    if result.returncode != 0:
        # 失败的完整输出留着 —— 截断的那几行常常正好把原因截掉
        log_path = Path(tempfile.gettempdir()) / "eduagentx-a2-vitest.log"
        log_path.write_text(output, encoding="utf-8")
        reason = next((ln.strip() for ln in output.splitlines() if "FAIL" in ln or "Error" in ln), "")
        return rep.fail(
            "P0-A2",
            "四页导航不白屏",
            f"App.spec 未通过（returncode={result.returncode}）{reason}\n完整输出：{log_path}",
        )

    rep.ok(
        "P0-A2",
        "四页导航不白屏",
        f"App.spec（四页渲染 + console.error 零调用）通过 {summary.strip()}",
    )


def check_a3(rep: Report) -> None:
    """设置页 5 张服务商卡片按原型渲染（数据半边）。"""
    status, envelope = api("GET", "/settings/providers")
    data = _data(status, envelope)
    if data is None:
        return rep.fail("P0-A3", "5 张服务商卡片", f"GET /settings/providers 返回 {status} {brief(envelope)}")

    items = data.get("items", [])
    want = ["deepseek", "openai", "qwen", "kimi", "custom"]
    got = [item.get("id") for item in items]
    if got != want:
        return rep.fail("P0-A3", "5 张服务商卡片", f"卡片顺序/数量不符：期望 {want}，实际 {got}")

    for item in items:
        missing = [f for f in ("name", "enabled", "configured", "available", "missing") if f not in item]
        if missing:
            return rep.fail("P0-A3", "5 张服务商卡片", f"{item.get('id')} 卡片缺字段：{missing}")

    states = "，".join(
        f"{item['name']}={'已启用' if item['enabled'] else ('已配置' if item['configured'] else '未配置')}"
        for item in items
    )
    rep.ok("P0-A3", "5 张服务商卡片", states)


#: 卡片上「还缺什么」→ 保存接口里的字段名。键就是后端 missing_config() 的文案。
_MISSING_FIELDS = {"API Key": "apiKey", "接入地址": "baseUrl", "模型名": "defaultModel"}

_LLM_CONFIG_CACHE: dict[str, str] = {}


def _configured_llm() -> dict[str, str]:
    """后端配置里的接入地址与模型名。

    不写死在脚本里：AGENTS.md §4.1 要求端点 URL 一律配置化 ——
    这也让 A5b 拿假 Key 去撞的是你 .env 里那个地址，而不是我猜的一个。
    """
    if not _LLM_CONFIG_CACHE:
        result = run_python(
            "from app import create_app\n"
            "config = create_app().config\n"
            "print((config.get('LLM_BASE_URL') or '') + '\\t' + (config.get('LLM_MODEL') or ''))"
        )
        lines = (result.stdout or "").strip().splitlines()
        base_url, _, model = (lines[-1] if lines else "").partition("\t")
        _LLM_CONFIG_CACHE.update({"baseUrl": base_url.strip(), "model": model.strip()})
    return _LLM_CONFIG_CACHE


def _fill_payload(card: dict) -> tuple[dict[str, Any], list[str]]:
    """照卡片自己报的 `missing` 把缺的字段填上，返回 (payload, 填不上的字段)。

    为什么不「只填 Key 就完事」：接入地址与模型名是设置页的可改项，代码里
    给不了厂商默认值（AGENTS.md §4.1 不许写死端点），所以一张空卡本来就缺
    三样。A4 要验的是「填好一张卡 → 保存 → 刷新仍在 → 回显脱敏」，
    而不是「只填 Key 也能用」—— 后者产品上是**刻意不成立**的：
    卡片会如实说「还缺：接入地址、模型名」，而不是假装已配置
    （见 tests/contract/test_p0_api.py::test_card_says_which_field_is_still_missing）。
    """
    llm = _configured_llm()
    sources = {"apiKey": FAKE_KEY, "baseUrl": llm["baseUrl"], "defaultModel": llm["model"]}
    payload: dict[str, Any] = {}
    unfilled: list[str] = []
    for field in card.get("missing") or []:
        key = _MISSING_FIELDS.get(field, "")
        value = sources.get(key, "")
        if value:
            payload[key] = value
        else:
            unfilled.append(field)
    return payload, unfilled


def _restore_payload(card: dict) -> dict[str, Any]:
    """把试写过的卡片还原成原样：Key 清掉，地址与模型名回到写入前的值。

    还原成「原值」而不是「空值」：空卡也可能已经填了地址（比如指向自建端点
    的自定义卡），把它清掉同样是改用户的数据。
    """
    return {
        "clearApiKey": True,
        "baseUrl": card.get("baseUrl") or "",
        "defaultModel": card.get("defaultModel") or "",
    }


def _pick_empty_card(items: list[dict]) -> dict | None:
    """挑一张可以安全试写的卡：未配置，且**没有已存的 Key**。

    `configured=False` 还不够：用户可能只填了 Key 没填地址，这时卡片也是
    未配置，但覆盖它的 Key 就再也拿不回来了（接口只回掩码）。
    """
    return next(
        (item for item in items if not item["configured"] and not item.get("maskedKey")), None
    )


def _prepare_write(items: list[dict]) -> tuple[dict | None, dict[str, Any], str]:
    """挑一张能安全试写的空卡，并备好「把它填满」的 payload。

    返回 (卡片, payload, 不能试写的原因) —— 卡片为 None 时看第三个值。
    抽出来是因为 A4 与 A5b 都要走这一步，两处各写一遍迟早会走偏。
    """
    card = _pick_empty_card(items)
    if card is None:
        return None, {}, "没有「未配置且没存过 Key」的空卡可安全试写"
    payload, unfilled = _fill_payload(card)
    if unfilled:
        return None, {}, f"backend/.env 里没有可供填入的 {'、'.join(unfilled)}"
    return card, payload, ""


def check_a4(rep: Report) -> None:
    """保存 Key 并持久化 + 回显脱敏。

    专挑「本来就没配置、也没存过 Key」的卡试写：往已存的 Key 上写假 Key
    会把它覆盖掉（Key 只能读回掩码，覆盖了就要重新去厂商后台复制）。
    """
    status, envelope = api("GET", "/settings/providers")
    items = (_data(status, envelope) or {}).get("items", [])
    target, payload, why = _prepare_write(items)
    if target is None:
        return rep.skip("P0-A4", "Key 保存与脱敏", why)

    pid = target["id"]
    try:
        status, envelope = api("PUT", f"/settings/providers/{pid}", payload)
        card = _data(status, envelope)
        if card is None:
            return rep.fail("P0-A4", "Key 保存与脱敏", f"保存返回 {status} {brief(envelope)}")
        if not card.get("configured"):
            return rep.fail(
                "P0-A4",
                "Key 保存与脱敏",
                f"填好 {sorted(payload)} 保存后 configured 仍为 {card.get('configured')!r}，"
                f"还缺 {card.get('missing')}",
            )

        masked = card.get("maskedKey", "")
        if FAKE_KEY in masked:
            return rep.fail("P0-A4", "Key 保存与脱敏", f"回显里出现了明文 Key：{masked}")
        if not masked.endswith("1234") or "*" not in masked:
            return rep.fail("P0-A4", "Key 保存与脱敏", f"脱敏形状不对：{masked!r}，期望形如 sk-****1234")

        # 刷新页面 = 前端重新 GET，这里等价于重新拉一次列表
        status, envelope = api("GET", "/settings/providers")
        again = next((i for i in (_data(status, envelope) or {}).get("items", []) if i["id"] == pid), None)
        if not again or not again.get("configured") or again.get("maskedKey") != masked:
            return rep.fail("P0-A4", "Key 保存与脱敏", f"重新读取后不一致：{brief(again)}")

        rep.ok("P0-A4", "Key 保存与脱敏", f"{pid} 保存→重新读取仍为已配置，回显 {masked}")
    finally:
        # 还原成写入前的样子。失败也要还原，否则会留下一个假 Key 的卡。
        api("PUT", f"/settings/providers/{pid}", _restore_payload(target))


def check_a5(rep: Report, offline: bool) -> None:
    """测试连接返回真实结果：正确 Key 有延迟、错误 Key 有原因、断网有原因。"""
    status, envelope = api("GET", "/settings/providers")
    items = (_data(status, envelope) or {}).get("items", [])
    llm_ready = [item for item in items if item["kind"] == "llm" and item["configured"]]

    # (a) 正确 Key
    if offline:
        rep.skip("P0-A5a", "测试连接（正确 Key）", "--offline：跳过真实探活")
    elif not llm_ready:
        rep.skip("P0-A5a", "测试连接（正确 Key）", "没有已配置的文本模型，先在设置页填 Key")
    else:
        pid = llm_ready[0]["id"]
        status, envelope = api("POST", f"/settings/providers/{pid}/test", timeout=90.0)
        result = _data(status, envelope)
        if result is None:
            if envelope.get("code") == 40201:
                rep.skip("P0-A5a", "测试连接（正确 Key）", f"{pid} 未配置（40201）")
            else:
                rep.fail("P0-A5a", "测试连接（正确 Key）", f"{status} {brief(envelope)}")
        elif result.get("ok") and (result.get("latencyMs") or 0) > 0:
            rep.ok("P0-A5a", "测试连接（正确 Key）", f"{pid} ✓ 已连接 · {result['latencyMs']}ms · {result.get('model')}")
        else:
            rep.fail("P0-A5a", "测试连接（正确 Key）", f"探活未成功：{brief(result)}")

    # (b) 错误 Key：拿一张空卡填假 Key，指向真实接入地址与模型名，上游必须拒绝。
    #     「假 Key 必须被拒绝」要成立，那张卡得先真的配齐 —— 缺模型名的话
    #     后端会按 40201 挡在门前，我们测到的就变成「未配置」而不是「Key 错」。
    if offline:
        rep.skip("P0-A5b", "测试连接（错误 Key）", "--offline：跳过真实探活")
    else:
        empty, payload, why = _prepare_write(items)
        if empty is None:
            rep.skip("P0-A5b", "测试连接（错误 Key）", why)
        else:
            pid = empty["id"]
            try:
                api("PUT", f"/settings/providers/{pid}", payload)
                status, envelope = api("POST", f"/settings/providers/{pid}/test", timeout=90.0)
                result = _data(status, envelope) or {}
                if result.get("ok") is False and result.get("error"):
                    rep.ok(
                        "P0-A5b",
                        "测试连接（错误 Key）",
                        f"{pid} 如实返回失败：{result.get('errorCode')} · {result['error'][:120]}",
                    )
                else:
                    rep.fail(
                        "P0-A5b", "测试连接（错误 Key）", f"假 Key 竟然没被拒绝：{brief(result)}"
                    )
            finally:
                api("PUT", f"/settings/providers/{pid}", _restore_payload(empty))

    # (c) 断网 → 超时原因。拔网线没法自动化，跑两个已经覆盖该映射的单元测试。
    result = subprocess.run(
        [str(venv_python()), "-m", "pytest", "-q", *TIMEOUT_TESTS],
        cwd=str(BACKEND),
        capture_output=True,
        check=False,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        rep.fail("P0-A5c", "测试连接（断网/超时）", f"超时映射测试未通过：\n{(result.stdout or '')[-800:]}")
    else:
        rep.ok("P0-A5c", "测试连接（断网/超时）", "超时→可读原因 由 2 个单元测试覆盖（未真的断网，见 README）")


def check_a6(rep: Report) -> None:
    """启用服务商全局唯一，且 /api/health 跟着走。"""
    status, envelope = api("GET", "/settings/providers")
    items = (_data(status, envelope) or {}).get("items", [])
    original = next((item["id"] for item in items if item["enabled"]), None)
    target = "openai" if original != "openai" else "deepseek"

    try:
        status, envelope = api("POST", f"/settings/providers/{target}/enable")
        if _data(status, envelope) is None:
            return rep.fail("P0-A6", "服务商全局唯一", f"启用 {target} 返回 {status} {brief(envelope)}")

        status, envelope = api("GET", "/settings/providers")
        enabled = [i["id"] for i in (_data(status, envelope) or {}).get("items", []) if i["enabled"]]
        if enabled != [target]:
            return rep.fail("P0-A6", "服务商全局唯一", f"启用后 enabled 列表={enabled}，期望只有 {target}")

        status, envelope = api("GET", "/health")
        pointed = ((_data(status, envelope) or {}).get("llm") or {}).get("provider")
        if pointed != target:
            return rep.fail("P0-A6", "服务商全局唯一", f"health.llm.provider={pointed!r}，期望 {target!r}")

        rep.ok("P0-A6", "服务商全局唯一", f"启用 {target} 后仅它 enabled，health.llm 指向 {pointed}")
    finally:
        if original:
            api("POST", f"/settings/providers/{original}/enable")


def check_a7(rep: Report) -> None:
    """语音设置与生成参数可读写（选顾老师 + 语速 1.2 → 刷新回显一致）。"""
    status, envelope = api("GET", "/settings/voice")
    voice = _data(status, envelope)
    if voice is None:
        return rep.fail("P0-A7", "语音与生成参数读写", f"GET /settings/voice 返回 {status} {brief(envelope)}")

    voices = voice.get("voices", [])
    if not voices:
        return rep.fail("P0-A7", "语音与生成参数读写", "音色列表为空（种子数据没灌？）")

    # 优先挑一个和当前不同的音色，否则「改没改」根本看不出来
    other = next((v for v in voices if v["id"] != voice.get("teacherVoiceId")), voices[0])
    original = {"teacherVoiceId": voice.get("teacherVoiceId"), "speed": voice.get("speed")}

    status, envelope = api("GET", "/settings/generation")
    generation = _data(status, envelope)
    if generation is None:
        return rep.fail("P0-A7", "语音与生成参数读写", f"GET /settings/generation 返回 {status} {brief(envelope)}")
    original_gen = {"pageCount": generation.get("pageCount"), "intensity": generation.get("intensity")}

    try:
        api("PUT", "/settings/voice", {"teacherVoiceId": other["id"], "speed": 1.2})
        status, envelope = api("GET", "/settings/voice")
        after = _data(status, envelope) or {}
        if after.get("teacherVoiceId") != other["id"] or abs(float(after.get("speed", 0)) - 1.2) > 1e-6:
            return rep.fail(
                "P0-A7",
                "语音与生成参数读写",
                f"重新读取不一致：{after.get('teacherVoiceId')!r} / {after.get('speed')!r}",
            )

        new_pages = 16 if original_gen["pageCount"] != 16 else 14
        api("PUT", "/settings/generation", {"pageCount": new_pages})
        status, envelope = api("GET", "/settings/generation")
        after_gen = _data(status, envelope) or {}
        if after_gen.get("pageCount") != new_pages:
            return rep.fail("P0-A7", "语音与生成参数读写", f"页数没存住：{after_gen.get('pageCount')!r}")

        rep.ok(
            "P0-A7",
            "语音与生成参数读写",
            f"音色→{other['name']} 语速→1.2 页数→{new_pages}，重新读取一致",
        )
    finally:
        api("PUT", "/settings/voice", original)
        api("PUT", "/settings/generation", original_gen)


def check_a8(rep: Report) -> None:
    """种子数据完整且幂等：连跑两次，第二次一个新行都不该建出来。"""
    code = (
        "import json\n"
        "from app import create_app\n"
        "from app.seeds import run_seed\n"
        "app = create_app()\n"
        "with app.app_context():\n"
        "    first = run_seed()\n"
        "    second = run_seed()\n"
        "    print(json.dumps({'first': first, 'second': second}))\n"
    )
    result = run_python(code)
    if result.returncode != 0:
        return rep.fail("P0-A8", "种子数据完整且幂等", f"seed 执行失败：\n{(result.stderr or '')[-800:]}")

    line = next((ln for ln in reversed((result.stdout or "").splitlines()) if ln.startswith("{")), "")
    if not line:
        return rep.fail("P0-A8", "种子数据完整且幂等", f"读不到 seed 结果：{plain((result.stdout or '')[-300:])}")
    payload = json.loads(line)
    second = payload["second"]

    expected = {"agentRoles": 3, "voiceProfiles": 3, "courses": 1}
    missing = {k: second.get(k) for k, v in expected.items() if (second.get(k) or 0) < v}
    if missing:
        return rep.fail("P0-A8", "种子数据完整且幂等", f"种子不足：期望至少 {expected}，实际 {missing}")

    created_again = {k: v for k, v in (second.get("created") or {}).items() if v}
    if created_again:
        return rep.fail("P0-A8", "种子数据完整且幂等", f"第二次执行仍在建行（不幂等）：{created_again}")

    rep.ok(
        "P0-A8",
        "种子数据完整且幂等",
        f"角色 {second['agentRoles']} / 音色 {second['voiceProfiles']} / 课程 {second['courses']}，"
        "第二次执行新增 0 行",
    )


def check_a9(rep: Report) -> None:
    """数据库可重建：在临时库上跑 upgrade + seed + 启动。

    不在 backend/data/ 上做 —— 那里存着你填的服务商配置与设置，
    删掉是不可逆的。换一个 DATABASE_URL 走同一套代码路径，语义等价。
    """
    tmp = Path(tempfile.mkdtemp(prefix="eduagentx-accept-"))
    db_file = tmp / "accept.db"
    env = {"DATABASE_URL": f"sqlite:///{db_file.as_posix()}"}
    port = 5099
    proc = None
    try:
        upgrade = subprocess.run(
            [str(venv_python()), "-m", "flask", "--app", "app:create_app()", "db", "upgrade"],
            cwd=str(BACKEND),
            env={**os.environ, **env},
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if upgrade.returncode != 0:
            return rep.fail("P0-A9", "数据库可重建", f"db upgrade 失败：\n{(upgrade.stderr or '')[-800:]}")

        seeded = run_python(
            "import json\n"
            "from app import create_app\n"
            "from app.seeds import run_seed\n"
            "app = create_app()\n"
            "with app.app_context():\n"
            "    print(json.dumps(run_seed()))\n",
            env=env,
        )
        if seeded.returncode != 0:
            return rep.fail("P0-A9", "数据库可重建", f"seed 失败：\n{(seeded.stderr or '')[-800:]}")

        proc = start(
            [
                str(venv_python()),
                "-m",
                "flask",
                "--app",
                "app:create_app()",
                "run",
                "--port",
                str(port),
            ],
            cwd=BACKEND,
            log_path=tmp / "server.log",
            env=env,
        )
        if not wait_http(f"http://127.0.0.1:{port}/api/health", timeout=30):
            log = (tmp / "server.log").read_text(encoding="utf-8", errors="replace")
            return rep.fail("P0-A9", "数据库可重建", f"新库上服务没起来：\n{log[-600:]}")

        # 注意这里打的是临时实例自己的端口，不是 --api 指向的那个
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=10) as resp:
            health = json.loads(resp.read().decode("utf-8"))
        if (health.get("data") or {}).get("status") != "ok":
            return rep.fail("P0-A9", "数据库可重建", f"临时库上 health 不是 ok：{brief(health)}")

        rep.ok("P0-A9", "数据库可重建", f"临时库 upgrade + seed + 启动全通（端口 {port}），health=ok")
    finally:
        stop(proc)
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="P0 A 类验收（P0-G2）")
    parser.add_argument("--offline", action="store_true", help="不发起任何真实模型调用（A5a/A5b 记为跳过）")
    parser.add_argument("--keep-servers", action="store_true", help="跑完不关掉本脚本启动的服务")
    args = parser.parse_args()

    report = Report()
    started: list[Any] = []
    tmp = Path(tempfile.mkdtemp(prefix="eduagentx-servers-"))

    print("P0 A 类验收开始（A1~A9）")
    print(f"  后端 {API}　前端 {WEB}")
    print()

    # 服务没起就自己拉起来；已经在跑的复用，不动它（可能是你 `make dev` 开的）
    if is_up(f"{API}/health"):
        print("  后端已在运行，直接复用")
    else:
        print("  后端未运行，正在启动…")
        started.append(start(
            [str(venv_python()), "-m", "flask", "--app", "app:create_app()", "run", "--port", str(BACKEND_PORT)],
            cwd=BACKEND,
            log_path=tmp / "backend.log",
        ))
        if not wait_http(f"{API}/health", timeout=45):
            print(f"  后端启动失败，日志：{tmp / 'backend.log'}")
            print(plain((tmp / "backend.log").read_text(encoding="utf-8", errors="replace")[-1500:]))
            stop(started.pop())
            return 2
    if is_up(WEB):
        print("  前端已在运行，直接复用")
    else:
        print("  前端未运行，正在启动（首次冷启动较慢）…")
        started.append(start(
            [npx(), "vite", "--port", str(FRONTEND_PORT), "--strictPort"],
            cwd=FRONTEND,
            log_path=tmp / "frontend.log",
            env={"BACKEND_ORIGIN": f"http://127.0.0.1:{BACKEND_PORT}"},
        ))
        if not wait_http(WEB, timeout=120):
            print(f"  前端启动失败，日志：{tmp / 'frontend.log'}")
            print(plain((tmp / "frontend.log").read_text(encoding="utf-8", errors="replace")[-1500:]))

    print()
    try:
        check_a1(report)
        check_a2(report)
        check_a3(report)
        check_a4(report)
        check_a5(report, args.offline)
        check_a6(report)
        check_a7(report)
        check_a8(report)
        check_a9(report)
    finally:
        if started and not args.keep_servers:
            print()
            print("  正在关闭本脚本启动的服务…")
            for proc in started:
                stop(proc)
        elif started:
            print(f"\n  服务仍在运行（--keep-servers）：后端 :{BACKEND_PORT} / 前端 :{FRONTEND_PORT}")
        shutil.rmtree(tmp, ignore_errors=True)

    return report.summary()


if __name__ == "__main__":
    sys.exit(main())
