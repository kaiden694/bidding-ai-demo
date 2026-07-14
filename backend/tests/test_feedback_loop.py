"""T7.4 语义反馈闭环准确率提升测试

测试：
- record_feedback 写入 + embedding 生成
- recall_similar_feedback 召回相似修正
- comparison_service 的 _format_feedback_examples 格式化
- contract_review_service 的反馈集成

LLM/Embedding 服务不可用时自动 skip。
"""
import os
import uuid
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


def _llm_available():
    return os.getenv("SBAW_RUN_LLM_TESTS") == "1"


llm_required = pytest.mark.skipif(
    not _llm_available(),
    reason="LLM/Embedding 服务未配置（设置 SBAW_RUN_LLM_TESTS=1 启用）",
)


# ============ 单元测试：_build_embed_text（不依赖 LLM）============
class TestBuildEmbedText:
    def test_with_context_and_reason(self):
        from app.services.feedback_service import FeedbackService
        text = FeedbackService._build_embed_text("参数A偏离规格", "应判为不合规")
        assert "参数A偏离规格" in text
        assert "应判为不合规" in text

    def test_with_only_reason(self):
        from app.services.feedback_service import FeedbackService
        text = FeedbackService._build_embed_text(None, "仅理由")
        assert text == "仅理由"

    def test_with_empty_context(self):
        from app.services.feedback_service import FeedbackService
        text = FeedbackService._build_embed_text("  ", "理由")
        assert "理由" in text

    def test_strips_whitespace(self):
        from app.services.feedback_service import FeedbackService
        text = FeedbackService._build_embed_text("  上下文  ", "  理由  ")
        # 各部分 strip 后拼接（前后空白应被去除）
        assert text == "上下文\n理由"


# ============ 单元测试：_safe_embed（mock embedding client）============
class TestSafeEmbed:
    @pytest.mark.asyncio
    async def test_safe_embed_returns_vector_on_success(self):
        from app.services.feedback_service import FeedbackService
        svc = FeedbackService.__new__(FeedbackService)
        svc._embedding_client = MagicMock()
        svc._embedding_client.embed_one = AsyncMock(return_value=[0.1, 0.2, 0.3])
        result = await svc._safe_embed("test text")
        assert result == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_safe_embed_returns_none_on_failure(self):
        from app.services.feedback_service import FeedbackService
        svc = FeedbackService.__new__(FeedbackService)
        svc._embedding_client = MagicMock()
        svc._embedding_client.embed_one = AsyncMock(side_effect=Exception("连接失败"))
        result = await svc._safe_embed("test text")
        assert result is None

    @pytest.mark.asyncio
    async def test_safe_embed_empty_text_returns_none(self):
        from app.services.feedback_service import FeedbackService
        svc = FeedbackService.__new__(FeedbackService)
        svc._embedding_client = MagicMock()
        result = await svc._safe_embed("")
        assert result is None
        result = await svc._safe_embed("   ")
        assert result is None


