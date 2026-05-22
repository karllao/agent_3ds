"""
追问澄清 Agent。

职责：当有缺失信息时，针对第一个未回答的缺失字段，
用 LLM 生成友好的中文追问问题，结合 CAD 识别的房间信息使问题更具体。
"""

from __future__ import annotations

from typing import Any, List

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from loguru import logger

from .prompts import CLARIFICATION_SYSTEM_PROMPT, CLARIFICATION_TEMPLATE
from .state import AgentState

# 房间类型中文名映射
_ROOM_TYPE_CN = {
    "living_room": "客厅",
    "bedroom": "卧室",
    "master_bedroom": "主卧",
    "kitchen": "厨房",
    "bathroom": "卫生间",
    "dining_room": "餐厅",
    "study": "书房",
    "balcony": "阳台",
    "corridor": "走廊",
    "storage": "储藏室",
    "other": "其他",
}

# 缺失字段的中文名（用于生成问题上下文）
_FIELD_CN = {
    "floor_height": "层高",
    "render_mood": "渲染氛围/光线效果",
    "global_style": "整体风格",
    "furniture_level": "家具品质档次",
    "wall_thickness": "墙体厚度",
    "needs_render_preview": "是否需要渲染预览图",
    "renderer_preference": "渲染器偏好",
}

# 各字段的预设兜底追问（LLM 失败时使用）
_FALLBACK_QUESTIONS: dict[str, str] = {
    "floor_height": (
        "我已分析您的平面图，请问您希望层高设置为多少？"
        "（常见住宅层高为2.8米，部分楼盘为2.9米或3米，默认2.8米）"
    ),
    "render_mood": (
        "您希望效果图呈现什么光线氛围？"
        "①白天自然光  ②夜晚温馨暖光  ③日落黄昏暖调  ④明亮清爽高亮"
    ),
    "global_style": (
        "请问您整体希望打造什么室内风格？"
        "现代简约、轻奢精致、北欧原木、中式禅意，还是其他风格？"
    ),
    "furniture_level": (
        "您对家具的品质要求如何？①经济实用  ②中档品质  ③中高档品质  ④高端轻奢"
    ),
}


class ClarificationAgent:
    """
    追问澄清 Agent。

    从 missing_info 中取第一个未回答的字段，
    用 LLM 生成结合平面图背景的友好追问。
    """

    def __init__(self, llm: Any) -> None:
        """
        Args:
            llm: LangChain LLM 实例
        """
        self._llm = llm

    async def run(self, state: AgentState) -> AgentState:
        """
        执行追问生成。

        Args:
            state: 当前 LangGraph 状态

        Returns:
            更新了 pending_question / pending_question_field /
            needs_user_input / messages 的状态
        """
        missing_info: List[str] = state.get("missing_info", [])
        user_answers: dict = state.get("user_answers", {})

        if not missing_info:
            logger.info("[ClarificationAgent] 无缺失信息，无需追问")
            state["needs_user_input"] = False
            state["pending_question"] = None
            state["pending_question_field"] = None
            return state

        # 找到第一个未回答的缺失字段
        unanswered = [f for f in missing_info if f not in user_answers]
        if not unanswered:
            logger.info("[ClarificationAgent] 所有缺失字段已回答，无需追问")
            state["needs_user_input"] = False
            state["missing_info"] = []
            state["pending_question"] = None
            state["pending_question_field"] = None
            return state

        target_field = unanswered[0]
        logger.info(f"[ClarificationAgent] 针对字段 '{target_field}' 生成追问")

        # 提取 CAD 房间信息用于上下文
        cad_result = state.get("cad_parse_result", {})
        rooms = cad_result.get("rooms", [])
        room_names = self._format_room_names(rooms)
        room_areas = self._format_room_areas(rooms)
        total_area = sum(r.get("area", 0) for r in rooms)

        # 已回答字段的摘要
        answered_summary = self._format_answered(user_answers)

        # 已提取的全局风格（用于上下文）
        extracted = state.get("extracted_requirements", {}) or {}
        global_style = extracted.get("global_style", "未确定")

        # 构建 Prompt
        user_prompt = CLARIFICATION_TEMPLATE.format(
            missing_field=target_field,
            room_names=room_names,
            room_areas=room_areas,
            total_area=f"{total_area:.1f}",
            user_description=state.get("user_description", ""),
            answered_fields=answered_summary,
            global_style=global_style,
        )

        messages = [
            SystemMessage(content=CLARIFICATION_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]

        # 调用 LLM 生成追问
        question = await self._generate_question(messages, target_field, room_names)

        logger.info(f"[ClarificationAgent] 生成追问：{question}")

        # 更新状态
        state["pending_question"] = question
        state["pending_question_field"] = target_field
        state["needs_user_input"] = True
        state["current_step"] = "waiting_user_input"

        # 将追问添加到消息历史
        state["messages"] = state.get("messages", []) + [
            AIMessage(content=question),
        ]

        return state

    # ── 辅助方法 ──────────────────────────────────────────────────────────────

    async def _generate_question(
        self,
        messages: list,
        target_field: str,
        room_names: str,
    ) -> str:
        """
        调用 LLM 生成追问，失败时使用预设兜底问题。
        """
        try:
            response = await self._llm.ainvoke(messages)
            question = response.content.strip()
            if not question:
                raise ValueError("LLM 返回了空问题")
            return question
        except Exception as e:
            logger.warning(
                f"[ClarificationAgent] LLM 生成追问失败（{e}），使用预设问题"
            )
            # 使用兜底问题，并将房间信息嵌入其中
            fallback = _FALLBACK_QUESTIONS.get(
                target_field,
                f"请提供关于【{_FIELD_CN.get(target_field, target_field)}】的详细信息：",
            )
            # 如果包含 {room_names} 占位符，替换
            return fallback.replace("{room_names}", room_names)

    def _format_room_names(self, rooms: list) -> str:
        """格式化房间名列表。"""
        if not rooms:
            return "（未识别到房间）"
        names = []
        for r in rooms:
            room_type = r.get("room_type", "other")
            cn = _ROOM_TYPE_CN.get(room_type, room_type)
            names.append(r.get("name", cn))
        return "、".join(names)

    def _format_room_areas(self, rooms: list) -> str:
        """格式化房间面积。"""
        if not rooms:
            return "（无数据）"
        parts = []
        for r in rooms:
            room_type = r.get("room_type", "other")
            cn = _ROOM_TYPE_CN.get(room_type, room_type)
            name = r.get("name", cn)
            area = r.get("area", 0)
            parts.append(f"{name}{area:.0f}m²")
        return "、".join(parts)

    def _format_answered(self, user_answers: dict) -> str:
        """格式化已回答字段摘要。"""
        if not user_answers:
            return "（暂无）"
        parts = []
        for k, v in user_answers.items():
            cn = _FIELD_CN.get(k, k)
            parts.append(f"{cn}={v}")
        return "；".join(parts)
