"""
LangGraph Agent 状态类型定义。

定义了整个多 Agent 流水线的共享状态，使用 TypedDict 约束结构。
消息列表通过 add_messages 减少器支持增量追加。
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from langgraph.graph.message import add_messages


class AgentState(dict):
    """
    LangGraph 状态字典。

    使用普通字典继承以确保与 LangGraph 0.1.x 的兼容性，
    同时通过类型注释提供 IDE 自动补全支持。

    所有字段通过 state.get("key", default) 访问。
    """

    # ── 输入字段 ──────────────────────────────────────────────────────────────
    # user_description: str        用户原始描述
    # cad_parse_result: dict       CAD 解析结果（序列化为 dict）
    # project_id: str              项目 ID

    # ── 对话历史 ──────────────────────────────────────────────────────────────
    # messages: list               消息历史，由 add_messages 累积

    # ── 中间状态 ──────────────────────────────────────────────────────────────
    # extracted_requirements: Optional[dict]   需求理解 Agent 输出
    # missing_info: List[str]                  缺失信息列表
    # user_answers: dict                       用户追问回答

    # ── 设计规划输出 ──────────────────────────────────────────────────────────
    # room_designs: Optional[dict]      每个房间的设计方案
    # material_plan: Optional[dict]     材质方案
    # lighting_plan: Optional[dict]     灯光方案
    # furniture_plan: Optional[dict]    家具方案
    # camera_plan: Optional[dict]       相机方案

    # ── 最终输出 ──────────────────────────────────────────────────────────────
    # full_scene_data: Optional[dict]   完整场景 JSON

    # ── 流程控制 ──────────────────────────────────────────────────────────────
    # current_step: str
    # needs_user_input: bool
    # pending_question: Optional[str]
    # pending_question_field: Optional[str]   对应的 missing_field key
    # error: Optional[str]
    # iteration_count: int


def make_initial_state(
    project_id: str,
    cad_result_dict: dict,
    user_description: str,
    conversation_history: Optional[List[Any]] = None,
) -> AgentState:
    """
    创建 LangGraph 初始状态。

    Args:
        project_id: 项目唯一 ID
        cad_result_dict: CAD 解析结果（来自 CADParseResult.to_dict()）
        user_description: 用户自然语言描述
        conversation_history: 已有的对话消息列表（可选）

    Returns:
        完整初始化的 AgentState 字典
    """
    state = AgentState()
    state["project_id"] = project_id
    state["cad_parse_result"] = cad_result_dict or {}
    state["user_description"] = user_description
    state["messages"] = conversation_history or []
    state["extracted_requirements"] = None
    state["missing_info"] = []
    state["user_answers"] = {}
    state["room_designs"] = None
    state["material_plan"] = None
    state["lighting_plan"] = None
    state["furniture_plan"] = None
    state["camera_plan"] = None
    state["full_scene_data"] = None
    state["current_step"] = "start"
    state["needs_user_input"] = False
    state["pending_question"] = None
    state["pending_question_field"] = None
    state["error"] = None
    state["iteration_count"] = 0
    return state
