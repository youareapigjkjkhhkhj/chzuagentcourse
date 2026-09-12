"""每个接口都要有 docstring 与请求示例（P0-E3）。

为什么用测试盯着而不是人肉 review：接口是会一直加的，而「文档」这件事
一旦靠自觉，第一个漏掉的就是下一个接口。这里遍历真实的路由表 ——
新加的接口没写文档，这条测试立刻红，且说得出是哪个路径。

顺带钉住两件容易忘的事：
- 蓝图不要写进 docstring 的**第一行**（`flask --help` 与 OpenAPI 生成器
  都只取第一行，那行必须是「这个接口干什么」）；
- 未认领的 `/static` 不算接口。
"""

from __future__ import annotations

import pytest

#: 有路由但不属于「我们承诺的接口」的 endpoint
IGNORED_ENDPOINTS = {"static"}


def _routes(app):
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        if rule.endpoint in IGNORED_ENDPOINTS:
            continue
        yield rule, app.view_functions[rule.endpoint]


def test_every_endpoint_has_a_docstring_with_a_request_example(app_factory):
    app = app_factory()

    problems: list[str] = []
    for rule, view in _routes(app):
        doc = (view.__doc__ or "").strip()
        if not doc:
            problems.append(f"{rule.rule}（{rule.endpoint}）没有 docstring")
            continue
        if "请求示例" not in doc:
            problems.append(f"{rule.rule}（{rule.endpoint}）没写「请求示例」")
            continue
        # 第一行是摘要：不能是「请求示例」这种标签，也不能只有一个字
        summary = doc.splitlines()[0].strip()
        if len(summary) < 8:
            problems.append(f"{rule.rule}（{rule.endpoint}）的摘要太短：{summary!r}")

    assert not problems, "接口文档不完整（P0-E3）：\n  - " + "\n  - ".join(problems)


def test_documented_methods_match_the_route_table(app_factory):
    """示例里的方法要真的是这个路由允许的方法。

    防的是复制粘贴：把 GET 的说明抄给 PUT 之后，文档看着齐全、却全错。
    """
    app = app_factory()

    wrong: list[str] = []
    for rule, view in _routes(app):
        doc = view.__doc__ or ""
        example = next((ln.strip() for ln in doc.splitlines() if "请求示例" in ln), "")
        # 「请求示例：」在上一行时，方法在下一行
        if example.endswith("："):
            lines = doc.splitlines()
            index = next(i for i, ln in enumerate(lines) if "请求示例" in ln)
            example = lines[index + 1].strip() if index + 1 < len(lines) else ""
        example = example.replace("请求示例：", "").strip()
        method = example.split(" ")[0].upper() if example else ""
        if method not in rule.methods - {"HEAD", "OPTIONS"}:
            wrong.append(f"{rule.rule} 允许 {sorted(rule.methods - {'HEAD', 'OPTIONS'})}，示例写的是 {method!r}")

    assert not wrong, "文档里的方法与路由表不符：\n  - " + "\n  - ".join(wrong)


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
