"""Embedding 提供商配置 Schema"""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_serializer


def _mask_api_key(value: str) -> str:
    """脱敏 api_key：仅保留前 4 与后 4 位"""
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}****{value[-4:]}"


class EmbeddingProviderCreate(BaseModel):
    name: str = Field(..., max_length=64, description="唯一标识")
    base_url: str = Field(..., max_length=512)
    api_key: str = Field(..., max_length=512)
    model: str = Field(..., max_length=128)
    dim: int = Field(1024, ge=64, le=8192, description="向量维度")
    is_active: bool = True
    metadata_json: Optional[dict] = None


class EmbeddingProviderUpdate(BaseModel):
    name: Optional[str] = Field(None, max_length=64)
    base_url: Optional[str] = Field(None, max_length=512)
    api_key: Optional[str] = Field(None, max_length=512)
    model: Optional[str] = Field(None, max_length=128)
    dim: Optional[int] = Field(None, ge=64, le=8192)
    is_active: Optional[bool] = None
    is_healthy: Optional[bool] = None
    metadata_json: Optional[dict] = None


class EmbeddingProviderOut(BaseModel):
    id: uuid.UUID
    name: str
    base_url: str
    api_key: str  # 序列化时脱敏
    model: str
    dim: int
    is_active: bool
    is_healthy: bool
    last_check_at: Optional[datetime] = None
    consecutive_failures: int
    metadata_json: Optional[dict] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

    @field_serializer("api_key")
    def _serialize_api_key(self, value: str) -> str:
        return _mask_api_key(value) if value else value


class EmbeddingHealthCheckResult(BaseModel):
    id: str
    name: str
    is_healthy: bool
    dim: Optional[int] = None
    latency_ms: Optional[int] = None
    error: Optional[str] = None
    last_check_at: Optional[str] = None
