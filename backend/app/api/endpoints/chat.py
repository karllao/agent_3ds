"""
用户与 Agent 的多轮对话 API。

支持：
  - 创建对话会话
  - 发送消息（触发 AI 响应）
  - 查询对话历史
  - 删除对话
"""

from __future__ import annotations

import json
from datetime import datetime

from app.config import get_settings
from app.database import DbSession
from app.models.conversation import Conversation, Message, MessageRole
from app.models.project import Project
from app.utils.logger import get_logger
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

router = APIRouter()
logger = get_logger(__name__)
settings = get_settings()


# ── Pydantic 请求 / 响应模型 ─────────────────────────────────────────────────


class ConversationCreate(BaseModel):
    project_id: int = Field(..., description="关联的项目 ID")
    title: str | None = Field(default=None, max_length=200)


class MessageRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=8192, description="用户消息内容")


class MessageResponse(BaseModel):
    id: int
    conversation_id: int
    role: MessageRole
    content: str
    meta: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_with_meta(cls, msg: Message) -> "MessageResponse":
        meta_dict: dict | None = None
        if msg.meta:
            try:
                meta_dict = json.loads(msg.meta)
            except (json.JSONDecodeError, TypeError):
                meta_dict = None
        return cls(
            id=msg.id,
            conversation_id=msg.conversation_id,
            role=msg.role,
            content=msg.content,
            meta=meta_dict,
            created_at=msg.created_at,
        )


class ConversationResponse(BaseModel):
    id: int
    project_id: int
    title: str | None
    created_at: datetime
    updated_at: datetime
    messages: list[MessageResponse]

    model_config = {"from_attributes": True}


# ── 创建对话会话 ──────────────────────────────────────────────────────────────
@router.post(
    "/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="为项目创建新的对话会话",
)
async def create_conversation(
    payload: ConversationCreate,
    db: DbSession,
) -> ConversationResponse:
    # 验证项目存在
    proj_result = await db.execute(
        select(Project).where(Project.id == payload.project_id)
    )
    if proj_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"项目 {payload.project_id} 不存在",
        )

    conv = Conversation(project_id=payload.project_id, title=payload.title)
    db.add(conv)
    await db.flush()
    await db.refresh(conv)
    logger.info("Conversation created: id={} project_id={}", conv.id, conv.project_id)

    return ConversationResponse(
        id=conv.id,
        project_id=conv.project_id,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=[],
    )


# ── 获取对话列表 ──────────────────────────────────────────────────────────────
@router.get(
    "/conversations",
    response_model=list[ConversationResponse],
    summary="获取项目的所有对话会话",
)
async def list_conversations(
    project_id: int,
    db: DbSession,
) -> list[ConversationResponse]:
    result = await db.execute(
        select(Conversation)
        .where(Conversation.project_id == project_id)
        .order_by(Conversation.updated_at.desc())
    )
    convs = result.scalars().all()
    return [
        ConversationResponse(
            id=c.id,
            project_id=c.project_id,
            title=c.title,
            created_at=c.created_at,
            updated_at=c.updated_at,
            messages=[MessageResponse.from_orm_with_meta(m) for m in c.messages],
        )
        for c in convs
    ]


# ── 获取单个对话详情 ──────────────────────────────────────────────────────────
@router.get(
    "/conversations/{conversation_id}",
    response_model=ConversationResponse,
    summary="获取对话详情及完整历史消息",
)
async def get_conversation(
    conversation_id: int,
    db: DbSession,
) -> ConversationResponse:
    conv = await _get_conversation_or_404(conversation_id, db)
    return ConversationResponse(
        id=conv.id,
        project_id=conv.project_id,
        title=conv.title,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=[MessageResponse.from_orm_with_meta(m) for m in conv.messages],
    )


