"""
AI 助手服务：前台/后台用户共用的咨询问答
- RAG 增强：先从通用知识库 + 产品库 + 历史案例召回相关证据
- LLM 基于证据 + 会话历史生成回答
- 会话历史持久化（多轮对话）
"""
import uuid
from typing import Optional, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.llm.client import get_llm_client
from app.ai.rag.retriever import get_rag_retriever
from app.models.assistant import AssistantConversation, AssistantMessage, AssistantScope
from app.core.config import settings


SYSTEM_PROMPT = """你是智能招投标与合同合规 AI 工作台的助手。
你的职责是帮助用户解答关于招投标流程、合同合规、产品参数、企业资质、政策法规等方面的问题。

回答原则：
1. 优先依据提供的"参考资料"作答，资料来源会在每次召回时给出
2. 如果参考资料不足以回答，明确说明"根据现有资料无法完整回答"，不要编造
3. 引用资料时标注来源（如：根据《xxx 文件》第 x 页）
4. 涉及具体数值/参数/条款时，必须给出原文依据
5. 回答使用中文，结构清晰"""


class AssistantService:
    """AI 助手服务"""

    def __init__(self):
        self._llm = get_llm_client()
        self._rag = get_rag_retriever()

    async def chat(
        self,
        session: AsyncSession,
        conversation_id: Optional[str],
        question: str,
        scope: AssistantScope = AssistantScope.ALL,
        user_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """咨询问答
        - conversation_id 为空则新建会话
        - scope 控制检索范围（前台/后台/全部）
        - 返回 {answer, evidence, conversation_id}
        """
        # 1. 会话管理
        if conversation_id:
            conv = await session.get(AssistantConversation, uuid.UUID(conversation_id))
            if not conv:
                conv = AssistantConversation(
                    id=uuid.uuid4(), title=question[:50], scope=scope, user_id=user_id
                )
                session.add(conv)
        else:
            conv = AssistantConversation(
                id=uuid.uuid4(), title=question[:50], scope=scope, user_id=user_id
            )
            session.add(conv)
        # 2. 加载会话历史（最近 10 轮，需在记录新消息前加载，避免重复包含当前问题）
        history = await self._load_history(session, conv.id, limit=20)

        # 记录用户问题
        user_msg = AssistantMessage(
            conversation_id=conv.id, role="user", content=question
        )
        session.add(user_msg)
        await session.flush()

        # 3. RAG 召回证据（按 scope 过滤可见范围）
        evidence = await self._retrieve_evidence(session, question, scope)

        # 4. 组装 Prompt
        context_text = self._format_context(evidence)

        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        if context_text:
            messages.append({"role": "system", "content": f"参考资料：\n{context_text}"})
        messages.extend(history)
        messages.append({"role": "user", "content": question})

        # 5. LLM 生成回答
        answer = await self._llm.chat(messages, temperature=0.3, max_tokens=2048)

        # 6. 记录 AI 回答
        ai_msg = AssistantMessage(
            conversation_id=conv.id, role="assistant", content=answer,
            evidence=[e for e in evidence[:5]]  # 保留 Top5 证据
        )
        session.add(ai_msg)
        await session.commit()

        return {
            "answer": answer,
            "evidence": evidence[:5],
            "conversation_id": str(conv.id),
        }

    async def _retrieve_evidence(
        self, session: AsyncSession, query: str, scope: AssistantScope
    ) -> List[dict]:
        """RAG 召回：通用知识库 + 历史知识库
        - scope=FRONT: 通用知识库只检索 visibility in (front, all)
        - scope=BACK: 通用知识库只检索 visibility in (back, all)
        - scope=ALL: 通用知识库全部可见（不传 visibility 过滤）
        - 按 chunk_id 去重；RAG 召回失败不阻断对话
        """
        evidence: List[dict] = []
        seen_chunk_ids: set = set()

        # 1. 通用知识库召回（按 scope 过滤 visibility）
        # retriever.search_general_knowledge 内部会同时匹配 [visibility, "all"]
        visibility_filter: Optional[str] = None
        if scope == AssistantScope.FRONT:
            visibility_filter = "front"
        elif scope == AssistantScope.BACK:
            visibility_filter = "back"
        try:
            results = await self._rag.search_general_knowledge(
                session, query=query, top_k=3, visibility=visibility_filter
            )
            for r in results:
                cid = r.get("chunk_id")
                if cid and cid not in seen_chunk_ids:
                    seen_chunk_ids.add(cid)
                    evidence.append(r)
        except Exception:
            pass

        # 2. 历史知识库召回（无 visibility 限制）
        try:
            results = await self._rag.search_knowledge(session, query, top_k=3)
            for r in results:
                cid = r.get("chunk_id")
                if cid and cid not in seen_chunk_ids:
                    seen_chunk_ids.add(cid)
                    evidence.append(r)
        except Exception:
            pass

        return evidence

    @staticmethod
    def _format_context(evidence: List[dict]) -> str:
        if not evidence:
            return ""
        lines = []
        for i, e in enumerate(evidence, 1):
            src = e.get("title") or e.get("section") or "知识库"
            lines.append(f"[{i}] 来源：{src}\n{e.get('content', '')[:300]}")
        return "\n\n".join(lines)

    async def _load_history(self, session: AsyncSession, conv_id: uuid.UUID, limit: int = 20) -> List[dict]:
        stmt = (
            select(AssistantMessage)
            .where(AssistantMessage.conversation_id == conv_id)
            .order_by(AssistantMessage.created_at.desc())
            .limit(limit)
        )
        result = await session.execute(stmt)
        msgs = list(reversed(result.scalars().all()))
        return [{"role": m.role, "content": m.content} for m in msgs]


_assistant: Optional[AssistantService] = None


def get_assistant_service() -> AssistantService:
    global _assistant
    if _assistant is None:
        _assistant = AssistantService()
    return _assistant
