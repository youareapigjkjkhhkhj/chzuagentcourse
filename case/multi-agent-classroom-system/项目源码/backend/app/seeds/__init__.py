"""种子数据：内置音色、课堂角色与两门**官方示例课**（P1-7）。

设计原则：**只补缺，不覆盖**。
- 反复执行不产生重复行（幂等，P0-C5）
- 用户改过的字段不会被下次 seed 冲掉
- 音色 ID 等环境相关值从配置读取，不写死在代码里
- 课程内容只从 `app/seeds/courses/` 那一份作者稿来：页面形状走
  `schema.validate_page()`，页数/时长/封面由 `store.rebuild_dsl()` 从页面行重算

用法：
    flask --app app seed          # CLI
    from app.seeds import run_seed; run_seed()
"""

from __future__ import annotations

from typing import Any

from flask import current_app

from app.common.dbw import db_write
from app.common.logging import get_logger
from app.extensions import db
from app.models import AgentRole, Course, CoursePage, Provider, User, VoiceProfile
from app.models.provider import BUILTIN_PROVIDERS
from app.seeds.courses import (
    OWNER_ID,
    course_specs,
    dsl_of,
    meta_of,
    page_specs_of,
)
from app.seeds.roles import role_specs
from app.seeds.voices import voice_specs
from app.services.courses import store

_logger = get_logger("app.seeds")

DEMO_OWNER_NAME = "演示教师"


def _ensure(model, row_id: str, **fields) -> tuple[Any, bool]:
    """存在就原样返回，不存在才插入。返回 (实例, 是否新建)。

    fields 里若带 id（种子 spec 通常自带）会被忽略，以 row_id 为准。
    """
    fields.pop("id", None)
    existing = db.session.get(model, row_id)
    if existing is not None:
        return existing, False
    row = model(id=row_id, **fields)
    db.session.add(row)
    return row, True


def _default_enabled_id() -> str:
    """种子把哪家标成「已启用」。

    .env 指定了 LLM_PROVIDER 就听它的 —— 否则会出现
    「卡片显示 DeepSeek 已启用，实际请求发去 Qwen」这种自相矛盾，
    而 /api/health 与设置页会各说各话。没指定时用内置默认（DeepSeek）。
    """
    configured = str(current_app.config.get("LLM_PROVIDER") or "").strip()
    if configured:
        return configured
    return next(spec["id"] for spec in BUILTIN_PROVIDERS if spec["enabled"])


def _seed_providers() -> int:
    enabled_id = _default_enabled_id()
    created = 0
    for spec in BUILTIN_PROVIDERS:
        _, is_new = _ensure(
            Provider,
            spec["id"],
            name=spec["name"],
            kind=spec["kind"],
            enabled=spec["id"] == enabled_id,
        )
        created += int(is_new)
    return created


def _seed_voices() -> int:
    created = 0
    for spec in voice_specs():
        _, is_new = _ensure(VoiceProfile, spec["id"], **spec)
        created += int(is_new)
    return created


def _seed_roles() -> int:
    created = 0
    for spec in role_specs():
        fields = {k: v for k, v in spec.items() if k != "persona"}
        row, is_new = _ensure(AgentRole, spec["id"], **fields)
        if is_new:
            row.persona = spec["persona"]  # JSONField 描述符负责编码
        created += int(is_new)
    return created


def _seed_courses() -> tuple[int, int]:
    """预置示例课（P1-7）+ 它们的页面。返回 (新建课程数, 新建页面数)。

    两处判重：课程按 id、页面按 (course_id, page_no)。**只补缺，不改已有的** ——
    用户在示例课上改过的页，重跑种子不会被冲回原样。

    页面走 `store.save_page(reason="seed")` 而不是直插：这样每一页都有
    V1 版本记录。用户第一次重写它时，版本表里才有能退回去的那一版。
    """
    owner, _ = _ensure(User, OWNER_ID, name=DEMO_OWNER_NAME, role="teacher")
    courses_created = 0
    pages_created = 0

    for spec in course_specs():
        course_id = spec["id"]
        course, is_new = _ensure(Course, course_id, owner_id=owner.id, **spec)
        courses_created += int(is_new)

        # 章节骨架（章节标题/讨论点是作者写的；页号列表由 rebuild_dsl 重算）。
        # 「缺才补」而不是「新建才写」：P0 的种子只写了页面行、没写章节，
        # 那些库里升上来，整门课会被大纲树当成一堆不属于任何一章的散页。
        if not (course.dsl or {}).get("chapters"):
            course.dsl = {**dsl_of(course_id), "meta": meta_of(course_id)}

        pages_created += _seed_pages(course, page_specs_of(course_id))
        # 页数、时长、封面都是派生值，只由页面行算出来（P1-C1）
        store.rebuild_dsl(course)

    return courses_created, pages_created


def _seed_pages(course: Course, specs: list[dict]) -> int:
    """把缺的页面补齐。已存在的页号一律跳过（用户可能已经改过它）。"""
    existing = {
        page.page_no for page in CoursePage.query.filter_by(course_id=course.id).all()
    }
    created = 0
    for spec in specs:
        if spec["page_no"] in existing:
            continue
        row = CoursePage(
            course_id=course.id,
            chapter_no=spec["chapter_no"],
            page_no=spec["page_no"],
            kind=spec["kind"],
            title=spec["title"],
        )
        db.session.add(row)
        db.session.flush()  # 版本行要 page.id
        store.save_page(row, spec["dsl"], reason="seed", meta={"source": "seed"})
        created += 1
    return created


def _summarize() -> dict:
    return {
        "providers": Provider.query.count(),
        "voiceProfiles": VoiceProfile.query.count(),
        "agentRoles": AgentRole.query.count(),
        "users": User.query.count(),
        "courses": Course.query.count(),
        "coursePages": CoursePage.query.count(),
    }


def run_seed() -> dict:
    """灌入全部种子数据，返回当前各表数量摘要。幂等。"""

    def _work() -> dict:
        created = {
            "providers": _seed_providers(),
            "voiceProfiles": _seed_voices(),
            "agentRoles": _seed_roles(),
        }
        created["courses"], created["coursePages"] = _seed_courses()
        summary = _summarize()
        summary["created"] = created
        return summary

    summary = db_write(_work)
    _logger.info(
        "种子数据就绪 新增=%s 总计=%s",
        summary["created"],
        {k: v for k, v in summary.items() if k != "created"},
    )
    return summary


def register_cli(app) -> None:
    """注册 `flask seed` 命令（Makefile / 部署脚本依赖）。"""

    @app.cli.command("seed")
    def seed_command() -> None:  # pragma: no cover - 通过 CLI 触发
        """灌入内置音色、课堂角色与示例课程（幂等）。"""
        import click

        summary = run_seed()
        click.echo(f"种子数据：{summary['created']}")
        click.echo(
            "当前总计："
            f"角色 {summary['agentRoles']} / 音色 {summary['voiceProfiles']} / "
            f"课程 {summary['courses']} / 页面 {summary['coursePages']}"
        )
        unconfigured = VoiceProfile.query.filter_by(voice_type="").count()
        if unconfigured:
            click.echo(
                f"提示：{unconfigured} 个音色尚未配置厂商音色 ID，"
                "请在 .env 中填写 VOLC_TTS_VOICE_* 后重新执行本命令。"
            )


__all__ = ["register_cli", "run_seed"]
