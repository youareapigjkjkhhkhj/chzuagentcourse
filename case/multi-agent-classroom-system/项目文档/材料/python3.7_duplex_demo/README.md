# Realtime Duplex Dialog Python Demo

This demo connects to the realtime duplex dialogue WebSocket API with the same JSON event protocol used by the Go demo.

## Requirements

- Python 3.7 or later
- `websockets`
- `tomli` on Python versions earlier than 3.11
- `PyAudio` only when using microphone input and realtime playback

Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

For microphone input and local playback, install PyAudio separately:

```bash
python3 -m pip install PyAudio
```

## Configuration

Edit `config.toml` before running:

- `auth.api_key`: realtime dialogue API key.
- `search.api_key`: Volcano Engine Search API key used by the `volc_search` function-call example.
- `session.asr_format`: optional. Empty means the code default is used.
- `session.tts_format`: optional. Empty means the code default is used.

The demo keeps the two auth header choices in `realtime_client.py`; `X-Api-Key` is enabled by default.

## Run

Audio file input mode:

```bash
python3 main.py --audio ./whoareyou.wav
```

Microphone input mode:

```bash
python3 main.py
```

Microphone mode sends PCM audio. Set `session.asr_format = "pcm"` and use `session.tts_format = "pcm_s16le"` or `"pcm"` if you want local playback.

## Included Examples

- `session.create` and `session.update`
- `input_audio_buffer.append`
- streaming greeting through `speech_text_buffer.*`
- probabilistic intervention through `speech_text_buffer.replacement.*`
- conversation item create/update/retrieve/delete helpers with unified `items` arrays
- function calling with batched `conversation.item.create` tool outputs
- Volcano Engine Search API client in `tools.py`
