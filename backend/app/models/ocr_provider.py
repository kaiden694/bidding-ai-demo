"""
OCR 提供商配置（支持运行时增删，兼容多种在线 OCR 服务）

支持类型：
- MINERU    MinerU 在线服务（上海 AI Lab，Bearer Token 鉴权，异步任务流）
- PADDLEOCR PaddleOCR 在线服务（百度，API Key + Secret Key 换 access_token）
- LOCAL     本地 rapidocr（无需外部配置，兜底）
- OTHER     其他兼容服务

差异配置存 metadata_json：
- MinerU: {enable_formula, enable_table, language, is_ocr}
- PaddleOCR: {secret_key, language_type}
"""
import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import String, Integer, Boolean, DateTime, Enum, Index
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import UUIDPKMixin, TimestampMixin


class OCRProviderType(str, enum.Enum):
    """OCR 服务类型"""
    MINERU = "mineru"           # MinerU 在线服务
    PADDLEOCR = "paddleocr"     # PaddleOCR 在线服务
    LOCAL = "local"             # 本地 rapidocr
    OTHER = "other"             # 其他兼容服务


class OCRProvider(Base, UUIDPKMixin, TimestampMixin):
    """OCR 提供商配置（支持运行时增删，无需重启）

    兼容 MinerU / PaddleOCR 等多种在线 OCR 服务
    """
    __tablename__ = "ocr_provider"

    name: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    # 服务类型（区分鉴权方式和请求模型）
    provider_type: Mapped[OCRProviderType] = mapped_column(
        Enum(OCRProviderType, name="ocr_provider_type_enum"),
        default=OCRProviderType.OTHER,
        nullable=False,
        index=True,
    )
    # 服务地址（MinerU 固定 https://mineru.net；PaddleOCR 可配置）
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    # API Key（MinerU 的 bearer token / PaddleOCR 的 API Key）
    api_key: Mapped[str] = mapped_column(String(512), nullable=False)
    # 模型/服务标识（如 paddleocr 的模型版本，MinerU 可留空）
    model: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # 是否启用（同一时刻仅一个生效）
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    # 健康检查
    is_healthy: Mapped[bool] = mapped_column(Boolean, default=True)
    last_check_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    # 扩展参数（PaddleOCR 的 secret_key、MinerU 的 enable_formula 等）
    metadata_json: Mapped[Optional[dict]] = mapped_column(JSON)

    __table_args__ = (
        Index("ix_ocr_provider_active", "is_active"),
    )
