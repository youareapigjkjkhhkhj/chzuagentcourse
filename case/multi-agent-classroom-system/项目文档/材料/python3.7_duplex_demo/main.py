from __future__ import annotations

import argparse
import asyncio
import base64
import queue as thread_queue
import random
import signal
import threading
import uuid
from pathlib import Path
from typing import Optional

from config import DEFAULT_PCM, OGG_OPUS, PCM_S16LE, load_config
from tools import shutdown_executor
from realtime_client import (
    TYPE_CONVERSATION_ITEM_ADDED,
    TYPE_CONVERSATION_ITEM_DELETED,
    TYPE_CONVERSATION_ITEM_RETRIEVED,
    TYPE_CONVERSATION_ITEM_UPDATED,
    TYPE_ERROR,
    TYPE_INPUT_AUDIO_BUFFER_COMMITTED,
    TYPE_RESPONSE_CANCELED,
    TYPE_RESPONSE_DONE,
    TYPE_RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE,
    TYPE_RESPONSE_OUTPUT_AUDIO_DELTA,
    TYPE_RESPONSE_OUTPUT_AUDIO_DONE,
    TYPE_RESPONSE_OUTPUT_AUDIO_STARTED,
    TYPE_RESPONSE_OUTPUT_TEXT_DELTA,
    TYPE_RESPONSE_OUTPUT_TEXT_DONE,
    TYPE_SESSION_CLOSED,
    TYPE_SESSION_CREATED,
    TYPE_SESSION_UPDATED,
    TYPE_TRANSCRIPTION_COMPLETED,
    TYPE_TRANSCRIPTION_DELTA,
    TYPE_TRANSCRIPTION_FAILED,
    TYPE_TRANSCRIPTION_STARTED,
    RealtimeClient,
)

try:
    import pyaudio
except ImportError:  # pragma: no cover - optional runtime dependency
    pyaudio = None


SAMPLE_RATE = 16000
OUTPUT_SAMPLE_RATE = 24000
CHANNELS = 1
MIC_CHUNK = 320
FILE_CHUNK = 640


