from __future__ import annotations

import asyncio
import base64
import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

import websockets

from config import DemoConfig
from tools import FunctionCallItem, build_tools, run_tool


TYPE_SESSION_CREATE = "session.create"
TYPE_SESSION_UPDATE = "session.update"
TYPE_SESSION_CLOSE = "session.close"
TYPE_INPUT_AUDIO_BUFFER_APPEND = "input_audio_buffer.append"
TYPE_INPUT_AUDIO_BUFFER_COMMIT = "input_audio_buffer.commit"
TYPE_SPEECH_TEXT_BUFFER_APPEND = "speech_text_buffer.append"
TYPE_SPEECH_TEXT_BUFFER_COMMIT = "speech_text_buffer.commit"
TYPE_SPEECH_TEXT_BUFFER_REPLACEMENT_APPEND = "speech_text_buffer.replacement.append"
TYPE_SPEECH_TEXT_BUFFER_REPLACEMENT_COMMIT = "speech_text_buffer.replacement.commit"
TYPE_CONVERSATION_ITEM_CREATE = "conversation.item.create"
TYPE_CONVERSATION_ITEM_UPDATE = "conversation.item.update"
TYPE_CONVERSATION_ITEM_RETRIEVE = "conversation.item.retrieve"
TYPE_CONVERSATION_ITEM_DELETE = "conversation.item.delete"

TYPE_SESSION_CREATED = "session.created"
TYPE_SESSION_UPDATED = "session.updated"
TYPE_SESSION_CLOSED = "session.closed"
TYPE_INPUT_AUDIO_BUFFER_COMMITTED = "input_audio_buffer.committed"
TYPE_TRANSCRIPTION_STARTED = "conversation.item.input_audio_transcription.started"
TYPE_TRANSCRIPTION_DELTA = "conversation.item.input_audio_transcription.delta"
TYPE_TRANSCRIPTION_COMPLETED = "conversation.item.input_audio_transcription.completed"
TYPE_TRANSCRIPTION_FAILED = "conversation.item.input_audio_transcription.failed"
TYPE_RESPONSE_OUTPUT_TEXT_DELTA = "response.output_text.delta"
TYPE_RESPONSE_OUTPUT_TEXT_DONE = "response.output_text.done"
TYPE_RESPONSE_OUTPUT_AUDIO_STARTED = "response.output_audio.started"
TYPE_RESPONSE_OUTPUT_AUDIO_DELTA = "response.output_audio.delta"
TYPE_RESPONSE_OUTPUT_AUDIO_DONE = "response.output_audio.done"
TYPE_CONVERSATION_ITEM_ADDED = "conversation.item.added"
TYPE_CONVERSATION_ITEM_RETRIEVED = "conversation.item.retrieved"
TYPE_CONVERSATION_ITEM_UPDATED = "conversation.item.updated"
TYPE_CONVERSATION_ITEM_DELETED = "conversation.item.deleted"
TYPE_RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE = "response.function_call_arguments.done"
TYPE_RESPONSE_CANCELED = "response.canceled"
TYPE_RESPONSE_DONE = "response.done"
TYPE_ERROR = "error"


