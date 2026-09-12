"""API Key 加密落库与脱敏展示（AGENTS.md §4.1 / §24）。

- 落库：Fernet（AES-128-CBC + HMAC），带随机 IV，同一明文两次密文不同。
- 展示：mask() 只保留前缀与后 4 位，供设置页回显。
- 指纹：fingerprint() 用于判断「Key 是否变过」，不可逆。
- 密钥来源：环境变量 FERNET_KEY，绝不硬编码。
"""

from __future__ import annotations

import binascii
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app


class CryptoError(Exception):
    """密钥缺失、格式非法或密文被篡改。"""


# 已知的 Key 前缀，按长度降序匹配，让设置页能一眼看出是哪家的 Key
_KNOWN_PREFIXES = tuple(
    sorted(
        (
            "sk-proj-",
            "sk-ant-",
            "sk-or-",
            "sk-",
            "Bearer ",
            "bearer ",
            "Bearer-",
            "bearer-",
            "volc-",
            "ark-",
            "gsk_",
            "ak-",
        ),
        key=len,
        reverse=True,
    )
)

# 短于该长度的 Key 一律整体打码，避免「掩了等于没掩」
_MIN_LEN_FOR_PARTIAL_MASK = 8


def _get_fernet() -> Fernet:
    try:
        raw = current_app.config.get("FERNET_KEY") or ""
    except RuntimeError as exc:  # 没有应用上下文
        raise CryptoError("缺少应用上下文，无法读取 FERNET_KEY") from exc

    if not raw:
        raise CryptoError(
            "未配置 FERNET_KEY：请在 backend/.env 中生成一个并重启服务"
            "（python -c \"from cryptography.fernet import Fernet;"
            " print(Fernet.generate_key().decode())\"）"
        )
    try:
        return Fernet(raw.encode("utf-8") if isinstance(raw, str) else raw)
    except (ValueError, binascii.Error, TypeError) as exc:
        raise CryptoError("FERNET_KEY 不是合法的 Fernet 密钥（需 32 字节 urlsafe base64）") from exc


def encrypt(plaintext: str) -> str:
    """明文 → 密文（str）。空值直接报错，避免把空 Key 落库。"""
    if plaintext is None or str(plaintext) == "":
        raise CryptoError("待加密内容不能为空")
    token = _get_fernet().encrypt(str(plaintext).encode("utf-8"))
    return token.decode("ascii")


def decrypt(token: str) -> str:
    """密文 → 明文。密文被篡改或不是本机密钥加密的，一律 CryptoError。"""
    if not token:
        raise CryptoError("待解密内容不能为空")
    try:
        raw = _get_fernet().decrypt(str(token).encode("ascii"))
    except (InvalidToken, binascii.Error, ValueError, UnicodeEncodeError) as exc:
        raise CryptoError("密文无效或已被篡改") from exc
    return raw.decode("utf-8")


def mask(value: str | None) -> str:
    """脱敏展示：sk-****1234。

    - None / 空串 → 空串（设置页显示「未配置」）
    - 过短 → 整体 ****
    - 其余 → 已知前缀原样保留 + **** + 后 4 位
    - 幂等：对已掩码的值再掩码结果不变
    """
    if not value:
        return ""

    text = str(value)
    if len(text) < _MIN_LEN_FOR_PARTIAL_MASK:
        return "****"

    for prefix in _KNOWN_PREFIXES:
        if text.startswith(prefix):
            return f"{prefix}****{text[-4:]}"

    return f"****{text[-4:]}"


def fingerprint(value: str | None) -> str:
    """Key 指纹：同一 Key 稳定、不同 Key 不同、不可逆。

    仅用于「凭据是否变更」的比对，不参与任何鉴权。
    """
    if not value:
        return ""

    salt = ""
    try:
        salt = str(current_app.config.get("SECRET_KEY") or "")
    except RuntimeError:
        salt = ""

    digest = hmac.new(salt.encode("utf-8"), str(value).encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()[:8]


def generate_key() -> str:
    """生成一个可用的 FERNET_KEY（供脚手架脚本 / 首次部署使用）。"""
    return Fernet.generate_key().decode("ascii")


def mask_config_keys(config: dict) -> dict:
    """把配置里所有疑似凭据的值打码，供 /api/settings 回显。"""
    sensitive = ("KEY", "TOKEN", "SECRET", "PASSWORD")
    result = {}
    for key, value in config.items():
        if any(marker in key.upper() for marker in sensitive) and isinstance(value, str):
            result[key] = mask(value)
        else:
            result[key] = value
    return result


__all__ = [
    "CryptoError",
    "_get_fernet",
    "decrypt",
    "encrypt",
    "fingerprint",
    "generate_key",
    "mask",
    "mask_config_keys",
]
