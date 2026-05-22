"""
需求理解 Agent。

职责：解析用户自然语言描述，结合 CAD 解析结果，
提取结构化的室内设计需求，并识别缺失的关键信息。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from .prompts import REQUIREMENT_EXTRACT_TEMPLATE, REQUIREMENT_SYSTEM_PROMPT
from .state import AgentState

# 最大迭代次数（防止无限追问循环）
_MAX_ITERATIONS = 5

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


def _extract_json_from_text(text: str) -> dict:
    """
    从 LLM 输出文本中健壮地提取 JSON。

    支持以下格式：
    - 纯 JSON 文本
    - ```json ... ``` 代码块
    - ``` ... ``` 代码块
    - 夹杂说明文字的 JSON
    """
    # 去除首尾空白
    text = text.strip()

    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试提取 ```json ... ``` 块
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 尝试提取最外层花括号
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"无法从 LLM 输出中提取有效 JSON，原始输出：{text[:300]}")


def _build_user_answers_text(user_answers: dict) -> str:
    """将用户回答格式化为 prompt 中的可读文本。"""
    if not user_answers:
        return "（无）"
    lines = []
    field_cn = {
        "floor_height": "层高",
        "render_mood": "渲染氛围",
        "global_style": "整体风格",
        "furniture_level": "家具档次",
    }
    for field, answer in user_answers.items():
        cn_name = field_cn.get(field, field)
        lines.append(f"- {cn_name}：{answer}")
    return "\n".join(lines)


def _parse_floor_height_from_answer(answer: str) -> Optional[float]:
    """
    从用户回答中解析层高数值（转换为 mm）。

    Examples:
        "2.8米" → 2800.0
        "280厘米" → 2800.0
        "2800毫米" → 2800.0
        "3米" → 3000.0
    """
    answer = answer.strip()
    # 匹配 X.X 米 / X米
    m = re.search(r"(\d+(?:\.\d+)?)\s*米", answer)
    if m:
        return float(m.group(1)) * 1000

    # 匹配 厘米
    m = re.search(r"(\d+(?:\.\d+)?)\s*(?:厘米|cm)", answer, re.IGNORECASE)
    if m:
        return float(m.group(1)) * 10

    # 匹配 毫米 或纯数字
    m = re.search(r"(\d{3,4})(?:\s*(?:毫米|mm))?", answer, re.IGNORECASE)
    if m:
        val = float(m.group(1))
        # 如果是 2-4 位数，判断单位
        if val < 100:  # 可能是 2.8 这样的数字，按米处理
            return val * 1000
        elif val < 1000:  # 可能是 280cm
            return val * 10
        else:  # 已是毫米
            return val

    return None


class RequirementAgent:
    """
    需求理解 Agent。

    使用 LLM 从用户自然语言描述中提取结构化的室内设计需求。
    支持多轮追问后的增量更新（通过 user_answers 字段）。
    """

    def __init__(self, llm: Any) -> None:
        """
        Args:
            llm: LangChain LLM 实例（ChatOpenAI / ChatAnthropic 等）
        """
        self._llm = llm

    async def run(self, state: AgentState) -> AgentState:
        """
        执行需求提取。

        Args:
            state: 当前 LangGraph 状态

        Returns:
            更新后的状态（extracted_requirements / missing_info / messages）
        """
        logger.info(
            f"[RequirementAgent] 开始运行，项目 {state.get('project_id')}，"
            f"迭代次数 {state.get('iteration_count', 0)}"
        )

        # 检查是否超过最大迭代次数
        iteration_count = state.get("iteration_count", 0)
        if iteration_count >= _MAX_ITERATIONS:
            logger.warning(
                f"[RequirementAgent] 已达到最大迭代次数 {_MAX_ITERATIONS}，"
                "跳过追问，直接进行设计规划"
            )
            state["missing_info"] = []
            state["needs_user_input"] = False
            state["current_step"] = "design"
            return state

        # ── 1. 提取 CAD 信息 ──────────────────────────────────────────────────
        cad_result = state.get("cad_parse_result", {})
        rooms = cad_result.get("rooms", [])
        scale_info = cad_result.get("scale_info", {})

        room_names = self._format_room_names(rooms)
        room_areas = self._format_room_areas(rooms)
        total_area = sum(r.get("area", 0) for r in rooms)
        cad_floor_height = scale_info.get("floor_height", 2800.0)

        # ── 2. 处理用户追问回答，进行语义预处理 ────────────────────────────
        user_answers = state.get("user_answers", {})
        user_answers_text = _build_user_answers_text(user_answers)

        # 对 floor_height 做特殊解析（用户可能用中文回答）
        if "floor_height" in user_answers and isinstance(
            user_answers["floor_height"], str
        ):
            parsed_h = _parse_floor_height_from_answer(user_answers["floor_height"])
            if parsed_h:
                user_answers = dict(user_answers)
                user_answers["floor_height"] = parsed_h
                logger.debug(
                    f"[RequirementAgent] 解析用户层高回答: "
                    f"{state['user_answers']['floor_height']} → {parsed_h} mm"
                )

        # ── 3. 构建 Prompt ────────────────────────────────────────────────────
        user_prompt = REQUIREMENT_EXTRACT_TEMPLATE.format(
            user_description=state.get("user_description", ""),
            user_answers_text=user_answers_text,
            room_names=room_names,
            room_areas=room_areas,
            total_area=f"{total_area:.1f}",
            cad_floor_height=cad_floor_height,
        )

        messages = [
            SystemMessage(content=REQUIREMENT_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]

        # ── 4. 调用 LLM ──────────────────────────────────────────────────────
        try:
            logger.debug("[RequirementAgent] 调用 LLM 提取需求...")
            response = await self._llm.ainvoke(messages)
            raw_output = response.content
            logger.debug(
                f"[RequirementAgent] LLM 原始输出（前500字符）：{raw_output[:500]}"
            )
        except Exception as e:
            logger.error(f"[RequirementAgent] LLM 调用失败：{e}")
            state["error"] = f"需求提取 LLM 调用失败：{e}"
            state["current_step"] = "requirement_failed"
            # 使用空需求继续流程（尽量不中断）
            state["extracted_requirements"] = self._default_requirements(rooms)
            state["missing_info"] = []
            state["needs_user_input"] = False
            return state

        # ── 5. 解析 LLM 输出 ─────────────────────────────────────────────────
        try:
            requirements = _extract_json_from_text(raw_output)
        except ValueError as e:
            logger.error(f"[RequirementAgent] JSON 解析失败：{e}")
            state["error"] = f"需求提取 JSON 解析失败：{e}"
            state["extracted_requirements"] = self._default_requirements(rooms)
            state["missing_info"] = []
            state["needs_user_input"] = False
            return state

        # ── 6. 吸收用户追问回答（覆盖 LLM 提取结果）───────────────────────
        if "floor_height" in user_answers and user_answers["floor_height"]:
            requirements["floor_height"] = user_answers["floor_height"]
            logger.debug(
                f"[RequirementAgent] 已从 user_answers 吸收层高：{user_answers['floor_height']}"
            )

        # 从 missing_fields 中移除已回答的字段
        missing_fields: List[str] = requirements.get("missing_fields", [])
        answered_keys = set(user_answers.keys())
        missing_fields = [f for f in missing_fields if f not in answered_keys]
        requirements["missing_fields"] = missing_fields

        logger.info(
            f"[RequirementAgent] 提取完成：风格={requirements.get('global_style')}，"
            f"氛围={requirements.get('render_mood')}，"
            f"层高={requirements.get('floor_height')}，"
            f"缺失字段={missing_fields}"
        )

        # ── 7. 更新状态 ───────────────────────────────────────────────────────
        state["extracted_requirements"] = requirements
        state["missing_info"] = missing_fields
        state["needs_user_input"] = len(missing_fields) > 0
        state["current_step"] = "clarification" if missing_fields else "design"
        state["iteration_count"] = iteration_count + 1

        # 更新对话消息
        state["messages"] = state.get("messages", []) + [
            HumanMessage(content=state.get("user_description", "")),
        ]

        return state

    # ── 辅助方法 ──────────────────────────────────────────────────────────────

    def _format_room_names(self, rooms: List[dict]) -> str:
        """将房间列表格式化为中文描述字符串。"""
        if not rooms:
            return "（未识别到房间，请确认 CAD 文件）"
        names = []
        for r in rooms:
            room_type = r.get("room_type", "other")
            cn = _ROOM_TYPE_CN.get(room_type, room_type)
            name = r.get("name", cn)
            names.append(name)
        return "、".join(names)

    def _format_room_areas(self, rooms: List[dict]) -> str:
        """将房间面积格式化为可读字符串。"""
        if not rooms:
            return "（无数据）"
        parts = []
        for r in rooms:
            room_type = r.get("room_type", "other")
            cn = _ROOM_TYPE_CN.get(room_type, room_type)
            name = r.get("name", cn)
            area = r.get("area", 0)
            parts.append(f"{name}约{area:.1f}m²")
        return "、".join(parts)

    def _default_requirements(self, rooms: List[dict]) -> dict:
        """生成默认需求（LLM 失败时的兜底方案）。"""
        room_reqs = {}
        for r in rooms:
            rt = r.get("room_type", "other")
            room_reqs[rt] = {
                "floor_material": "tile",
                "wall_material": "paint",
                "ceiling_type": "flat",
                "style_notes": "",
                "furniture_level": "mid",
                "lighting_mood": "warm",
                "custom_style": None,
            }
        return {
            "global_style": "modern",
            "render_mood": "day_natural",
            "floor_height": 2800.0,
            "wall_thickness": None,
            "room_requirements": room_reqs,
            "special_requests": [],
            "renderer_preference": "vray",
            "needs_render_preview": False,
            "missing_fields": [],
        }
