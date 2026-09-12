"""课堂角色（§4.2）。

只读：内置角色（沈老师 + 林晓 / 陈默 / 苏雨）由种子数据提供，
用户在 P0 阶段不需要增删角色 —— 他怎么说话由 persona 里的语气、
语速、音调偏移决定，那是角色自带的东西。

按 sort_order 排序：老师必须第一个（前端头像是按顺序摆的）。
"""

from __future__ import annotations

from flask import Blueprint

from app.common.response import ok
from app.models import AgentRole

bp = Blueprint("agents", __name__, url_prefix="/api/agents")


@bp.get("/roles")
def list_roles():
    """课堂角色列表：1 位主讲老师 + 3 位 AI 同学（老师排第一）。

    请求示例：
        GET /api/agents/roles

    返回 `data.items[]`，每项含 id / name / role / avatarColor / voiceId / persona。
    """
    roles = AgentRole.query.order_by(AgentRole.sort_order, AgentRole.id).all()
    items = [role.to_dict() for role in roles]
    return ok({"items": items, "total": len(items)})
