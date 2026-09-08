import hashlib
import json
import os
from pathlib import Path
import tempfile
import time

from openai import OpenAI


class LLMNotConfiguredError(RuntimeError):
    """Raised when no usable LLM API key is available."""


PROVIDER_DEFAULTS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "env_key": "DEEPSEEK_API_KEY",
        "env_model": "DEEPSEEK_MODEL",
        "label": "DeepSeek",
    },
    "openai": {
        "base_url": None,
        "model": "gpt-5-mini",
        "env_key": "OPENAI_API_KEY",
        "env_model": "OPENAI_MODEL",
        "label": "OpenAI",
    },
    "custom": {
        "base_url": "",
        "model": "",
        "env_key": "CUSTOM_LLM_API_KEY",
        "env_model": "CUSTOM_LLM_MODEL",
        "label": "Custom",
    },
}

SYSTEM_PROMPT = "You are a careful academic research assistant."
CACHE_VERSION = "llm-cache-v1"


def _load_dotenv_once():
    env_path = Path(__file__).resolve().parents[1] / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _config_value(config, key, default=""):
    if not config:
        return default
    if isinstance(config, dict):
        value = config.get(key, default)
    else:
        value = getattr(config, key, default)
    return value if value is not None else default


def resolve_llm_settings(config=None):
    _load_dotenv_once()

    provider = (_config_value(config, "provider", "deepseek") or "deepseek").lower()
    defaults = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS["custom"])

    api_key = _config_value(config, "api_key", "").strip()
    if not api_key:
        api_key = os.getenv(defaults["env_key"], "")

    if not api_key:
        raise LLMNotConfiguredError(
            f"{defaults['label']} API key is not configured. Enter it in the UI "
            f"or set {defaults['env_key']} in .env."
        )

    model = _config_value(config, "model", "").strip()
    if not model:
        model = os.getenv(defaults["env_model"], defaults["model"])
    if not model:
        raise LLMNotConfiguredError("LLM model is not configured.")

    base_url = _config_value(config, "base_url", "").strip()
    if not base_url:
        # 兼容 OpenAI 兼容代理：优先环境变量 OPENAI_BASE_URL，其次 provider 默认
        base_url = os.getenv("OPENAI_BASE_URL", "") or defaults["base_url"]

    return {
        "provider": provider,
        "api_key": api_key,
        "model": model,
        "base_url": base_url,
    }


def invoke_llm(prompt, config=None):
    settings = resolve_llm_settings(config)
    cache_key = _cache_key(prompt, settings)
    cached = _read_cache(cache_key)
    if cached:
        print(f"[LLM] local response cache hit: {cache_key[:12]}")
        return cached

    client_kwargs = {"api_key": settings["api_key"]}
    if settings["base_url"]:
        client_kwargs["base_url"] = settings["base_url"]

    client = OpenAI(**client_kwargs)
    request = {
        "model": settings["model"],
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }
    # 注：不附加非标准 prompt_cache_key 参数，确保与任意 OpenAI 兼容代理兼容；
    # 去重与降本由本地响应缓存（_read_cache/_write_cache）承担。

    print(f"[LLM] local response cache miss: {cache_key[:12]}")
    result = client.chat.completions.create(**request)
    _log_provider_cache_usage(result)
    content = result.choices[0].message.content or ""
    _write_cache(cache_key, content, settings)
    return content


def _cache_key(prompt, settings):
    payload = {
        "version": CACHE_VERSION,
        "provider": settings["provider"],
        "base_url": settings["base_url"] or "",
        "model": settings["model"],
        "system": SYSTEM_PROMPT,
        "temperature": 0.2,
        "prompt": prompt,
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _cache_dir():
    root = Path(__file__).resolve().parents[1]
    configured = os.getenv("LLM_CACHE_DIR", "").strip()
    return Path(configured) if configured else root / "runtime_cache" / "llm"


def _cache_enabled():
    return os.getenv("LLM_RESPONSE_CACHE", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _read_cache(cache_key):
    if not _cache_enabled():
        return ""

    path = _cache_dir() / f"{cache_key}.json"
    if not path.exists():
        return ""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[LLM] failed to read local cache {cache_key[:12]}: {exc}")
        return ""

    return data.get("content", "")


def _write_cache(cache_key, content, settings):
    if not _cache_enabled() or not content:
        return

    directory = _cache_dir()
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "created_at": int(time.time()),
        "provider": settings["provider"],
        "model": settings["model"],
        "content": content,
    }

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=directory,
            delete=False,
            suffix=".tmp",
        ) as file:
            tmp_path = Path(file.name)
            json.dump(payload, file, ensure_ascii=False)
        tmp_path.replace(directory / f"{cache_key}.json")
    except Exception as exc:
        print(f"[LLM] failed to write local cache {cache_key[:12]}: {exc}")
        if tmp_path and tmp_path.exists():
            tmp_path.unlink(missing_ok=True)


def _log_provider_cache_usage(result):
    usage = getattr(result, "usage", None)
    if not usage:
        return

    prompt_tokens = _usage_value(usage, "prompt_tokens")
    cached_tokens = (
        _usage_value(usage, "prompt_tokens_details.cached_tokens")
        or _usage_value(usage, "prompt_cache_hit_tokens")
    )
    miss_tokens = _usage_value(usage, "prompt_cache_miss_tokens")

    parts = []
    if prompt_tokens is not None:
        parts.append(f"prompt_tokens={prompt_tokens}")
    if cached_tokens is not None:
        parts.append(f"provider_cached_tokens={cached_tokens}")
    if miss_tokens is not None:
        parts.append(f"provider_cache_miss_tokens={miss_tokens}")

    if parts:
        print("[LLM] " + ", ".join(parts))


def _usage_value(obj, dotted_path):
    current = obj
    for part in dotted_path.split("."):
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
    return current
