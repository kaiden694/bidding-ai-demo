"""
LLM 客户端：多提供商架构（Phase 3 T3）

特性：
- 多 provider 负载均衡（加权 Round-Robin）
- 健康检查（GET /models，不消耗 token）
- 故障切换（请求失败自动尝试下一个 provider）
- 熔断器（连续 3 次失败 → 熔断 30s，期间跳过）
- 用量统计（每次调用异步写 LLMUsageLog，不阻塞响应）
- 降级策略（DB 不可用或无 provider 记录时，降级到 settings 单模型配置）
- 向后兼容：chat / chat_stream 接口签名不变

并发安全：_pick_provider 用 threading.Lock 保护（多 worker / 多线程并发）
"""
import asyncio
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, Optional

from loguru import logger
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import settings


# 熔断阈值
_CIRCUIT_FAILURE_THRESHOLD = 3
_CIRCUIT_BREAK_SECONDS = 30
# half_open 试探间隔：熔断期结束后，每 N 秒允许 1 次试探请求
_HALF_OPEN_PROBE_INTERVAL = 10

# 任务池路由表（task_key → 池名）：
# - param_compare/param_summary/doc_structure → param_compare 池（高优先级，长上下文）
# - chat/qa/embedding/health → general 池（默认）
# - 不在表中的 task_key 走 general 池
_TASK_POOL_MAP = {
    "param_compare": "param_compare",
    "param_summary": "param_compare",
    "doc_structure": "param_compare",
    "tender_parse": "param_compare",
    "contract_review": "param_compare",
    "comparison_orchestrator": "param_compare",
    # 通用池
    "chat": "general",
    "qa": "general",
    "embedding": "general",
    "health": "general",
}
_DEFAULT_TASK_POOL = "general"

# 运行时配额默认值（可通过 enforce_runtime_usage_quota 调整）
_DEFAULT_QUOTA_WINDOW_MINUTES = 60
_DEFAULT_QUOTA_MAX_CALLS = 1000       # 每窗口最大调用次数
_DEFAULT_QUOTA_MAX_TOKENS = 2_000_000  # 每窗口最大 token 总量