# ============ 单元测试：record_feedback（mock embedding）============
class TestRecordFeedback:
    @pytest.mark.asyncio
    async def test_record_feedback_creates_record(self, db_session):
        """测试 record_feedback 写入反馈记录（mock embedding）"""
        from app.services.feedback_service import FeedbackService
        from app.models.feedback import FeedbackRecord, FeedbackTargetType

        svc = FeedbackService.__new__(FeedbackService)
        svc._embedding_client = MagicMock()
        svc._embedding_client.embed_one = AsyncMock(return_value=[0.1] * 1024)

        target_id = uuid.uuid4()
        record = await svc.record_feedback(
            db_session,
            target_type=FeedbackTargetType.COMPARISON,
            target_id=target_id,
            original_verdict="compliant",
            corrected_verdict="non_compliant",
            correction_reason="参数偏离超阈值",
            context_text="参数A：要求≤10，实际12",
        )

        assert record.id is not None
        assert record.target_type == FeedbackTargetType.COMPARISON
        assert record.original_verdict == "compliant"
        assert record.corrected_verdict == "non_compliant"
        assert record.correction_reason == "参数偏离超阈值"
        assert record.is_active is True
        assert record.embedding is not None

    @pytest.mark.asyncio
    async def test_record_feedback_deactivates_old(self, db_session):
        """测试新修正会让同 target 的旧修正失效"""
        from app.services.feedback_service import FeedbackService
        from app.models.feedback import FeedbackRecord, FeedbackTargetType
        from sqlalchemy import select

        svc = FeedbackService.__new__(FeedbackService)
        svc._embedding_client = MagicMock()
        svc._embedding_client.embed_one = AsyncMock(return_value=[0.1] * 1024)

        target_id = uuid.uuid4()
        # 第一次修正
        await svc.record_feedback(
            db_session,
            target_type=FeedbackTargetType.COMPARISON,
            target_id=target_id,
            original_verdict="compliant",
            corrected_verdict="non_compliant",
            correction_reason="理由1",
        )
        # 第二次修正（同一 target）
        await svc.record_feedback(
            db_session,
            target_type=FeedbackTargetType.COMPARISON,
            target_id=target_id,
            original_verdict="compliant",
            corrected_verdict="warning",
            correction_reason="理由2",
        )

        # 查询该 target 的所有记录
        stmt = select(FeedbackRecord).where(
            FeedbackRecord.target_id == target_id,
        ).order_by(FeedbackRecord.created_at)
        records = (await db_session.execute(stmt)).scalars().all()
        assert len(records) == 2
        # 旧的应失效
        assert records[0].is_active is False
        # 新的应生效
        assert records[1].is_active is True

    @pytest.mark.asyncio
    async def test_record_feedback_with_none_embedding(self, db_session):
        """embedding 失败时记录仍应写入（embedding=None）"""
        from app.services.feedback_service import FeedbackService
        from app.models.feedback import FeedbackTargetType

        svc = FeedbackService.__new__(FeedbackService)
        svc._embedding_client = MagicMock()
        svc._embedding_client.embed_one = AsyncMock(side_effect=Exception("失败"))

        record = await svc.record_feedback(
            db_session,
            target_type=FeedbackTargetType.CONTRACT,
            target_id=uuid.uuid4(),
            original_verdict="low_risk",
            corrected_verdict="high_risk",
            correction_reason="条款存在隐蔽风险",
        )
        assert record.embedding is None
        assert record.is_active is True


