"""
LangGraph 多 Agent 状态机编排。

将所有 Agent 组成有向状态图，处理：
- 需求提取 → 追问 → 设计 → 组装 → 验证
- 条件路由（有缺失信息 → 追问，信息完整 → 设计）
- 追问等待用户输入（中断并恢复）
- 错误处理和最大迭代保护

图结构：
    requirement_agent
        ├─ (有缺失信息) → clarification_agent → END (等待用户输入)
        └─ (信息完整)  → design_agent → scene_assembler → validation_agent → END

恢复流程：
    continue_with_user_answer(state, answer)
        → 更新 user_answers → 重新运行整个图（从 requirement_agent 开始）
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph
from loguru import logger

from .clarification_agent import ClarificationAgent
from .design_agent import DesignAgent
from .requirement_agent import RequirementAgent
from .scene_assembler import SceneAssembler
from .state import AgentState, make_initial_state
from .validation_agent import ValidationAgent

# ── LLM 初始化 ────────────────────────────────────────────────────────────────


def _create_llm(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    temperature: float = 0.2,
) -> Any:
    """
    根据配置创建 LangChain LLM 实例。

    优先级：
    1. 参数传入的 provider/model
    2. 环境变量 DEFAULT_LLM_PROVIDER / DEFAULT_MODEL
    3. 默认使用 OpenAI gpt-4o

    Args:
        provider: "openai" | "anthropic"
        model: 模型名称
        temperature: 温度

    Returns:
        LangChain Chat LLM 实例
    """
    # 从 config 加载（避免循环导入，用 lazy import）
    try:
        from app.config import get_settings

        settings = get_settings()
        effective_provider = provider or settings.default_llm_provider
        effective_model = model or settings.default_model
        effective_temp = temperature if temperature != 0.2 else settings.llm_temperature
        openai_key = settings.openai_api_key
        anthropic_key = settings.anthropic_api_key
        openai_base_url = settings.openai_base_url
        anthropic_base_url = settings.anthropic_base_url
    except Exception:
        # 回退到环境变量
        effective_provider = provider or os.getenv("DEFAULT_LLM_PROVIDER", "openai")
        effective_model = model or os.getenv("DEFAULT_MODEL", "gpt-4o")
        effective_temp = temperature
        openai_key = os.getenv("OPENAI_API_KEY", "")
        anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
        openai_base_url = os.getenv("OPENAI_BASE_URL", "")
        anthropic_base_url = os.getenv("ANTHROPIC_BASE_URL", "")

    logger.info(
        f"[Graph] 初始化 LLM：provider={effective_provider}, model={effective_model}, "
        f"base_url={(anthropic_base_url if effective_provider == 'anthropic' else openai_base_url) or '<default>'}"
    )

    if effective_provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        kwargs: dict[str, Any] = {
            "model": effective_model or "claude-3-5-sonnet-20241022",
            "api_key": anthropic_key,
            "temperature": effective_temp,
            "max_tokens": 4096,
        }
        if anthropic_base_url:
            kwargs["base_url"] = anthropic_base_url
        return ChatAnthropic(**kwargs)
    else:
        from langchain_openai import ChatOpenAI

        kwargs: dict[str, Any] = {
            "model": effective_model or "gpt-4o",
            "api_key": openai_key,
            "temperature": effective_temp,
            "max_tokens": 4096,
        }
        if openai_base_url:
            kwargs["base_url"] = openai_base_url
        return ChatOpenAI(**kwargs)


# ── 图构建函数 ────────────────────────────────────────────────────────────────


def create_agent_graph(llm: Optional[Any] = None) -> Any:
    """
    构建并编译 LangGraph 多 Agent 状态机。

    Args:
        llm: 可选的 LangChain LLM 实例，如果不传则自动从配置创建

    Returns:
        编译好的 CompiledGraph 对象
    """
    if llm is None:
        llm = _create_llm()

    # ── 实例化所有 Agent ───────────────────────────────────────────────────────
    requirement_agent = RequirementAgent(llm)
    clarification_agent = ClarificationAgent(llm)
    design_agent = DesignAgent(llm)
    scene_assembler = SceneAssembler()
    validation_agent = ValidationAgent()

    # ── 包装成 LangGraph 节点函数 ──────────────────────────────────────────────
    # LangGraph 0.1.x 的节点函数签名：(state: dict) -> dict
    # 返回值是对 state 的完整更新（非增量，直接替换整个 state）

    async def requirement_node(state: AgentState) -> AgentState:
        logger.debug("[Graph] 进入节点: requirement_agent")
        return await requirement_agent.run(state)

    async def clarification_node(state: AgentState) -> AgentState:
        logger.debug("[Graph] 进入节点: clarification_agent")
        return await clarification_agent.run(state)

    async def design_node(state: AgentState) -> AgentState:
        logger.debug("[Graph] 进入节点: design_agent")
        return await design_agent.run(state)

    async def assembler_node(state: AgentState) -> AgentState:
        logger.debug("[Graph] 进入节点: scene_assembler")
        return await scene_assembler.run(state)

    async def validation_node(state: AgentState) -> AgentState:
        logger.debug("[Graph] 进入节点: validation_agent")
        return await validation_agent.run(state)

    # ── 路由函数 ──────────────────────────────────────────────────────────────

    def route_after_requirement(state: AgentState) -> str:
        """
        需求提取完成后的路由决策：
        - 有缺失信息且未超出迭代次数 → clarification
        - 信息完整或已超出迭代次数 → design
        """
        needs_input = state.get("needs_user_input", False)
        missing_info = state.get("missing_info", [])
        iteration_count = state.get("iteration_count", 0)
        error = state.get("error")

        if error and not state.get("extracted_requirements"):
            # 需求提取完全失败，直接进入设计（使用默认值）
            logger.warning("[Graph] 需求提取失败，使用默认值进行设计")
            return "design"

        if needs_input and missing_info and iteration_count < 5:
            logger.info(
                f"[Graph] 路由 → clarification（缺失：{missing_info}，迭代 {iteration_count}）"
            )
            return "clarification"

        logger.info("[Graph] 路由 → design（信息完整或已达最大迭代次数）")
        return "design"

    # ── 构建图 ────────────────────────────────────────────────────────────────
    graph = StateGraph(AgentState)

    # 添加节点
    graph.add_node("requirement_agent", requirement_node)
    graph.add_node("clarification_agent", clarification_node)
    graph.add_node("design_agent", design_node)
    graph.add_node("scene_assembler", assembler_node)
    graph.add_node("validation_agent", validation_node)

    # 设置入口节点
    graph.set_entry_point("requirement_agent")

    # 条件路由：requirement_agent → clarification 或 design
    graph.add_conditional_edges(
        "requirement_agent",
        route_after_requirement,
        {
            "clarification": "clarification_agent",
            "design": "design_agent",
        },
    )

    # clarification_agent → END（等待用户输入，由 API 层恢复）
    graph.add_edge("clarification_agent", END)

    # 设计 → 组装 → 验证 → 结束
    graph.add_edge("design_agent", "scene_assembler")
    graph.add_edge("scene_assembler", "validation_agent")
    graph.add_edge("validation_agent", END)

    logger.info("[Graph] LangGraph 图构建完成，开始编译...")
    compiled = graph.compile()
    logger.success("[Graph] LangGraph 图编译成功")
    return compiled


# ── 顶层流水线函数 ─────────────────────────────────────────────────────────────


async def run_agent_pipeline(
    project_id: str,
    cad_result_dict: dict,
    user_description: str,
    conversation_history: Optional[List[Any]] = None,
    llm: Optional[Any] = None,
    llm_provider: Optional[str] = None,
    llm_model: Optional[str] = None,
) -> dict:
    """
    运行完整的多 Agent 流水线。

    Args:
        project_id: 项目唯一 ID
        cad_result_dict: CAD 解析结果 dict（来自 CADParseResult.to_dict()）
        user_description: 用户自然语言描述
        conversation_history: 已有的对话历史（可选）
        llm: 可选的 LangChain LLM 实例
        llm_provider: LLM 提供商（"openai" | "anthropic"）
        llm_model: 具体模型名称

    Returns:
        结果字典，结构：
        {
            "status": "completed" | "needs_user_input" | "error",
            "full_scene_data": dict | None,
            "pending_question": str | None,
            "pending_question_field": str | None,
            "state_snapshot": dict,  # 用于 continue_with_user_answer
            "warnings": list[str],
            "error": str | None,
        }
    """
    logger.info(
        f"[Pipeline] 开始运行，项目 {project_id}，描述：{user_description[:50]}..."
    )

    # 创建 LLM（如果未提供）
    if llm is None:
        llm = _create_llm(provider=llm_provider, model=llm_model)

    # 创建图
    compiled_graph = create_agent_graph(llm)

    # 创建初始状态
    initial_state = make_initial_state(
        project_id=project_id,
        cad_result_dict=cad_result_dict,
        user_description=user_description,
        conversation_history=conversation_history,
    )

    # 运行图
    try:
        final_state = await compiled_graph.ainvoke(initial_state)
    except Exception as e:
        logger.error(f"[Pipeline] 图执行失败：{e}", exc_info=True)
        return {
            "status": "error",
            "full_scene_data": None,
            "pending_question": None,
            "pending_question_field": None,
            "state_snapshot": dict(initial_state),
            "warnings": [],
            "error": str(e),
        }

    # 提取结果
    return _build_pipeline_result(final_state)


async def continue_with_user_answer(
    state_snapshot: dict,
    user_answer: str,
    llm: Optional[Any] = None,
    llm_provider: Optional[str] = None,
    llm_model: Optional[str] = None,
) -> dict:
    """
    用户回答追问后，继续执行流水线。

    Args:
        state_snapshot: 之前流水线返回的 state_snapshot
        user_answer: 用户的回答文本
        llm: 可选的 LLM 实例
        llm_provider: LLM 提供商
        llm_model: 模型名称

    Returns:
        与 run_agent_pipeline 相同结构的结果字典
    """
    logger.info(
        f"[Pipeline] 用户追问回答：{user_answer[:100]}，"
        f"字段：{state_snapshot.get('pending_question_field')}"
    )

    # 从 snapshot 恢复状态
    state = AgentState(state_snapshot)

    # 提取当前待回答的字段
    pending_field = state.get("pending_question_field")
    if not pending_field:
        logger.warning(
            "[Pipeline] state_snapshot 中没有 pending_question_field，"
            "将用户回答存为 'general_answer'"
        )
        pending_field = "general_answer"

    # 更新 user_answers
    user_answers = dict(state.get("user_answers", {}))
    user_answers[pending_field] = user_answer
    state["user_answers"] = user_answers

    # 添加用户消息到历史
    messages = list(state.get("messages", []))
    messages.append(HumanMessage(content=user_answer))
    state["messages"] = messages

    # 重置等待状态
    state["needs_user_input"] = False
    state["pending_question"] = None
    state["pending_question_field"] = None
    state["current_step"] = "start"

    # 创建 LLM（如果未提供）
    if llm is None:
        llm = _create_llm(provider=llm_provider, model=llm_model)

    # 重新运行图
    compiled_graph = create_agent_graph(llm)

    try:
        final_state = await compiled_graph.ainvoke(state)
    except Exception as e:
        logger.error(f"[Pipeline] 继续执行图失败：{e}", exc_info=True)
        return {
            "status": "error",
            "full_scene_data": None,
            "pending_question": None,
            "pending_question_field": None,
            "state_snapshot": dict(state),
            "warnings": [],
            "error": str(e),
        }

    return _build_pipeline_result(final_state)


def _build_pipeline_result(state: AgentState) -> dict:
    """
    从最终 state 构建统一的返回结果字典。

    Args:
        state: 图执行完成后的最终状态

    Returns:
        标准化的结果字典
    """
    needs_input = state.get("needs_user_input", False)
    error = state.get("error")
    full_scene_data = state.get("full_scene_data")

    # 提取警告
    warnings: List[str] = []
    if full_scene_data:
        extra = full_scene_data.get("extra", {})
        warnings = extra.get("warnings", [])

    if needs_input:
        status = "needs_user_input"
        logger.info(
            f"[Pipeline] 等待用户回答：{state.get('pending_question', '')[:80]}"
        )
    elif error and not full_scene_data:
        status = "error"
        logger.error(f"[Pipeline] 流水线错误：{error}")
    else:
        status = "completed"
        logger.success(
            f"[Pipeline] 流水线完成，场景数据大小："
            f"{len(str(full_scene_data)) if full_scene_data else 0} 字符"
        )

    return {
        "status": status,
        "full_scene_data": full_scene_data,
        "pending_question": state.get("pending_question"),
        "pending_question_field": state.get("pending_question_field"),
        "state_snapshot": dict(state),
        "extracted_requirements": state.get("extracted_requirements"),
        "warnings": warnings,
        "error": error,
    }