class LLMClient:
    """LLM 编排客户端（多 provider + 健康检查 + 熔断 + 用量统计）"""

    def __init__(self):
        # 内存中的 provider 缓存（来自 DB 或 settings 降级）
        self._providers: list[dict] = []
        # Round-Robin 游标
        self._active_idx = 0
        # 并发锁（多 worker 线程并发保护）
        self._lock = threading.Lock()
        # 异步用量日志待处理任务引用（防止 GC 回收）
        self._pending_logs: set = set()
        # AsyncOpenAI 客户端缓存（按 provider id 缓存）
        self._async_clients: dict = {}
        self._load_providers()

    # ============================================================
    # Provider 加载（同步，避免在 async 上下文中嵌套事件循环）
    # ============================================================
    def _load_providers(self):
        """从 DB 加载启用的 provider；DB 不可用或无记录时降级到 settings"""
        providers: list[dict] = []
        try:
            # 延迟导入避免循环依赖
            from app.core.database import SyncSessionLocal
            from app.models.llm_provider import LLMProvider
            from sqlalchemy import select

            with SyncSessionLocal() as session:
                stmt = select(LLMProvider).where(LLMProvider.is_active == True)  # noqa: E712
                rows = session.execute(stmt).scalars().all()
                for row in rows:
                    providers.append(self._row_to_provider(row))
        except Exception as e:
            logger.warning(f"[LLMClient] DB 加载 provider 失败，降级到 settings: {e}")

        if not providers:
            # 降级到 settings 单模型配置
            providers.append(self._fallback_provider())
            logger.info("[LLMClient] 使用 settings 降级配置（单 provider）")

        with self._lock:
            self._providers = providers
            self._active_idx = 0
            self._async_clients.clear()

    @staticmethod
    def _row_to_provider(row) -> dict:
        """将 ORM 行转为内存 dict（解耦 DB 会话生命周期）"""
        return {
            "id": row.id,
            "name": row.name,
            "base_url": row.base_url,
            "api_key": row.api_key,
            "model": row.model,
            "weight": max(int(row.weight or 1), 1),
            "is_healthy": bool(row.is_healthy),
            "is_active": bool(row.is_active),
            "consecutive_failures": int(row.consecutive_failures or 0),
            "circuit_breaker_until": row.circuit_breaker_until,
            "_is_fallback": False,
        }

    @staticmethod
    def _fallback_provider() -> dict:
        """基于 settings 的降级 provider（DB 不可用 / 无记录时使用）"""
        return {
            "id": None,
            "name": "default",
            "base_url": settings.LLM_BASE_URL,
            "api_key": settings.LLM_API_KEY,
            "model": settings.LLM_MODEL,
            "weight": 1,
            "is_healthy": True,
            "is_active": True,
            "consecutive_failures": 0,
            "circuit_breaker_until": None,
            "_is_fallback": True,
        }

    def reload_providers(self):
        """重新从 DB 加载（配置变更后调用）"""
        self._load_providers()
        logger.info(f"[LLMClient] 配置已热加载，共 {len(self._providers)} 个 provider")

    # ============================================================
    # Provider 选择（加权 Round-Robin + 健康过滤 + 熔断检查 + 任务池路由）
    # ============================================================
    @staticmethod
    def _get_circuit_state(provider: dict) -> str:
        """返回熔断状态：closed / open / half_open

        - closed: 正常可用（无 circuit_breaker_until 或失败计数为 0）
        - open: 熔断期未结束（circuit_breaker_until > now）
        - half_open: 熔断期已结束但失败计数仍 >= 阈值（试探期）
          half_open 期间允许少量试探请求通过（由 _pick_provider 限流）
        """
        until = provider.get("circuit_breaker_until")
        if until is None:
            return "closed"
        # 处理 naive / aware datetime 比较
        now = datetime.now(until.tzinfo) if until.tzinfo else datetime.now()
        if now < until:
            return "open"
        # until <= now：熔断期已过，但失败计数可能仍 >= 阈值 → half_open
        if int(provider.get("consecutive_failures", 0)) >= _CIRCUIT_FAILURE_THRESHOLD:
            return "half_open"
        return "closed"

    @staticmethod
    def _check_circuit_breaker(provider: dict) -> bool:
        """返回 True 表示当前处于熔断期（应跳过该 provider）
        保留旧 API 兼容：half_open 状态不直接跳过（由 _pick_provider 限流）"""
        return LLMClient._get_circuit_state(provider) == "open"

    @staticmethod
    def _get_provider_pools(provider: dict) -> list[str]:
        """获取 provider 所属的任务池列表（通过 metadata_json.task_pools 字段）

        - 未配置时视为 [_DEFAULT_TASK_POOL]（general 池）
        - 配置为 ["*"] 表示属于所有池（万能池）
        """
        meta = provider.get("metadata_json") or {}
        if not isinstance(meta, dict):
            return [_DEFAULT_TASK_POOL]
        pools = meta.get("task_pools")
        if not pools or not isinstance(pools, list):
            return [_DEFAULT_TASK_POOL]
        return [str(p) for p in pools if p]

    @staticmethod
    def _resolve_task_pool(task_key: Optional[str]) -> str:
        """task_key → 池名（未知 task_key 走 general 池）"""
        if not task_key:
            return _DEFAULT_TASK_POOL
        return _TASK_POOL_MAP.get(task_key, _DEFAULT_TASK_POOL)

    def _pick_provider(self, task_key: Optional[str] = None) -> dict:
        """Round-Robin 选健康节点（跳过 is_healthy=False 和 open 熔断）

        - task_key: 任务池路由键（param_compare/param_summary/chat 等）
        - half_open 限流：每个 half_open 状态的 provider 每 _HALF_OPEN_PROBE_INTERVAL 秒
          允许 1 次试探请求（成功 → closed；失败 → 重新 open + 延长熔断期）
        全部不可用时降级返回第一个（让请求失败并记录）
        """
        target_pool = self._resolve_task_pool(task_key)

        with self._lock:
            providers = list(self._providers)

            # 任务池过滤：仅保留属于 target_pool 的 provider
            pooled = []
            for p in providers:
                pools = self._get_provider_pools(p)
                if target_pool in pools or "*" in pools:
                    pooled.append(p)
            if not pooled:
                # 无对应池 → 退化为全部 provider（避免完全无可用节点）
                pooled = providers
                if task_key:
                    logger.debug(
                        f"[LLMClient] task_key={task_key} pool={target_pool} 无专属 provider，"
                        "退化为全量池"
                    )

            # 构建加权候选池
            candidates: list[dict] = []
            half_open_candidates: list[dict] = []  # half_open 单独收集，限流试探
            for p in pooled:
                if not p.get("is_active", True):
                    continue
                if not p.get("is_healthy", True):
                    continue
                state = self._get_circuit_state(p)
                if state == "open":
                    continue
                if state == "half_open":
                    # half_open 仅在 closed 候选为空时尝试，且限流 1 次
                    if self._can_probe_half_open(p):
                        half_open_candidates.append(p)
                    continue
                # closed
                candidates.extend([p] * p.get("weight", 1))

            # 无 closed 候选时降级到 half_open 试探
            if not candidates and half_open_candidates:
                probed = half_open_candidates[0]
                self._mark_half_open_probed(probed)
                logger.info(
                    f"[LLMClient] task_key={task_key} 无 closed provider，试探 half_open: "
                    f"{probed.get('name')}"
                )
                return probed

            if not candidates:
                # 全部不可用 → 降级返回第一个（让请求失败并记录）
                if pooled:
                    picked = pooled[0]
                else:
                    picked = self._fallback_provider()
                logger.warning(
                    f"[LLMClient] task_key={task_key} 无健康 provider，降级使用: {picked.get('name')}"
                )
                return picked

            # Round-Robin
            idx = self._active_idx % len(candidates)
            self._active_idx = (self._active_idx + 1) % (10 ** 9)
            return candidates[idx]

    @staticmethod
    def _can_probe_half_open(provider: dict) -> bool:
        """half_open 试探限流：距上次试探 >= _HALF_OPEN_PROBE_INTERVAL 才允许"""
        last_probe = provider.get("_last_half_open_probe_at")
        if last_probe is None:
            return True
        now = datetime.now(last_probe.tzinfo) if last_probe.tzinfo else datetime.now()
        elapsed = (now - last_probe).total_seconds()
        return elapsed >= _HALF_OPEN_PROBE_INTERVAL

    @staticmethod
    def _mark_half_open_probed(provider: dict) -> None:
        """标记 half_open provider 已试探（用于限流）"""
        provider["_last_half_open_probe_at"] = datetime.now(timezone.utc)

    def _get_async_client(self, provider: dict) -> AsyncOpenAI:
        """按 provider 缓存 AsyncOpenAI 客户端"""
        key = provider.get("id") or provider.get("name")
        with self._lock:
            client = self._async_clients.get(key)
            if client is None:
                client = AsyncOpenAI(
                    base_url=provider["base_url"],
                    api_key=provider["api_key"],
                    timeout=settings.LLM_TIMEOUT,
                )
                self._async_clients[key] = client
            return client

    # ============================================================
    # 失败 / 成功记录（同步更新 DB）
    # ============================================================
    def _record_failure(self, provider: dict, error: str):
        """连续失败累加；达到阈值则设置熔断期"""
        if provider.get("_is_fallback"):
            return  # 降级配置不写 DB

        pid = provider.get("id")
        if pid is None:
            return

        try:
            from app.core.database import SyncSessionLocal
            from app.models.llm_provider import LLMProvider

            with SyncSessionLocal() as session:
                row = session.get(LLMProvider, pid)
                if row is None:
                    return
                row.consecutive_failures = int(row.consecutive_failures or 0) + 1
                failures = row.consecutive_failures
                if failures >= _CIRCUIT_FAILURE_THRESHOLD:
                    row.circuit_breaker_until = datetime.now(timezone.utc) + timedelta(
                        seconds=_CIRCUIT_BREAK_SECONDS
                    )
                    row.is_healthy = False
                    logger.warning(
                        f"[LLMClient] provider {row.name} 连续失败 {failures} 次，熔断 {_CIRCUIT_BREAK_SECONDS}s"
                    )
                session.commit()

                # 同步回内存缓存
                provider["consecutive_failures"] = failures
                provider["circuit_breaker_until"] = row.circuit_breaker_until
                provider["is_healthy"] = row.is_healthy
        except Exception as e:
            logger.error(f"[LLMClient] 记录失败状态写 DB 异常: {e}")

    def _record_success(self, provider: dict):
        """重置失败计数，标记健康"""
        if provider.get("_is_fallback"):
            return

        pid = provider.get("id")
        if pid is None:
            return

        try:
            from app.core.database import SyncSessionLocal
            from app.models.llm_provider import LLMProvider

            with SyncSessionLocal() as session:
                row = session.get(LLMProvider, pid)
                if row is None:
                    return
                row.consecutive_failures = 0
                row.is_healthy = True
                row.circuit_breaker_until = None
                session.commit()

                provider["consecutive_failures"] = 0
                provider["is_healthy"] = True
                provider["circuit_breaker_until"] = None
        except Exception as e:
            logger.error(f"[LLMClient] 记录成功状态写 DB 异常: {e}")

    # ============================================================
    # 用量日志（异步写入，不阻塞响应）
    # ============================================================
    def _log_usage_async(
        self,
        provider: dict,
        *,
        tokens_in: Optional[int],
        tokens_out: Optional[int],
        latency_ms: Optional[int],
        success: bool,
        error: Optional[str],
        request_type: str,
        messages_count: Optional[int],
    ):
        """异步写 LLMUsageLog（fire-and-forget，异常仅记录日志）"""
        pid = provider.get("id")
        pname = provider.get("name")
        model = provider.get("model")

        async def _write():
            try:
                from app.core.database import AsyncSessionLocal
                from app.models.llm_provider import LLMUsageLog

                async with AsyncSessionLocal() as session:
                    log = LLMUsageLog(
                        provider_id=pid,
                        provider_name=pname,
                        model=model,
                        messages_count=messages_count,
                        tokens_in=tokens_in,
                        tokens_out=tokens_out,
                        latency_ms=latency_ms,
                        success=success,
                        error=error,
                        request_type=request_type,
                    )
                    session.add(log)
                    await session.commit()
            except Exception as e:
                logger.error(f"[LLMClient] 写 LLMUsageLog 失败: {e}")

        try:
            task = asyncio.create_task(_write())
            self._pending_logs.add(task)
            task.add_done_callback(self._pending_logs.discard)
        except RuntimeError:
            # 无事件循环（同步上下文）→ 静默跳过
            pass

    # ============================================================
    # Prometheus 指标采集（Phase 4 T2）
    # ============================================================
    @staticmethod
    def _record_metrics(provider: dict, success: bool, latency_ms: int) -> None:
        """记录 Prometheus 指标（fire-and-forget，异常仅吞掉，不影响主流程）

        - llm_requests_total{provider, model, success}
        - llm_latency_seconds{provider}
        """
        try:
            from app.core.metrics import get_metrics_collector

            name = provider.get("name") or "unknown"
            model_name = provider.get("model") or "unknown"
            # latency_ms → 秒
            get_metrics_collector().record_llm_request(
                provider=name,
                model=model_name,
                success=bool(success),
                duration=latency_ms / 1000.0,
            )
        except Exception:  # noqa: BLE001
            # 指标采集失败绝不影响主请求
            pass

    # ============================================================
    # 对话接口（向后兼容：签名不变）
    # ============================================================
    @retry(
        stop=stop_after_attempt(settings.LLM_MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def chat(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        task_key: Optional[str] = None,
        **kwargs,
    ) -> str:
        """同步对话（返回完整文本）

        失败自动重试（tenacity），每次重试会切换到下一个健康 provider
        - task_key: 任务池路由键（param_compare/chat/tender_parse 等），
          None 时走 general 池（向后兼容）
        """
        provider = self._pick_provider(task_key=task_key)
        client = self._get_async_client(provider)
        start = time.monotonic()

        try:
            resp = await client.chat.completions.create(
                model=model or provider["model"],
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                **kwargs,
            )
            latency_ms = int((time.monotonic() - start) * 1000)
            content = resp.choices[0].message.content or ""

            # 成功：记录 + 用量日志
            self._record_success(provider)
            usage = getattr(resp, "usage", None)
            self._log_usage_async(
                provider,
                tokens_in=getattr(usage, "prompt_tokens", None),
                tokens_out=getattr(usage, "completion_tokens", None),
                latency_ms=latency_ms,
                success=True,
                error=None,
                request_type="chat",
                messages_count=len(messages),
            )
            # Prometheus 指标采集（不破坏现有逻辑，异常仅吞掉）
            self._record_metrics(provider, True, latency_ms)
            return content

        except Exception as e:
            latency_ms = int((time.monotonic() - start) * 1000)
            err_msg = f"{type(e).__name__}: {e}"
            # 失败：记录 + 用量日志
            self._record_failure(provider, err_msg)
            self._log_usage_async(
                provider,
                tokens_in=None,
                tokens_out=None,
                latency_ms=latency_ms,
                success=False,
                error=err_msg,
                request_type="chat",
                messages_count=len(messages),
            )
            # Prometheus 指标采集（失败也记录）
            self._record_metrics(provider, False, latency_ms)
            logger.warning(f"[LLMClient] provider={provider.get('name')} chat 失败: {err_msg}")
            raise

    async def chat_stream(
        self,
        messages: list[dict],
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        task_key: Optional[str] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """流式对话（SSE）

        注意：流式不使用 @retry（生成器无法重试），失败时记录并抛出
        - task_key: 任务池路由键（同 chat）
        """
        provider = self._pick_provider(task_key=task_key)
        client = self._get_async_client(provider)
        start = time.monotonic()
        collected: list[str] = []
        success = False
        err_msg: Optional[str] = None

        try:
            stream = await client.chat.completions.create(
                model=model or provider["model"],
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=True,
                **kwargs,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    collected.append(delta)
                    yield delta
            success = True
        except Exception as e:
            err_msg = f"{type(e).__name__}: {e}"
            logger.warning(f"[LLMClient] provider={provider.get('name')} chat_stream 失败: {err_msg}")
            raise
        finally:
            latency_ms = int((time.monotonic() - start) * 1000)
            if success:
                self._record_success(provider)
            else:
                self._record_failure(provider, err_msg or "unknown")
            self._log_usage_async(
                provider,
                tokens_in=None,
                tokens_out=None,
                latency_ms=latency_ms,
                success=success,
                error=err_msg,
                request_type="chat_stream",
                messages_count=len(messages),
            )
            # Prometheus 指标采集（finally 中确保成功/失败都记录）
            self._record_metrics(provider, success, latency_ms)

    # ============================================================
    # 健康检查（GET /models，不消耗 token）
    # ============================================================
    async def health_check_all(self) -> list[dict]:
        """并发 ping 所有 provider，更新 is_healthy / last_check_at

        返回每个 provider 的检查结果摘要
        """
        with self._lock:
            providers = list(self._providers)

        if not providers:
            return []

        results = await asyncio.gather(
            *(self._ping_one(p) for p in providers), return_exceptions=True
        )
        # 更新内存缓存健康状态
        with self._lock:
            for p, r in zip(self._providers, results):
                if isinstance(r, dict):
                    p["is_healthy"] = r.get("is_healthy", p.get("is_healthy", True))
        return [r for r in results if isinstance(r, dict)]

    async def _ping_one(self, provider: dict) -> dict:
        """单个 provider 健康检查（GET /models）"""
        pid = provider.get("id")
        pname = provider.get("name")
        is_healthy = False
        error: Optional[str] = None
        try:
            client = self._get_async_client(provider)
            await client.models.list()
            is_healthy = True
        except Exception as e:
            error = f"{type(e).__name__}: {e}"

        # 更新 DB（降级 provider 不写）
        if not provider.get("_is_fallback") and pid is not None:
            try:
                from app.core.database import SyncSessionLocal
                from app.models.llm_provider import LLMProvider

                with SyncSessionLocal() as session:
                    row = session.get(LLMProvider, pid)
                    if row is not None:
                        row.is_healthy = is_healthy
                        row.last_check_at = datetime.now(timezone.utc)
                        if is_healthy:
                            # 健康检查通过但保持失败计数（不主动重置，由成功请求重置）
                            pass
                        else:
                            row.is_healthy = False
                        session.commit()
            except Exception as e:
                logger.error(f"[LLMClient] 健康检查写 DB 异常 ({pname}): {e}")

        return {
            "id": str(pid) if pid else None,
            "name": pname,
            "is_healthy": is_healthy,
            "error": error,
            "last_check_at": datetime.now(timezone.utc).isoformat(),
        }

    # ============================================================
    # 用量统计
    # ============================================================
    async def get_usage_stats(self, days: int = 7) -> dict:
        """查询 LLMUsageLog 统计（按 provider 分组，最近 N 天）"""
        from sqlalchemy import Integer, select, func, and_

        from app.core.database import AsyncSessionLocal
        from app.models.llm_provider import LLMUsageLog

        since = datetime.now(timezone.utc) - timedelta(days=max(days, 1))

        async with AsyncSessionLocal() as session:
            stmt = (
                select(
                    LLMUsageLog.provider_name,
                    LLMUsageLog.model,
                    func.count().label("total_calls"),
                    func.sum(
                        func.cast(LLMUsageLog.success, Integer())
                    ).label("success_count"),
                    func.coalesce(func.sum(LLMUsageLog.tokens_in), 0).label("tokens_in"),
                    func.coalesce(func.sum(LLMUsageLog.tokens_out), 0).label("tokens_out"),
                    func.coalesce(func.avg(LLMUsageLog.latency_ms), 0).label("avg_latency_ms"),
                )
                .where(LLMUsageLog.created_at >= since)
                .group_by(LLMUsageLog.provider_name, LLMUsageLog.model)
                .order_by(func.count().desc())
            )
            result = await session.execute(stmt)
            rows = result.all()

            # 失败总数
            fail_stmt = select(func.count()).where(
                and_(LLMUsageLog.created_at >= since, LLMUsageLog.success == False)  # noqa: E712
            )
            total_fail = (await session.execute(fail_stmt)).scalar() or 0

        providers_stats = []
        total_calls = 0
        total_tokens_in = 0
        total_tokens_out = 0
        for row in rows:
            calls = int(row.total_calls or 0)
            succ = int(row.success_count or 0)
            tin = int(row.tokens_in or 0)
            tout = int(row.tokens_out or 0)
            providers_stats.append(
                {
                    "provider_name": row.provider_name,
                    "model": row.model,
                    "total_calls": calls,
                    "success_count": succ,
                    "failure_count": max(calls - succ, 0),
                    "tokens_in": tin,
                    "tokens_out": tout,
                    "avg_latency_ms": round(float(row.avg_latency_ms or 0), 2),
                }
            )
            total_calls += calls
            total_tokens_in += tin
            total_tokens_out += tout

        return {
            "days": days,
            "total_calls": total_calls,
            "total_failures": int(total_fail),
            "total_tokens_in": total_tokens_in,
            "total_tokens_out": total_tokens_out,
            "providers": providers_stats,
        }

    # ============================================================
    # 状态概览（供 admin 端点直接使用）
    # ============================================================
    def list_providers_status(self) -> list[dict]:
        """返回内存中所有 provider 的状态（含熔断信息）"""
        with self._lock:
            providers = list(self._providers)
        return [
            {
                "id": str(p["id"]) if p.get("id") else None,
                "name": p.get("name"),
                "base_url": p.get("base_url"),
                "model": p.get("model"),
                "weight": p.get("weight", 1),
                "is_healthy": p.get("is_healthy", True),
                "is_active": p.get("is_active", True),
                "is_fallback": p.get("_is_fallback", False),
                "consecutive_failures": p.get("consecutive_failures", 0),
                "circuit_breaker_until": p.get("circuit_breaker_until").isoformat()
                if p.get("circuit_breaker_until")
                else None,
                "circuit_state": self._get_circuit_state(p),
                "task_pools": self._get_provider_pools(p),
                "in_circuit_break": self._check_circuit_breaker(p),
            }
            for p in providers
        ]

    # ============================================================
    # 运行时配额预检（P2-10 T10.4）
    # ============================================================
    async def enforce_runtime_usage_quota(
        self,
        *,
        window_minutes: int = _DEFAULT_QUOTA_WINDOW_MINUTES,
        max_calls: int = _DEFAULT_QUOTA_MAX_CALLS,
        max_tokens: int = _DEFAULT_QUOTA_MAX_TOKENS,
        raise_on_exceed: bool = True,
    ) -> dict:
        """调用前预检配额（calls + tokens 双维度）

        - 查询最近 window_minutes 分钟内 LLMUsageLog 的总 calls 与 tokens
        - 超出配额时 raise_on_exceed=True 抛 RuntimeError；False 仅返回状态 dict
        - 返回 dict: {"within_quota": bool, "calls": int, "tokens": int,
                      "max_calls": int, "max_tokens": int, "window_minutes": int}
        """
        try:
            from sqlalchemy import func, and_
            from app.core.database import AsyncSessionLocal
            from app.models.llm_provider import LLMUsageLog

            since = datetime.now(timezone.utc) - timedelta(minutes=max(window_minutes, 1))
            async with AsyncSessionLocal() as session:
                stmt = select(
                    func.count().label("total_calls"),
                    func.coalesce(func.sum(LLMUsageLog.tokens_in), 0).label("tokens_in"),
                    func.coalesce(func.sum(LLMUsageLog.tokens_out), 0).label("tokens_out"),
                ).where(
                    and_(
                        LLMUsageLog.created_at >= since,
                        LLMUsageLog.success.is_(True),
                    )
                )
                row = (await session.execute(stmt)).one()
        except Exception as e:
            logger.warning(f"[LLMClient] 配额预检查询失败（视为通过）: {e}")
            return {
                "within_quota": True,
                "calls": 0,
                "tokens": 0,
                "max_calls": max_calls,
                "max_tokens": max_tokens,
                "window_minutes": window_minutes,
                "error": str(e),
            }

        calls = int(row.total_calls or 0)
        tokens = int(row.tokens_in or 0) + int(row.tokens_out or 0)
        within = (calls <= max_calls) and (tokens <= max_tokens)
        status = {
            "within_quota": within,
            "calls": calls,
            "tokens": tokens,
            "max_calls": max_calls,
            "max_tokens": max_tokens,
            "window_minutes": window_minutes,
        }
        if not within and raise_on_exceed:
            raise RuntimeError(
                f"LLM 运行时配额超限: calls={calls}/{max_calls}, "
                f"tokens={tokens}/{max_tokens} (最近 {window_minutes} 分钟)"
            )
        return status

    # ============================================================
    # MeteredClient（P2-10 T10.5）
    # ============================================================
    def get_metered_client(self, provider: Optional[dict] = None) -> "MeteredClient":
        """获取一个 MeteredClient 实例（代理 AsyncOpenAI，记录 usage/success/failure）

        用法：
            client = llm.get_metered_client()
            resp = await client.chat.completions.create(...)
        """
        if provider is None:
            provider = self._pick_provider()
        raw = self._get_async_client(provider)
        return MeteredClient(raw, self, provider)


# ============================================================
# MeteredClient：AsyncOpenAI 代理层（P2-10 T10.5）
# ============================================================
class MeteredClient:
    """AsyncOpenAI 透明代理：__getattr__ 转发 + 自动计量 usage/success/failure

    - 透明转发所有属性访问到底层 AsyncOpenAI 客户端
    - 包装 chat.completions.create / chat.completions.create(stream=True)
    - 自动调用 LLMClient._record_success/_record_failure/_log_usage_async
    - 失败不抛异常给业务，由业务自行处理（与 LLMClient.chat 行为对齐）

    用法：
        client = llm.get_metered_client()
        resp = await client.chat.completions.create(model=..., messages=...)
        # usage/success/failure 自动写入 LLMUsageLog
    """

    def __init__(self, raw_client: AsyncOpenAI, llm_client: "LLMClient", provider: dict):
        # 用 object.__setattr__ 避免触发自定义 __getattr__
        object.__setattr__(self, "_raw", raw_client)
        object.__setattr__(self, "_llm", llm_client)
        object.__setattr__(self, "_provider", provider)
        # 预先包装 chat 属性
        object.__setattr__(self, "chat", _MeteredChat(
            getattr(raw_client, "chat"), llm_client, provider
        ))

    def __getattr__(self, name: str):
        """转发未识别属性到底层 AsyncOpenAI（chat 已包装，其他属性透传）"""
        return getattr(self._raw, name)


class _MeteredChat:
    """chat.completions 层的计量包装"""

    def __init__(self, raw_chat, llm_client: "LLMClient", provider: dict):
        object.__setattr__(self, "_raw", raw_chat)
        object.__setattr__(self, "_llm", llm_client)
        object.__setattr__(self, "_provider", provider)
        object.__setattr__(self, "completions", _MeteredCompletions(
            getattr(raw_chat, "completions"), llm_client, provider
        ))

    def __getattr__(self, name: str):
        return getattr(self._raw, name)


class _MeteredCompletions:
    """completions.create 层的计量包装（实际记录 usage/success/failure）"""

    def __init__(self, raw_completions, llm_client: "LLMClient", provider: dict):
        object.__setattr__(self, "_raw", raw_completions)
        object.__setattr__(self, "_llm", llm_client)
        object.__setattr__(self, "_provider", provider)

    async def create(self, *args, **kwargs):
        """异步 create：计量 usage/success/failure"""
        start = time.monotonic()
        success = False
        err: Optional[Exception] = None
        resp = None
        try:
            resp = await self._raw.create(*args, **kwargs)
            success = True
            return resp
        except Exception as e:
            err = e
            raise
        finally:
            latency_ms = int((time.monotonic() - start) * 1000)
            try:
                usage = getattr(resp, "usage", None) if resp is not None else None
                self._llm._log_usage_async(
                    self._provider,
                    tokens_in=getattr(usage, "prompt_tokens", None) if usage else None,
                    tokens_out=getattr(usage, "completion_tokens", None) if usage else None,
                    latency_ms=latency_ms,
                    success=success,
                    error=f"{type(err).__name__}: {err}" if err else None,
                    request_type="metered_chat",
                    messages_count=len(kwargs.get("messages") or []),
                )
                if success:
                    self._llm._record_success(self._provider)
                else:
                    self._llm._record_failure(
                        self._provider, f"{type(err).__name__}: {err}" if err else "unknown"
                    )
                self._llm._record_metrics(self._provider, success, latency_ms)
            except Exception as meter_err:
                logger.warning(f"[MeteredClient] 计量写入失败（不阻断）: {meter_err}")

    def __getattr__(self, name: str):
        return getattr(self._raw, name)


# 单例
_llm_client: Optional[LLMClient] = None


def get_llm_client() -> LLMClient:
    global _llm_client
    if _llm_client is None:
        _llm_client = LLMClient()
    return _llm_client


def reload_llm_client() -> LLMClient:
    """重置单例并重新加载（配置变更后调用）"""
    global _llm_client
    _llm_client = LLMClient()
    return _llm_client