class RealtimeClient:
    def __init__(self, cfg: DemoConfig):
        self.cfg = cfg
        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self.session_id = str(uuid.uuid4())
        self.dialog_id = ""
        self._event_id = 0
        self._write_lock = asyncio.Lock()

    def new_event_id(self) -> str:
        self._event_id += 1
        return f"event_{self._event_id}"

    async def connect(self) -> None:
        headers = {
            # 二选一
            # "Authorization": "Bearer " + self.cfg.api_key,
            "X-Api-Key": self.cfg.api_key,
        }
        print(f"connect url={self.cfg.endpoint_url}")
        self.ws = await websockets.connect(
            self.cfg.endpoint_url,
            extra_headers=headers,
            ping_interval=None,
        )
        logid = self.ws.response_headers.get("X-Tt-Logid")
        if logid:
            print(f"dialog server response logid: {logid}")

    async def close(self) -> None:
        if self.ws is None:
            return
        try:
            await self.session_close()
            # 发送 session.close 后等待服务端回 session.closed（带超时）。
            # 接收循环此时已退出，这里负责读取剩余下行帧。
            await self._wait_session_closed()
        except Exception as e:
            print(f"session.close error: {e}")
        await self.ws.close()

    async def _wait_session_closed(self, timeout: float = 3.0) -> None:
        loop = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        while True:
            remaining = deadline - loop.time()
            if remaining <= 0:
                print("[session.closed] not received before timeout")
                return
            try:
                event = await asyncio.wait_for(self.recv_event(), timeout=remaining)
            except asyncio.TimeoutError:
                print("[session.closed] not received before timeout")
                return
            except Exception:
                return
            if event.get("type") == TYPE_SESSION_CLOSED:
                print("[session.closed]")
                return

    async def send_event(self, event: Dict[str, Any]) -> None:
        if self.ws is None:
            raise RuntimeError("websocket is not connected")
        payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        if event.get("type") != TYPE_INPUT_AUDIO_BUFFER_APPEND:
            print(f"[send event] {payload}")
        async with self._write_lock:
            await self.ws.send(payload)

    async def recv_event(self) -> Dict[str, Any]:
        if self.ws is None:
            raise RuntimeError("websocket is not connected")
        frame = await self.ws.recv()
        if isinstance(frame, bytes):
            frame = frame.decode("utf-8")
        event = json.loads(frame)
        event_type = event.get("type")
        if event_type != TYPE_RESPONSE_OUTPUT_AUDIO_DELTA:
            print(f"[recv event] type={event_type} frame={frame[:500]}")
        return event

    def build_session_config(self) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        session = {
            "id": self.session_id,
            "model": self.cfg.model,
            "instructions": self.cfg.instructions,
            "audio": {
                "input": {
                    "format": {"type": self.cfg.asr_format, "rate": 16000},
                },
                "output": {
                    "format": {"type": self.cfg.tts_format, "rate": 24000},
                    "voice": self.cfg.speaker,
                },
            },
            "tools": build_tools(),
        }
        extension = {
            "asr": {"extra": {}},
            "tts": {"extra": {}},
            "dialog": {
                "location": {
                    "longitude": 114.305556,
                    "latitude": 22.62,
                    "city": "深圳",
                    "country": "中国",
                    "province": "广东省",
                    "district": "南山区",
                    "town": "深圳",
                    "country_code": "CN",
                    "address": "中国深圳市南山区",
                },
                "extra": {
                    "audit_response": "抱歉，这个问题我无法回答，你可以换个其他话题，我会尽力为你提供帮助。",
                    "enable_loudness_norm": True,
                    "enable_music": False,
                },
            },
        }
        return session, extension

    async def session_create(self) -> None:
        session, extension = self.build_session_config()
        await self.send_event(
            {
                "type": TYPE_SESSION_CREATE,
                "event_id": self.new_event_id(),
                "session": session,
                "extension": extension,
            }
        )
        while True:
            event = await self.recv_event()
            event_type = event.get("type")
            if event_type == TYPE_SESSION_CREATED:
                self.dialog_id = event.get("session", {}).get("id", "")
                print(f"Session created, dialog_id={self.dialog_id}")
                return
            if event_type == TYPE_ERROR:
                raise RuntimeError(f"session.create error: {event}")
            print(f"Ignore event before session.created: {event_type}")

    async def session_update(self, session: Dict[str, Any], extension: Optional[Dict[str, Any]] = None) -> None:
        if "id" not in session:
            session["id"] = self.session_id
        await self.send_event(
            {
                "type": TYPE_SESSION_UPDATE,
                "event_id": self.new_event_id(),
                "session": session,
                "extension": extension,
            }
        )

    async def session_close(self) -> None:
        await self.send_event({"type": TYPE_SESSION_CLOSE, "event_id": self.new_event_id()})

    async def input_audio_append(self, data: bytes) -> None:
        await self.send_event(
            {
                "type": TYPE_INPUT_AUDIO_BUFFER_APPEND,
                "audio": base64.b64encode(data).decode("ascii"),
            }
        )

    async def input_audio_commit(self) -> None:
        await self.send_event({"type": TYPE_INPUT_AUDIO_BUFFER_COMMIT, "event_id": self.new_event_id()})

    async def speech_text_append(self, speech_id: str, text: str) -> None:
        await self.send_event(
            {
                "type": TYPE_SPEECH_TEXT_BUFFER_APPEND,
                "event_id": self.new_event_id(),
                "speech_id": speech_id,
                "text": text,
            }
        )

    async def speech_text_commit(self, speech_id: str, text: str) -> None:
        await self.send_event(
            {
                "type": TYPE_SPEECH_TEXT_BUFFER_COMMIT,
                "event_id": self.new_event_id(),
                "speech_id": speech_id,
                "text": text,
            }
        )

    async def speech_text_replacement_append(self, speech_id: str, text: str) -> None:
        await self.send_event(
            {
                "type": TYPE_SPEECH_TEXT_BUFFER_REPLACEMENT_APPEND,
                "event_id": self.new_event_id(),
                "speech_id": speech_id,
                "text": text,
            }
        )

    async def speech_text_replacement_commit(self, speech_id: str, text: str) -> None:
        await self.send_event(
            {
                "type": TYPE_SPEECH_TEXT_BUFFER_REPLACEMENT_COMMIT,
                "event_id": self.new_event_id(),
                "speech_id": speech_id,
                "text": text,
            }
        )

    async def conversation_item_create(self, items: List[Dict[str, Any]]) -> None:
        await self.send_event(
            {
                "type": TYPE_CONVERSATION_ITEM_CREATE,
                "event_id": self.new_event_id(),
                "items": items,
            }
        )

    async def conversation_item_update(self, items: List[Dict[str, Any]]) -> None:
        await self.send_event(
            {
                "type": TYPE_CONVERSATION_ITEM_UPDATE,
                "event_id": self.new_event_id(),
                "items": items,
            }
        )

    async def conversation_item_retrieve(self, items: Optional[List[Dict[str, Any]]] = None) -> None:
        await self.send_event(
            {
                "type": TYPE_CONVERSATION_ITEM_RETRIEVE,
                "event_id": self.new_event_id(),
                "items": items or [],
            }
        )

    async def conversation_item_delete(self, items: List[Dict[str, Any]]) -> None:
        await self.send_event(
            {
                "type": TYPE_CONVERSATION_ITEM_DELETE,
                "event_id": self.new_event_id(),
                "items": items,
            }
        )

    async def handle_function_call(self, event: Dict[str, Any]) -> None:
        raw_items = event.get("items") or []
        calls = [
            FunctionCallItem(
                call_id=str(item.get("call_id", "")),
                name=str(item.get("name", "")),
                arguments=str(item.get("arguments", "")),
            )
            for item in raw_items
        ]
        if not calls:
            print("[FC] function_call_arguments.done with empty items")
            return
        outputs = await asyncio.gather(
            *(run_tool(call, self.cfg.search_api_key) for call in calls),
            return_exceptions=True,
        )
        response_items: List[Dict[str, Any]] = []
        for call, output in zip(calls, outputs):
            if isinstance(output, Exception):
                print(f"[FC] tool call fail, call_id={call.call_id}, err={output}")
                output_text = f"{call.name}工具调用失败"
            else:
                output_text = output
            response_items.append(
                {
                    "type": "message",
                    "role": "tool",
                    "call_id": call.call_id,
                    "content": [{"type": "input_text", "text": output_text}],
                }
            )
        print(f"[FC] function_call_output, items={len(response_items)}")
        await self.conversation_item_create(response_items)
