"""
设计规划 Agent。

职责：结合 CAD 房间信息和用户需求，为每个房间生成完整的设计方案，
包括材质、灯光和家具配置。
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Dict, List, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from loguru import logger

from .prompts import DESIGN_ROOM_TEMPLATE, DESIGN_SYSTEM_PROMPT
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

# 各渲染氛围的灯光强度系数
_MOOD_INTENSITY = {
    "day_natural": 1.6,
    "night_warm": 0.8,
    "night_cool": 1.0,
    "dusk": 0.6,
    "bright": 2.4,
}

# 各风格的默认材质色
_STYLE_DEFAULTS: Dict[str, Dict[str, str]] = {
    "modern": {
        "wall": "#F5F5F0",
        "floor": "#D4CFC8",
        "ceiling": "#FFFFFF",
        "wall_type": "paint",
        "floor_type": "tile",
        "roughness_wall": "0.85",
        "roughness_floor": "0.30",
    },
    "luxury": {
        "wall": "#F0EAD2",
        "floor": "#E8E4D8",
        "ceiling": "#FFFFFF",
        "wall_type": "paint",
        "floor_type": "marble",
        "roughness_wall": "0.70",
        "roughness_floor": "0.15",
    },
    "minimalist": {
        "wall": "#FAFAFA",
        "floor": "#DDD0B8",
        "ceiling": "#FFFFFF",
        "wall_type": "paint",
        "floor_type": "hardwood",
        "roughness_wall": "0.95",
        "roughness_floor": "0.60",
    },
    "nordic": {
        "wall": "#F4F0EB",
        "floor": "#D4B896",
        "ceiling": "#FAFAFA",
        "wall_type": "paint",
        "floor_type": "hardwood",
        "roughness_wall": "0.88",
        "roughness_floor": "0.55",
    },
    "chinese": {
        "wall": "#F2ECD8",
        "floor": "#D8C8A0",
        "ceiling": "#F5EED5",
        "wall_type": "paint",
        "floor_type": "tile",
        "roughness_wall": "0.90",
        "roughness_floor": "0.25",
    },
    "japanese": {
        "wall": "#F5F0E8",
        "floor": "#C8A878",
        "ceiling": "#FAFAFA",
        "wall_type": "paint",
        "floor_type": "hardwood",
        "roughness_wall": "0.92",
        "roughness_floor": "0.60",
    },
    "industrial": {
        "wall": "#808080",
        "floor": "#484848",
        "ceiling": "#606060",
        "wall_type": "concrete",
        "floor_type": "concrete",
        "roughness_wall": "0.90",
        "roughness_floor": "0.50",
    },
    "rural": {
        "wall": "#F0E8D8",
        "floor": "#C07850",
        "ceiling": "#F5EDD5",
        "wall_type": "paint",
        "floor_type": "tile",
        "roughness_wall": "0.90",
        "roughness_floor": "0.60",
    },
}


def _extract_json_from_text(text: str) -> dict:
    """从 LLM 输出中健壮提取 JSON。"""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except json.JSONDecodeError:
            pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(f"无法从 LLM 输出中提取 JSON：{text[:400]}")


def _round_up_even(n: float) -> int:
    """向上取偶数（用于灯具数量计算）。"""
    n_ceil = math.ceil(n)
    return n_ceil if n_ceil % 2 == 0 else n_ceil + 1


class DesignAgent:
    """
    设计规划 Agent。

    使用 LLM 对每个房间生成完整的材质、灯光、家具设计方案。
    所有房间在一次 LLM 调用中批量处理。
    """

    def __init__(self, llm: Any) -> None:
        """
        Args:
            llm: LangChain LLM 实例
        """
        self._llm = llm

    async def run(self, state: AgentState) -> AgentState:
        """
        执行设计规划。

        Args:
            state: 当前 LangGraph 状态

        Returns:
            更新了 room_designs / material_plan / lighting_plan /
            furniture_plan / camera_plan 的状态
        """
        logger.info(f"[DesignAgent] 开始设计规划，项目 {state.get('project_id')}")

        # 获取提取的需求
        requirements = state.get("extracted_requirements") or {}
        global_style = requirements.get("global_style", "modern")
        render_mood = requirements.get("render_mood", "day_natural")
        floor_height = requirements.get("floor_height") or 2800.0
        renderer = requirements.get("renderer_preference", "vray")
        special_requests = requirements.get("special_requests", [])
        room_requirements = requirements.get("room_requirements", {})

        # 获取 CAD 房间信息
        cad_result = state.get("cad_parse_result", {})
        rooms = cad_result.get("rooms", [])

        if not rooms:
            logger.warning("[DesignAgent] CAD 未识别到任何房间，将生成空设计")
            state["room_designs"] = {}
            state["material_plan"] = {}
            state["lighting_plan"] = {}
            state["furniture_plan"] = {}
            state["camera_plan"] = {}
            state["current_step"] = "assemble"
            return state

        # ── 构建 Prompt ──────────────────────────────────────────────────────
        rooms_info = self._format_rooms_info(rooms)
        room_reqs_text = self._format_room_requirements(room_requirements, rooms)
        special_text = "、".join(special_requests) if special_requests else "无特殊需求"

        user_prompt = DESIGN_ROOM_TEMPLATE.format(
            global_style=global_style,
            render_mood=render_mood,
            floor_height=int(floor_height),
            renderer=renderer,
            special_requests=special_text,
            rooms_info=rooms_info,
            room_requirements=room_reqs_text,
        )

        messages = [
            SystemMessage(content=DESIGN_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]

        # ── 调用 LLM ────────────────────────────────────────────────────────
        try:
            logger.debug("[DesignAgent] 调用 LLM 生成设计方案...")
            response = await self._llm.ainvoke(messages)
            raw_output = response.content
            logger.debug(f"[DesignAgent] LLM 原始输出（前600字符）：{raw_output[:600]}")
        except Exception as e:
            logger.error(f"[DesignAgent] LLM 调用失败：{e}")
            state["error"] = f"设计规划 LLM 调用失败：{e}"
            # 生成默认设计方案
            room_designs = self._generate_default_designs(
                rooms, global_style, render_mood, floor_height, room_requirements
            )
            state["room_designs"] = room_designs
            state["material_plan"] = {}
            state["lighting_plan"] = {}
            state["furniture_plan"] = {}
            state["camera_plan"] = {}
            state["current_step"] = "assemble"
            return state

        # ── 解析 LLM 输出 ────────────────────────────────────────────────────
        try:
            room_designs = _extract_json_from_text(raw_output)
        except ValueError as e:
            logger.error(f"[DesignAgent] JSON 解析失败：{e}")
            state["error"] = f"设计规划 JSON 解析失败：{e}"
            room_designs = self._generate_default_designs(
                rooms, global_style, render_mood, floor_height, room_requirements
            )

        # ── 后处理：补充缺失字段、修正数值 ──────────────────────────────────
        room_designs = self._post_process_designs(
            room_designs, rooms, global_style, render_mood, floor_height
        )

        logger.info(
            f"[DesignAgent] 设计完成，共 {len(room_designs)} 个房间类型：{list(room_designs.keys())}"
        )

        # ── 派生子计划（scene_assembler 会从 room_designs 直接读取） ──────────
        material_plan = self._extract_material_plan(room_designs, global_style)
        lighting_plan = self._extract_lighting_plan(room_designs, render_mood)
        furniture_plan = self._extract_furniture_plan(room_designs)
        camera_plan = self._generate_camera_plan(rooms)

        # ── 更新状态 ─────────────────────────────────────────────────────────
        state["room_designs"] = room_designs
        state["material_plan"] = material_plan
        state["lighting_plan"] = lighting_plan
        state["furniture_plan"] = furniture_plan
        state["camera_plan"] = camera_plan
        state["current_step"] = "assemble"

        return state

    # ── 格式化辅助 ────────────────────────────────────────────────────────────

    def _format_rooms_info(self, rooms: List[dict]) -> str:
        """将 CAD 房间信息格式化为 prompt 中的可读文本。"""
        lines = []
        for r in rooms:
            room_type = r.get("room_type", "other")
            cn = _ROOM_TYPE_CN.get(room_type, room_type)
            name = r.get("name", cn)
            area = r.get("area", 0)
            lines.append(f"- {name}（{room_type}）：面积 {area:.1f} m²")
        return "\n".join(lines) if lines else "（无房间信息）"

    def _format_room_requirements(self, room_reqs: dict, rooms: List[dict]) -> str:
        """将用户对每个房间的需求格式化为 prompt 文本。"""
        if not room_reqs:
            return "（用户未提供具体房间需求，请根据风格自动选择）"
        lines = []
        for room_type, reqs in room_reqs.items():
            cn = _ROOM_TYPE_CN.get(room_type, room_type)
            line_parts = [f"**{cn}**（{room_type}）："]
            if reqs.get("floor_material"):
                line_parts.append(f"地面={reqs['floor_material']}")
            if reqs.get("wall_material"):
                line_parts.append(f"墙面={reqs['wall_material']}")
            if reqs.get("ceiling_type"):
                line_parts.append(f"天花={reqs['ceiling_type']}")
            if reqs.get("furniture_level"):
                line_parts.append(f"家具档次={reqs['furniture_level']}")
            if reqs.get("lighting_mood"):
                line_parts.append(f"灯光氛围={reqs['lighting_mood']}")
            if reqs.get("style_notes"):
                line_parts.append(f"备注：{reqs['style_notes']}")
            lines.append("  ".join(line_parts))
        return "\n".join(lines)

    # ── 后处理 ────────────────────────────────────────────────────────────────

    def _post_process_designs(
        self,
        room_designs: dict,
        rooms: List[dict],
        global_style: str,
        render_mood: str,
        floor_height: float,
    ) -> dict:
        """
        对 LLM 输出的 room_designs 进行后处理：
        - 补充 ceiling_height（如果 LLM 未设置）
        - 计算合理的筒灯数量（基于实际面积）
        - 调整灯光强度（根据 render_mood）
        - 确保所有房间类型都有设计（未设计的用默认值补全）
        """
        defaults = _STYLE_DEFAULTS.get(global_style, _STYLE_DEFAULTS["modern"])
        mood_factor = _MOOD_INTENSITY.get(render_mood, 1.0)

        # 获取所有实际房间类型（去重）
        room_type_areas: Dict[str, float] = {}
        for r in rooms:
            rt = r.get("room_type", "other")
            room_type_areas[rt] = room_type_areas.get(rt, 0) + r.get("area", 0)

        # 对已有的设计做后处理
        for room_type, design in room_designs.items():
            if not isinstance(design, dict):
                continue

            # 补全 ceiling_height
            if not design.get("ceiling_height"):
                design["ceiling_height"] = int(floor_height)

            # 修正灯光数量（基于实际面积）
            area = room_type_areas.get(room_type, 15.0)
            ls = design.get("lighting_scheme", {})
            primary = ls.get("primary", {})
            if isinstance(primary, dict) and primary.get("type") == "downlight":
                recommended_count = _round_up_even(area / 3.0)
                recommended_count = max(2, min(recommended_count, 16))
                primary["count"] = recommended_count
                # 调整强度
                base_intensity = primary.get("intensity", 500)
                primary["intensity"] = int(base_intensity * mood_factor)

            # 补全材质默认值
            fm = design.get("floor_material")
            if not fm or not isinstance(fm, dict):
                design["floor_material"] = {
                    "type": defaults["floor_type"],
                    "color": defaults["floor"],
                    "texture_preset": f"{global_style}_floor",
                    "roughness": float(defaults["roughness_floor"]),
                    "metallic": 0.0,
                    "uv_scale": 2.0,
                }

            wm = design.get("wall_material")
            if not wm or not isinstance(wm, dict):
                design["wall_material"] = {
                    "type": defaults["wall_type"],
                    "color": defaults["wall"],
                    "texture_preset": f"{global_style}_wall",
                    "roughness": float(defaults["roughness_wall"]),
                    "metallic": 0.0,
                    "uv_scale": 1.0,
                }

        # 为没有设计的房间类型生成默认设计
        for room_type in room_type_areas:
            if room_type not in room_designs:
                area = room_type_areas[room_type]
                room_designs[room_type] = self._default_room_design(
                    room_type, area, global_style, render_mood, floor_height
                )
                logger.debug(f"[DesignAgent] 为 {room_type} 生成兜底默认设计")

        return room_designs

    def _default_room_design(
        self,
        room_type: str,
        area: float,
        style: str,
        mood: str,
        floor_height: float,
    ) -> dict:
        """为单个房间生成默认设计（LLM 未覆盖该房间时使用）。"""
        defaults = _STYLE_DEFAULTS.get(style, _STYLE_DEFAULTS["modern"])
        mood_factor = _MOOD_INTENSITY.get(mood, 1.0)
        downlight_count = _round_up_even(area / 3.0)
        downlight_count = max(2, min(downlight_count, 16))
        base_intensity = int(500 * mood_factor)

        # 不同房间的默认色温
        color_temp_map = {
            "living_room": 3000,
            "dining_room": 3000,
            "master_bedroom": 2700,
            "bedroom": 2700,
            "kitchen": 4000,
            "bathroom": 4000,
            "study": 4000,
        }
        color_temp = color_temp_map.get(room_type, 3000)

        return {
            "floor_material": {
                "type": defaults["floor_type"],
                "color": defaults["floor"],
                "texture_preset": f"{style}_{room_type}_floor",
                "roughness": float(defaults["roughness_floor"]),
                "metallic": 0.0,
                "uv_scale": 2.0,
            },
            "wall_material": {
                "type": defaults["wall_type"],
                "color": defaults["wall"],
                "texture_preset": f"{style}_wall",
                "roughness": float(defaults["roughness_wall"]),
                "metallic": 0.0,
                "uv_scale": 1.0,
            },
            "ceiling_type": "flat",
            "ceiling_height": int(floor_height),
            "lighting_scheme": {
                "primary": {
                    "type": "downlight",
                    "count": downlight_count,
                    "color_temp": color_temp,
                    "intensity": base_intensity,
                    "ies": "downlight_narrow",
                },
                "accent": {
                    "type": "led_strip",
                    "location": "ceiling_cove",
                    "color_temp": 2700,
                    "intensity": int(200 * mood_factor),
                },
            },
            "furniture_list": self._default_furniture(room_type, area, style),
            "special_features": [],
        }

    def _default_furniture(self, room_type: str, area: float, style: str) -> List[dict]:
        """根据房间类型和面积生成默认家具列表。"""
        templates: Dict[str, List[dict]] = {
            "living_room": [
                {"category": "sofa", "placement": "main_wall"},
                {"category": "coffee_table", "placement": "center"},
                {"category": "tv_stand", "placement": "opposite_wall"},
                {"category": "rug", "placement": "center"},
                {"category": "floor_lamp", "placement": "corner"},
            ],
            "master_bedroom": [
                {"category": "bed", "placement": "back_wall"},
                {"category": "cabinet", "placement": "side_wall"},
                {"category": "table", "placement": "bed_side"},
            ],
            "bedroom": [
                {"category": "bed", "placement": "back_wall"},
                {"category": "cabinet", "placement": "side_wall"},
                {"category": "desk", "placement": "corner"},
            ],
            "dining_room": [
                {"category": "dining_table", "placement": "center"},
                {"category": "chair", "placement": "around_table"},
            ],
            "kitchen": [
                {"category": "kitchen_cabinet", "placement": "along_wall"},
                {"category": "appliance", "placement": "counter"},
            ],
            "bathroom": [
                {"category": "appliance", "placement": "wall"},
            ],
            "study": [
                {"category": "desk", "placement": "window_side"},
                {"category": "chair", "placement": "desk_front"},
                {"category": "bookshelf", "placement": "side_wall"},
            ],
        }

        items = templates.get(
            room_type, [{"category": "decoration", "placement": "center"}]
        )
        result = []
        for item in items:
            result.append(
                {
                    "category": item["category"],
                    "style": style,
                    "size_class": "medium",
                    "color": "#A0A0A0",
                    "placement": item["placement"],
                }
            )
        return result

    # ── 派生子计划 ────────────────────────────────────────────────────────────

    def _extract_material_plan(self, room_designs: dict, global_style: str) -> dict:
        """从 room_designs 提炼材质汇总计划。"""
        materials = {}
        for room_type, design in room_designs.items():
            if not isinstance(design, dict):
                continue
            materials[f"{room_type}_floor"] = design.get("floor_material", {})
            materials[f"{room_type}_wall"] = design.get("wall_material", {})
        materials["global_style"] = global_style
        return materials

    def _extract_lighting_plan(self, room_designs: dict, render_mood: str) -> dict:
        """从 room_designs 提炼灯光汇总计划。"""
        lighting = {"render_mood": render_mood}
        for room_type, design in room_designs.items():
            if isinstance(design, dict):
                lighting[room_type] = design.get("lighting_scheme", {})
        return lighting

    def _extract_furniture_plan(self, room_designs: dict) -> dict:
        """从 room_designs 提炼家具汇总计划。"""
        furniture = {}
        for room_type, design in room_designs.items():
            if isinstance(design, dict):
                furniture[room_type] = design.get("furniture_list", [])
        return furniture

    def _generate_camera_plan(self, rooms: List[dict]) -> dict:
        """根据房间列表生成相机规划。"""
        cameras = []
        for r in rooms:
            room_type = r.get("room_type", "other")
            cameras.append(
                {
                    "room_id": r.get("id"),
                    "room_type": room_type,
                    "fov": 60 if room_type in ("living_room", "dining_room") else 55,
                    "position_mode": "corner",  # scene_assembler 根据房间几何计算实际位置
                }
            )
        # 全局鸟瞰相机
        cameras.append(
            {
                "room_id": None,
                "room_type": "overview",
                "fov": 60,
                "position_mode": "top_down",
            }
        )
        return {"cameras": cameras}

    def _generate_default_designs(
        self,
        rooms: List[dict],
        global_style: str,
        render_mood: str,
        floor_height: float,
        room_requirements: dict,
    ) -> dict:
        """LLM 完全失败时，纯代码生成完整的默认设计方案。"""
        room_type_areas: Dict[str, float] = {}
        for r in rooms:
            rt = r.get("room_type", "other")
            room_type_areas[rt] = room_type_areas.get(rt, 0) + r.get("area", 0)

        designs = {}
        for room_type, area in room_type_areas.items():
            designs[room_type] = self._default_room_design(
                room_type, area, global_style, render_mood, floor_height
            )
        return designs
