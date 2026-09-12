"""Provider 分层约束（AGENTS.md §14.2）。

「换一家服务商只改一个文件」这句承诺，只有在厂商 SDK 被关在
app/providers/ 里时才成立。这条约束靠人自觉守不住 —— 一次
`from openai import OpenAI` 出现在 service 里，密钥与协议细节就开始外泄。

用 ast 而不是正则：正则会被注释、文档字符串、以及 `import openai_compatible`
这类同名导入骗过去。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
APP_DIR = BACKEND_DIR / "app"
PROVIDERS_DIR = APP_DIR / "providers"

#: 只允许出现在 app/providers/ 里的第三方模块。
#: 通用 HTTP 客户端（httpx / requests / urllib）不在此列 —— 拉取用户提供的
#: 材料链接是正经业务需求，不是厂商耦合（但仍须过 SSRF 校验）。
VENDOR_MODULES = frozenset(
    {
        "openai",
        "volcengine",
        "volcenginesdk",
        "volcengine_python_sdk",
        "websockets",
        "websocket",
    }
)


def vendor_imports(source: str) -> list[str]:
    """返回源码里直接 import 的厂商模块名（去重、有序）。"""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            # level > 0 是相对导入（from . import x），不可能是厂商模块
            names = [node.module or ""] if node.level == 0 else []
        else:
            continue
        for name in names:
            root = name.split(".")[0]
            if root in VENDOR_MODULES:
                found.add(root)
    return sorted(found)


def test_vendor_import_detector_actually_detects():
    """扫描器自测 —— 一个悄悄不再匹配的约束检查比没有检查更糟。"""
    assert vendor_imports("import openai") == ["openai"]
    assert vendor_imports("from openai import OpenAI") == ["openai"]
    assert vendor_imports("import websockets.client") == ["websockets"]
    assert vendor_imports("from app.providers.llm.openai_compatible import X") == []
    assert vendor_imports("# import openai") == []
    assert vendor_imports('"""import openai"""') == []


def test_business_code_does_not_import_vendor_sdks():
    offenders: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        if PROVIDERS_DIR in path.parents:
            continue  # 厂商细节就该待在这里，见 AGENTS.md §14.2
        hits = vendor_imports(path.read_text(encoding="utf-8"))
        if hits:
            offenders.append(f"{path.relative_to(BACKEND_DIR)} → {', '.join(hits)}")

    assert not offenders, (
        "厂商 SDK 只允许出现在 app/providers/ 下，请改成经注册表调用：\n  "
        + "\n  ".join(offenders)
    )


def test_provider_adapters_live_where_the_layout_says():
    """AGENTS.md §14.2 钉死的文件布局 —— 路径本身也是接口。"""
    for relative in (
        "providers/base.py",
        "providers/registry.py",
        "providers/llm/openai_compatible.py",
        "providers/tts/volc_tts.py",
        "providers/tts/volc_realtime.py",
        "providers/asr/volc_asr.py",
    ):
        assert (APP_DIR / relative).is_file(), f"缺少 {relative}"


def test_registry_import_is_the_only_way_in():
    """业务层只能通过注册表取 Provider，不能自己 new 一个适配器。

    否则「注册表里没有的 Provider 也能被调用」——设置页的启用/禁用就形同虚设。
    """
    # 装配处天生要 import 具体适配器 —— 那是它的职责，不是违规
    allowed = {"services/provider_registry.py"}
    offenders: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        if PROVIDERS_DIR in path.parents:
            continue
        relative = path.relative_to(APP_DIR).as_posix()
        if relative in allowed:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            module = node.module or "" if isinstance(node, ast.ImportFrom) else ""
            # app.providers.<kind>.<adapter> 是具体适配器；app.providers.base/registry
            # 是抽象层与注册表本身，业务层用它们是正当的。
            if module.startswith("app.providers.") and module.count(".") > 2:
                offenders.append(f"{relative}:{node.lineno} → {module}")

    assert not offenders, "业务代码请用 get_registry()/current_*()：\n  " + "\n  ".join(offenders)
