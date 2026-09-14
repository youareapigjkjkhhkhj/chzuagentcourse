"""健康检查与能力清单（§4.1）。

`/api/health` 是唯一一个「永远不会因为业务原因失败」的接口：
它要能在数据库连不上、Provider 全没配的情况下照样返回 200，
否则监控与容器编排会把它当成「服务挂了」而反复重启。

`db` 字段如实报告数据库状态：健康检查的价值就在于发现问题，
把它做成永远绿的灯，等于把这个接口删掉。
"""

from __future__ import annotations

from flask import Blueprint

from app.common.response import ok
from app.providers.registry import MOCK_NAME
from app.services import provider_registry
from app.services.exports import theme as themes

bp = Blueprint("health", __name__, url_prefix="/api")


def _database_status() -> str:
    """探一次数据库。失败返回 error:<原因>，绝不抛。"""
    from sqlalchemy import text

    from app.extensions import db

    try:
        db.session.execute(text("SELECT 1"))
    except Exception as exc:
        db.session.rollback()
        return f"error:{type(exc).__name__}"
    return "ok"


@bp.get("/health")
def health():
    """健康检查：版本、数据库连通性、四类 Provider 的就绪状态。

    请求示例：
        GET /api/health

    它永远返回 200，数据库挂了也在 `data.db` 字段里说 —— 监控按状态码
    判断存活，业务原因不该让容器被反复重启。
    """
    report = provider_registry.self_check()

    def state(kind: str) -> str:
        """`ready` 的判据是「真的配好了」，**离线替身不算**。

        与 /api/capabilities 的 available 刻意不同：那里回答「能不能点」
        （mock 的文本模型确实能出内容，点了不报错），
        这里回答「运维上配好了没」——语音指向 mock 就等于没有声音，
        报 ready 会让「为什么没声音」变成一个需要翻代码才能回答的问题。
        规格给的就是这个语义：providers.tts = "unconfigured"。

        凭据齐**且**适配器已实现才算 ready：P0 的三个语音适配器只有骨架，
        .env 里的真 Key 会让它们「已配置」，但调用只会抛 50201。
        报 ready 就是把「P2 才交付」伪装成「已经好了」—— 而排查一个
        报 50201 的 ready 服务，比排查一个明说 unconfigured 的要难得多。

        取值仍然只有 ready / unconfigured 两种（§4.1 钉死的形状）；
        「为什么不是 ready」由 issues 里的 {kind}_pending 说清楚。
        """
        name = report["active"][kind]
        info = report["providers"].get(kind, {}).get(name)
        if name == MOCK_NAME or not info:
            return "unconfigured"
        ready = bool(info.get("configured")) and bool(info.get("implemented", True))
        return "ready" if ready else "unconfigured"

    from app import __version__

    return ok(
        {
            "status": "ok",
            "version": __version__,
            "db": _database_status(),
            "providers": {kind: state(kind) for kind in ("llm", "tts", "asr", "realtime")},
            "llm": {
                "provider": report["active"]["llm"],
                "model": report["providers"]
                .get("llm", {})
                .get(report["active"]["llm"], {})
                .get("model", ""),
            },
            "issues": report["issues"],
        }
    )


@bp.get("/capabilities")
def capabilities():
    """能力清单：四类能力各自能不能用、不能用是缺什么。

    请求示例：
        GET /api/capabilities

    前端据此置灰不可用的入口。只暴露「配没配」，绝不回显凭据。

    顺带下发一份 PPT 模板清单（`templates`）：首页开始生成时选模板、以及工作台
    预览要照模板换色/换版式，都在**还没有课程**的时候就要这份清单，不能等
    `/courses/{id}/exports`（那个要先有课）。模板只是配色+字体+版式的纯数据，
    与凭据无关，搭能力清单的顺风车下发最省一个端点。
    """
    data = dict(provider_registry.capabilities())
    data["templates"] = themes.catalogue()
    return ok(data)