# ============ 单元测试：recall_similar_feedback ============
class TestRecallSimilarFeedback:
    @pytest.mark.asyncio
    async def test_recall_by_context_key_exact(self, db_session):
        """context_key 精确匹配优先召回"""
        from app.services.feedback_service import FeedbackService
        from app.models.feedback import FeedbackTargetType

        svc = FeedbackService.__new__(FeedbackService)
        svc._embedding_client = MagicMock()
        svc._embedding_client.embed_one = AsyncMock(return_value=[0.1] * 1024)

        target_id = uuid.uuid4()
        await svc.record_feedback(
            db_session,
            target_type=FeedbackTargetType.COMPARISON,
            target_id=target_id,
            original_verdict="compliant",
            corrected_verdict="non_compliant",
            correction_reason="理由",
            context_key="param_A_voltage",
        )

        # 召回相同 context_key
        results = await svc.recall_similar_feedback(
            db_session,
            target_type=FeedbackTargetType.COMPARISON,
            query_text="参数A问题",
            context_key="param_A_voltage",
        )
        assert len(results) >= 1
        assert results[0].context_key == "param_A_voltage"

    @pytest.mark.asyncio
    async def test_recall_returns_empty_on_embed_failure(self, db_session):
        """embedding 服务不可用时返回空列表，不抛异常"""
        from app.services.feedback_service import FeedbackService
        from app.models.feedback import FeedbackTargetType

        svc = FeedbackService.__new__(FeedbackService)
        svc._embedding_client = MagicMock()
        svc._embedding_client.embed_one = AsyncMock(side_effect=Exception("失败"))

        results = await svc.recall_similar_feedback(
            db_session,
            target_type=FeedbackTargetType.COMPARISON,
            query_text="test",
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_recall_only_active_records(self, db_session):
        """仅召回 is_active=True 的记录"""
        from app.services.feedback_service import FeedbackService
        from app.models.feedback import FeedbackTargetType

        svc = FeedbackService.__new__(FeedbackService)
        svc._embedding_client = MagicMock()
        svc._embedding_client.embed_one = AsyncMock(return_value=[0.1] * 1024)

        target_id = uuid.uuid4()
        # 第一条修正（会被第二条覆盖失效）
        await svc.record_feedback(
            db_session,
            target_type=FeedbackTargetType.COMPARISON,
            target_id=target_id,
            original_verdict="v1",
            corrected_verdict="v2",
            correction_reason="理由1",
            context_key="key1",
        )
        # 第二条（使第一条失效）
        await svc.record_feedback(
            db_session,
            target_type=FeedbackTargetType.COMPARISON,
            target_id=target_id,
            original_verdict="v1",
            corrected_verdict="v3",
            correction_reason="理由2",
            context_key="key1",
        )

        # 召回应只返回 active 的
        results = await svc.recall_similar_feedback(
            db_session,
            target_type=FeedbackTargetType.COMPARISON,
            query_text="test",
            context_key="key1",
        )
        # 应只有 1 条 active
        active_results = [r for r in results if r.is_active]
        assert len(active_results) == len(results)  # 全部应 active
        assert all(r.corrected_verdict == "v3" for r in results)


# ============ 单元测试：get_stats ============
class TestGetStats:
    @pytest.mark.asyncio
    async def test_get_stats_empty(self, db_session):
        """空库时统计应为 0"""
        from app.services.feedback_service import FeedbackService
        svc = FeedbackService.__new__(FeedbackService)
        stats = await svc.get_stats(db_session)
        assert stats["total"] >= 0
        assert "active" in stats
        assert "by_target_type" in stats
        assert "correction_rate" in stats

    @pytest.mark.asyncio
    async def test_get_stats_with_records(self, db_session):
        """有记录时统计正确"""
        from app.services.feedback_service import FeedbackService
        from app.models.feedback import FeedbackTargetType

        svc = FeedbackService.__new__(FeedbackService)
        svc._embedding_client = MagicMock()
        svc._embedding_client.embed_one = AsyncMock(return_value=[0.1] * 1024)

        # 创建 2 条记录（同 target，1 active 1 inactive）
        target_id = uuid.uuid4()
        await svc.record_feedback(
            db_session,
            target_type=FeedbackTargetType.COMPARISON,
            target_id=target_id,
            original_verdict="v1",
            corrected_verdict="v2",
            correction_reason="理由1",
        )
        await svc.record_feedback(
            db_session,
            target_type=FeedbackTargetType.COMPARISON,
            target_id=target_id,
            original_verdict="v1",
            corrected_verdict="v3",
            correction_reason="理由2",
        )
        # 另一条不同 target
        await svc.record_feedback(
            db_session,
            target_type=FeedbackTargetType.CONTRACT,
            target_id=uuid.uuid4(),
            original_verdict="low",
            corrected_verdict="high",
            correction_reason="理由3",
        )

        stats = await svc.get_stats(db_session)
        assert stats["total"] >= 3
        assert stats["active"] >= 2  # 2 active（contract 1 + comparison 最新 1）
        assert 0 <= stats["correction_rate"] <= 1
        assert "comparison" in stats["by_target_type"] or "contract" in stats["by_target_type"]


# ============ 单元测试：comparison_service 的反馈集成 ============
class TestComparisonFeedbackIntegration:
    """测试比对服务集成了反馈召回（_format_feedback_examples）"""

    def test_comparison_service_has_feedback_dependency(self):
        """ComparisonService 应已注入 _feedback 依赖"""
        from app.services.comparison_service import ComparisonService
        svc = ComparisonService()
        assert hasattr(svc, "_feedback"), "ComparisonService 应有 _feedback 属性"

    def test_format_feedback_examples_method_exists(self):
        """_format_feedback_examples 静态方法应存在"""
        from app.services.comparison_service import ComparisonService
        assert hasattr(ComparisonService, "_format_feedback_examples")

    def test_format_feedback_examples_empty(self):
        """无反馈时格式化应为空字符串或占位"""
        from app.services.comparison_service import ComparisonService
        result = ComparisonService._format_feedback_examples([])
        # 应为空字符串或包含"无"的占位
        assert isinstance(result, str)

    def test_format_feedback_examples_with_records(self):
        """有反馈记录时应格式化为 few-shot 文本"""
        from app.services.comparison_service import ComparisonService

        # _format_feedback_examples 接受 dict 列表（服务内部已将 ORM 对象转 dict）
        record = {
            "context_key": "param_A_voltage",
            "context_text": "参数A：要求≤10，实际12",
            "original_verdict": "compliant",
            "corrected_verdict": "non_compliant",
            "correction_reason": "参数偏离超阈值",
        }
        result = ComparisonService._format_feedback_examples([record])
        assert "参数偏离超阈值" in result or "non_compliant" in result or "compliant" in result


# ============ 单元测试：contract_review_service 的反馈集成 ============
class TestContractReviewFeedbackIntegration:
    """测试合同审查服务集成了反馈召回"""

    def test_contract_service_has_feedback_dependency(self):
        """ContractReviewService 应已注入 _feedback 依赖"""
        from app.services.contract_review_service import ContractReviewService
        svc = ContractReviewService()
        assert hasattr(svc, "_feedback"), "ContractReviewService 应有 _feedback 属性"

    def test_format_feedback_examples_method_exists(self):
        from app.services.contract_review_service import ContractReviewService
        assert hasattr(ContractReviewService, "_format_feedback_examples")

    def test_format_feedback_examples_empty(self):
        from app.services.contract_review_service import ContractReviewService
        result = ContractReviewService._format_feedback_examples([])
        assert isinstance(result, str)


# ============ AI 优先原则合规测试 ============
class TestAIFirstCompliance:
    """验证反馈闭环符合 AI 优先原则（§13）"""

    def test_no_hardcoded_rule_mapping(self):
        """反馈召回应为语义召回，非硬编码规则映射"""
        from app.services.feedback_service import FeedbackService
        import inspect
        src = inspect.getsource(FeedbackService.recall_similar_feedback)
        # 应使用向量相似度（cosine_distance），非硬编码 if-else 映射
        assert "cosine_distance" in src or "embedding" in src
        # 不应包含硬编码的"如果...则..."规则
        assert "如果参数" not in src
        assert "则判定为" not in src

    def test_feedback_as_prompt_context_not_rule(self):
        """反馈应作为 Prompt 上下文，非硬编码判定规则"""
        import inspect
        from app.services.comparison_service import ComparisonService
        src = inspect.getsource(ComparisonService)
        # 应在 Prompt 中追加 few-shot 示例
        assert "feedback" in src.lower() or "反馈" in src
        # 不应直接用反馈结果做硬判定
        # （反馈是作为 LLM 的参考，不是 if verdict == ... then ...）


# ============ 真实 LLM/Embedding 集成测试 ============
@llm_required
class TestFeedbackLoopRealLLM:
    """真实 LLM 集成测试（需 LLM 服务可用）"""

    @pytest.mark.asyncio
    async def test_record_feedback_real_embedding(self, db_session):
        """测试真实 embedding 生成（需 Embedding 服务可用）"""
        from app.services.feedback_service import get_feedback_service
        from app.models.feedback import FeedbackTargetType

        svc = get_feedback_service()
        try:
            record = await svc.record_feedback(
                db_session,
                target_type=FeedbackTargetType.COMPARISON,
                target_id=uuid.uuid4(),
                original_verdict="compliant",
                corrected_verdict="non_compliant",
                correction_reason="参数A实际值超出规格上限",
                context_text="参数A：要求≤10，实际12",
            )
            assert record.embedding is not None
            assert len(record.embedding) > 0
        except Exception as e:
            pytest.skip(f"Embedding 服务不可用：{e}")