class DialogSession:
    def __init__(self, client: RealtimeClient, audio_file: str = ""):
        self.client = client
        self.audio_file = audio_file
        self.is_audio_file_input = bool(audio_file)
        self.output_audio = bytearray()
        self.output_audio_path = Path("output.pcm")
        self.running = True
        self.is_user_querying = False
        self.is_sending_greeting = False
        # 播放队列由事件循环写入、由播放线程消费，使用线程安全的 queue.Queue。
        self.audio_queue: "thread_queue.Queue" = thread_queue.Queue()
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.pyaudio = None
        self.output_stream = None
        self.input_stream = None
        # 麦克风采集 / 音频播放使用 daemon 线程，避免退出时阻塞解释器。
        self.mic_thread: Optional[threading.Thread] = None
        self.play_thread: Optional[threading.Thread] = None

    async def start(self) -> None:
        if not self.is_audio_file_input:
            self.ensure_realtime_audio_supported()
        await self.client.connect()
        await self.client.session_create()
        try:
            receiver = asyncio.create_task(self.receive_loop())
            if self.is_audio_file_input:
                sender = asyncio.create_task(self.send_audio_file())
                done, pending = await asyncio.wait(
                    {sender, receiver},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                for task in done:
                    await task
            else:
                self.loop = asyncio.get_event_loop()
                self.open_audio_devices()
                await self.send_greeting()
                self.start_audio_threads()
                try:
                    await receiver
                except asyncio.CancelledError:
                    pass
        finally:
            # 先停循环，确保采集 / 播放线程退出阻塞调用，再关闭音频设备。
            self.running = False
            self.audio_queue.put(None)
            self.join_audio_threads()
            self.cleanup_audio_devices()
            await self.client.close()
            if self.output_audio:
                self.output_audio_path.write_bytes(self.output_audio)
                print(f"saved output audio to {self.output_audio_path}")

    def ensure_realtime_audio_supported(self) -> None:
        if pyaudio is None:
            raise RuntimeError("pyaudio is required for microphone input and audio playback")
        if self.client.cfg.asr_format != DEFAULT_PCM:
            raise RuntimeError(f"unsupported microphone asr_format: {self.client.cfg.asr_format}")
        if self.client.cfg.tts_format not in (DEFAULT_PCM, PCM_S16LE):
            raise RuntimeError(f"unsupported realtime tts_format for playback: {self.client.cfg.tts_format}")

    def open_audio_devices(self) -> None:
        assert pyaudio is not None
        self.pyaudio = pyaudio.PyAudio()
        self.input_stream = self.pyaudio.open(
            format=pyaudio.paInt16,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=MIC_CHUNK,
        )
        output_format = pyaudio.paInt16 if self.client.cfg.tts_format == PCM_S16LE else pyaudio.paFloat32
        self.output_stream = self.pyaudio.open(
            format=output_format,
            channels=CHANNELS,
            rate=OUTPUT_SAMPLE_RATE,
            output=True,
            frames_per_buffer=1024,
        )

    def cleanup_audio_devices(self) -> None:
        for stream in (self.input_stream, self.output_stream):
            if stream is None:
                continue
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
        if self.pyaudio is not None:
            self.pyaudio.terminate()

    def start_audio_threads(self) -> None:
        self.mic_thread = threading.Thread(target=self.mic_worker, daemon=True)
        self.play_thread = threading.Thread(target=self.play_worker, daemon=True)
        self.mic_thread.start()
        self.play_thread.start()

    def join_audio_threads(self) -> None:
        # daemon 线程，join 仅做优雅等待；超时也不会阻塞解释器退出。
        for t in (self.mic_thread, self.play_thread):
            if t is not None:
                t.join(timeout=0.5)

    def mic_worker(self) -> None:
        if self.input_stream is None or self.loop is None:
            return
        while self.running:
            try:
                data = self.input_stream.read(MIC_CHUNK, exception_on_overflow=False)
            except Exception:
                break
            if not self.running:
                break
            try:
                fut = asyncio.run_coroutine_threadsafe(
                    self.client.input_audio_append(data), self.loop
                )
                fut.result(timeout=2)
            except Exception:
                break

    def play_worker(self) -> None:
        if self.output_stream is None:
            return
        while self.running:
            try:
                data = self.audio_queue.get(timeout=0.1)
            except thread_queue.Empty:
                continue
            if data is None:
                break
            try:
                self.output_stream.write(data)
            except Exception:
                break

    async def send_greeting(self) -> None:
        speech_id = str(uuid.uuid4())
        await self.client.speech_text_append(speech_id, "你好，")
        await self.client.speech_text_append(speech_id, "我是豆包")
        await self.client.speech_text_commit(speech_id, "很高兴为你服务。")

    async def send_audio_file(self) -> None:
        path = Path(self.audio_file)
        data = path.read_bytes()
        if path.suffix.lower() == ".wav":
            data = data[44:]
        pos = 0
        while self.running and pos < len(data):
            chunk = data[pos : pos + FILE_CHUNK]
            await self.client.input_audio_append(chunk)
            pos += len(chunk)
            await asyncio.sleep(0.02)
        while self.running:
            await self.client.input_audio_append(b"\x00" * FILE_CHUNK)
            await asyncio.sleep(0.02)

    async def receive_loop(self) -> None:
        while self.running:
            event = await self.client.recv_event()
            done = await self.handle_event(event)
            if done:
                return

    async def handle_event(self, event: dict) -> bool:
        event_type = event.get("type")
        if event_type in (TYPE_SESSION_CREATED, TYPE_SESSION_UPDATED):
            session_id = event.get("session", {}).get("id")
            if session_id:
                self.client.dialog_id = session_id
            print(f"[{event_type}] dialog_id={self.client.dialog_id}")

        elif event_type == TYPE_SESSION_CLOSED:
            print("[session.closed]")
            return True

        elif event_type == TYPE_INPUT_AUDIO_BUFFER_COMMITTED:
            print("[input_audio_buffer.committed]")

        elif event_type == TYPE_TRANSCRIPTION_STARTED:
            self.is_user_querying = True
            clear_queue(self.audio_queue)
            print("[transcription.started]")

        elif event_type == TYPE_TRANSCRIPTION_DELTA:
            print(f"[ASR delta] item={event.get('item_id')} delta={event.get('delta')}")

        elif event_type == TYPE_TRANSCRIPTION_COMPLETED:
            self.is_user_querying = False
            transcript = event.get("transcript") or event.get("text")
            print(f"[ASR completed] item={event.get('item_id')} transcript={transcript}")
            if random.randint(0, 99999) % 100 == 0:
                asyncio.create_task(self.trigger_intervention())

        elif event_type == TYPE_TRANSCRIPTION_FAILED:
            print(f"[ASR failed] {event}")

        elif event_type == TYPE_RESPONSE_OUTPUT_TEXT_DELTA:
            print(f"[Chat delta] resp={event.get('response_id')} delta={event.get('delta')}")

        elif event_type == TYPE_RESPONSE_OUTPUT_TEXT_DONE:
            print(f"[Chat done] resp={event.get('response_id')} text={event.get('text')}")

        elif event_type == TYPE_RESPONSE_OUTPUT_AUDIO_STARTED:
            print(f"[TTS start] resp={event.get('response_id')} tts_type={event.get('tts_type')}")
            if self.is_sending_greeting and event.get("tts_type") in ("chat_tts_text", "external_rag"):
                clear_queue(self.audio_queue)
                self.is_sending_greeting = False

        elif event_type == TYPE_RESPONSE_OUTPUT_AUDIO_DELTA:
            delta = event.get("delta") or ""
            try:
                data = base64.b64decode(delta)
            except Exception as e:
                print(f"[TTS delta] base64 decode error: {e}")
                return False
            if not self.is_sending_greeting and not self.is_audio_file_input:
                self.audio_queue.put(data)
            self.output_audio.extend(data)

        elif event_type == TYPE_RESPONSE_OUTPUT_AUDIO_DONE:
            print(f"[TTS done] resp={event.get('response_id')} status={event.get('status_code')}")
            if self.is_audio_file_input:
                return True

        elif event_type == TYPE_RESPONSE_FUNCTION_CALL_ARGUMENTS_DONE:
            asyncio.create_task(self.client.handle_function_call(event))

        elif event_type in (
            TYPE_CONVERSATION_ITEM_ADDED,
            TYPE_CONVERSATION_ITEM_RETRIEVED,
            TYPE_CONVERSATION_ITEM_UPDATED,
        ):
            for item in event.get("items") or []:
                print(f"[{event_type}] item_id={item.get('id')} role={item.get('role')}")

        elif event_type == TYPE_CONVERSATION_ITEM_DELETED:
            for item in event.get("items") or []:
                print(f"[{event_type}] item_id={item.get('id')}")

        elif event_type == TYPE_RESPONSE_CANCELED:
            print(f"[response.canceled] event_id={event.get('event_id')}")

        elif event_type == TYPE_RESPONSE_DONE:
            print(f"[response.done] {event}")

        elif event_type == TYPE_ERROR:
            print(f"[error] {event.get('error')}")
            return True

        else:
            print(f"[unhandled event] type={event_type} {event}")
        return False

    async def trigger_intervention(self) -> None:
        self.is_sending_greeting = True
        await asyncio.sleep(1)
        print("hit replacement intervention, start sending...")
        speech_id = str(uuid.uuid4())
        await self.client.speech_text_replacement_append(speech_id, "这是干预回复，")
        await self.client.speech_text_replacement_commit(speech_id, "我来帮你换个说法。")


def clear_queue(q: "thread_queue.Queue") -> None:
    while True:
        try:
            q.get_nowait()
        except thread_queue.Empty:
            return


async def async_main() -> None:
    parser = argparse.ArgumentParser(description="Realtime duplex dialogue JSON protocol Python demo")
    parser.add_argument("--config", default="config.toml", help="Path to config.toml")
    parser.add_argument("--audio", default="", help="Audio file input. If empty, use microphone input.")
    args = parser.parse_args()

    cfg = load_config(args.config)
    if args.audio:
        cfg.asr_format = DEFAULT_PCM
    if not cfg.api_key:
        raise RuntimeError("auth.api_key is required in config.toml")
    if cfg.tts_format == OGG_OPUS and not args.audio:
        raise RuntimeError("Python demo cannot play ogg_opus directly. Use tts_format = \"pcm_s16le\" for microphone mode.")

    client = RealtimeClient(cfg)
    session = DialogSession(client, audio_file=args.audio)
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def stop() -> None:
        session.running = False
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop)
        except NotImplementedError:
            pass

    task = asyncio.create_task(session.start())
    stop_task = asyncio.create_task(stop_event.wait())
    done, pending = await asyncio.wait({task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
    if stop_task in done:
        session.running = False
        task.cancel()
    for pending_task in pending:
        pending_task.cancel()
    # 等待 start 真正收尾（含音频线程 join、session.close），避免退出时仍有阻塞线程。
    try:
        await task
    except asyncio.CancelledError:
        pass
    finally:
        shutdown_executor()


if __name__ == "__main__":
    asyncio.run(async_main())
