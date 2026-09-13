"""应用配置。

安全基线（AGENTS.md §4.1）：厂商凭据 / 端点 / 音色 ID 一律来自环境变量或 .env，
代码里不得出现任何字面量。没有 .env 也必须能启动（走 Mock Provider）。

注意：所有环境变量都在 create_app 时读取，不在 import 时冻结 ——
否则测试里 monkeypatch.setenv 会失效，多环境部署也会互相污染。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import ClassVar

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent

# --- 静态常量（与环境无关，不随 .env 变化）---

# 内网网段黑名单：自定义 base_url 命中即拒绝（AGENTS.md §4.1 防 SSRF）
SSRF_BLOCKED_NETWORKS = [
    "0.0.0.0/8",
    "10.0.0.0/8",
    "127.0.0.0/8",
    "169.254.0.0/16",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "::1/128",
    "fc00::/7",
    "fe80::/10",
]

SSRF_BLOCKED_SCHEMES = ["file", "gopher", "ftp", "dict", "ldap", "data"]

# 上传白名单（AGENTS.md §4.1：类型白名单 + 魔数校验 + 大小上限）
ALLOWED_UPLOAD_EXTENSIONS = [
    ".pdf",
    ".docx",
    ".pptx",
    ".txt",
    ".md",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
]

ALLOWED_UPLOAD_MIMETYPES = [
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain",
    "text/markdown",
    "image/png",
    "image/jpeg",
    "image/webp",
]


_dotenv_loaded = False


def _load_dotenv_once() -> None:
    """加载 backend/.env。测试可设 EDUAGENTX_DISABLE_DOTENV=1 跳过。

    在**第一次读配置时**加载，而不是 import 这个模块时 ——
    否则「测试不要读 .env」这个开关永远慢半拍：pytest 在 import 阶段
    就跑完了 app.config，而那会儿夹具还没机会设这个变量，开发机上的
    .env（含真实 Key）就漏进了整个测试进程。
    """
    # 模块级的一次性标记：测试要能把它重置回 False 来复现加载过程，
    # 所以用全局变量而不是闭包 / lru_cache
    global _dotenv_loaded  # noqa: PLW0603
    if _dotenv_loaded or os.environ.get("EDUAGENTX_DISABLE_DOTENV"):
        return
    _dotenv_loaded = True
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - 依赖缺失时不阻断启动
        return
    # override=False：真实环境变量优先于 .env，便于容器 / CI 覆盖
    load_dotenv(BACKEND_DIR / ".env", override=False)


def env_str(name: str, default: str = "") -> str:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip()


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return default


def default_database_uri(env_name: str) -> str:
    """显式配置优先；否则用 backend/data 下的 SQLite 文件（测试走内存库）。"""
    explicit = env_str("DATABASE_URL") or env_str("SQLALCHEMY_DATABASE_URI")
    if explicit:
        return explicit
    if env_name == "testing":
        return "sqlite://"
    return f"sqlite:///{(BACKEND_DIR / 'data' / 'eduagentx.db').as_posix()}"


def read_env_config(env_name: str) -> dict:
    """把当前进程环境读成一份配置字典。每次调用都重新读，不缓存。"""
    return {
        # --- 基础 ---
        "SECRET_KEY": env_str("SECRET_KEY", ""),
        "FERNET_KEY": env_str("FERNET_KEY", ""),
        # --- 数据库 ---
        "SQLALCHEMY_DATABASE_URI": default_database_uri(env_name),
        "DB_WRITE_SERIALIZE": env_bool("DB_WRITE_SERIALIZE", True),
        # --- 上传 ---
        "UPLOAD_DIR": env_str("UPLOAD_DIR") or str(BACKEND_DIR / "data" / "uploads"),
        "MAX_CONTENT_LENGTH": env_int("MAX_CONTENT_LENGTH", 20 * 1024 * 1024),
        # --- 文本 LLM（OpenAI 兼容）---
        "LLM_PROVIDER": env_str("LLM_PROVIDER", "deepseek"),
        "LLM_API_KEY": env_str("LLM_API_KEY", ""),
        "LLM_BASE_URL": env_str("LLM_BASE_URL", ""),
        "LLM_MODEL": env_str("LLM_MODEL", ""),
        "LLM_TIMEOUT": env_float("LLM_TIMEOUT", 120.0),
        "LLM_MAX_RETRIES": env_int("LLM_MAX_RETRIES", 2),
        # --- 课程生成管线 ---
        # 单页生成的超时（秒）。与 LLM_TIMEOUT 是两回事：后者是共享 HTTP 客户端的
        # 传输超时，前者是「这一页给你多少秒」（P1-F4）。并发写页时各自计时，
        # 慢的一页到点就放弃并标记失败，不让整门课等它。
        "GEN_PAGE_TIMEOUT": env_float("GEN_PAGE_TIMEOUT", 60.0),
        # 写页的并发路数（默认 3）。它是一次任务的平均速度与上游限流之间的平衡点：
        # 调大能更快跑完，但多数兼容实现在 5~10 路并发时开始返回 429。
        "GEN_CONCURRENCY": env_int("GEN_CONCURRENCY", 3),
        # 后台线程池大小（同时能跑几门课）。写页的并发数在上面，这里是任务级的
        # 并发：超出的任务会**被拒绝**（返回 False）而不是排队 —— 同一门课的两次
        # 生成同时跑会把页码与版本号写乱（见 common/tasks.py）。
        "GEN_WORKERS": env_int("GEN_WORKERS", 4),
        # SSE 心跳间隔（秒）。中间代理（Nginx 默认 60s）会掐掉长时间没有字节的
        # 连接，15s 是「比任何常见代理超时都短、又不至于刷屏」的取值（AGENTS §17）。
        "SSE_HEARTBEAT": env_float("SSE_HEARTBEAT", 15.0),
        # 敏感词表的**本地追加项**（逗号分隔）。内置表在 services/generation/filter.py，
        # 这里只放「这台机器/这所学校额外要拦的词」——不在代码里写死，
        # 是因为它随场景变化，而内置表要能保证「一份代码到哪都拦得住基本盘」。
        "SENSITIVE_WORDS": env_str("SENSITIVE_WORDS", ""),
        # --- 语音：大模型 TTS 2.0（双向流式 WS，二进制私有帧）---
        "VOLC_TTS_ENDPOINT": env_str("VOLC_TTS_ENDPOINT", ""),
        "VOLC_TTS_API_KEY": env_str("VOLC_TTS_API_KEY", ""),
        "VOLC_TTS_RESOURCE_ID": env_str("VOLC_TTS_RESOURCE_ID", ""),
        "VOLC_TTS_AUDIO_FORMAT": env_str("VOLC_TTS_AUDIO_FORMAT", "mp3"),
        "VOLC_TTS_SAMPLE_RATE": env_int("VOLC_TTS_SAMPLE_RATE", 24000),
        "VOLC_TTS_SPEECH_RATE": env_int("VOLC_TTS_SPEECH_RATE", 0),
        "VOLC_TTS_ENABLE_SUBTITLE": env_bool("VOLC_TTS_ENABLE_SUBTITLE", True),
        # 一次合成的等待上限（秒）。0 = 用 Provider 自己的缺省。
        "VOLC_TTS_TIMEOUT": env_float("VOLC_TTS_TIMEOUT", 0.0),
        # 音色必须来自 TTS 2.0 池（_uranus_bigtts），与实时语音池不通用
        "VOLC_TTS_SPEAKER": env_str("VOLC_TTS_SPEAKER", ""),
        # 内置音色卡的厂商音色 ID（种子数据从这里取，代码里零字面量）
        "VOLC_TTS_VOICE_TEACHER": env_str("VOLC_TTS_VOICE_TEACHER", ""),
        "VOLC_TTS_VOICE_HISTORY": env_str("VOLC_TTS_VOICE_HISTORY", ""),
        "VOLC_TTS_VOICE_SCIENCE": env_str("VOLC_TTS_VOICE_SCIENCE", ""),
        # --- 语音：端到端实时语音（全双工，纯 JSON 文本帧 + Base64）---
        "VOLC_REALTIME_ENDPOINT": env_str("VOLC_REALTIME_ENDPOINT", ""),
        "VOLC_REALTIME_API_KEY": env_str("VOLC_REALTIME_API_KEY", ""),
        "VOLC_REALTIME_MODEL": env_str("VOLC_REALTIME_MODEL", ""),
        # 音色必须来自实时池（_jupiter_bigtts），中文只有 4 个
        "VOLC_REALTIME_SPEAKER": env_str("VOLC_REALTIME_SPEAKER", ""),
        "VOLC_REALTIME_QPM_LIMIT": env_int("VOLC_REALTIME_QPM_LIMIT", 60),
        # 同三位老师的**实时池**音色 ID（与上面 TTS 池成对，两池不通用）。
        # 不落库：换了 .env 就该立刻生效，不该还要重新灌一次种子。
        "VOLC_REALTIME_VOICE_TEACHER": env_str("VOLC_REALTIME_VOICE_TEACHER", ""),
        "VOLC_REALTIME_VOICE_HISTORY": env_str("VOLC_REALTIME_VOICE_HISTORY", ""),
        "VOLC_REALTIME_VOICE_SCIENCE": env_str("VOLC_REALTIME_VOICE_SCIENCE", ""),
        # --- 语音：流式 ASR（二进制私有帧，与 TTS 编解码器不通用）---
        "VOLC_ASR_ENDPOINT": env_str("VOLC_ASR_ENDPOINT", ""),
        "VOLC_ASR_API_KEY": env_str("VOLC_ASR_API_KEY", ""),
        "VOLC_ASR_RESOURCE_ID": env_str("VOLC_ASR_RESOURCE_ID", ""),
        "VOLC_ASR_PACKET_MS": env_int("VOLC_ASR_PACKET_MS", 200),
        # --- 语音资产与开关（P2）---
        # 合成出来的音频放在这儿（`{AUDIO_DIR}/{course_id}/{beat_id}_{hash8}.mp3`）。
        # 库里只记相对路径（P2-C4），所以换机器只需要改这一个值。
        "AUDIO_DIR": env_str("AUDIO_DIR")
        or str(BACKEND_DIR / "data" / "assets" / "audio"),
        # 语音总开关（P2-G3）。关掉后课堂退化为纯文字：讲稿还在、字幕还在、
        # 问答还能打字，只是没有声音 —— 不是把功能藏起来，是换成能用的那一档。
        "VOICE_ENABLED": env_bool("VOICE_ENABLED", True),
        # 预合成是**顺序**做的（P2-D4 的 3 分钟预算靠单次时延，不靠并发）：
        # VolcTTS 复用一条连接、整段合成期间持锁，起多个线程只会让请求排队，
        # 却把「上游同一时刻收到几个请求」变得说不清 —— 而限流是按账号算的。
        # 这里不提供并发开关，是因为提供了也做不到。
        # 试听固定说这一句（P2-A5）。改了它就会重新合成一次 —— 试听缓存按文本做哈希。
        "VOICE_PREVIEW_TEXT": env_str("VOICE_PREVIEW_TEXT", "同学们好，我是这节课的老师。"),
        # 价目表（元）。默认 0 = **没配价目**，界面如实显示「未配置单价」。
        # 各账号的合同价不同，代码里编一个数字出来只会让看板显得可信而实际不准。
        "VOICE_TTS_PRICE_PER_KCHARS": env_float("VOICE_TTS_PRICE_PER_KCHARS", 0.0),
        "VOICE_REALTIME_PRICE_PER_MINUTE": env_float("VOICE_REALTIME_PRICE_PER_MINUTE", 0.0),
        "VOICE_ASR_PRICE_PER_MINUTE": env_float("VOICE_ASR_PRICE_PER_MINUTE", 0.0),
        # --- 成本看板（P5）---
        # 文本模型的价目表（元 / 千 token），输入输出分开：两者的价差常常有好几倍，
        # 合成一个数会让「为什么这次特别贵」永远答不出来。
        # 与语音同理，默认 0 = 没配 —— 看板照实说「未配置单价」，不编一个数出来。
        # 设置页的覆盖（`settings_kv.pricing`）优先级更高，见 `services/usage/pricing.py`。
        "LLM_PRICE_PROMPT_PER_1K": env_float("LLM_PRICE_PROMPT_PER_1K", 0.0),
        "LLM_PRICE_COMPLETION_PER_1K": env_float("LLM_PRICE_COMPLETION_PER_1K", 0.0),
        # 「一天」从几点开始算（P5 §4.2）。
        #
        # 库里所有时间都是 UTC，但「今天花了多少」是给人看的：按 UTC 算的话，
        # 北京时间早上 8 点日预算就重置了 —— 用户看到的是「我什么都没干，
        # 今天的额度就回来了」。所以日切按本地时间，这个值就是本地时区与 UTC
        # 的偏移小时数（8 = 北京）。它同时决定看板的横轴切点、
        # `daily_usage.date` 的含义、以及日预算何时重置 —— 三处必须是同一个值。
        "USAGE_DAY_OFFSET_HOURS": env_int("USAGE_DAY_OFFSET_HOURS", 8),
        # --- 课堂运行时（P3）---
        # 课堂总开关（P3-G3）。关掉后没有推送通道，课堂退化为「逐页手动翻页
        # + 文字消息」—— 退了但能用，而不是白屏。与 VOICE_ENABLED 是同一种开关：
        # 关掉一个能力，剩下的那条路要自己站得住。
        "CLASSROOM_WS": env_bool("CLASSROOM_WS", True),
        # 单会话连接数上限与单用户并发开的课堂数上限（P3-F5）。
        # 50 是「一个班 + 几个旁听」；2 是「一个人不该同时开两堂课」。
        "CLASSROOM_MAX_CONNECTIONS": env_int("CLASSROOM_MAX_CONNECTIONS", 50),
        "CLASSROOM_MAX_SESSIONS_PER_USER": env_int("CLASSROOM_MAX_SESSIONS_PER_USER", 2),
        # 心跳与判死（§4.2）：20s 打一次 ping，60s 没动静就从在线数里摘掉。
        # 两个值分开配，是因为它们回答的是两个问题：「多久问一次」和「多久算没了」。
        "CLASSROOM_HEARTBEAT": env_float("CLASSROOM_HEARTBEAT", 20.0),
        "CLASSROOM_TIMEOUT": env_float("CLASSROOM_TIMEOUT", 60.0),
        # 一个 Turn 排队超过这么久没轮上就丢弃（§2.2）。恢复播放时不该一次性
        # 蹦出五条过期发言 —— 那不是课堂，那是缓存穿透。
        "CLASSROOM_TURN_TTL": env_float("CLASSROOM_TURN_TTL", 20.0),
        # `session_events` 的单会话条数上限（P3-C2）。到顶后按 TTL 从头清理最老的
        # 事件 —— 清掉的是「补发能力」，不是「记录」：记录页读的是 messages 那几张表。
        "CLASSROOM_MAX_EVENTS": env_int("CLASSROOM_MAX_EVENTS", 5000),
        # 讲稿的节奏：一拍说完到下一句开口之间留的那口气，以及翻到新一页之后的
        # 留白（秒）。0 就是一句接一句不留白 —— 听着赶；两个值都是**口味**不是
        # 对错，觉得快了就调大、觉得拖就调小（上限 10s，再大课堂就该像卡住了）。
        # 翻页比换句久，是因为幻灯片换了得先让学生看一眼那张图。
        "CLASSROOM_BEAT_GAP": env_float("CLASSROOM_BEAT_GAP", 0.6),
        "CLASSROOM_PAGE_GAP": env_float("CLASSROOM_PAGE_GAP", 1.5),
        # 插话决策（一次 LLM 调用）的等待上限（P3-D3）。超时直接跳过这一轮：
        # 宁可这节课少一次插话，也不能让整堂课的进度卡在一次模型调用上。
        "CLASSROOM_INTERJECTION_TIMEOUT": env_float("CLASSROOM_INTERJECTION_TIMEOUT", 3.0),
        # 学生发言的长度上限与限流（P3-F2）。
        "CLASSROOM_MAX_MESSAGE_CHARS": env_int("CLASSROOM_MAX_MESSAGE_CHARS", 500),
        "CLASSROOM_RATE_LIMIT_COUNT": env_int("CLASSROOM_RATE_LIMIT_COUNT", 5),
        "CLASSROOM_RATE_LIMIT_WINDOW": env_float("CLASSROOM_RATE_LIMIT_WINDOW", 10.0),
        # 每页至少隔几页才允许 AI 同学再插一次话（§2.3「每 3 页最多插话 1 次」）。
        "CLASSROOM_INTERJECTION_MIN_PAGES": env_int("CLASSROOM_INTERJECTION_MIN_PAGES", 3),
        # --- 材料（P4）---
        # 材料总开关（P4-G3）。关掉后上传入口隐藏、生成回到 P1 那条只凭主题的路
        # —— 与 VOICE_ENABLED / CLASSROOM_WS 同一种开关：关掉一个能力，
        # 剩下的那条路要自己站得住。
        "MATERIAL_ENABLED": env_bool("MATERIAL_ENABLED", True),
        # 原文件放这儿（`{MATERIAL_DIR}/{material_id}/`）。与 AUDIO_DIR 同一条口径：
        # 库里只记相对路径（P4-C3），换机器只需要改这一个值。
        "MATERIAL_DIR": env_str("MATERIAL_DIR")
        or str(BACKEND_DIR / "data" / "materials"),
        # --- 导出（P5）---
        # 产物放这儿（`{EXPORT_DIR}/{course_id}/{export_id}.{ext}`）。与 AUDIO_DIR /
        # MATERIAL_DIR 同一条口径：库里只记相对路径（P5-C1），换机器改这一个值。
        # 它和 `data/` 一样是**可再生的**：产物过期即删，课程 DSL 还在库里，
        # 想要再导一次就是（这条写在 models/export.py 的头注释里）。
        "EXPORT_DIR": env_str("EXPORT_DIR")
        or str(BACKEND_DIR / "data" / "exports"),
        # 产物在盘上留多久（P5-A6 的「24h 后链接过期」）。到点由清理任务删文件与记录。
        "EXPORT_TTL_HOURS": env_float("EXPORT_TTL_HOURS", 24.0),
        # 单份产物的字节上限。超过就不落盘、直接判失败：与其让用户点开一个
        # 打不开的 200MB HTML，不如当场说「这份导出太大了，试试只导某几章」。
        "EXPORT_MAX_BYTES": env_int("EXPORT_MAX_BYTES", 64 * 1024 * 1024),
        # 单份材料的字节上限（P4-B1 要 50MB）。比全局 MAX_CONTENT_LENGTH 大是故意的：
        # 那个值管的是**所有**上传（语音样本几十 KB、图片几 MB），材料是唯一真需要
        # 大文件的那条路 —— 按端点放开，而不是把全站上限抬到 50MB。
        "MATERIAL_MAX_BYTES": env_int("MATERIAL_MAX_BYTES", 50 * 1024 * 1024),
        # 分块的目标长度与相邻块的重叠（F4-3）。600 字是「一口气读得完的一段」，
        # 60 字的重叠是「跨块的一句话两边都捞得到」—— 检索命中时不会因为
        # 刚好落在切口上而丢。
        "MATERIAL_CHUNK_CHARS": env_int("MATERIAL_CHUNK_CHARS", 600),
        "MATERIAL_CHUNK_OVERLAP": env_int("MATERIAL_CHUNK_OVERLAP", 60),
        # 生成时注入的片段数（F4-7）：写页 8 段、大纲阶段每章 5 段。
        # 8 × 600 字 ≈ 5k 字，是「材料够用」与「别把上下文吃光」之间的一个数；
        # 材料更长时按章检索（F4-13），不会把整份讲义塞进去。
        "MATERIAL_PAGE_TOP_K": env_int("MATERIAL_PAGE_TOP_K", 8),
        "MATERIAL_OUTLINE_TOP_K": env_int("MATERIAL_OUTLINE_TOP_K", 5),
        # 引文校验要求的最短匹配长度（P4-C2）。20 字是「这句话确实来自材料」
        # 的下限：再短就可能是巧合（「因此我们可以看出」这种句子到处都是）。
        "MATERIAL_QUOTE_MIN_CHARS": env_int("MATERIAL_QUOTE_MIN_CHARS", 20),
        # 材料超过这么多字时提示「建议拆分」（F4-13）。按 600 字一块算，
        # 10 万字约 170 块 —— 检索还跑得动，但整份灌进上下文已经不可能了。
        "MATERIAL_MAX_CHARS": env_int("MATERIAL_MAX_CHARS", 200_000),
        # --- 站点访问码（P5-A13，§6）---
        # 空 = 关闭（本地单机缺省）。见 common/access.py 第 1 条：默认开着但没人配，
        # 比默认关着危险得多 —— 前者会让人以为有保护。
        "SITE_ACCESS_CODE": env_str("SITE_ACCESS_CODE", ""),
        # 通过之后记多久（秒）。7 天是「不用天天输，但换台机器就得重来」。
        "ACCESS_TTL_SECONDS": env_int("ACCESS_TTL_SECONDS", 7 * 24 * 3600),
        # Cookie 名带 eduagentx_ 前缀与同类 cookie 区分开；改名会让已发出去的
        # cookie 全部作废（等于把人全踢下线），所以别随手改。
        "ACCESS_COOKIE_NAME": env_str("ACCESS_COOKIE_NAME", "eduagentx_access"),
        # 只在 HTTPS 上设 Secure。缺省关：http 上开了它浏览器直接丢弃这个 cookie，
        # 表现是「码输对了还是一直弹回校验页」（见 common/access.py 的注释）。
        # 加了 TLS 的部署（compose 的 nginx 档）把它设成 true。
        "ACCESS_COOKIE_SECURE": env_bool("ACCESS_COOKIE_SECURE", False),
        # 同一个 IP 在一个窗口里最多试几次。0 = 不限（本地调试用）。
        "ACCESS_RATE_LIMIT_COUNT": env_int("ACCESS_RATE_LIMIT_COUNT", 10),
        "ACCESS_RATE_LIMIT_WINDOW": env_float("ACCESS_RATE_LIMIT_WINDOW", 60.0),
        # --- 审计（P5-A14）---
        # 审计里的 IP 取不取 `X-Forwarded-For`。**只有确实在反向代理后面才开**：
        # 那个头是客户端能自己填的，无条件采信等于让「从哪来」变成操作者说了算。
        "AUDIT_TRUST_PROXY": env_bool("AUDIT_TRUST_PROXY", False),
        # --- 前端产物 ---
        # 生产由后端托管（compose 里 app 一个容器就是完整站点）。目录不存在
        # 时不注册路由：开发期是 Vite 在 5173 提供页面，后端这儿不该多出一堆 404。
        "FRONTEND_DIST": env_str("FRONTEND_DIST")
        or str(PROJECT_ROOT / "frontend" / "dist"),
        # --- 备份（P5-C3 / §6）---
        # 备份落在 data 树里，于是它就是那个卷的一部分：宿主机 `./data/backups`
        # 直接能看到、能拷走。**不会递归**：归档只收库与四类文件，
        # 不含 backups 自己。
        "BACKUP_DIR": env_str("BACKUP_DIR")
        or str(BACKEND_DIR / "data" / "backups"),
        # 留最近的几份（0 = 全部留着）。7 份是按「一天一份」配的：
        # 定时备份不设上限，总有一天会把盘写满，而写满之后先坏的是主库。
        "BACKUP_KEEP": env_int("BACKUP_KEEP", 7),
        # --- 日志 ---
        "LOG_LEVEL": env_str("LOG_LEVEL", "INFO").upper(),
        # 写文件才轮转；空 = 只出控制台。容器里保持为空是对的 ——
        # docker/k8s 本来就是「打进 stdout 由运行时收」，自己再写一份文件，
        # 日志就有了两个去处，而运维只会看其中一个。
        "LOG_FILE": env_str("LOG_FILE", ""),
        # 单文件上限与保留份数（P5-F4：单文件 ≤ 50MB）。按默认 50MB × 5 份算，
        # 长期运行的机器最多留 250MB 日志。
        "LOG_MAX_BYTES": env_int("LOG_MAX_BYTES", 50 * 1024 * 1024),
        "LOG_BACKUP_COUNT": env_int("LOG_BACKUP_COUNT", 5),
    }


class BaseConfig:
    """跨环境共享的配置。所有属性都可被环境变量覆盖（见 read_env_config）。"""

    ENV_NAME = "base"
    DEBUG = False
    TESTING = False

    JSON_SORT_KEYS = False
    PROPAGATE_EXCEPTIONS = None  # 交给 Flask 按 TESTING/DEBUG 决定

    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS: ClassVar[dict] = {
        # SQLite 单写者：由 common.dbw 串行化，连接本身放开线程检查
        "connect_args": {"check_same_thread": False, "timeout": 15},
        "pool_pre_ping": True,
    }

    ALLOWED_UPLOAD_EXTENSIONS: ClassVar[list[str]] = list(ALLOWED_UPLOAD_EXTENSIONS)
    ALLOWED_UPLOAD_MIMETYPES: ClassVar[list[str]] = list(ALLOWED_UPLOAD_MIMETYPES)
    SSRF_BLOCKED_NETWORKS: ClassVar[list[str]] = list(SSRF_BLOCKED_NETWORKS)
    SSRF_BLOCKED_SCHEMES: ClassVar[list[str]] = list(SSRF_BLOCKED_SCHEMES)
    # 校验自定义 base_url 时是否解析域名。IP 字面量不受此开关影响，永远会查黑名单。
    SSRF_RESOLVE_HOSTS = True

    # 生成参数边界（P0 §4.2：页数 8~20、同学数 0~5）
    MIN_PAGE_COUNT = 8
    MAX_PAGE_COUNT = 20
    MIN_CLASSMATE_COUNT = 0
    MAX_CLASSMATE_COUNT = 5

    @classmethod
    def load(cls) -> dict:
        """展开成 Flask 可直接 from_mapping 的字典：静态 → 父类 → 子类 → 环境变量。"""
        _load_dotenv_once()  # 读环境变量之前先把 .env 铺进 os.environ（只做一次）
        config: dict = {}
        for klass in reversed(cls.__mro__):
            config.update({k: v for k, v in vars(klass).items() if k.isupper()})
        config.update(read_env_config(cls.ENV_NAME))
        return config


class DevelopmentConfig(BaseConfig):
    ENV_NAME = "development"
    DEBUG = env_bool("DEBUG", True)


class TestingConfig(BaseConfig):
    ENV_NAME = "testing"
    TESTING = True
    DEBUG = False
    # 测试不联网（AGENTS.md §23）。关掉域名解析，但内网 IP 字面量照样会被拒 ——
    # 那一条判定不需要 DNS，所以 SSRF 的契约测试仍然测的是真代码。
    SSRF_RESOLVE_HOSTS = False


class ProductionConfig(BaseConfig):
    ENV_NAME = "production"
    DEBUG = False
    TESTING = False


CONFIG_MAP = {
    "development": DevelopmentConfig,
    "dev": DevelopmentConfig,
    "testing": TestingConfig,
    "test": TestingConfig,
    "production": ProductionConfig,
    "prod": ProductionConfig,
}


def resolve_config(name: str | None = None):
    """按名字取配置类，未知名字回落到 development。"""
    key = (name or os.environ.get("APP_ENV") or "development").strip().lower()
    return CONFIG_MAP.get(key, DevelopmentConfig)


# 注：这里曾有一个 describe_capabilities()，只按 .env 判断能力可用性。
# 它会有第二个事实来源 —— 设置页存进 providers 表的凭据它看不见。
# 现在统一由 services/provider_registry.capabilities() 回答（基于注册表）。