# ── 发送消息（触发 AI 响应） ──────────────────────────────────────────────────
@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=list[MessageResponse],
    status_code=status.HTTP_201_CREATED,
    summary="发送用户消息并获取 AI 回复",
)
async def send_message(
    conversation_id: int,
    payload: MessageRequest,
    db: DbSession,
) -> list[MessageResponse]:
    conv = await _get_conversation_or_404(conversation_id, db)

    # ── 保存用户消息 ──────────────────────────────────────────────────────
    user_msg = Message(
        conversation_id=conv.id,
        role=MessageRole.USER,
        content=payload.content,
    )
    db.add(user_msg)
    await db.flush()
    await db.refresh(user_msg)

    # ── 构造历史消息上下文 ─────────────────────────────────────────────────
    history = [
        {"role": m.role.value, "content": m.content}
        for m in conv.messages
        if m.id != user_msg.id
    ]
    history.append({"role": "user", "content": payload.content})

    # ── 调用 LLM ──────────────────────────────────────────────────────────
    ai_content, token_usage = await _call_llm(
        messages=history,
        project_id=conv.project_id,
        db=db,
    )

    # ── 保存 AI 回复 ──────────────────────────────────────────────────────
    assistant_msg = Message(
        conversation_id=conv.id,
        role=MessageRole.ASSISTANT,
        content=ai_content,
        meta=json.dumps(token_usage, ensure_ascii=False),
    )
    db.add(assistant_msg)
    await db.flush()
    await db.refresh(assistant_msg)

    logger.info(
        "Chat round-trip: conversation_id={} tokens={}",
        conversation_id,
        token_usage.get("total_tokens", "?"),
    )
    return [
        MessageResponse.from_orm_with_meta(user_msg),
        MessageResponse.from_orm_with_meta(assistant_msg),
    ]


# ── 删除对话 ──────────────────────────────────────────────────────────────────
@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除对话（级联删除所有消息）",
)
async def delete_conversation(conversation_id: int, db: DbSession):
    conv = await _get_conversation_or_404(conversation_id, db)
    await db.delete(conv)
    logger.info("Conversation deleted: id={}", conversation_id)


# ── 工具函数 ──────────────────────────────────────────────────────────────────
async def _get_conversation_or_404(conv_id: int, db: DbSession) -> Conversation:
    result = await db.execute(select(Conversation).where(Conversation.id == conv_id))
    conv = result.scalar_one_or_none()
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"对话 {conv_id} 不存在",
        )
    return conv


async def _call_llm(
    messages: list[dict],
    project_id: int,
    db: DbSession,
) -> tuple[str, dict]:
    """
    调用 LLM 生成回复。

    根据配置选择 OpenAI 或 Anthropic。
    返回 (ai_content, token_usage_dict)
    """
    from openai import AsyncOpenAI

    cfg = settings

    # 获取项目的场景上下文（如已生成）
    proj_result = await db.execute(select(Project).where(Project.id == project_id))
    project = proj_result.scalar_one_or_none()

    system_prompt = (
        "你是一位专业的室内设计 AI 助手，协助用户根据 CAD 图纸生成三维室内场景。\n"
        "你了解建筑结构、室内设计风格、3ds Max 建模流程，以及 V-Ray 渲染技术。\n"
        "回答时请简洁、专业，并针对用户的具体场景给出可落地的建议。\n"
    )

    if project and project.user_description:
        system_prompt += f"\n当前项目描述：{project.user_description}"

    if cfg.default_llm_provider == "anthropic":
        from anthropic import AsyncAnthropic

        client = AsyncAnthropic(api_key=cfg.anthropic_api_key)
        # Anthropic 的系统消息单独传递
        user_messages = [m for m in messages if m["role"] != "system"]
        resp = await client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=4096,
            system=system_prompt,
            messages=user_messages,  # type: ignore[arg-type]
        )
        content = resp.content[0].text
        usage = {
            "input_tokens": resp.usage.input_tokens,
            "output_tokens": resp.usage.output_tokens,
            "total_tokens": resp.usage.input_tokens + resp.usage.output_tokens,
            "model": resp.model,
        }
    else:
        # 默认 OpenAI
        client = AsyncOpenAI(api_key=cfg.openai_api_key)
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        resp = await client.chat.completions.create(
            model=cfg.default_model,
            messages=full_messages,  # type: ignore[arg-type]
            temperature=cfg.llm_temperature,
            max_tokens=4096,
        )
        content = resp.choices[0].message.content or ""
        usage = {
            "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
            "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
            "total_tokens": resp.usage.total_tokens if resp.usage else 0,
            "model": resp.model,
        }

    return content, usage
