"""加密工具 —— 保护 redaction_map 中的敏感原始数据。

使用 AES-128-GCM 加密（通过 cryptography 库）。
密钥从环境变量 LEGAL_REDACTOR_KEY 获取，
首次运行如未设置密钥会自动生成一个并保存在 ~/.config/legal-redactor/key。
"""

from __future__ import annotations

import base64
import os
import secrets
from pathlib import Path

from ._logging import get_logger

_logger = get_logger("crypto")

_KEY_ENV = "LEGAL_REDACTOR_KEY"
_KEY_FILE = Path.home() / ".config" / "legal-redactor" / "key"
_RAW_KEY_LENGTH = 16  # 128 bits


def get_or_create_key() -> bytes:
    """获取加密密钥：环境变量 → 持久化文件 → 自动生成。"""
    env_key = os.environ.get(_KEY_ENV)
    if env_key:
        key_bytes = _decode_key(env_key)
        if len(key_bytes) == _RAW_KEY_LENGTH:
            return key_bytes

    if _KEY_FILE.exists():
        try:
            saved = _KEY_FILE.read_text(encoding="utf-8").strip()
            key_bytes = _decode_key(saved)
            if len(key_bytes) == _RAW_KEY_LENGTH:
                return key_bytes
        except Exception:
            pass

    new_key = secrets.token_bytes(_RAW_KEY_LENGTH)
    encoded = base64.b64encode(new_key).decode("ascii")
    _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _KEY_FILE.write_text(encoded, encoding="utf-8")
    os.chmod(_KEY_FILE, 0o600)
    _logger.info("已生成加密密钥并保存到 %s", _KEY_FILE)
    return new_key


def _decode_key(value: str) -> bytes:
    value = value.strip()
    try:
        return base64.b64decode(value)
    except Exception:
        pass
    try:
        return bytes.fromhex(value)
    except Exception:
        pass
    return b""


def encrypt(plaintext: str) -> bytes:
    """使用 AES-128-GCM 加密字符串，返回二进制 payload。"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = get_or_create_key()
    nonce = secrets.token_bytes(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return nonce + ciphertext


def decrypt(data: bytes) -> str:
    """解密由 encrypt() 产生的 payload，返回明文字符串。"""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if len(data) < 12 + 16:
        raise ValueError("加密数据格式无效或已损坏")

    key = get_or_create_key()
    nonce = data[:12]
    ciphertext = data[12:]
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")
