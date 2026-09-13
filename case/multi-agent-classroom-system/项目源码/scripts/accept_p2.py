#!/usr/bin/env python
"""P2 A/B/C/F/G 类验收（P2-G2）：用离线桩跑通「会说话的课堂」。

    python scripts/accept_p2.py            # 跑全部
    python scripts/accept_p2.py --keep     # 跑完留下临时库、日志与三个后端进程

三条原则（与 accept_p0 / accept_p1 相同，理由见那两份脚本）：

1. **不改你的数据。** 这份脚本会真的生成一门 12 页的课、真的合成一整套音频、
   真的删掉一门课。所以它**自己起三个后端**，三个都连临时库、都把
   `AUDIO_DIR` 指到临时目录；:5000 上那个（连你自己库的）它连碰都不碰。
2. **不联网。** 三个实例一律 `EDUAGENTX_DISABLE_DOTENV=1` + 三个 `VOLC_*_API_KEY`
   显式置空：**连 `backend/.env` 都不读**。这不是防呆，是防花钱 —— 这台机器上
   有真 Key 时，一个「没配好的服务商」会变成一次真调用，而验收脚本本该是
   断网也能跑完的（AGENTS §23）。
3. **说得出为什么。** 每条不通过都打印实际收到的响应；跑不到的条目
   （要真上游的保活/优雅关闭/纠音、要人耳的听辨与准确率）明确跳过，
   并附上「离线侧能验的那一半」的结果，而不是假装通过。

三个实例不是重复劳动，而是 §7 里三种部署形态：

    主实例   :5096  离线替身（TTS/ASR/实时语音全是 Mock）—— §7 的 A/B/C 大部分
    半配实例 :5095  有 Key 但缺接入地址（配错密钥就是这个形状）—— A9 / B2 的降级
    关闭实例 :5094  VOICE_ENABLED=false  —— G3 的纯文字课堂

跑不到的与跑得到的分界，就是 P2 §7 自己的分界：

    A（功能）/ B（接口）/ C（数据）  → 离线桩可验，脚本逐条查
    D（性能）/ E（质量人工分）       → 要真上游与人耳，记跳过并附离线侧的数字
    F（安全）/ G（回归）             → 能脚本化的那几条照查，其余指向用例
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

#: Windows 控制台是 GBK，而讲稿、标题、日志里全是中文与 ✓。
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

#: 三个临时后端。刻意不用 5000：那是 `make dev` 的端口，连的是你的库。
TEMP_PORT = 5096
DEGRADED_PORT = 5095
NOVOICE_PORT = 5094

#: 由 main() 赋值的接口前缀（脚本要等临时后端起来才知道自己该调谁）。
API = ""

#: 主线课程：12 页、每章一测验（P1 的默认形状，A2/A4/A6 都在它身上验）。
TOPIC = "机器学习入门"
PAGE_COUNT = 12
#: P2-A6 重写的那一页（与 accept_p1 的 REWRITE_PAGE 取同一个号）。
REWRITE_PAGE = 7

#: 假凭据当金丝雀（P2-F1）：日志、响应体、前端源码里都不该出现它。
#: 用半配实例来验，是因为**只有它的进程里真的有这个字符串** —— 主实例
#: 干干净净什么 Key 都没有，拿它扫「有没有泄漏」等于什么都没扫。
CANARY_KEY = "canary-not-a-real-key-9f3a"

#: A1 的两句。选这两个长度有两个原因：短句够短、长句仍在 Mock 的封顶
#: （`MAX_MOCK_MS=5000`，22 字）以内 —— 撞上封顶就看不出「时长与字数成正比」。
TTS_SHORT = "梯度下降"
TTS_LONG = "学习率决定了每一步走多远以及方向"

#: 离线的中文语速基准（Mock 的 `MS_PER_CHAR=220` → 4.5 字/秒）。
CHARS_PER_SEC_RANGE = (4.0, 6.0)

#: 20ms 的 16k / 单声道 / 16bit 一包（§4.2 的上行规格）。
PCM_FRAME = 16000 * 20 // 1000 * 2

#: 三个实例共用的「这台机器上不该有真凭据」的保证。见模块 docstring 第 2 条。
#:
#: **为什么连接入地址一起清空**（不是只清 Key）：一个「有 Key、没地址」的服务商
#: 才是 §7 A9 说的那种配错，也正是半配实例要造的状态。只清 Key 的话，
#: `default_name()` 会回落到离线替身，那是另一种场景，验不到 40201。
OFFLINE_ENV: dict[str, str] = {
    # 应用自己**不再读 .env**（`app/config.py` 的那道开关）。
    "EDUAGENTX_DISABLE_DOTENV": "1",
    # Flask CLI **自己也会读 .env**（装上 python-dotenv 就有这个行为），而且比
    # 应用更早：`flask run` 先把 .env 铺进 os.environ，应用再看到 `EDUAGENTX_...`
    # 时已经晚了 —— 那时真 Key 已经在环境里了。这一条才是真正拦住它的那道闸。
    # （实测踩过一次：accept 脚本的三个实例全被 .env 喂成了「真配」，
    #   半配实例于是发起了一次真的上游连接。）
    "FLASK_SKIP_DOTENV": "1",
    "LLM_PROVIDER": "mock",
    "LLM_API_KEY": "",
    "LLM_BASE_URL": "",
    # 三家语音的每一处凭据与接入地址都显式置空：这里漏一个变量，
    # 验收就可能变成一次真调用（而真调用要花钱）。
    "VOLC_TTS_API_KEY": "",
    "VOLC_TTS_ENDPOINT": "",
    "VOLC_TTS_RESOURCE_ID": "",
    "VOLC_ASR_API_KEY": "",
    "VOLC_ASR_ENDPOINT": "",
    "VOLC_ASR_RESOURCE_ID": "",
    "VOLC_REALTIME_API_KEY": "",
    "VOLC_REALTIME_ENDPOINT": "",
    "VOLC_REALTIME_MODEL": "",
    # 音色 ID 一律走配置（AGENTS §4.1）：这里给的是**离线替身自己的**音色，
    # 不是任何厂商的 ID。陆老师的留空 —— A5 要用「没配上游音色 ID」的那个音色
    # 验「试听按钮置灰」。
    "VOLC_TTS_VOICE_TEACHER": "mock-voice-teacher",
    "VOLC_TTS_VOICE_HISTORY": "mock-voice-humanities",
}

#: 半配实例：有 Key、缺接入地址 —— 「配错了密钥」在注册表里的样子就是这个。
#: 它在**任何网络请求之前**就报 40201（`ProviderNotConfiguredError`）。
DEGRADED_ENV: dict[str, str] = {
    **OFFLINE_ENV,
    "VOLC_TTS_API_KEY": CANARY_KEY,
    "VOLC_REALTIME_API_KEY": CANARY_KEY,
}

#: 关闭实例：语音总开关关着（P2-G3）。
NOVOICE_ENV: dict[str, str] = {**OFFLINE_ENV, "VOICE_ENABLED": "false"}

#: 整课预合成要跑一会儿（顺序合成，一句一次往返）。给足余量。
NARRATE_TIMEOUT = 180.0
#: 生成一门 12 页的课（离线桩也要走完六个步骤）。
GENERATE_TIMEOUT = 240.0


# --------------------------------------------------------------------------
# 委托给 pytest 的那几条
# --------------------------------------------------------------------------

#: 能由离线用例**判定**的条目：`(编号, 标题, 用例)`。
#: 这些条目要么是纯编解码断言（没有比单测更合适的验法），要么是上游替身
#: 才能构造的场景（断连、重连、45000003 重建会话）。脚本负责把结果逐条记账。
DELEGATED: list[tuple[str, str, list[str]]] = [
    (
        "P2-A15",
        "ASR 二进制帧编码正确",
        ["tests/unit/test_voice_codecs.py::TestASRFrames"],
    ),
    (
        "P2-A16",
        "分包规格不串用（640B / 100~200ms，常量只在 providers）",
        [
            "tests/unit/test_voice_codecs.py::test_packet_constants_live_in_providers_only",
            "tests/unit/test_voice_codecs.py::test_realtime_and_asr_packet_sizes_differ",
            "tests/unit/test_voice_codecs.py::TestASRFrames::test_packet_size_matches_200ms_of_16k_mono_16bit",
            "tests/unit/test_voice_providers.py::TestVolcRealtime::test_audio_is_repacked_into_640_byte_base64_frames",
            "tests/unit/test_voice_providers.py::TestVolcASR::test_packet_size_follows_configuration",
        ],
    ),
    (
        "P2-A21",
        "TTS 二进制帧编码正确（帧头/事件号/gzip/大端）",
        ["tests/unit/test_voice_codecs.py::TestTTSFrames"],
    ),
    (
        "P2-A22",
        "TTS 与 ASR 编解码器不通用",
        ["tests/unit/test_voice_codecs.py::TestCodecsAreNotInterchangeable"],
    ),
    (
        "P2-A17",
        "会话被释放后自动重建（45000003 是正常路径）",
        [
            "tests/unit/test_voice_providers.py::TestVolcRealtime::test_released_session_is_rebuilt_without_the_user_noticing",
            "tests/unit/test_voice_providers.py::TestVolcRealtime::test_broken_transport_reconnects_and_recreates",
        ],
    ),
    (
        "P2-B1",
        "WS 全序列（start → ready → audio/reply → done，上游用 Mock）",
        [
            "tests/contract/test_p2_voice_ws.py::test_full_turn_sequence",
            "tests/contract/test_p2_voice_ws.py::test_audio_frames_are_sequenced",
            "tests/contract/test_p2_voice_ws.py::test_done_reports_this_turn_only",
            "tests/contract/test_p2_voice_ws.py::test_client_hangup_closes_the_channel",
        ],
    ),
    (
        "P2-B3",
        "清单字段与播放器对齐（五字段 + 字幕/时长基准/状态）",
        [
            "tests/unit/test_voice_assets.py::test_the_manifest_has_the_fields_the_player_needs",
            "tests/unit/test_voice_assets.py::test_the_manifest_says_why_there_is_no_sound",
            "tests/contract/test_p2_voice_api.py::test_manifest_fields_match_the_player",
        ],
    ),
    (
        "P2-B4",
        "上游异常映射为业务码（不裸抛 500）",
        [
            "tests/unit/test_voice_providers.py::TestVolcTTS::test_error_frame_raises_and_drops_the_connection",
            "tests/unit/test_voice_providers.py::TestVolcTTS::test_connection_drop_is_retried_once",
            "tests/unit/test_voice_providers.py::TestVolcASR::test_5xx_is_marked_retryable",
            "tests/unit/test_voice_providers.py::TestVolcASR::test_wrong_sample_rate_is_refused_before_touching_the_network",
            "tests/unit/test_voice_providers.py::TestVolcRealtime::test_missing_config_raises_40201",
            "tests/unit/test_voice_providers.py::TestVolcRealtime::test_qpm_guard_blocks_before_the_upstream_does",
            "tests/contract/test_p2_voice_ws.py::test_broken_message_is_reported_and_the_session_survives",
            "tests/contract/test_p2_voice_ws.py::test_errors_before_start_are_reported",
            "tests/contract/test_p2_voice_api.py::test_asr_rejects_browser_recordings_with_a_clear_message",
        ],
    ),
    (
        "P2-C1",
        "重复合成命中缓存（不产生新文件与新计费）",
        [
            "tests/unit/test_voice_assets.py::test_synthesizing_the_same_beat_again_changes_nothing",
            "tests/unit/test_voice_assets.py::test_previewing_a_voice_is_cached_across_clicks",
            "tests/unit/test_voice_assets.py::test_narrating_a_whole_course_reports_hits_and_misses",
        ],
    ),
    (
        "P2-C4",
        "音频路径不落绝对路径（路径越界与穿越都拿不到）",
        [
            "tests/unit/test_voice_assets.py::test_paths_stay_under_the_configured_audio_dir",
            "tests/unit/test_voice_assets.py::test_foreign_and_traversing_paths_resolve_to_nothing",
            "tests/unit/test_voice_assets.py::test_ids_are_neutralized_before_they_reach_the_path",
        ],
    ),
    (
        "P2-F4",
        "会话票据：签发 / 一次性 / 过期 / 归属人",
        [
            "tests/unit/test_voice_tickets.py",
            "tests/contract/test_p2_voice_api.py::test_a_ticket_is_issued_before_the_socket",
            "tests/contract/test_p2_voice_api.py::test_the_handshake_is_refused_before_the_upgrade",
            "tests/contract/test_p2_voice_api.py::test_a_ticket_can_only_be_spent_once",
            "tests/contract/test_p2_voice_api.py::test_tickets_are_refused_when_voice_is_disabled",
            "tests/contract/test_p2_voice_api.py::test_tickets_are_refused_when_the_provider_is_unconfigured",
        ],
    ),
    (
        "P2-F5",
        "单用户并发上限 1（重复 start 返回 42901）",
        [
            "tests/unit/test_voice_sessions.py",
            "tests/contract/test_p2_voice_ws.py::test_a_second_session_for_the_same_person_is_refused",
            "tests/contract/test_p2_voice_ws.py::test_the_slot_is_released_when_the_first_session_ends",
            "tests/contract/test_p2_voice_ws.py::test_another_person_can_talk_at_the_same_time",
        ],
    ),
    (
        "P2-G3",
        "关掉语音开关后是纯文字课堂（清单/试听/合成三条路）",
        [
            "tests/unit/test_voice_assets.py::test_voice_disabled_turns_narration_into_a_no_op",
            "tests/unit/test_voice_assets.py::test_preview_refuses_when_voice_is_off",
            "tests/unit/test_voice_assets.py::test_the_switch_defaults_to_on",
            "tests/contract/test_p2_voice_api.py::test_voice_disabled_is_not_an_error",
            "tests/contract/test_p2_voice_api.py::test_narrate_when_voice_is_disabled_does_nothing",
        ],
    ),
]

#: 判定本身要真上游 / 真人耳的条目：离线只验「结构那一半」，验完记跳过。
#: `(编号, 标题, 离线代理用例, 跳过原因)`。
PROXIED: list[tuple[str, str, list[str], str]] = [
    (
        "P2-A12",
        "麦克风空闲保活（60s 不说话，日志无 52000042）",
        ["tests/unit/test_voice_providers.py::TestVolcRealtime::test_keep_alive_mode_is_configurable"],
        "「空闲 60 秒后仍存活」是上游的行为，离线无从观察",
    ),
    (
        "P2-A13",
        "优雅关闭不报错（日志无 ContextCanceled）",
        [
            "tests/unit/test_voice_providers.py::TestVolcRealtime::test_close_waits_for_the_closed_ack",
            "tests/unit/test_voice_providers.py::TestVolcRealtime::test_close_tolerates_a_missing_ack",
        ],
        "「等服务端回执再断连」的对照要真上游才会报 55000001",
    ),
    (
        "P2-A14",
        "流式 ASR 边说边上屏（8 秒推流，≥3 次中间结果）",
        [
            "tests/unit/test_voice_providers.py::TestVolcASR::test_stream_merges_incremental_results_monotonically",
            "tests/unit/test_voice_providers.py::TestVolcASR::test_merge_text_rules",
        ],
        "真上游才有 8 秒的连续中间结果；离线替身一次把整段给完",
    ),
    (
        "P2-A19",
        "Markdown 不被照念（不出现「星星」）",
        ["tests/unit/test_voice_providers.py::TestVolcTTS::test_req_params_carry_markdown_and_pronunciation"],
        "「耳朵听不到星星」要真人听；离线验的是 disable_markdown_filter 真的发出去了",
    ),
    (
        "P2-A20",
        "术语纠音生效（与 ASR 热词同一份术语表）",
        [
            "tests/unit/test_voice_providers.py::TestVolcTTS::test_req_params_carry_markdown_and_pronunciation",
            "tests/unit/test_voice_providers.py::TestVolcASR::test_hotwords_go_into_the_first_packet",
            "tests/unit/test_voice_assets.py::test_the_glossary_comes_from_the_course_content",
            "tests/unit/test_voice_assets.py::test_the_glossary_can_be_limited_to_one_page",
        ],
        "读音对不对要真人听辨；离线验的是「同一份术语表投给了纠音与热词两处」",
    ),
    (
        "P2-A18",
        "按住说话用官方 push_to_talk 模式（噪声不误判停）",
        [
            "tests/unit/test_voice_providers.py::TestVolcRealtime::test_session_create_shape",
            "tests/unit/test_voice_providers.py::TestVolcRealtime::test_commit_flushes_the_tail_before_saying_done",
        ],
        "「环境噪声里不被 VAD 截断」要在真麦真上游上比；离线验的是 input_mod 与松开即 commit",
    ),
]


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
        """一组断言：`problems` 非空即不通过，内容原样打印（P2 的写法都差不多）。"""
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
        print(f"P2 验收：通过 {passed} / 不通过 {len(failed)} / 跳过 {len(skipped)}")
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
    raw: bytes | None = None,
    content_type: str = "application/json",
    timeout: float = 30.0,
) -> tuple[int, dict]:
    """调后端接口，返回 (HTTP 状态, 信封)。业务错误也在信封里，不抛异常。

    `base` 不传就打到主实例；降级与关开关那两条路显式传自己的前缀 ——
    它们验的是**同一条接口在另一种部署下的答复**，用错实例就什么都验不到。
    """
    data = raw
    headers = {"X-Request-Id": "accept-p2"}
    if raw is None and body is not None:
        data = json.dumps(body).encode("utf-8")
    if data is not None:
        headers["Content-Type"] = content_type
    if owner:
        headers["X-Owner-Id"] = owner
    req = urllib.request.Request(f"{base or API}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(text)
        except json.JSONDecodeError:
            return exc.code, {"raw": text[:400]}
    except Exception as exc:  # 连不上 / 超时
        return 0, {"error": f"{type(exc).__name__}: {exc}"}


def _data(status: int, envelope: dict) -> Any:
    return envelope.get("data") if status == 200 and envelope.get("code") == 0 else None


def fallback_of(envelope: Mapping[str, Any]) -> str:
    """错误信封里的降级路径。40302 是**平铺**的，其余走 `details`（P2-B2）。

    与前端 `utils/voice.ts` 的 `fallbackOf` 同一条口径 —— 两边读不出来就都按
    空串处理，于是「服务端没给」这件事在两端都看得见。
    """
    data = envelope.get("data")
    if not isinstance(data, Mapping):
        return ""
    flat = data.get("fallback")
    if isinstance(flat, str) and flat:
        return flat
    details = data.get("details")
    if isinstance(details, Mapping):
        nested = details.get("fallback")
        if isinstance(nested, str):
            return nested
    return ""


def brief(payload: Any, limit: int = 300) -> str:
    text = json.dumps(payload, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "…"


def url_of(url: str, base: str = "") -> str:
    """接口给的地址 → 能直接取的绝对地址。

    清单里的 `url` 是 `/api/courses/…/audio/p1-b1?v=…`（自带 `/api`），
    而 `API` 已经是 `http://host/api` —— 直接拼会拼出 `/api/api/…`，
    拿到一个 404，而 404 的响应体是 JSON，看起来像「音频坏了」。
    """
    if url.startswith("http"):
        return url
    root = re.sub(r"/api/?$", "", base or API)
    return f"{root}{url if url.startswith('/') else '/' + url}"


def multipart(field: str, filename: str, payload: bytes) -> tuple[bytes, str]:
    """拼一个最小的 multipart 表单（标准库里没有现成的构造器）。"""
    boundary = "----acceptp2boundary9f3a"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return head + payload + tail, f"multipart/form-data; boundary={boundary}"


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
# WebSocket 客户端（标准库手写）
# --------------------------------------------------------------------------

#: 上行帧**必须**加掩码（RFC 6455 §5.3）：服务端收到没掩码的客户端帧要断开。
_WS_TEXT, _WS_BINARY, _WS_CLOSE, _WS_PING, _WS_PONG = 0x1, 0x2, 0x8, 0x9, 0xA


class WsClosed(Exception):
    """对端走了。"""


class WsClient:
    """够用的 WebSocket 客户端：握手 + 掩码发送 + 分帧接收。

    为什么手写而不装一个库：这份脚本要能被系统 python 直接跑起来（与
    accept_p0/p1 同一条纪律），而为了验收再往 requirements 里加一个
    **只在这里用到**的依赖，是在给部署添一件要维护的东西。用到的协议
    只有 RFC 6455 的一小半（文本/二进制/关闭/心跳），一百来行写得完。
    """

    def __init__(self, sock: socket.socket, leftover: bytes = b"") -> None:
        self.sock = sock
        self.buf = bytearray(leftover)
        self.closed = False

    # --- 收发 ---

    def send_text(self, payload: Mapping[str, Any]) -> None:
        self._frame(_WS_TEXT, json.dumps(dict(payload), ensure_ascii=False).encode("utf-8"))

    def send_bytes(self, payload: bytes) -> None:
        self._frame(_WS_BINARY, payload)

    def _frame(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        head = bytearray([0x80 | opcode])
        size = len(payload)
        if size < 126:
            head.append(0x80 | size)
        elif size < 65536:
            head.append(0x80 | 126)
            head += struct.pack(">H", size)
        else:
            head.append(0x80 | 127)
            head += struct.pack(">Q", size)
        head += mask
        masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(bytes(head) + masked)

    def _read(self, size: int, deadline: float) -> bytes:
        while len(self.buf) < size:
            remaining = deadline - time.time()
            if remaining <= 0:
                raise TimeoutError("等一帧超时")
            self.sock.settimeout(min(remaining, 1.0))
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                continue
            if not chunk:
                self.closed = True
                raise WsClosed("对端关闭了连接")
            self.buf += chunk
        out = bytes(self.buf[:size])
        del self.buf[:size]
        return out

    def recv(self, timeout: float) -> tuple[str, Any]:
        """收一帧，返回 `("text"|"binary"|"close", 内容)`。心跳就地回掉，不往上抛。"""
        deadline = time.time() + timeout
        while True:
            head = self._read(2, deadline)
            opcode = head[0] & 0x0F
            masked = bool(head[1] & 0x80)
            size = head[1] & 0x7F
            if size == 126:
                size = struct.unpack(">H", self._read(2, deadline))[0]
            elif size == 127:
                size = struct.unpack(">Q", self._read(8, deadline))[0]
            mask = self._read(4, deadline) if masked else b""
            payload = self._read(size, deadline) if size else b""
            if masked:
                payload = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))

            if opcode == _WS_PING:
                self._frame(_WS_PONG, payload)  # 不回会心跳超时被掐断
                continue
            if opcode == _WS_PONG:
                continue
            if opcode == _WS_CLOSE:
                self.closed = True
                return "close", payload
            return ("text" if opcode == _WS_TEXT else "binary"), payload

    def drain(self, seconds: float, until: Callable[[list], bool] | None = None) -> list[tuple[str, Any]]:
        """收帧直到超时（或 `until` 说够了）。返回 `[(kind, 内容)]`。

        `until` 让「等这一轮说完」不必靠猜时间：Mock 一手把整轮吐出来，
        而真上游是一句一句来的 —— 判据只能是「收到了 done」。
        """
        out: list[tuple[str, Any]] = []
        deadline = time.time() + seconds
        while time.time() < deadline:
            if until is not None and until(out):
                break
            try:
                kind, payload = self.recv(max(0.05, deadline - time.time()))
            except (TimeoutError, WsClosed, OSError):
                break
            out.append((kind, payload))
        return out

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:  # pragma: no cover - 已经关了
            pass


def ws_connect(
    port: int, path: str, *, host: str = "127.0.0.1", timeout: float = 10.0
) -> tuple[WsClient | None, str, bytes]:
    """一次 WebSocket 握手。返回 `(客户端, 状态行, 响应体)`。

    **状态行不是 101 时 `client` 为 None** —— 那正是 P2-F4 要看的：票据不对时
    服务端必须在**升级之前**拒绝，客户端拿到的是一个普通的 HTTP 响应
    （连 101 都见不到）。这个函数把响应体也读回来，所以「拒绝时带没带
    fallback」在验收这一层也是能直接看的。
    """
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    sock = socket.create_connection((host, port), timeout=timeout)
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    )
    sock.sendall(request.encode("ascii"))

    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(65536)
        if not chunk:
            break
        buf += chunk
    head, _, rest = buf.partition(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = lines[0] if lines else ""

    if " 101" not in status:
        # 失败响应有 body（那是一封普通的错误信封），按 Content-Length 读完
        length = 0
        for line in lines[1:]:
            if line.lower().startswith("content-length:"):
                length = int(line.split(":", 1)[1].strip() or 0)
        while len(rest) < length:
            chunk = sock.recv(65536)
            if not chunk:
                break
            rest += chunk
        sock.close()
        return None, status, rest

    return WsClient(sock, rest), status, b""


def _frames_of(frames: Sequence[tuple[str, Any]], kind: str) -> list[Any]:
    return [payload for name, payload in frames if name == kind]


def _json_frames(frames: Sequence[tuple[str, Any]], type_name: str) -> list[dict]:
    out = []
    for name, payload in frames:
        if name != "text":
            continue
        try:
            parsed = json.loads(payload)
        except ValueError:
            continue
        if isinstance(parsed, dict) and parsed.get("type") == type_name:
            out.append(parsed)
    return out


# --------------------------------------------------------------------------
# 子进程
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
    讲稿、日志、断言里的中文全成乱码。这类失败看着像业务 bug，其实是编码。

    `FLASK_SKIP_DOTENV=1` 是**每一个**子进程都要的，不只是 flask 那几个：
    少一处，那一处就可能读到 `backend/.env` 里的真凭据（见 `OFFLINE_ENV`
    上面那段说明）。
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


#: 委托用例的逐条结果（节点 id → PASSED/FAILED/…）。跑一趟、多处引用：
#: 同一条用例会被两个编号同时用到（比如纠音那条同时是 A19 和 A20 的代理）。
_NODE_CACHE: dict[str, str] = {}
#: 这一趟 pytest 的原始输出。同一个选择器里的用例**全都没跑到**时，
#: 唯一能说清为什么的就是它（通常是收集阶段就崩了）。
_LAST_RUN: subprocess.CompletedProcess | None = None


def pytest_verdicts(nodes: Iterable[str]) -> None:
    """跑一趟 `-rA`，把逐条结论记进 `_NODE_CACHE`。

    `-rA` 是关键：默认的短摘要只在失败时列名字，而我们要**逐条**知道
    通过还是没通过（每条验收都要有自己的结论）。`-p no:cacheprovider`
    免得在仓库里留下 `.pytest_cache`。
    """
    global _LAST_RUN
    unique = sorted(set(nodes))
    if not unique:
        return
    result = run_pytest("-rA", "-p", "no:cacheprovider", *unique)
    _LAST_RUN = result
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
    # 一条结果都没解析出来 —— 选择器本身出了问题（写错了名字、收集阶段就崩）
    tail = (_pytest_tail(result, 6).splitlines() or ["（pytest 没有输出）"])[-1]
    for node in unique:
        _NODE_CACHE.setdefault(node, f"没跑到（pytest 这么说：{tail}）")


def pytest_node_ok(node: str) -> tuple[bool, str]:
    """一条委托用例的结论。

    `node` 既可能是单条用例（`…::test_x`），也可能是一整个文件
    （`tests/unit/test_voice_tickets.py`）—— 后者要把文件里每一条都算上。
    「没跑到」也算不通过：用例被改名或删掉时，验收不该悄悄变成绿灯。
    """
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
    """三个临时后端 + 这次跑出来的那门课。检查函数从这里取料，不各自新建。"""

    env: dict[str, str]           # 主实例（离线替身）
    work_dir: Path
    audio_dir: Path
    course_id: str = ""           # 主线课程：12 页、每章一测验
    job_id: str = ""
    steps: list[dict] = field(default_factory=list)   # 六个步骤（含 tts 的 detail）
    manifest: dict = field(default_factory=dict)      # 主线课程的音频清单
    voice_files: dict = field(default_factory=dict)   # 合成完之后的音频目录快照

    @property
    def degraded(self) -> str:
        return f"http://127.0.0.1:{DEGRADED_PORT}/api"

    @property
    def novoice(self) -> str:
        return f"http://127.0.0.1:{NOVOICE_PORT}/api"


# --------------------------------------------------------------------------
# 辅助
# --------------------------------------------------------------------------


def _guard(rep: Report, label: str, fn, *args) -> None:
    """跑一组检查。抛异常也要留下痕迹：一组崩掉就把后面几十条结果全丢了，
    那才是最坏的一种「验收通过」。"""
    try:
        fn(rep, *args)
    except Exception as exc:  # noqa: BLE001 - 脚本要活下去
        rep.fail("P2-EXC", f"{label} 组检查中断", f"{type(exc).__name__}: {exc}")


def snapshot(root: Path) -> dict[str, tuple[float, int]]:
    """音频目录的快照：`{相对路径: (mtime, 字节数)}`。A4/A6 靠它比 mtime。"""
    out: dict[str, tuple[float, int]] = {}
    if not root.is_dir():
        return out
    for path in sorted(root.rglob("*")):
        if path.is_file():
            stat = path.stat()
            out[path.relative_to(root).as_posix()] = (round(stat.st_mtime, 3), stat.st_size)
    return out


def diff_snapshots(
    before: Mapping[str, tuple[float, int]], after: Mapping[str, tuple[float, int]]
) -> tuple[list[str], list[str], list[str]]:
    """返回 `(新增, 变动, 消失)` 三组路径。"""
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(name for name in set(before) & set(after) if before[name] != after[name])
    return added, changed, removed


def page_of(name: str) -> int:
    """`c_xx/p7-b1_ab12cd34.wav` → 7。认不出来返回 0（当作「不属于任何一页」）。"""
    match = re.search(r"(?:^|/)p(\d+)-", name)
    return int(match.group(1)) if match else 0


def _wait_manifest(course_id: str, *, want: int, timeout: float) -> dict:
    """等这门课有 `want` 个 beat 可播。进度就是清单里的 `readyCount`（没有第二个计数器）。"""
    deadline = time.time() + timeout
    manifest: dict = {}
    while time.time() < deadline:
        status, envelope = api("GET", f"/courses/{course_id}/audio-manifest")
        manifest = _data(status, envelope) or {}
        if int(manifest.get("readyCount") or 0) >= want:
            return manifest
        time.sleep(0.2)
    return manifest


def _wait_pages(course_id: str, *, want: int, timeout: float) -> int:
    """等这门课至少写出 `want` 页（点「重写」之前要确认这一页真的写完了）。"""
    deadline = time.time() + timeout
    written = 0
    while time.time() < deadline:
        status, envelope = api("GET", f"/courses/{course_id}/outline")
        tree = _data(status, envelope) or {}
        pages = [p for chapter in tree.get("chapters") or [] for p in chapter.get("pages") or []]
        pages += list(tree.get("front") or []) + list(tree.get("back") or [])
        written = len([p for p in pages if p.get("status") == "ready"])
        if written >= want:
            return written
        time.sleep(0.15)
    return written


def _wait_audio_job(course_id: str, *, timeout: float) -> bool:
    """等这门课的预合成跑完。

    判据是「清单满了**且**连着两次读到 `running: false`」。为什么要连着两次：
    后台线程要过一会儿才把 `running` 立起来，只读一次的话，可能在任务真正
    开始**之前**就读到一个「已经跑完」的假象 —— 然后拿着半套音频去断言。
    """
    deadline = time.time() + timeout
    stable = 0
    while time.time() < deadline:
        status, envelope = api("GET", f"/courses/{course_id}/audio-manifest")
        manifest = _data(status, envelope) or {}
        beats = int(manifest.get("beatCount") or 0)
        full = beats > 0 and manifest.get("readyCount") == beats
        if full and not manifest.get("running"):
            stable += 1
            if stable >= 2:
                return True
        else:
            stable = 0
        time.sleep(0.3)
    return False


def _settle_audio(ctx: Ctx, *, quiet: float = 0.6) -> dict:
    """等音频目录停稳（连着两次快照一致），返回稳定后的快照。

    A4/A6 判的是「哪些文件的 mtime 动了」，所以**必须**确信后台合成已经收工：
    还在写的时候拍一次照，之后任何一个文件被补写一下，都会变成一条
    「不该动的页也动了」的假失败。
    """
    previous = snapshot(ctx.audio_dir)
    deadline = time.time() + 10.0
    while time.time() < deadline:
        time.sleep(quiet)
        current = snapshot(ctx.audio_dir)
        if current == previous:
            return current
        previous = current
    return previous


def _narrate_and_wait(ctx: Ctx, course_id: str, *, force: bool = True) -> dict:
    """排一次整课预合成，等它跑完，返回停稳之后的清单。"""
    api("POST", f"/courses/{course_id}/narrate", {"force": force})
    time.sleep(0.4)  # 让后台线程把 running 立起来，见 `_wait_audio_job`
    _wait_audio_job(course_id, timeout=NARRATE_TIMEOUT)
    _settle_audio(ctx)
    return _data(*api("GET", f"/courses/{course_id}/audio-manifest")) or {}


# --------------------------------------------------------------------------
# A. 功能 / C. 数据 —— 音频资产那条链
# --------------------------------------------------------------------------


def check_voices(rep: Report, ctx: Ctx) -> None:
    """P2-A5：音色列表与试听（含「没配上游音色 ID 的置灰」）。"""
    status, envelope = api("GET", "/voice/voices")
    data = _data(status, envelope) or {}
    rows = {item["id"]: item for item in data.get("items") or []}
    problems = []
    if len(rows) != 3:
        problems.append(f"音色卡应有 3 张，实际 {len(rows)}")
    if data.get("provider") != "mock":
        problems.append(f"离线部署该落到替身，实际 provider={data.get('provider')!r}")
    if not data.get("enabled") or not data.get("usable"):
        problems.append(f"enabled/usable 应为真：{brief(data)}")
    if rows.get("vp_teacher_shen", {}).get("usable") is not True:
        problems.append("配了上游音色 ID 的沈老师应当 usable")
    if rows.get("vp_teacher_lu", {}).get("usable") is not False:
        problems.append("没配上游音色 ID 的陆老师应当**不可用**（试听按钮据此置灰）")
    rep.verdict(
        "P2-A5",
        "音色列表与可用性",
        problems,
        "3 张音色卡；沈/顾可用、陆未配上游 ID 不可用；provider=mock、enabled=true",
    )

    # --- 试听：3s 内出音 + 重复点击不重复计费 ---
    started = time.perf_counter()
    status, envelope = api("POST", "/voice/voices/vp_teacher_shen/preview", {"text": "同学们好"})
    elapsed = time.perf_counter() - started
    first = _data(status, envelope) or {}
    if not first.get("url"):
        return rep.fail("P2-A5b", "试听可用（≤3s 出音、重复不重复计费）", f"试听没给出 url：{brief(envelope)}")

    audio_status, _, body = _http_get(url_of(first["url"]))
    again = _data(*api("POST", "/voice/voices/vp_teacher_shen/preview", {"text": "同学们好"})) or {}
    usage = _data(*api("GET", "/voice/usage")) or {}
    tts_calls = next((k["calls"] for k in usage.get("kinds") or [] if k["kind"] == "tts"), 0)

    problems = []
    if elapsed > 3.0:
        problems.append(f"第一次试听用了 {elapsed:.2f}s（上限 3s）")
    if audio_status != 200 or body[:4] != b"RIFF":
        problems.append(f"试听地址取到的不是可播的音频：HTTP {audio_status}，开头 {body[:8]!r}")
    if not first.get("cached") is False or not again.get("cached") is True:
        problems.append(f"第二次试听应当命中缓存：first={first.get('cached')}, again={again.get('cached')}")
    if again.get("url") != first.get("url"):
        problems.append("命中缓存的两次试听应当给同一个地址")
    if tts_calls != 1:
        problems.append(f"两次试听只该记一笔账，实际 tts.calls={tts_calls}")
    rep.verdict(
        "P2-A5b",
        "试听可用（≤3s 出音、重复不重复计费）",
        problems,
        f"{elapsed:.2f}s 出音；第二次 cached=true 且账本仍只有 1 笔",
    )

    # --- 没配上游音色 ID 的音色：拒绝，而不是合成一段静音 ---
    status, envelope = api("POST", "/voice/voices/vp_teacher_lu/preview")
    if status == 400 and envelope.get("code") == 40001:
        rep.ok("P2-A5c", "未配置的音色拒绝试听", f"40001「{envelope.get('message')}」")
    else:
        rep.fail("P2-A5c", "未配置的音色拒绝试听", f"期望 400/40001，实际 {status}/{envelope.get('code')} {brief(envelope)}")


def _http_get(url: str, timeout: float = 20.0) -> tuple[int, dict, bytes]:
    """取一个二进制响应（音频）。与 `api()` 分开：那个只解析 JSON。"""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()
    except Exception as exc:
        return 0, {}, f"{type(exc).__name__}: {exc}".encode()


def check_tts(rep: Report, ctx: Ctx) -> None:
    """P2-A1：单句合成可用，时长与文本长度成正比（中文 4~6 字/秒）。"""
    durations = {}
    for label, text in (("短", TTS_SHORT), ("长", TTS_LONG)):
        status, envelope = api(
            "POST", "/voice/tts", {"text": text, "voiceId": "vp_teacher_shen", "speed": 1.0}
        )
        data = _data(status, envelope) or {}
        if not data.get("url"):
            return rep.fail("P2-A1", "单句 TTS 可用", f"{label}句没合出来：{brief(envelope)}")
        audio_status, headers, body = _http_get(url_of(data["url"]))
        durations[label] = (text, int(data.get("durationMs") or 0), audio_status, body, headers)

    problems = []
    for label, (text, duration, audio_status, body, headers) in durations.items():
        if audio_status != 200 or len(body) <= 44:
            problems.append(f"{label}句（{len(text)}字）没取到音频：HTTP {audio_status}，{len(body)} 字节")
            continue
        rate = len(text) / (duration / 1000) if duration else 0
        if not (CHARS_PER_SEC_RANGE[0] <= rate <= CHARS_PER_SEC_RANGE[1]):
            problems.append(f"{label}句语速 {rate:.2f} 字/秒，不在 {CHARS_PER_SEC_RANGE} 内")

    short_ms = durations["短"][1]
    long_ms = durations["长"][1]
    expected_ratio = len(durations["长"][0]) / len(durations["短"][0])
    actual_ratio = long_ms / short_ms if short_ms else 0
    if abs(actual_ratio - expected_ratio) > 0.05:
        problems.append(f"时长与字数不成正比：{actual_ratio:.2f}× vs 字数比 {expected_ratio:.2f}×")

    rep.verdict(
        "P2-A1",
        "单句 TTS 可用（时长 ∝ 字数，4~6 字/秒）",
        problems,
        f"{len(TTS_SHORT)}字→{short_ms}ms、{len(TTS_LONG)}字→{long_ms}ms"
        f"（{long_ms / short_ms:.2f}×，字数比 {expected_ratio:.2f}×），都是可播的 WAV",
    )


def check_generation(rep: Report, ctx: Ctx) -> None:
    """P2-A2：整课预合成 —— 走生成管线那一步（P2-6）。

    12 页由离线桩写出来，`tts` 那一步顺整合成。**这一条不只是「有个按钮能合成」**：
    它验的是「生成完的课本来就有声音」，而那条路与「全部合成」按钮走的是
    同一个 `voice.jobs.run`。
    """
    status, envelope = api(
        "POST",
        "/courses/generate",
        {"topic": TOPIC, "mode": "lecture", "pageCount": PAGE_COUNT, "quizPerChapter": True},
    )
    created = _data(status, envelope) or {}
    if not created.get("courseId"):
        for aid, title in (("P2-A2", "整课预合成"), ("P2-A3", "播放与字幕同步"), ("P2-C4", "音频路径不落绝对路径")):
            rep.fail(aid, title, f"POST /courses/generate 没给出 courseId：{brief(envelope)}")
        return
    ctx.course_id, ctx.job_id = created["courseId"], created["jobId"]

    deadline = time.time() + GENERATE_TIMEOUT
    payload: dict = {}
    while time.time() < deadline:
        payload = _data(*api("GET", f"/jobs/{ctx.job_id}")) or {}
        if payload.get("status") in {"done", "failed", "canceled"}:
            break
        time.sleep(0.3)
    ctx.steps = list(payload.get("steps") or [])
    if payload.get("status") != "done":
        return rep.fail(
            "P2-A2",
            "整课预合成",
            f"生成没跑完：status={payload.get('status')} failedSteps={payload.get('failedSteps')}",
        )

    # 步骤的**类型**是 `type`（`id` 是那一行的主键，形如 st_…）——
    # 用 `id` 找会永远找不到，然后每一步都成了「TTS 没跑」
    tts_step = next((step for step in ctx.steps if step.get("type") == "tts"), None)
    detail = (tts_step or {}).get("detail") or {}
    problems = []
    if tts_step is None or tts_step.get("status") != "done":
        problems.append(
            f"管线里的 tts 步骤状态是 {(tts_step or {}).get('status')!r}，应当是 done"
            f"（六步：{[step.get('type') for step in ctx.steps]}）"
        )
    if int(detail.get("failed") or 0):
        problems.append(f"tts 步骤里有 {detail['failed']} 句失败")
    if not int(detail.get("beats") or 0):
        problems.append(f"tts 步骤没报出 beat 数：{brief(detail)}")

    ctx.manifest = _wait_manifest(ctx.course_id, want=int(detail.get("beats") or 0), timeout=NARRATE_TIMEOUT)
    beats = ctx.manifest.get("beats") or []
    # 正向对照：这一趟必须落在**离线替身**上。要是这台机器的 .env 混了进来，
    # 这里会变成 volc_tts —— 那样后面每条「合成成功」都是在拿真钱跑验收
    if ctx.manifest.get("provider") != "mock" or ctx.manifest.get("simulated") is not True:
        problems.append(
            f"合成没有落在离线替身上：provider={ctx.manifest.get('provider')!r}、"
            f"simulated={ctx.manifest.get('simulated')!r} —— 检查 .env 是不是被读进来了"
        )
    not_ready = [beat["beatId"] for beat in beats if beat.get("status") != "ready"]
    if ctx.manifest.get("readyCount") != ctx.manifest.get("beatCount"):
        problems.append(
            f"清单里 ready {ctx.manifest.get('readyCount')} / {ctx.manifest.get('beatCount')}，"
            f"没合成的：{not_ready[:6]}"
        )
    if not beats:
        problems.append("清单里一个 beat 都没有")
    if problems:
        return rep.fail("P2-A2", "整课预合成", "；".join(problems))

    rep.ok(
        "P2-A2",
        "整课预合成（生成管线那一步）",
        f"{ctx.manifest['beatCount']} 句全部 ready（新合成 {detail.get('synthesized')}、"
        f"命中缓存 {detail.get('cached')}、失败 0），12 页课程一句话不用手点就有声音",
    )

    # --- P2-A3：字幕与节奏的数据那一半 ---
    problems = []
    for beat in beats:
        missing = {"pageNo", "beatId", "textHash", "url", "durationMs", "text", "estSec", "status", "subtitles"}
        if not missing <= set(beat):
            problems.append(f"{beat.get('beatId')} 少了字段 {sorted(missing - set(beat))}")
        elif not beat.get("text"):
            problems.append(f"{beat['beatId']} 没有讲稿文本（字幕与纯文字降级都靠它）")
        elif beat["durationMs"] <= 0 or beat["estSec"] <= 0:
            problems.append(f"{beat['beatId']} 的 durationMs/estSec 是 {beat['durationMs']}/{beat['estSec']}")
    empty_subtitles = [beat["beatId"] for beat in beats if not beat.get("subtitles")]
    rep.verdict(
        "P2-A3",
        "播放与字幕同步（数据那一半）",
        problems,
        f"{len(beats)} 句都带 url/durationMs/estSec/text/subtitles；"
        f"离线替身不给字级时间戳（{len(empty_subtitles)} 句 subtitles 为空 → 前端整句切换），"
        "误差 ≤150ms / ≤300ms 要真上游与真音频，见 P2-E 与 §10.2",
    )

    # --- P2-C4：库里的路径是相对的、且不超出 AUDIO_DIR ---
    probe = run_python(
        "import json, os\n"
        "from app import create_app\n"
        "from app.models import AudioAsset\n"
        "app = create_app()\n"
        "with app.app_context():\n"
        "    rows = AudioAsset.query.filter_by(course_id=%r).all()\n"
        "    print(json.dumps({'paths': [row.file_path for row in rows],\n"
        "                      'root': app.config['AUDIO_DIR'],\n"
        "                      'sep': os.sep}))\n" % ctx.course_id,
        env=ctx.env,
    )
    lines = [line for line in (probe.stdout or "").splitlines() if line.startswith("{")]
    if not lines:
        rep.fail("P2-C4", "音频路径不落绝对路径", f"读资产失败：{plain((probe.stderr or '')[-300:])}")
        return
    info = json.loads(lines[-1])
    root = Path(str(info.get("root"))).resolve()
    problems = []
    for rel in info.get("paths") or []:
        text = str(rel)
        if os.path.isabs(text) or re.match(r"^[A-Za-z]:", text) or text.startswith(("/", "\\")):
            problems.append(f"绝对路径进了库：{text}")
            continue
        resolved = (root / text).resolve()
        if root not in resolved.parents:
            problems.append(f"路径跑到 AUDIO_DIR 外面去了：{text}")
    rep.verdict(
        "P2-C4",
        "音频路径不落绝对路径",
        problems,
        f"{len(info.get('paths') or [])} 行 `file_path` 全部是相对路径、且都在 AUDIO_DIR 之下",
    )


def check_switch_voice(rep: Report, ctx: Ctx) -> None:
    """P2-A4：换了教师音色之后，合成规格跟着变 —— 每个 beat 都重合成、URL 都变。

    **音色本身好不好听要人耳**（E 类）。离线能钉住的是那条因果链：音色 → 规格
    哈希 → 缓存键。这一条要是在现实里坏了，症状是「设置了 1.5 倍速 / 换了音色，
    听着还是老样子，而且不报错」。
    """
    if not ctx.course_id:
        return rep.fail("P2-A4", "音色切换生效", "主线课程没生成出来")

    before = snapshot(ctx.audio_dir)
    before_urls = {beat["beatId"]: beat["url"] for beat in ctx.manifest.get("beats") or []}

    status, envelope = api("PUT", "/settings/voice", {"teacherVoiceId": "vp_teacher_gu"})
    if status != 200:
        return rep.fail("P2-A4", "音色切换生效", f"切换音色失败：{brief(envelope)}")

    manifest = _narrate_and_wait(ctx, ctx.course_id)
    if manifest.get("readyCount") != manifest.get("beatCount"):
        return rep.fail(
            "P2-A4", "音色切换生效", f"换音色后有句子没合出来：{manifest.get('readyCount')}/{manifest.get('beatCount')}"
        )

    after = snapshot(ctx.audio_dir)
    added, changed, _removed = diff_snapshots(before, after)
    after_urls = {beat["beatId"]: beat["url"] for beat in manifest.get("beats") or []}
    same_url = [beat_id for beat_id, url in after_urls.items() if url == before_urls.get(beat_id)]

    problems = []
    if not added:
        problems.append("换音色之后一个音频文件都没重写（合成的规格哈希没跟着音色变？）")
    if same_url:
        problems.append(f"{len(same_url)} 句的 url 没变，浏览器会接着播旧音色的缓存：{same_url[:3]}")
    if manifest.get("voiceId") != "vp_teacher_gu":
        problems.append(f"清单里的 voiceId 是 {manifest.get('voiceId')!r}，应当是 vp_teacher_gu")

    # 换回来，后面的条目（A6/C1）继续用沈老师的那一套
    api("PUT", "/settings/voice", {"teacherVoiceId": "vp_teacher_shen"})
    ctx.manifest = _narrate_and_wait(ctx, ctx.course_id)
    ctx.voice_files = snapshot(ctx.audio_dir)

    rep.verdict(
        "P2-A4",
        "音色切换生效（规格哈希跟着音色走）",
        problems,
        f"沈老师 → 顾老师：新增 {len(added)} 个文件、{len(changed)} 个被重写，"
        f"{len(after_urls)} 句的 url 全变；再换回沈老师时清单回到 "
        f"{ctx.manifest.get('readyCount')}/{ctx.manifest.get('beatCount')}。"
        "听感差异（音色、1.5x 不变调）要人工听辨，见 P2-A10 / E1~E2",
    )


def check_invalidation(rep: Report, ctx: Ctx) -> None:
    """P2-A6：重写第 7 页 → 这一页的音频失效并自动重合成，其余页一个文件都不动。"""
    if not ctx.course_id:
        return rep.fail("P2-A6", "讲稿修改后音频失效", "主线课程没生成出来")
    written = _wait_pages(ctx.course_id, want=REWRITE_PAGE, timeout=60)
    if written < REWRITE_PAGE:
        return rep.fail("P2-A6", "讲稿修改后音频失效", f"只写出了 {written} 页，还改不了第 {REWRITE_PAGE} 页")

    before = snapshot(ctx.audio_dir)
    page_beats = [beat for beat in ctx.manifest.get("beats") or [] if int(beat["pageNo"]) == REWRITE_PAGE]
    if not page_beats:
        return rep.fail("P2-A6", "讲稿修改后音频失效", f"第 {REWRITE_PAGE} 页在清单里没有 beat")

    status, envelope = api(
        "POST", f"/courses/{ctx.course_id}/pages/{REWRITE_PAGE}/rewrite", {"instruction": "更通俗"}
    )
    if status != 200:
        return rep.fail("P2-A6", "讲稿修改后音频失效", f"重写失败：{brief(envelope)}")

    # 重写是同步的，重新合成是**排队**的（P2-A6 的那个钩子）—— 等它跑完。
    # 这里不必额外等「running 立起来」：第 7 页刚失效，清单在有新音频之前
    # 本来就不满，`_wait_audio_job` 的「满」条件自己就把这扇门关上了。
    _wait_audio_job(ctx.course_id, timeout=NARRATE_TIMEOUT)
    ctx.manifest = _data(*api("GET", f"/courses/{ctx.course_id}/audio-manifest")) or ctx.manifest
    after = _settle_audio(ctx)
    added, changed, removed = diff_snapshots(before, after)

    touched = set(added) | set(changed) | set(removed)
    elsewhere = sorted(name for name in touched if page_of(name) != REWRITE_PAGE)
    page_untouched = not any(page_of(name) == REWRITE_PAGE for name in touched)
    still_ready = [beat["beatId"] for beat in ctx.manifest.get("beats") or [] if beat.get("status") != "ready"]

    problems = []
    if page_untouched:
        problems.append(f"第 {REWRITE_PAGE} 页的音频一个都没动（改完讲稿声音还是旧的）")
    if elsewhere:
        problems.append(f"只该动第 {REWRITE_PAGE} 页，这几处也动了：{elsewhere[:5]}")
    if still_ready:
        problems.append(f"重合成之后还有句子没声音：{still_ready[:5]}")

    ctx.voice_files = after
    rep.verdict(
        "P2-A6",
        "讲稿修改后音频失效并自动重合成",
        problems,
        f"页 {REWRITE_PAGE} 的 {len(page_beats)} 句全部重合成，其余 {len(after) - len(touched)} 个"
        "文件按 mtime 比对未被重写",
    )


def check_usage(rep: Report, ctx: Ctx) -> None:
    """P2-A11 / P2-C3：用量可查、与账本一致、能按课/会话分开看。"""
    if not ctx.course_id:
        return rep.fail("P2-A11", "用量可查", "主线课程没生成出来")

    here = _data(*api("GET", f"/voice/usage?refType=course&refId={ctx.course_id}")) or {}
    other = _data(*api("GET", "/voice/usage?refType=course&refId=course_demo_photosynthesis")) or {}
    all_usage = _data(*api("GET", "/voice/usage")) or {}

    # 界面上的数字必须与账本求和一致 —— 所以在这里自己再求一次
    probe = run_python(
        "import json\n"
        "from app import create_app\n"
        "from app.models import UsageRecord\n"
        "app = create_app()\n"
        "with app.app_context():\n"
        "    rows = UsageRecord.query.filter_by(ref_type='course', ref_id=%r).all()\n"
        "    print(json.dumps({'byKind': {k: sum(int(r.units or 0) for r in rows if r.kind == k)\n"
        "                                 for k in {r.kind for r in rows}},\n"
        "                      'cost': round(sum(float(r.est_cost or 0) for r in rows), 6)}))\n"
        % ctx.course_id,
        env=ctx.env,
    )
    lines = [line for line in (probe.stdout or "").splitlines() if line.startswith("{")]
    if not lines:
        return rep.fail("P2-A11", "用量可查", f"读账本失败：{plain((probe.stderr or '')[-300:])}")
    ledger = json.loads(lines[-1])

    api_units = {item["kind"]: item["units"] for item in here.get("kinds") or []}
    problems = []
    for kind, units in (ledger.get("byKind") or {}).items():
        if api_units.get(kind) != units:
            problems.append(f"{kind}：接口说 {api_units.get(kind)}，账本是 {units}")
    tts = next((item for item in here.get("kinds") or [] if item["kind"] == "tts"), {})
    if tts.get("unitName") != "chars":
        problems.append(f"TTS 的计量单位应当是 chars，实际 {tts.get('unitName')!r}")
    if here.get("totalCost") != ledger.get("cost"):
        problems.append(f"估算金额不一致：接口 {here.get('totalCost')} vs 账本 {ledger.get('cost')}")
    if here.get("priced") is not False:
        problems.append("没配价目表时 priced 应当为 false（界面据此说「未配置单价」）")
    other_units = sum(item["units"] for item in other.get("kinds") or [])
    if other_units:
        problems.append(f"另一门课的用量不该串进来：{other_units}")
    if not all_usage.get("kinds"):
        problems.append("不筛条件的用量该给出完整的三个链路")

    rep.verdict(
        "P2-A11",
        "用量可查且与账本一致",
        problems,
        "本课 TTS " + str(api_units.get("tts", 0)) + " 字（单位 chars）与账本求和一致；"
        f"实时语音 {api_units.get('realtime', 0)} 秒、ASR {api_units.get('asr', 0)} 秒；"
        "priced=false 时如实说「未配置单价」",
    )

    # --- P2-C3：refType/refId 能分开查 ---
    session_rows = run_python(
        "import json\n"
        "from app import create_app\n"
        "from app.models import UsageRecord\n"
        "app = create_app()\n"
        "with app.app_context():\n"
        "    rows = UsageRecord.query.filter(UsageRecord.ref_type != 'course').all()\n"
        "    print(json.dumps({'kinds': sorted({r.kind for r in rows}),\n"
        "                      'refs': sorted({r.ref_type for r in rows})}))\n",
        env=ctx.env,
    )
    session_lines = [line for line in (session_rows.stdout or "").splitlines() if line.startswith("{")]
    info = json.loads(session_lines[-1]) if session_lines else {}
    scoped = _data(*api("GET", f"/voice/usage?refType=course&refId={ctx.course_id}")) or {}
    problems = []
    if not scoped.get("refType") == "course" or scoped.get("refId") != ctx.course_id:
        problems.append(f"按课筛的响应没回显筛选条件：{brief(scoped)}")
    if not info.get("refs"):
        problems.append("账本里一条非课程归属的记录都没有（试听/ASR/实时语音都该是 session）")
    else:
        by_session = _data(*api("GET", "/voice/usage?refType=session&refId=preview:vp_teacher_shen")) or {}
        if sum(item["units"] for item in by_session.get("kinds") or []) <= 0:
            problems.append("按会话筛（试听那一笔）什么都没筛出来")
    rep.verdict(
        "P2-C3",
        "用量能按课程 / 会话关联查询",
        problems,
        f"course 与 session 两类归属都在账本里（{info.get('refs')}），筛选条件原样回显",
    )


def check_purge(rep: Report, ctx: Ctx) -> None:
    """P2-C2：真删一门课 → 音频文件与 `audio_assets` 一并清掉，磁盘不留孤儿。

    **这里的「删」是 `store.purge_course`，不是 `DELETE /api/courses/<id>`。**
    接口那个是软删（置 `deleted_at`），它**故意**把页面与音频都留着 ——
    P1 §4 的口径是「点错了还能捞回来」，复盘那次生成也还有依据。真删是
    部署方的动作（`store.purge_course` 的 docstring 写了这件事），所以验收
    直接驱动那个函数，并且先把「软删之后库和盘都还在」这一步也钉住 ——
    免得哪天有人把软删改成真删，学生点一下「删除」就把花了钱的音频丢了。
    """
    if not ctx.course_id:
        return rep.fail("P2-C2", "删课清理音频", "主线课程没生成出来")

    course_id = ctx.course_id
    directory = ctx.audio_dir / course_id
    before = snapshot(directory)
    rows_before = _count_assets(ctx, course_id)
    if not before or rows_before <= 0:
        return rep.fail(
            "P2-C2", "删课清理音频", f"这门课本来就没有音频：{len(before)} 个文件 / {rows_before} 行"
        )

    status, envelope = api("DELETE", f"/courses/{course_id}")
    if status != 200:
        return rep.fail("P2-C2", "删课清理音频", f"删课失败：{brief(envelope)}")

    soft_files, soft_rows = snapshot(directory), _count_assets(ctx, course_id)
    problems = []
    if not soft_files or soft_rows <= 0:
        problems.append(
            "软删就把音频清掉了 —— 点错「删除」就再也捞不回来，P1 那把口子破了"
        )

    purged = run_python(
        "import json, pathlib\n"
        "from app import create_app\n"
        "from app.models import AudioAsset, Course\n"
        "from app.services.courses import store\n"
        "from app.services.voice import assets\n"
        "app = create_app()\n"
        "with app.app_context():\n"
        "    course = Course.query.filter_by(id=%r).one()\n"
        "    store.purge_course(course)\n"
        "    root = assets.audio_root()\n"
        "    directory = root / %r\n"
        "    print(json.dumps({'rows': AudioAsset.query.filter_by(course_id=%r).count(),\n"
        "                      'files': len([p for p in directory.rglob('*') if p.is_file()]),\n"
        "                      'exists': directory.is_dir()}))\n"
        % (course_id, course_id, course_id),
        env=ctx.env,
    )
    lines = [line for line in (purged.stdout or "").splitlines() if line.startswith("{")]
    if not lines:
        return rep.fail(
            "P2-C2", "删课清理音频", f"真删失败：{plain((purged.stderr or '')[-300:])}"
        )
    info = json.loads(lines[-1])
    if info["rows"]:
        problems.append(f"真删之后 audio_assets 里还剩 {info['rows']} 行")
    if info["files"]:
        problems.append(f"真删之后磁盘上还剩 {info['files']} 个文件")
    if info["exists"] and info["files"]:
        problems.append("真删之后目录还在，里面还有东西")

    rep.verdict(
        "P2-C2",
        "删课清理音频（软删保留 / 真删清干净）",
        problems,
        f"接口软删后 {rows_before} 行与 {len(before)} 个文件照旧留着（有意为之）；"
        "真删（`store.purge_course`）之后行与文件都清零",
    )


def _count_assets(ctx: Ctx, course_id: str) -> int:
    """这门课在 `audio_assets` 里有多少行（直接查库，不经过接口）。"""
    probe = run_python(
        "import json\n"
        "from app import create_app\n"
        "from app.models import AudioAsset\n"
        "app = create_app()\n"
        "with app.app_context():\n"
        "    print(json.dumps({'n': AudioAsset.query.filter_by(course_id=%r).count()}))\n" % course_id,
        env=ctx.env,
    )
    lines = [line for line in (probe.stdout or "").splitlines() if line.startswith("{")]
    return int(json.loads(lines[-1])["n"]) if lines else -1


def check_asr_and_privacy(rep: Report, ctx: Ctx) -> None:
    """P2-F3（不落盘）+ §4.1 的 `/voice/asr` 出口：格式闸门在接口层。"""
    before = snapshot(ctx.audio_dir)

    body, content_type = multipart("file", "ask.wav", b"\x00\x01" * 8000)
    status, envelope = api("POST", "/voice/asr", raw=body, content_type=content_type)
    data = _data(status, envelope) or {}

    webm, webm_type = multipart("file", "ask.webm", b"\x1a\x45\xdf\xa3" + b"\x00" * 64)
    webm_status, webm_envelope = api("POST", "/voice/asr", raw=webm, content_type=webm_type)

    after = snapshot(ctx.audio_dir)
    added, changed, removed = diff_snapshots(before, after)

    problems = []
    if not data.get("text") or data.get("final") is not True:
        problems.append(f"识别没给出定稿文本：{brief(envelope)}")
    if not data.get("segments"):
        problems.append("识别没给分句（前端要用它做逐句上屏）")
    if webm_status != 400 or webm_envelope.get("code") != 40001:
        problems.append(
            f"webm 应当在**接口层**被挡成 40001，实际 {webm_status}/{webm_envelope.get('code')}"
        )
    elif "pcm" not in str(webm_envelope.get("message")) and "webm" not in str(webm_envelope.get("message")):
        problems.append(f"拒绝 webm 时该说清为什么，实际：{webm_envelope.get('message')!r}")
    if added or changed or removed:
        problems.append(f"上传的录音落盘了：新增 {added[:3]} 变动 {changed[:3]} 消失 {removed[:3]}")

    rep.verdict(
        "P2-F3",
        "录音数据默认不落盘（顺带验 ASR 的格式闸门）",
        problems,
        f"wav → 「{data.get('text')}」（{data.get('durationMs')}ms、{len(data.get('segments') or [])} 个分句）；"
        f"webm → 40001 并在接口层说清原因；AUDIO_DIR 一个文件都没多",
    )


# --------------------------------------------------------------------------
# 实时语音：真端口、真握手
# --------------------------------------------------------------------------


def check_realtime(rep: Report, ctx: Ctx) -> None:
    """P2-B1 / F4 / F5 / A18 的线上那一半：走真的 WebSocket。

    契约测试能验到「票据不对时视图会拒绝」，但验不到**握手本身**：那条路由
    要 `Server.accept()` 从 WSGI 环境里掏一个真 socket，测试客户端没有。
    所以这一条只能在真端口上验，而它正是 P2-F4 的全部意思 ——
    「没票的握手被拒绝」是一句关于接线的话。
    """
    status, envelope = api("POST", "/voice/ticket")
    ticket = (_data(status, envelope) or {}).get("ticket") or ""
    if not ticket:
        return rep.fail("P2-F4", "会话票据：真握手", f"取票失败：{brief(envelope)}")

    # --- 没票 / 假票：握手在升级之前就被拒 ---
    problems = []
    for query in ("", "?ticket=not-a-ticket"):
        client, line, body = ws_connect(TEMP_PORT, f"/ws/voice/realtime{query}")
        payload = {}
        try:
            payload = json.loads(body.decode("utf-8", "replace"))
        except ValueError:
            payload = {}
        if client is not None:
            client.close()
            problems.append(f"{query or '（不带票）'}：握手居然成功了（{line}）")
            continue
        if "401" not in line:
            problems.append(f"{query or '（不带票）'}：期望 HTTP 401，实际 {line!r}")
        if payload.get("code") != 40101:
            problems.append(f"{query or '（不带票）'}：期望业务码 40101，实际 {payload.get('code')!r}")
        if not fallback_of(payload):
            problems.append(f"{query or '（不带票）'}：拒绝时没带 fallback（P2-B2）")
    rep.verdict(
        "P2-F4a",
        "没票 / 假票的握手被拒（且带 fallback）",
        problems,
        "两次都拿到 HTTP 401 + 40101 + fallback，**连 101 都没见着** —— 拒绝发生在升级之前",
    )

    # --- 用真票建连：全序列 ---
    client, line, _ = ws_connect(TEMP_PORT, f"/ws/voice/realtime?ticket={ticket}")
    if client is None:
        return rep.fail("P2-B1", "WS 全序列（真端口）", f"带票的握手没成：{line!r}")
    try:
        _realtime_turn(rep, ctx, client, ticket=ticket)
    finally:
        client.close()


def _realtime_turn(rep: Report, ctx: Ctx, client: WsClient, *, ticket: str) -> None:
    """一条通道上跑完：ready → 一轮问答 → 打断 → 再问一轮 → 收工。"""
    before = snapshot(ctx.audio_dir)
    context = {"courseId": ctx.course_id, "pageNo": 3} if ctx.course_id else {}
    client.send_text(
        {"type": "start", "mode": "push_to_talk", "context": context, "sessionId": "accept-p2"}
    )
    frames = client.drain(10.0, until=lambda out: bool(_json_frames(out, "ready")))
    ready = _json_frames(frames, "ready")
    problems = []
    if not ready:
        problems.append(f"没等到 ready：{_describe(frames)}")
    else:
        if not ready[0].get("sessionId"):
            problems.append("ready 里没有 sessionId（前端要用它认这一次会话）")
    rep.verdict("P2-B1a", "建连后进 ready", problems, "start → ready（带 sessionId/dialogId/ttsFirstFrameMs）")
    if problems:
        return

    # --- 一轮问答（按住说话那一套：先二进制、再 final）---
    client.send_bytes(b"\x00" * PCM_FRAME)
    client.send_text({"type": "audio", "seq": 1, "final": True})
    turn = client.drain(15.0, until=lambda out: bool(_json_frames(out, "done")))
    types = [json.loads(p).get("type") for name, p in turn if name == "text" and _is_json(p)]
    binaries = _frames_of(turn, "binary")
    asr = _json_frames(turn, "asr")
    replies = _json_frames(turn, "reply")
    audios = _json_frames(turn, "audio")
    done = _json_frames(turn, "done")

    problems = []
    if not done:
        problems.append(f"这一轮没等到 done：{types}")
    if not asr or asr[-1].get("final") is not True:
        problems.append(f"识别没给出定稿：{types}")
    elif len(asr) < 2:
        problems.append(f"只收到 {len(asr)} 条识别结果（应当有中间结果 + 定稿）")
    else:
        texts = [item.get("text") or "" for item in asr]
        if any(not later.startswith(earlier) for earlier, later in zip(texts, texts[1:])):
            problems.append(f"识别结果回退了：{texts}")
    if not replies:
        problems.append(f"老师一句话都没说：{types}")
    if len(audios) != len(binaries):
        problems.append(f"音频说明 {len(audios)} 条对不上二进制帧 {len(binaries)} 个（seq 关联断了）")
    if not binaries:
        problems.append("一帧音频都没收到")
    else:
        seqs = [item.get("seq") for item in audios]
        if seqs != list(range(1, len(seqs) + 1)):
            problems.append(f"音频 seq 不连续：{seqs}")
    if done:
        usage = done[-1].get("usage") or {}
        if int(usage.get("replyChars") or 0) <= 0:
            problems.append(f"这一轮的记账里 replyChars={usage.get('replyChars')!r}")
    else:
        usage = {}
    rep.verdict(
        "P2-B1b",
        "一轮问答：asr → reply → audio → done（真端口）",
        problems,
        f"{len(asr)} 条识别（单调不回退）、{len(replies)} 句回答、"
        f"{len(binaries)} 帧音频（seq 1..{len(audios)}）、done 带本轮用量",
    )

    # --- 打断 ---
    client.send_text({"type": "barge_in"})
    ack = client.drain(5.0, until=lambda out: bool(_json_frames(out, "barge_in_ack")))
    acks = _json_frames(ack, "barge_in_ack")
    problems = []
    if not acks:
        problems.append(f"打断没回执：{_describe(ack)}")
    elif not isinstance(acks[0].get("latencyMs"), int):
        problems.append(f"回执里没有延迟：{brief(acks[0])}")
    rep.verdict(
        "P2-B1c",
        "打断有回执（前端据此确认 ≤300ms）",
        problems,
        f"barge_in → barge_in_ack（latencyMs={acks[0].get('latencyMs') if acks else '?'}）；"
        "真上游上的 300ms 上限见 P2-D3",
    )

    # --- P2-F5：同一个人开第二条通道 ---
    second_ticket = (_data(*api("POST", "/voice/ticket")) or {}).get("ticket") or ""
    second, line, _ = ws_connect(TEMP_PORT, f"/ws/voice/realtime?ticket={second_ticket}")
    if second is None:
        rep.fail("P2-F5b", "同一人第二条通道被拒（真端口）", f"第二条握手就没成：{line!r}")
    else:
        try:
            second.send_text({"type": "start", "mode": "push_to_talk", "context": context})
            out = second.drain(8.0, until=lambda frames: bool(_json_frames(frames, "error")))
            errors = _json_frames(out, "error")
            problems = []
            if not errors:
                problems.append(f"第二条通道居然建起来了：{_describe(out)}")
            else:
                error = errors[0]
                if error.get("code") != "42901":
                    problems.append(f"期望业务码 42901，实际 {error.get('code')!r}")
                if error.get("fallback") != "text":
                    problems.append(f"被拒时要给出降级路径 text，实际 {error.get('fallback')!r}")
            rep.verdict(
                "P2-F5b",
                "同一人第二条通道被拒（真端口）",
                problems,
                "第二条通道拿到 error 42901 + fallback=text，前端据此退到文字问答；"
                "名额释放后能否再进由 test_p2_voice_ws 的两个用例守着",
            )
        finally:
            second.close()

    # --- 收工：不带票的重复使用 ---
    client.send_text({"type": "stop"})
    closed = client.drain(6.0, until=lambda out: bool(_json_frames(out, "closed")))
    stopped = _json_frames(closed, "closed")
    problems = []
    if not stopped:
        problems.append(f"发 stop 之后没收到 closed：{_describe(closed)}")
    rep.verdict("P2-B1d", "收工：stop → closed", problems, f"closed.reason={stopped[0].get('reason') if stopped else '?'}")

    # --- 票据用过即废 ---
    replay, line, body = ws_connect(TEMP_PORT, f"/ws/voice/realtime?ticket={ticket}")
    if replay is not None:
        replay.close()
        rep.fail("P2-F4b", "票据用过即废（真端口）", f"同一张票据居然又开了一次：{line}")
    else:
        rep.ok("P2-F4b", "票据用过即废（真端口）", f"重放同一张票据 → {line.strip()}（HTTP 401）")

    # 会话期间不落盘（F3 的另一半：麦克风上行不该在服务端留下文件）
    added, changed, removed = diff_snapshots(before, snapshot(ctx.audio_dir))
    if added or changed or removed:
        rep.fail(
            "P2-F3b",
            "实时语音的音频不落盘",
            f"这一轮之后音频目录变了：新增 {added[:3]} 变动 {changed[:3]} 消失 {removed[:3]}",
        )
    else:
        rep.ok("P2-F3b", "实时语音的音频不落盘", "整轮问答 + 打断之后 AUDIO_DIR 一个文件都没多")

    # --- 关掉会话之后名额该放出来了 ---
    third_ticket = (_data(*api("POST", "/voice/ticket")) or {}).get("ticket") or ""
    third, line, _ = ws_connect(TEMP_PORT, f"/ws/voice/realtime?ticket={third_ticket}")
    if third is None:
        return rep.fail("P2-F5c", "结束之后名额释放", f"第三条握手没成：{line!r}")
    try:
        third.send_text({"type": "start", "mode": "push_to_talk", "context": context})
        out = third.drain(8.0, until=lambda frames: bool(_json_frames(frames, "ready")))
        if _json_frames(out, "ready"):
            rep.ok("P2-F5c", "结束之后名额释放", "第一条通道 stop 之后，第三条通道能正常建起来")
        else:
            rep.fail("P2-F5c", "结束之后名额释放", f"第三条通道没进 ready：{_describe(out)}")
    finally:
        third.close()


def _is_json(payload: Any) -> bool:
    try:
        return isinstance(json.loads(payload), dict)
    except (TypeError, ValueError):
        return False


def _describe(frames: Sequence[tuple[str, Any]]) -> str:
    """一帧一帧地写出来（断言失败时最想知道的就是「到底收到了什么」）。"""
    parts = []
    for name, payload in frames:
        if name == "binary":
            parts.append(f"binary({len(payload)}B)")
        elif _is_json(payload):
            parsed = json.loads(payload)
            text = str(parsed.get("text") or parsed.get("message") or "")
            parts.append(f"{parsed.get('type')}{('：' + text[:20]) if text else ''}")
        else:
            parts.append(f"{name}({str(payload)[:40]!r})")
    return "、".join(parts) or "（什么都没收到）"


# --------------------------------------------------------------------------
# 降级：半配实例与关闭实例
# --------------------------------------------------------------------------


def check_degraded(rep: Report, ctx: Ctx) -> None:
    """P2-A9 / B2：配错了密钥 —— 每一条语音路都给出 40201 与降级路径。"""
    tts_status, tts = api("POST", "/voice/tts", {"text": "同学们好"}, base=ctx.degraded)
    ticket_status, ticket = api("POST", "/voice/ticket", base=ctx.degraded)
    manifest = _data(*api("GET", "/courses/course_demo_ml/audio-manifest", base=ctx.degraded)) or {}
    voices = _data(*api("GET", "/voice/voices", base=ctx.degraded)) or {}

    problems = []
    for label, status, envelope in (("单句合成", tts_status, tts), ("会话票据", ticket_status, ticket)):
        # 期望的是**业务码** 40201，不是 HTTP 402：P0-B3 把 40201 定在 4xxxx 那一段
        # （「去设置页补一下就好」而不是服务端故障），随它的 http_status 是 400。
        # 这里要钉住的是「不能是 5xx、也不能假装成功」，具体数字归 P0 管。
        if envelope.get("code") != 40201:
            problems.append(f"{label}：期望业务码 40201，实际 {status}/{envelope.get('code')} {brief(envelope)}")
        elif not 400 <= status < 500:
            problems.append(f"{label}：40201 的 HTTP 状态该落在 4xx（配置问题不是故障），实际 {status}")
        elif fallback_of(envelope) != "browser":
            problems.append(
                f"{label}：上游没配好时该退到**浏览器本地朗读**（服务端没声音、设备有），"
                f"实际 fallback={fallback_of(envelope)!r}"
            )
    if manifest.get("reason") != "provider_not_configured":
        problems.append(f"清单没说清是服务商没配：reason={manifest.get('reason')!r}")
    if manifest.get("available") is not False:
        problems.append("上游没配好时清单不该说自己可播")
    if not manifest.get("beats"):
        problems.append("降级之后清单里的讲稿不该消失（学生还要读它）")
    if voices.get("usable") is not False:
        problems.append("上游没配好时音色卡不该是可用的（试听按钮要置灰）")

    rep.verdict(
        "P2-B2",
        "未配置上游时统一 40201 + fallback",
        problems,
        "合成 / 票据 / 清单 / 音色四条路都给出 40201 或明确的 reason，"
        "fallback=browser（退到浏览器本地朗读）",
    )

    # --- P2-A9：降级之后这节课还能上 ---
    problems = []
    # `withPages=1`：详情默认不带页面正文（那是另一个接口的事），
    # 不传这个参数会得到一份没有 pages 的响应，看着像「课没了」
    status, envelope = api("GET", "/courses/course_demo_ml?withPages=1", base=ctx.degraded)
    detail = _data(status, envelope) or {}
    if status != 200:
        problems.append(f"降级时课都打不开了：{status} {brief(envelope)}")
    elif not detail.get("pages"):
        problems.append("课程详情里没有页面（纯文字的那条路也断了）")
    page = _data(*api("GET", "/courses/course_demo_ml/pages/1", base=ctx.degraded)) or {}
    if not page.get("dsl"):
        problems.append("单页也读不到内容")
    rep.verdict(
        "P2-A9",
        "配错密钥后降级可用（课还能照常上）",
        problems,
        "语音四条路全部给出「为什么 + 怎么办」的降级说明，课程详情与单页照常可读；"
        "课堂顶部那条黄条由 ClassroomView 消费同一个 fallback（见 P2-G2 的前端用例）。"
        "注：退到文字问答的**作答**那一步在 P3 的课堂运行时（ClassroomView 上写着「文字提问也由它作答」），"
        "P2 这一轮验到的是提示 + 课程可用，见 §10.2",
    )


def check_disabled(rep: Report, ctx: Ctx) -> None:
    """P2-G3：`VOICE_ENABLED=false` 之后是一节纯文字的课堂，不是一地错误。"""
    manifest = _data(*api("GET", "/courses/course_demo_ml/audio-manifest", base=ctx.novoice)) or {}
    tts_status, tts = api("POST", "/voice/tts", {"text": "同学们好"}, base=ctx.novoice)
    narrate = _data(*api("POST", "/courses/course_demo_ml/narrate", base=ctx.novoice)) or {}
    ticket_status, ticket = api("POST", "/voice/ticket", base=ctx.novoice)
    page = _data(*api("GET", "/courses/course_demo_ml/pages/1", base=ctx.novoice)) or {}

    problems = []
    if manifest.get("enabled") is not False:
        problems.append("清单里的 enabled 应当为 false")
    if manifest.get("reason") != "voice_disabled":
        problems.append(f"清单该说清是开关关着：reason={manifest.get('reason')!r}")
    if manifest.get("fallback") != "text":
        problems.append(f"开关关着该退到纯文字，实际 {manifest.get('fallback')!r}")
    if not manifest.get("beats"):
        problems.append("关掉语音之后讲稿不该消失")
    if any(beat.get("url") for beat in manifest.get("beats") or []):
        problems.append("关掉语音之后不该还有可播的地址")
    for label, status, envelope in (("单句合成", tts_status, tts), ("会话票据", ticket_status, ticket)):
        if status != 403 or envelope.get("code") != 40302:
            problems.append(f"{label}：期望 403/40302，实际 {status}/{envelope.get('code')} {brief(envelope)}")
        elif fallback_of(envelope) != "text":
            problems.append(f"{label}：fallback 应当是 text，实际 {fallback_of(envelope)!r}")
    if narrate.get("started") is not False or narrate.get("enabled") is not False:
        problems.append(f"关掉语音时「全部合成」该是一次什么都不做：{brief(narrate)}")
    if not page.get("dsl"):
        problems.append("纯文字课堂里单页应当照常可读")

    rep.verdict(
        "P2-G3",
        "关掉语音后是纯文字课堂",
        problems,
        f"清单 {manifest.get('beatCount')} 句讲稿全在、url 全空，"
        "合成/票据一律 40302 + fallback=text，单页与课程照常可读",
    )


# --------------------------------------------------------------------------
# F. 安全
# --------------------------------------------------------------------------


def check_security(rep: Report, ctx: Ctx) -> None:
    """P2-F1 / F2：凭据不出服务端、麦克风只在用户动作里开。"""
    # --- F1：金丝雀扫三处：日志、响应体、前端源码 ---
    hits: list[str] = []
    for name in ("degraded.log", "backend.log"):
        path = ctx.work_dir / name
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            if CANARY_KEY in text:
                hits.append(f"{name} 里出现了凭据")

    sweep = [
        ("GET", "/voice/voices", None),
        ("POST", "/voice/tts", {"text": "同学们好"}),
        ("POST", "/voice/ticket", None),
        ("GET", "/courses/course_demo_ml/audio-manifest", None),
        ("GET", "/voice/usage", None),
    ]
    for base in (API, ctx.degraded, ctx.novoice):
        for method, path, body in sweep:
            status, envelope = api(method, path, body, base=base)
            if CANARY_KEY in json.dumps(envelope, ensure_ascii=False):
                hits.append(f"{base}{path} 的响应里出现了凭据")

    front_hits = []
    patterns = (r"X-Api-Key", r"access_token", r"VOLC_[A-Z_]*KEY", CANARY_KEY)
    for path in (FRONTEND / "src").rglob("*"):
        if path.suffix not in {".ts", ".vue", ".js", ".json"} or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in patterns:
            if re.search(pattern, text):
                front_hits.append(f"{path.relative_to(FRONTEND)} 命中 {pattern}")
    if front_hits:
        hits.extend(front_hits[:4])

    rep.verdict(
        "P2-F1",
        "凭据只存在服务端",
        hits,
        f"拿一个假凭据（{CANARY_KEY}）当金丝雀：三个实例的日志、{len(sweep) * 3} 次接口响应、"
        "前端全部源码里都搜不到它；票据是一串随机数，也不含凭据",
    )

    # --- F2：麦克风只在用户按住/点击时开 ---
    composable = FRONTEND / "src" / "composables" / "useRealtimeVoice.ts"
    view = FRONTEND / "src" / "views" / "ClassroomView.vue"
    problems = []
    if not composable.is_file() or not view.is_file():
        problems.append("前端源码没找到（目录结构变了？）")
    else:
        text = composable.read_text(encoding="utf-8", errors="replace")
        calls = [m.start() for m in re.finditer(r"navigator\.mediaDevices\.getUserMedia", text)]
        if not calls:
            problems.append("useRealtimeVoice 里没有 getUserMedia —— 检查方式要更新了")
        inside = False
        for start in calls:
            head = text[:start]
            body_start = head.rfind("async function startMicrophone")
            if body_start != -1 and "\n}" not in head[body_start:]:
                inside = True
        if calls and not inside:
            problems.append("getUserMedia 不在 startMicrophone 里 —— 得确认它不是模块加载时就调的")
        view_text = view.read_text(encoding="utf-8", errors="replace")
        mounted = view_text.split("onMounted(", 1)
        if len(mounted) > 1:
            block = mounted[1].split("onBeforeUnmount", 1)[0]
            for forbidden in ("voice.open(", "beginTalk(", "startTalk("):
                if forbidden in block:
                    problems.append(f"onMounted 里调了 {forbidden} —— 页面一加载就会要麦克风权限")
        if "getUserMedia" in view_text:
            problems.append("视图层直接碰了 getUserMedia（应当只经 composable）")

    rep.verdict(
        "P2-F2",
        "麦克风只在用户动作里请求",
        problems,
        "getUserMedia 只出现在 useRealtimeVoice 的 startMicrophone 里，"
        "ClassroomView.onMounted 只挂键盘监听；按住空格 / 点按钮才走到 beginTalk → open",
    )


def check_frontend(rep: Report, ctx: Ctx) -> None:
    """P2 的前端那一半：播放器、字幕、按住说话、降级条（用例逐条跑）。"""
    specs = [
        "src/__tests__/narration-player.spec.ts",
        "src/__tests__/realtime-voice.spec.ts",
        "src/__tests__/voice-utils.spec.ts",
        "src/__tests__/voice-api.spec.ts",
        "src/__tests__/ClassroomView.spec.ts",
        "src/__tests__/SettingsView.spec.ts",
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
        log_path = ctx.work_dir / "vitest-p2.log"
        log_path.write_text(output, encoding="utf-8")
        reason = next((ln.strip() for ln in output.splitlines() if "FAIL" in ln or "Error" in ln), "")
        return rep.fail("P2-G2", "前端：播放器/字幕/提问/降级", f"用例未通过：{reason}\n完整输出：{log_path}")

    summary = next((ln.strip() for ln in reversed(output.splitlines()) if "Tests" in ln), "")
    rep.ok(
        "P2-G2",
        "前端：播放器 / 字幕 / 按住说话 / 降级提示",
        f"课堂、播放器、实时语音、语音工具与接口层五份用例全通过（{summary}）",
    )


# --------------------------------------------------------------------------
# 委托给 pytest 的那几条 + P0/P1 回归
# --------------------------------------------------------------------------


def check_delegated(rep: Report, ctx: Ctx) -> None:
    """跑一遍离线用例，逐条记账（A15/A16/A17/A21/A22/B1/B3/B4/C1/C4/F4/F5/G3）。"""
    proxy_nodes = [node for _aid, _title, nodes, _why in PROXIED for node in nodes]
    all_nodes = [node for _aid, _title, nodes in DELEGATED for node in nodes] + proxy_nodes
    pytest_verdicts(all_nodes)

    for aid, title, nodes in DELEGATED:
        problems = []
        for node in nodes:
            ok, why = pytest_node_ok(node)
            if not ok:
                problems.append(f"{node}（{why}）")
        rep.verdict(aid, title, problems, f"{len(nodes)} 条用例全通过")

    # 代理用例的结果写进跳过理由里 —— 「离线验了哪一半」要看得见
    for aid, title, nodes, why in PROXIED:
        pairs = []
        for node in nodes:
            ok, _ = pytest_node_ok(node)
            pairs.append(f"{node.rsplit('::', 1)[-1]}：{'通过' if ok else '**未通过**'}")
        rep.skip(aid, title, f"{why}；离线侧（{len(nodes)} 条）—— " + "、".join(pairs))


def check_suites(rep: Report, ctx: Ctx) -> None:
    """P2-G1：P0/P1 的验收保持通过（尤其：没配语音时 P1 的生成不受影响）。"""
    p0 = run_pytest("tests/contract/test_p0_api.py")
    p1 = run_pytest("tests/contract/test_p1_api.py")
    problems = []
    if p0.returncode != 0:
        problems.append(f"P0 契约测试未通过：{_pytest_tail(p0, 6)}")
    if p1.returncode != 0:
        problems.append(f"P1 契约测试未通过：{_pytest_tail(p1, 6)}")
    rep.verdict(
        "P2-G1",
        "P0/P1 验收保持通过",
        problems,
        f"P0（{_pytest_tail(p0, 2).replace(chr(10), ' ')}）、P1（{_pytest_tail(p1, 2).replace(chr(10), ' ')}）；"
        "另外三个实例里有两个压根没有可用语音（半配 / 关闭），它们的课程接口都照常",
    )


def check_unreachable(rep: Report, ctx: Ctx) -> None:
    """D / E 与几条只有真上游能判的：如实跳过，并说清卡在哪。"""
    rep.skip(
        "P2-D1~D6",
        "时延与资源占用（首帧 ≤1.5s、提问到回答 ≤2s、打断 ≤300ms、整课 ≤3min、CPU ≤20%、25 分钟不涨内存）",
        "要真实上游（本次全程离线替身：它不模拟网络节奏，也不产生真实音频流）；"
        "接上真 Key 后按 §7 D 类逐条采样，打断那一条脚本已经能测到回执延迟（见 P2-B1c）",
    )
    rep.skip(
        "P2-E1~E4",
        "听辨与识别质量（可懂度 ≥98%、断句错误 ≤1、识别准确率 ≥90%、不叠音）",
        "要人耳与真音频；离线替身出的是结构合法的静音，量不出可懂度。"
        "§10.2 记了取样口径：三个音色各抽 10 句听写、20 句断句、10 条提问（含 2 条口音）",
    )
    rep.skip(
        "P2-A10",
        "倍速不变调（1.5x 下无明显失真）",
        "要人耳听真音频；离线侧只能钉住「speed 真的进了合成与缓存键」（见 test_voice_providers 的语速映射用例）",
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


def start_server(ctx: Ctx, port: int, log_name: str, env: dict[str, str]):
    proc = start(
        [str(venv_python()), "-m", "flask", "--app", "app:create_app()", "run", "--port", str(port)],
        cwd=BACKEND,
        log_path=ctx.work_dir / log_name,
        env=env,
    )
    if not wait_http(f"http://127.0.0.1:{port}/api/health", timeout=90):
        log = (ctx.work_dir / log_name).read_text(encoding="utf-8", errors="replace")
        print(f"  {port} 上的后端没起来，日志：\n{plain(log[-1200:])}")
        stop(proc)
        return None
    return proc


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="P2 A/B/C/F/G 类验收（P2-G2，离线 Mock）")
    parser.add_argument("--keep", action="store_true", help="跑完留下临时库、日志与三个后端进程")
    args = parser.parse_args()

    global API
    API = f"http://127.0.0.1:{TEMP_PORT}/api"

    for port in (TEMP_PORT, DEGRADED_PORT, NOVOICE_PORT):
        if is_up(f"http://127.0.0.1:{port}/api/health"):
            print(f"端口 {port} 上已经有服务了。这台机器上它可能是别人的 —— 停掉它再跑。")
            return 2

    work_dir = Path(tempfile.mkdtemp(prefix="eduagentx-p2-"))
    audio_dir = work_dir / "assets" / "audio"
    shared = {
        "DATABASE_URL": f"sqlite:///{(work_dir / 'accept.db').as_posix()}",
        "AUDIO_DIR": audio_dir.as_posix(),
    }
    ctx = Ctx(
        env={**OFFLINE_ENV, **shared},
        work_dir=work_dir,
        audio_dir=audio_dir,
    )
    degraded_env = {**DEGRADED_ENV, **shared}
    novoice_env = {**NOVOICE_ENV, **shared}

    print("P2 A/B/C/F/G 类验收开始（三个离线实例，全程不联网）")
    print(f"  主实例   http://127.0.0.1:{TEMP_PORT}/api（离线替身）")
    print(f"  半配实例 http://127.0.0.1:{DEGRADED_PORT}/api（有 Key 缺地址 → 40201）")
    print(f"  关闭实例 http://127.0.0.1:{NOVOICE_PORT}/api（VOICE_ENABLED=false）")
    print(f"  临时库   {work_dir / 'accept.db'}")
    print(f"  音频目录 {audio_dir}")
    print()

    report = Report()
    servers: list[Any] = []
    try:
        ok, why = prepare_database(ctx)
        if not ok:
            print(f"  临时库没准备好：\n{why}")
            return 2
        for port, name, env in (
            (TEMP_PORT, "backend.log", ctx.env),
            (DEGRADED_PORT, "degraded.log", degraded_env),
            (NOVOICE_PORT, "novoice.log", novoice_env),
        ):
            proc = start_server(ctx, port, name, env)
            if proc is None:
                return 2
            servers.append(proc)

        _guard(report, "音色与试听", check_voices, ctx)
        _guard(report, "单句合成", check_tts, ctx)
        _guard(report, "生成与整课预合成", check_generation, ctx)
        _guard(report, "音色切换", check_switch_voice, ctx)
        _guard(report, "讲稿改动失效", check_invalidation, ctx)
        _guard(report, "识别与落盘", check_asr_and_privacy, ctx)
        # 实时语音排在删课**之前**：它要断言「一整轮问答下来音频目录一个文件
        # 都没多」，而目录里得有东西，这句话才有分量
        _guard(report, "实时语音", check_realtime, ctx)
        _guard(report, "用量", check_usage, ctx)
        _guard(report, "删课清理", check_purge, ctx)
        _guard(report, "降级（半配实例）", check_degraded, ctx)
        _guard(report, "关闭开关（关闭实例）", check_disabled, ctx)
        _guard(report, "安全", check_security, ctx)
        _guard(report, "前端", check_frontend, ctx)
        _guard(report, "委托用例", check_delegated, ctx)
        _guard(report, "P0/P1 回归", check_suites, ctx)
        _guard(report, "离线跑不了的条目", check_unreachable, ctx)

        passed = sum(1 for row in report.rows if row[2] == "PASS")
        skipped = sum(1 for row in report.rows if row[2] == "SKIP")
        report.ok(
            "P2-G2",
            "scripts/accept_p2.py 用 Mock 跑通播放器与降级链路",
            f"以上 {passed} 条在离线替身上通过、{skipped} 条按 §7 的分工记跳过"
            "（要真上游或人耳）；三个实例全程未联网、未读 .env",
        )
    finally:
        if not args.keep:
            print()
            print("  正在关闭三个临时后端…")
            for proc in servers:
                stop(proc)
            shutil.rmtree(work_dir, ignore_errors=True)
        else:
            print(f"\n  三个临时后端还在 :{TEMP_PORT} / :{DEGRADED_PORT} / :{NOVOICE_PORT}（--keep）")
            print(f"  临时库 {work_dir}")

    return report.summary()


if __name__ == "__main__":
    sys.exit(main())
