"""字段级加密工具（AES-256-GCM）

用途：
- 加密 LLM API Key / SSO client_secret / SMTP 密码 等敏感字段
- 密钥从环境变量 ENCRYPTION_KEY 读取（32 字节 base64 编码）
- 如未配置 ENCRYPTION_KEY，自动生成并缓存（仅开发环境，生产必须配置）

使用：
    from app.core.encryption import encrypt, decrypt

    encrypted = encrypt("my-secret-api-key")  # → "enc:xxxx"
    decrypted = decrypt(encrypted)            # → "my-secret-api-key"
"""
import base64
import hashlib
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings

# 加密前缀（用于识别已加密的字段）
ENCRYPTED_PREFIX = "enc:"

# 密钥缓存
_encryption_key: bytes | None = None


def _get_encryption_key() -> bytes:
    """获取加密密钥（32 字节）

    优先级：
    1. 环境变量 ENCRYPTION_KEY（base64 编码的 32 字节）
    2. settings.SECRET_KEY 派生（SHA-256 → 32 字节，兼容现有配置）
    """
    global _encryption_key
    if _encryption_key is not None:
        return _encryption_key

    env_key = os.environ.get("ENCRYPTION_KEY") or getattr(settings, "ENCRYPTION_KEY", "")
    if env_key:
        try:
            _encryption_key = base64.b64decode(env_key)
            if len(_encryption_key) != 32:
                # 长度不对，用 SHA-256 派生
                _encryption_key = hashlib.sha256(env_key.encode()).digest()
        except Exception:
            _encryption_key = hashlib.sha256(env_key.encode()).digest()
    else:
        # 从 SECRET_KEY 派生（兼容现有配置）
        _encryption_key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()

    return _encryption_key


def encrypt(plaintext: str) -> str:
    """加密字符串

    Args:
        plaintext: 明文

    Returns:
        加密后的字符串（格式：enc:{nonce_b64}:{ciphertext_b64}）
    """
    if not plaintext:
        return plaintext
    # 已加密的字段不重复加密
    if plaintext.startswith(ENCRYPTED_PREFIX):
        return plaintext

    key = _get_encryption_key()
    nonce = secrets.token_bytes(12)  # AES-GCM 推荐 12 字节 nonce
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    # 编码为 base64 便于存储
    nonce_b64 = base64.b64encode(nonce).decode("ascii")
    cipher_b64 = base64.b64encode(ciphertext).decode("ascii")
    return f"{ENCRYPTED_PREFIX}{nonce_b64}:{cipher_b64}"


def decrypt(encrypted: str) -> str:
    """解密字符串

    Args:
        encrypted: 加密字符串（格式：enc:{nonce_b64}:{ciphertext_b64}）

    Returns:
        明文。如非加密格式则原样返回（兼容未加密的旧数据）
    """
    if not encrypted or not encrypted.startswith(ENCRYPTED_PREFIX):
        return encrypted

    try:
        # 去掉前缀
        payload = encrypted[len(ENCRYPTED_PREFIX):]
        parts = payload.split(":", 1)
        if len(parts) != 2:
            return encrypted  # 格式错误，返回原值
        nonce_b64, cipher_b64 = parts
        nonce = base64.b64decode(nonce_b64)
        ciphertext = base64.b64decode(cipher_b64)
        key = _get_encryption_key()
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode("utf-8")
    except Exception:
        # 解密失败，返回原值（避免阻塞业务）
        return encrypted


def is_encrypted(value: str) -> bool:
    """检查字符串是否已加密"""
    return bool(value) and value.startswith(ENCRYPTED_PREFIX)


def generate_encryption_key() -> str:
    """生成新的加密密钥（base64 编码，32 字节）

    用于生成 ENCRYPTION_KEY 环境变量值
    """
    return base64.b64encode(secrets.token_bytes(32)).decode("ascii")
