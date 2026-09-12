"""密钥加密与脱敏测试（AGENTS.md §4.1 / P0-B1）。

两条硬要求：
1. 落库的 API Key 必须是密文，且同一明文两次加密结果不同（Fernet 带随机 IV）。
2. 任何对外展示、日志、异常里都不得出现明文 Key。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_encrypt_decrypt_roundtrip(app):
    from app.common.crypto import decrypt, encrypt

    with app.app_context():
        plain = "sk-9f2c4a1b7e8d4f6a0011223344556677"
        token = encrypt(plain)

        assert token != plain
        assert plain not in token
        assert decrypt(token) == plain


def test_encrypt_is_nondeterministic(app):
    """两次加密同一明文必须得到不同密文（随机 IV），否则可被比对。"""
    from app.common.crypto import encrypt

    with app.app_context():
        plain = "sk-abcdef0123456789"
        assert encrypt(plain) != encrypt(plain)


def test_decrypt_rejects_tampered_token(app):
    from app.common.crypto import CryptoError, decrypt

    with app.app_context():
        from app.common.crypto import encrypt

        token = encrypt("sk-original")
        tampered = token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB")

        with pytest.raises(CryptoError):
            decrypt(tampered)


def test_decrypt_rejects_garbage(app):
    from app.common.crypto import CryptoError, decrypt

    with app.app_context(), pytest.raises(CryptoError):
        decrypt("这不是一个密文")


def test_encrypt_empty_string_raises(app):
    from app.common.crypto import CryptoError, encrypt

    with app.app_context(), pytest.raises(CryptoError):
        encrypt("")


def test_mask_keeps_prefix_and_tail_only(app):
    """掩码规则：sk-****1234 —— 保留前缀与后 4 位，中间固定 4 个星号。"""
    from app.common.crypto import mask

    assert mask("sk-9f2c4a1b7e8d4f6a") == "sk-****4f6a"
    assert mask("sk-abcdef123456") == "sk-****3456"


def test_mask_preserves_known_prefixes(app):
    """常见前缀原样保留，方便用户在设置页认出是哪家的 Key。"""
    from app.common.crypto import mask

    assert mask("sk-proj-1234567890ab").startswith("sk-proj-****")
    assert mask("Bearer-abcdefgh-1234").startswith("Bearer-****")


def test_mask_never_leaks_middle(app):
    from app.common.crypto import mask

    secret = "sk-AAAABBBBCCCCDDDD"
    masked = mask(secret)
    assert "AAAA" not in masked
    assert "BBBB" not in masked
    assert "CCCC" not in masked


def test_mask_short_key_is_fully_hidden(app):
    """过短的 Key 不做前后缀保留，整体打码 —— 保留后 4 位等于把 Key 全暴露。"""
    from app.common.crypto import mask

    for short in ("abc", "sk-12", "a-b-c"):
        assert mask(short) == "****", short


def test_mask_none_and_blank_are_safe(app):
    from app.common.crypto import mask

    assert mask(None) == ""
    assert mask("") == ""


def test_mask_is_idempotent(app):
    """对已掩码的值再掩码，结果不变（设置页反复渲染不会越掩越短）。"""
    from app.common.crypto import mask

    once = mask("sk-9f2c4a1b7e8d4f6a")
    assert mask(once) == once


def test_key_fingerprint_is_stable_and_non_reversible(app):
    """指纹用于判断「Key 是否变过」，必须稳定且不含明文。"""
    from app.common.crypto import fingerprint

    with app.app_context():
        a = fingerprint("sk-same-key")
        b = fingerprint("sk-same-key")
        c = fingerprint("sk-other-key")

        assert a == b
        assert a != c
        assert "sk-same-key" not in a
        assert len(a) == 8


def test_missing_fernet_key_raises_config_error(app_factory):
    """没配 FERNET_KEY 时必须显式报错，不能静默用随机密钥（重启即失联）。"""
    from app.common.crypto import CryptoError, encrypt

    app_factory(unset=("FERNET_KEY",))

    with pytest.raises(CryptoError):
        encrypt("sk-anything")
