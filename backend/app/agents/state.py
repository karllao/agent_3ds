"""
LangGraph Agent 状态类型定义。

LangGraph 通过 TypedDict 的字段声明判断节点返回值里允许写入哪些 key —
裸 dict 子类会让它见到空字段列表，第一个节点写回 state 时报：
    "Must write to at least one of []"
所以这里必须显式列出所有字段。

`messages` 用 `Annotated[..., add_messages]` 让 LangGraph 在多轮中按 reducer
追加而不是覆盖。
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    # ── 输入字段 ──────────────────────────────────────────────────────────────
    project_id: str
    cad_parse_result: Dict[str, Any]
    user_description: str

    # ── 对话历史（LangGraph 的 add_messages reducer 会做增量追加）─────────────
    messages: Annotated[List[BaseMessage], add_messages]

    # ── 中间状态 ──────────────────────────────────────────────────────────────
    extracted_requirements: Optional[Dict[str, Any]]
    missing_info: List[str]
    user_answers: Dict[str, str]

    # ── 设计规划输出 ──────────────────────────────────────────────────────────
    room_designs: Optional[Dict[str, Any]]
    material_plan: Optional[Dict[str, Any]]
    lighting_plan: Optional[Dict[str, Any]]
    furniture_plan: Optional[Dict[str, Any]]
    camera_plan: Optional[Dict[str, Any]]

    # ── 最终输出 ──────────────────────────────────────────────────────────────
    full_scene_data: Optional[Dict[str, Any]]

    # ── 流程控制 ──────────────────────────────────────────────────────────────
    current_step: str
    needs_user_input: bool
    pending_question: Optional[str]
    pending_question_field: Optional[str]
    error: Optional[str]
    iteration_count: int


def make_initial_state(
    project_id: str,
    cad_result_dict: dict,
    user_description: str,
    conversation_history: Optional[List[Any]] = None,
) -> AgentState:
    """
    创建 LangGraph 初始状态。TypedDict 在运行期就是 dict，可以直接 dict 字面量构造。
    """
    return {
        "project_id": project_id,
        "cad_parse_result": cad_result_dict or {},
        "user_description": user_description,
        "messages": conversation_history or [],
        "extracted_requirements": None,
        "missing_info": [],
        "user_answers": {},
        "room_designs": None,
        "material_plan": None,
        "lighting_plan": None,
        "furniture_plan": None,
        "camera_plan": None,
        "full_scene_data": None,
        "current_step": "start",
        "needs_user_input": False,
        "pending_question": None,
        "pending_question_field": None,
        "error": None,
        "iteration_count": 0,
    }
