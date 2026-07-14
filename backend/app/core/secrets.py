"""密钥管理抽象层

统一密钥获取接口，支持多后端：
- 开发：环境变量 / .env 文件
- 生产：环境变量 / K8s Secret / Vault（可选）

使用：
    from app.core.secrets import get_secret

    db_password = get_secret("POSTGRES_PASSWORD")
    llm_api_key = get_secret("LLM_API_KEY")
"""
import os
from typing import Optional

from app.core.config import settings


def get_secret(key: str, default: str = "") -> str:
    """获取密钥

    优先级：
    1. 环境变量（os.environ）
    2. settings 配置（app/core/config.py）
    3. default 默认值

    Args:
        key: 密钥名（如 POSTGRES_PASSWORD）
        default: 默认值

    Returns:
        密钥值
    """
    # 1. 环境变量（最高优先级，K8s Secret 注入到环境变量）
    value = os.environ.get(key)
    if value:
        return value

    # 2. settings 配置
    value = getattr(settings, key, None)
    if value:
        return str(value)

    # 3. 默认值
    return default


def get_encrypted_secret(key: str, default: str = "") -> str:
    """获取加密的密钥（自动解密）

    读取的密钥如已加密（enc: 前缀），自动解密后返回明文

    Args:
        key: 密钥名
        default: 默认值

    Returns:
        解密后的明文
    """
    from app.core.encryption import decrypt, is_encrypted

    value = get_secret(key, default)
    if not value:
        return value

    # 如已加密，解密后返回
    if is_encrypted(value):
        decrypted = decrypt(value)
        return decrypted

    return value


def validate_required_secrets() -> list[str]:
    """校验必需的密钥是否已配置

    Returns:
        缺失的密钥名列表（空列表表示全部配置正确）
    """
    required = [
        "SECRET_KEY",
        "POSTGRES_PASSWORD",
        "LLM_API_KEY",
    ]
    missing = []
    for key in required:
        if not get_secret(key):
            missing.append(key)
    return missing
