"""LLM 提供商配置 + 用量统计 Schema"""
import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_serializer


def _mask_api_key(value: str) -> str:
    """脱敏 api_key：仅保留前 4 与后 4 位，中间用 **** 替代"""
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}****{value[-4:]}"


class LLMProviderCreate(BaseModel):
    """创建 LLM 提供商"""
    name: str = Field(..., max_length=64, description="唯一标识")
    base_url: str = Field(..., max_length=512)
    api_key: str = Field(..., max_length=512, description="生产应加密")
    model: str = Field(..., max_length=128)
    weight: int = Field(1, ge=1, description="负载权重")
    is_active: bool = True
    metadata_json: Optional[dict] = None


class LLMProviderUpdate(BaseModel):
    """更新 LLM 提供商（部分字段）"""
    name: Optional[str] = Field(None, max_length=64)
    base_url: Optional[str] = Field(None, max_length=512)
    api_key: Optional[str] = Field(None, max_length=512)
    model: Optional[str] = Field(None, max_length=128)
    weight: Optional[int] = Field(None, ge=1)
    is_active: Optional[bool] = None
    is_healthy: Optional[bool] = None  # 允许手动重置健康状态
    metadata_json: Optional[dict] = None


class LLMProviderOut(BaseModel):
    """LLM 提供商输出（api_key 脱敏，避免明文泄露）"""
    id: uuid.UUID
    name: str
    base_url: str
    api_key: str
    model: str
    weight: int
    is_healthy: bool
    is_active: bool
    last_check_at: Optional[datetime] = None
    consecutive_failures: int
    circuit_breaker_until: Optional[datetime] = None
    metadata_json: Optional[dict] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

    @field_serializer("api_key")
    def _serialize_api_key(self, value: str) -> str:  # noqa: D401
        return _mask_api_key(value) if value else value


class LLMProviderStatusOut(BaseModel):
    """LLM 提供商运行时状态（含熔断信息，来自内存缓存）"""
    id: Optional[str] = None
    name: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    weight: int = 1
    is_healthy: bool = True
    is_active: bool = True
    is_fallback: bool = False
    consecutive_failures: int = 0
    circuit_breaker_until: Optional[str] = None
    in_circuit_break: bool = False


class LLMHealthCheckResult(BaseModel):
    """单个 provider 健康检查结果"""
    id: Optional[str] = None
    name: Optional[str] = None
    is_healthy: bool
    error: Optional[str] = None
    last_check_at: Optional[str] = None


class LLMProviderUsageStat(BaseModel):
    """单个 provider 用量统计"""
    provider_name: Optional[str] = None
    model: Optional[str] = None
    total_calls: int
    success_count: int
    failure_count: int
    tokens_in: int
    tokens_out: int
    avg_latency_ms: float


class LLMUsageStatsOut(BaseModel):
    """用量统计聚合输出"""
    days: int
    total_calls: int
    total_failures: int
    total_tokens_in: int
    total_tokens_out: int
    providers: list[LLMProviderUsageStat] = []
