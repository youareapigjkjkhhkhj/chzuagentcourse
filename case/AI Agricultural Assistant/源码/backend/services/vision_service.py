from __future__ import annotations
import base64
import os
import time
from typing import Any, Optional, Tuple, Dict

from groq import Groq
from backend.core.config import settings
from backend.core.token_tracker import token_tracker

MAX_RETRIES = 3
RETRY_BACKOFF = (1, 2, 4)
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_VISION_PROMPT_CHARS = 2000


def _detect_mime(image_path: str) -> str:
    try:
        with open(image_path, "rb") as f:
            header = f.read(10)
    except Exception:
        return "unknown"

    if header.startswith(b"\x89PNG"):
        return "image/png"

    if header.startswith(b"\xFF\xD8"):
        return "image/jpeg"

    return "unknown"


def _normalize_output(output: Any) -> str:
    if output is None:
        return ""
    if isinstance(output, str):
        return output.strip()
    if isinstance(output, list):
        return "\n".join(_normalize_output(x) for x in output)
    if isinstance(output, dict):
        return "\n".join(f"{k}: {v}" for k, v in output.items())
    return str(output).strip()


def _get_vision_system_prompt() -> str:
    """Load vision system prompt from centralized prompts."""
    try:
        from backend.core.prompt_loader import get_prompt
        return get_prompt("pest_agent.vision_system")
    except Exception:
        return (
            "You are AgriGPT Vision, a multimodal agricultural image "
            "observation assistant.\n\n"
            "Your task is to describe ONLY what is clearly visible in the image.\n\n"
            "STRICT RULES:\n"
            "- Do NOT guess pests, diseases, or causes\n"
            "- Do NOT hallucinate unseen symptoms\n"
            "- Do NOT infer crop stage or health unless clearly visible\n"
            "- If uncertain, say so clearly\n\n"
            "ALLOWED:\n"
            "- Describe visible spots, discoloration, holes, insects, mold, wilting\n"
            "- Mention blur, poor lighting, or unclear image quality\n\n"
            "OUTPUT STYLE:\n"
            "- Bullet points\n"
            "- Simple, farmer-friendly language\n"
            "- No technical jargon unless unavoidable"
        )


def query_groq_image(
    image_path: str,
    prompt: str,
    request_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Tuple[str, Dict[str, int]]:
    """
    Vision model inference. Returns (content, usage_dict).
    """

    if not image_path or not os.path.exists(image_path):
        return "The image file was not found.", {"input_tokens": 0, "output_tokens": 0}

    if os.path.getsize(image_path) > MAX_IMAGE_BYTES:
        return "The image is too large. Please upload an image under 8MB.", {
            "input_tokens": 0,
            "output_tokens": 0,
        }

    mime = _detect_mime(image_path)
    if mime not in ("image/png", "image/jpeg"):
        return "Unsupported image format. Please upload a PNG or JPG image.", {
            "input_tokens": 0,
            "output_tokens": 0,
        }

    try:
        with open(image_path, "rb") as f:
            raw_bytes = f.read()
    except Exception:
        return "The image could not be read.", {"input_tokens": 0, "output_tokens": 0}

    if not raw_bytes:
        return "The image file appears to be empty.", {
            "input_tokens": 0,
            "output_tokens": 0,
        }

    if not isinstance(prompt, str):
        prompt = ""

    if len(prompt) > MAX_VISION_PROMPT_CHARS:
        prompt = prompt[:MAX_VISION_PROMPT_CHARS] + " [Prompt truncated]"

    image_b64 = base64.b64encode(raw_bytes).decode("utf-8")
    image_url = f"data:{mime};base64,{image_b64}"

    system_prompt = _get_vision_system_prompt()

    client = Groq(
        api_key=settings.GROQ_API_KEY,
        timeout=30,
    )

    for attempt in range(MAX_RETRIES):
        try:
            completion = client.chat.completions.create(
                model=settings.VISION_MODEL_NAME,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt.strip()},
                            {"type": "image_url", "image_url": {"url": image_url}},
                        ],
                    },
                ],
                max_tokens=900,
                temperature=0.3,
                top_p=1.0,
            )

            if not completion.choices:
                raise ValueError("No completion choices returned")
            first = completion.choices[0]
            msg = getattr(first, "message", None)
            content = getattr(msg, "content", None) if msg else None
            result = _normalize_output(content)

            input_tok = 0
            output_tok = 0
            if hasattr(completion, "usage") and completion.usage:
                input_tok = getattr(completion.usage, "input_tokens", 0) or 0
                output_tok = getattr(completion.usage, "output_tokens", 0) or 0

            if request_id or session_id:
                token_tracker.record(
                    input_tokens=input_tok,
                    output_tokens=output_tok,
                    model=settings.VISION_MODEL_NAME,
                    request_id=request_id,
                    session_id=session_id,
                )

            usage = {"input_tokens": input_tok, "output_tokens": output_tok}

            if not result or len(result) < 5:
                return (
                    "The image could not be analyzed clearly. "
                    "Please upload a clearer image.",
                    usage,
                )

            return result, usage

        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_BACKOFF[attempt])
                continue

            return (
                "The image could not be analyzed at this time. "
                "Please try again later.",
                {"input_tokens": 0, "output_tokens": 0},
            )

    return (
        "The image could not be analyzed at this time. Please try again later.",
        {"input_tokens": 0, "output_tokens": 0},
    )
