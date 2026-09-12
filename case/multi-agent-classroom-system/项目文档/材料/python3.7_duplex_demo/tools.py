from __future__ import annotations

import asyncio
import functools
import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Dict, List


TOOL_NAME_VOLC_SEARCH = "volc_search"
TOOL_NAME_EXIT = "detect_exit_intent"
SEARCH_API_URL = "https://open.feedcoopapi.com/search_api/web_search"

# daemon 线程池，进程退出时不会阻塞解释器。
_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="tooldemo")


@dataclass
class FunctionCallItem:
    call_id: str
    name: str
    arguments: str


def build_tools() -> List[Dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": TOOL_NAME_VOLC_SEARCH,
            "description": (
                "Search the internet for up-to-date information. Use this tool when the user asks for "
                "current, factual, or web-based information. If the user's request depends on location, "
                "such as nearby places, local weather, local news, traffic, restaurants, stores, hospitals, "
                "events, or local services, and the location is not available in the conversation context, "
                "do not call this tool. Ask the user for their city, district, address, or current location first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "array"},
                },
                "required": ["query"],
            },
        },
        {
            "type": "function",
            "name": TOOL_NAME_EXIT,
            "description": (
                "用于识别用户是否明确表达结束、退出当前对话的意图。仅当用户明确提出终止会话、"
                "结束交互、关闭对话时，才可调用此工具。正向触发关键词包含但不限于：中文类（退出、结束、"
                "关闭、不聊了、到此为止、终止对话、再见、拜拜、结束吧、挂了、退下、滚蛋、滚下去、停止对话、"
                "结束聊天、退了、结束会话）、英文类（exit、close、end、quit、stop）。注意：用户仅切换话题、"
                "暂停讨论、稍后再聊、吐槽抱怨但未明确要求结束对话时，严禁调用此工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string"},
                },
                "required": ["reason"],
            },
        },
    ]


async def run_tool(item: FunctionCallItem, search_api_key: str) -> str:
    if item.name in (TOOL_NAME_VOLC_SEARCH, "Search"):
        return await run_volc_search(item.arguments, search_api_key)
    if item.name == TOOL_NAME_EXIT:
        return run_exit_intent(item.arguments)
    return f"{item.name}工具未注册"


def parse_queries(arguments: str) -> List[str]:
    if not arguments:
        return []
    try:
        data = json.loads(arguments)
    except json.JSONDecodeError:
        return []
    query = data.get("query")
    if isinstance(query, str) and query:
        return [query]
    if isinstance(query, list):
        return [str(q) for q in query if str(q)]
    queries = data.get("queries")
    if isinstance(queries, list):
        return [str(q) for q in queries if str(q)]
    return []


async def run_volc_search(arguments: str, search_api_key: str) -> str:
    queries = parse_queries(arguments)
    if not queries:
        return "volc_search参数解析失败"
    if not search_api_key:
        return "volcSearchAPIKey is required for volc_search"

    tasks = [to_thread(search_api_key_client, search_api_key, q) for q in queries]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    success: List[Any] = []
    for query, result in zip(queries, results):
        if isinstance(result, Exception):
            print(f"[FC] volc search fail, query={query}, err={result}")
            continue
        success.append(result)
    if not success:
        return "volc_search工具调用失败"
    if len(success) == 1:
        return json.dumps({"result": success[0]}, ensure_ascii=False)
    return json.dumps({"results": success}, ensure_ascii=False)


def run_exit_intent(arguments: str) -> str:
    # 模型仅在确认用户要退出时才会调用此工具，因此被调用即视为退出。
    return "退出成功"


def search_api_key_client(api_key: str, query: str) -> Dict[str, Any]:
    if not api_key or not query:
        raise ValueError("invalid request params")
    body = json.dumps(
        {
            "Query": query,
            "SearchType": "web",
            "Count": 10,
            "Filter": {
                "NeedContent": False,
                "NeedUrl": True,
            },
            "NeedSummary": True,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        SEARCH_API_URL,
        data=body,
        method="POST",
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            payload = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"search api status={e.code}, body={detail}") from e
    return json.loads(payload.decode("utf-8"))


async def to_thread(func, *args, **kwargs):
    # 使用独立线程池执行阻塞调用，避免默认 executor 的线程
    # 在解释器退出时被 join 而导致进程卡死（Python 3.7 无 shutdown_default_executor）。
    loop = asyncio.get_event_loop()
    call = functools.partial(func, *args, **kwargs)
    return await loop.run_in_executor(_EXECUTOR, call)


def shutdown_executor() -> None:
    # 进程退出前调用，关闭工具线程池，避免遗留线程阻塞解释器退出。
    _EXECUTOR.shutdown(wait=False)
