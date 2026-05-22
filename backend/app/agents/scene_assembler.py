"""
场景数据组装器（Scene Assembler）。

职责：纯代码（不依赖 LLM），将所有子设计方案汇总为完整的 FullSceneData。

主要工作：
1. 从 CAD 解析结果读取墙体、房间、门、窗
2. 应用层高到墙体高度
3. DetectedWall → WallConfig（附材质）
4. DetectedRoom → RoomConfig（附材质、类型）
5. DetectedDoor → DoorConfig
6. DetectedWindow → WindowConfig
7. 根据 room_designs 生成 FurnitureConfig 列表（计算位置）
8. 根据 lighting_scheme 生成 LightConfig 列表（计算布灯位置）
9. 为每个主要空间生成 CameraConfig
10. 汇总为 FullSceneData 并序列化
"""

from __future__ import annotations

import math
import uuid
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.schemas.scene import (
    CameraConfig,
    CeilingType,
    ColorRGB,
    DoorConfig,
    DoorType,
    FullSceneData,
    FurnitureCategory,
    FurnitureConfig,
    LightConfig,
    LightType,
    MaterialConfig,
    MaterialType,
    Point2D,
    Point3D,
    RoomConfig,
    RoomType,
    Rotation3D,
    Scale3D,
    SceneConfig,
    SwingDirection,
    UnitSystem,
    WallConfig,
    WindowConfig,
    WindowType,
)

from .state import AgentState

# ── 常量 ─────────────────────────────────────────────────────────────────────
_DEFAULT_FLOOR_HEIGHT = 2800.0
_DEFAULT_WALL_THICKNESS = 240.0
_CEILING_LIGHT_OFFSET = 50.0  # 筒灯距天花板距离（mm）
_PENDANT_HANG_OFFSET = 400.0  # 吊灯悬挂长度（mm）
_CAMERA_EYE_HEIGHT = 1200.0  # 相机眼高（mm）
_CAMERA_CORNER_RATIO = 0.15  # 相机距房间角落的比例


# ── 颜色工具 ─────────────────────────────────────────────────────────────────


def _hex_to_rgb(hex_color: str) -> ColorRGB:
    """将 6 位十六进制颜色字符串转换为 ColorRGB。"""
    hex_color = hex_color.lstrip("#")
    if len(hex_color) != 6:
        return ColorRGB(r=200, g=200, b=200)
    try:
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        return ColorRGB(r=r, g=g, b=b)
    except ValueError:
        return ColorRGB(r=200, g=200, b=200)


# ── FurnitureCategory 映射 ────────────────────────────────────────────────────

_CATEGORY_MAP: Dict[str, FurnitureCategory] = {
    "sofa": FurnitureCategory.SOFA,
    "bed": FurnitureCategory.BED,
    "table": FurnitureCategory.TABLE,
    "chair": FurnitureCategory.CHAIR,
    "desk": FurnitureCategory.DESK,
    "wardrobe": FurnitureCategory.WARDROBE,
    "cabinet": FurnitureCategory.CABINET,
    "bookshelf": FurnitureCategory.BOOKSHELF,
    "tv_stand": FurnitureCategory.TV_STAND,
    "tv_cabinet": FurnitureCategory.TV_STAND,
    "dining_table": FurnitureCategory.DINING_TABLE,
    "kitchen_cabinet": FurnitureCategory.KITCHEN_CABINET,
    "appliance": FurnitureCategory.APPLIANCE,
    "decoration": FurnitureCategory.DECORATION,
    "plant": FurnitureCategory.PLANT,
    "rug": FurnitureCategory.DECORATION,
    "floor_lamp": FurnitureCategory.DECORATION,
    "coffee_table": FurnitureCategory.TABLE,
}

# ── RoomType 映射 ─────────────────────────────────────────────────────────────

_ROOM_TYPE_MAP: Dict[str, RoomType] = {
    "living_room": RoomType.LIVING_ROOM,
    "bedroom": RoomType.BEDROOM,
    "master_bedroom": RoomType.MASTER_BEDROOM,
    "kitchen": RoomType.KITCHEN,
    "bathroom": RoomType.BATHROOM,
    "dining_room": RoomType.DINING_ROOM,
    "study": RoomType.STUDY,
    "balcony": RoomType.BALCONY,
    "corridor": RoomType.CORRIDOR,
    "storage": RoomType.STORAGE,
    "other": RoomType.OTHER,
}

# ── CeilingType 映射 ─────────────────────────────────────────────────────────

_CEILING_TYPE_MAP: Dict[str, CeilingType] = {
    "flat": CeilingType.FLAT,
    "suspended": CeilingType.SUSPENDED,
    "coffered": CeilingType.COFFERED,
    "vaulted": CeilingType.VAULTED,
    "exposed": CeilingType.EXPOSED,
    "coved": CeilingType.SUSPENDED,  # coved 近似 suspended
}


# ── 家具尺寸参考（mm） ────────────────────────────────────────────────────────

_FURNITURE_SIZE: Dict[str, Tuple[float, float, float]] = {
    # (宽, 深, 高) mm
    "sofa": (2200, 900, 800),
    "bed": (1800, 2000, 500),
    "table": (1200, 600, 750),
    "chair": (500, 500, 850),
    "desk": (1400, 700, 750),
    "wardrobe": (2000, 600, 2200),
    "cabinet": (1800, 600, 2100),
    "bookshelf": (1200, 300, 2000),
    "tv_stand": (1800, 450, 500),
    "tv_cabinet": (1800, 450, 500),
    "dining_table": (1400, 800, 750),
    "kitchen_cabinet": (2000, 600, 850),
    "coffee_table": (1200, 600, 400),
    "rug": (2000, 1400, 10),
    "floor_lamp": (400, 400, 1700),
    "appliance": (600, 600, 850),
    "decoration": (300, 300, 500),
}


class SceneAssembler:
    """
    场景数据组装器。

    纯代码实现，不依赖 LLM，将所有设计方案转换为 FullSceneData。
    """

    async def run(self, state: AgentState) -> AgentState:
        """
        执行场景数据组装。

        Args:
            state: 当前 LangGraph 状态

        Returns:
            更新了 full_scene_data 的状态
        """
        logger.info(f"[SceneAssembler] 开始组装场景，项目 {state.get('project_id')}")

        try:
            full_scene_data = self._assemble(state)
            state["full_scene_data"] = full_scene_data.model_dump(mode="json")
            state["current_step"] = "validation"
            logger.success("[SceneAssembler] 场景组装完成")
        except Exception as e:
            logger.error(f"[SceneAssembler] 场景组装失败：{e}", exc_info=True)
            state["error"] = f"场景组装失败：{e}"
            state["current_step"] = "assemble_failed"

        return state

    # ── 核心组装方法 ──────────────────────────────────────────────────────────

    def _assemble(self, state: AgentState) -> FullSceneData:
        """核心组装逻辑，返回 FullSceneData。"""
        cad_result = state.get("cad_parse_result", {})
        room_designs = state.get("room_designs") or {}
        requirements = state.get("extracted_requirements") or {}

        # 全局参数
        floor_height = float(requirements.get("floor_height") or _DEFAULT_FLOOR_HEIGHT)
        global_style = requirements.get("global_style", "modern")
        render_mood = requirements.get("render_mood", "day_natural")
        renderer_pref = requirements.get("renderer_preference", "vray")
        project_id = state.get("project_id", "unknown")

        # ── 1. 场景全局配置 ───────────────────────────────────────────────────
        scene_config = SceneConfig(
            scene_name=f"project_{project_id}",
            unit_system=UnitSystem.MILLIMETER,
            floor_height=floor_height,
            style=global_style,
            renderer=self._normalize_renderer(renderer_pref),
            ambient_light_intensity=self._get_ambient_intensity(render_mood),
            background_color=self._get_bg_color(render_mood),
        )

        # ── 2. 材质库 ─────────────────────────────────────────────────────────
        materials = self._build_materials(room_designs, global_style)
        mat_index = {m.id: m for m in materials}

        # ── 3. 墙体 ───────────────────────────────────────────────────────────
        cad_walls = cad_result.get("walls", [])
        walls = self._build_walls(cad_walls, floor_height, mat_index)

        # ── 4. 房间 ───────────────────────────────────────────────────────────
        cad_rooms = cad_result.get("rooms", [])
        rooms = self._build_rooms(cad_rooms, room_designs, floor_height, mat_index)
        room_id_to_type = {r.id: r.type.value for r in rooms}

        # ── 5. 门 ─────────────────────────────────────────────────────────────
        cad_doors = cad_result.get("doors", [])
        valid_wall_ids = {w.id for w in walls}
        doors = self._build_doors(cad_doors, floor_height, valid_wall_ids)

        # ── 6. 窗 ─────────────────────────────────────────────────────────────
        cad_windows = cad_result.get("windows", [])
        windows = self._build_windows(cad_windows, floor_height, valid_wall_ids)

        # ── 7. 家具 ───────────────────────────────────────────────────────────
        furniture = self._build_furniture(cad_rooms, room_designs, global_style)

        # ── 8. 灯光 ───────────────────────────────────────────────────────────
        lights = self._build_lights(cad_rooms, room_designs, floor_height, render_mood)

        # ── 9. 相机 ───────────────────────────────────────────────────────────
        cameras = self._build_cameras(cad_rooms, room_designs, floor_height, cad_result)

        return FullSceneData(
            scene_config=scene_config,
            materials=materials,
            walls=walls,
            rooms=rooms,
            doors=doors,
            windows=windows,
            furniture=furniture,
            lights=lights,
            cameras=cameras,
            extra={
                "project_id": project_id,
                "global_style": global_style,
                "render_mood": render_mood,
                "cad_summary": cad_result.get("summary", {}),
            },
        )

    # ── 材质构建 ──────────────────────────────────────────────────────────────

    def _build_materials(
        self, room_designs: dict, global_style: str
    ) -> List[MaterialConfig]:
        """构建场景所有材质配置。"""
        mats: List[MaterialConfig] = []
        seen_ids: set = set()

        # 通用固定材质
        fixed_mats = [
            MaterialConfig(
                id="mat_ceiling_white",
                name="天花板白色乳胶漆",
                type=MaterialType.PHYSICAL,
                color=ColorRGB(r=255, g=255, b=255),
                roughness=0.92,
                metallic=0.0,
            ),
            MaterialConfig(
                id="mat_door_wood",
                name="木门面板",
                type=MaterialType.PHYSICAL,
                color=ColorRGB(r=160, g=120, b=80),
                roughness=0.6,
                metallic=0.0,
            ),
            MaterialConfig(
                id="mat_door_frame",
                name="门框",
                type=MaterialType.PHYSICAL,
                color=ColorRGB(r=240, g=235, b=225),
                roughness=0.7,
                metallic=0.0,
            ),
            MaterialConfig(
                id="mat_glass_clear",
                name="透明玻璃",
                type=MaterialType.PHYSICAL,
                color=ColorRGB(r=220, g=235, b=245),
                roughness=0.05,
                metallic=0.0,
                ior=1.52,
                opacity=0.1,
            ),
            MaterialConfig(
                id="mat_window_frame",
                name="窗框",
                type=MaterialType.PHYSICAL,
                color=ColorRGB(r=240, g=240, b=240),
                roughness=0.5,
                metallic=0.1,
            ),
            MaterialConfig(
                id="mat_curtain_white",
                name="白色窗帘",
                type=MaterialType.PHYSICAL,
                color=ColorRGB(r=248, g=246, b=240),
                roughness=0.9,
                metallic=0.0,
                opacity=0.85,
            ),
        ]
        for m in fixed_mats:
            if m.id not in seen_ids:
                mats.append(m)
                seen_ids.add(m.id)

        # 根据 room_designs 生成各房间的地面和墙面材质
        for room_type, design in room_designs.items():
            if not isinstance(design, dict):
                continue

            # 地面材质
            floor_mat_data = design.get("floor_material", {})
            floor_mat_id = f"mat_floor_{room_type}"
            if floor_mat_id not in seen_ids:
                floor_color_hex = floor_mat_data.get("color", "#C8C0B0")
                floor_roughness = float(floor_mat_data.get("roughness", 0.4))
                mats.append(
                    MaterialConfig(
                        id=floor_mat_id,
                        name=f"{room_type} 地面",
                        type=MaterialType.PHYSICAL,
                        color=_hex_to_rgb(floor_color_hex),
                        roughness=floor_roughness,
                        metallic=float(floor_mat_data.get("metallic", 0.0)),
                        uv_scale=Scale3D(
                            x=float(floor_mat_data.get("uv_scale", 2.0)),
                            y=float(floor_mat_data.get("uv_scale", 2.0)),
                            z=1.0,
                        ),
                    )
                )
                seen_ids.add(floor_mat_id)

            # 墙面材质
            wall_mat_data = design.get("wall_material", {})
            wall_mat_id = f"mat_wall_{room_type}"
            if wall_mat_id not in seen_ids:
                wall_color_hex = wall_mat_data.get("color", "#F5F5F0")
                wall_roughness = float(wall_mat_data.get("roughness", 0.85))
                mats.append(
                    MaterialConfig(
                        id=wall_mat_id,
                        name=f"{room_type} 墙面",
                        type=MaterialType.PHYSICAL,
                        color=_hex_to_rgb(wall_color_hex),
                        roughness=wall_roughness,
                        metallic=float(wall_mat_data.get("metallic", 0.0)),
                    )
                )
                seen_ids.add(wall_mat_id)

        # 确保有默认墙面和地面材质
        if "mat_wall_default" not in seen_ids:
            mats.append(
                MaterialConfig(
                    id="mat_wall_default",
                    name="默认墙面",
                    type=MaterialType.PHYSICAL,
                    color=ColorRGB(r=245, g=245, b=240),
                    roughness=0.85,
                )
            )
            seen_ids.add("mat_wall_default")

        if "mat_floor_default" not in seen_ids:
            mats.append(
                MaterialConfig(
                    id="mat_floor_default",
                    name="默认地面",
                    type=MaterialType.PHYSICAL,
                    color=ColorRGB(r=212, g=207, b=200),
                    roughness=0.35,
                )
            )
            seen_ids.add("mat_floor_default")

        logger.debug(f"[SceneAssembler] 生成材质 {len(mats)} 个")
        return mats

    # ── 墙体构建 ──────────────────────────────────────────────────────────────

    def _build_walls(
        self,
        cad_walls: List[dict],
        floor_height: float,
        mat_index: dict,
    ) -> List[WallConfig]:
        """将 CAD 墙体转换为 WallConfig 列表。"""
        walls: List[WallConfig] = []
        for i, w in enumerate(cad_walls):
            wall_id = w.get("id") or f"wall_{i:04d}"
            start_raw = w.get("start", {})
            end_raw = w.get("end", {})

            # 选择墙面材质（优先使用通用 wall_default）
            mat_id = "mat_wall_default"

            walls.append(
                WallConfig(
                    id=wall_id,
                    start=Point2D(
                        x=float(start_raw.get("x", 0)),
                        y=float(start_raw.get("y", 0)),
                    ),
                    end=Point2D(
                        x=float(end_raw.get("x", 0)),
                        y=float(end_raw.get("y", 0)),
                    ),
                    thickness=float(w.get("thickness", _DEFAULT_WALL_THICKNESS)),
                    height=floor_height,
                    material=mat_id,
                    is_exterior=False,
                )
            )
        logger.debug(f"[SceneAssembler] 生成墙体 {len(walls)} 段")
        return walls

    # ── 房间构建 ──────────────────────────────────────────────────────────────

    def _build_rooms(
        self,
        cad_rooms: List[dict],
        room_designs: dict,
        floor_height: float,
        mat_index: dict,
    ) -> List[RoomConfig]:
        """将 CAD 房间转换为 RoomConfig 列表。"""
        rooms: List[RoomConfig] = []
        for r in cad_rooms:
            room_id = r.get("id") or f"room_{uuid.uuid4().hex[:8]}"
            room_type_str = r.get("room_type", "other")
            room_type = _ROOM_TYPE_MAP.get(room_type_str, RoomType.OTHER)
            name = r.get("name", room_type_str)
            area = float(r.get("area", 1.0))

            boundary_raw = r.get("boundary", [])
            if len(boundary_raw) < 3:
                logger.warning(f"[SceneAssembler] 房间 {room_id} 边界点不足3个，跳过")
                continue

            boundary = [
                Point2D(x=float(p.get("x", 0)), y=float(p.get("y", 0)))
                for p in boundary_raw
            ]

            # 材质选择：优先使用该房间类型的专属材质
            floor_mat_id = (
                f"mat_floor_{room_type_str}"
                if f"mat_floor_{room_type_str}" in mat_index
                else "mat_floor_default"
            )
            wall_mat_id = (
                f"mat_wall_{room_type_str}"
                if f"mat_wall_{room_type_str}" in mat_index
                else "mat_wall_default"
            )

            # 天花板类型
            design = room_designs.get(room_type_str, {})
            ceiling_type_str = design.get("ceiling_type", "flat") if design else "flat"
            ceiling_type = _CEILING_TYPE_MAP.get(ceiling_type_str, CeilingType.FLAT)
            ceiling_height = design.get("ceiling_height") if design else None

            rooms.append(
                RoomConfig(
                    id=room_id,
                    name=name,
                    type=room_type,
                    boundary=boundary,
                    area=area,
                    floor_material=floor_mat_id,
                    ceiling_material="mat_ceiling_white",
                    ceiling_type=ceiling_type,
                    ceiling_height=float(ceiling_height) if ceiling_height else None,
                )
            )
        logger.debug(f"[SceneAssembler] 生成房间 {len(rooms)} 个")
        return rooms

    # ── 门构建 ────────────────────────────────────────────────────────────────

    def _build_doors(
        self,
        cad_doors: List[dict],
        floor_height: float,
        valid_wall_ids: set,
    ) -> List[DoorConfig]:
        """将 CAD 门转换为 DoorConfig 列表。"""
        doors: List[DoorConfig] = []
        for d in cad_doors:
            door_id = d.get("id") or f"door_{uuid.uuid4().hex[:8]}"
            wall_id = d.get("wall_id", "")

            # 验证 wall_id 有效性
            if wall_id not in valid_wall_ids:
                logger.debug(
                    f"[SceneAssembler] 门 {door_id} 关联的 wall_id={wall_id} 无效，使用 wall_unknown"
                )
                wall_id = wall_id or "wall_unknown"

            center = d.get("center", {})
            doors.append(
                DoorConfig(
                    id=door_id,
                    wall_id=wall_id,
                    position=Point3D(
                        x=float(center.get("x", 0)),
                        y=float(center.get("y", 0)),
                        z=float(d.get("floor_offset", 0)),
                    ),
                    width=float(d.get("width", 900.0)),
                    height=float(d.get("height", 2100.0)),
                    floor_offset=float(d.get("floor_offset", 0)),
                    swing_direction=self._parse_swing_direction(
                        d.get("swing_direction", "left")
                    ),
                    door_type=self._parse_door_type(d.get("door_type", "single")),
                    material="mat_door_wood",
                    frame_material="mat_door_frame",
                )
            )
        logger.debug(f"[SceneAssembler] 生成门 {len(doors)} 个")
        return doors

    def _parse_swing_direction(self, value: str) -> SwingDirection:
        """解析门的开合方向。"""
        mapping = {
            "left": SwingDirection.LEFT,
            "right": SwingDirection.RIGHT,
            "double": SwingDirection.DOUBLE,
            "sliding": SwingDirection.SLIDING,
            "folding": SwingDirection.FOLDING,
        }
        return mapping.get(value, SwingDirection.LEFT)

    def _parse_door_type(self, value: str) -> DoorType:
        """解析门的类型。"""
        mapping = {
            "single": DoorType.SINGLE,
            "double": DoorType.DOUBLE,
            "sliding": DoorType.SLIDING,
            "pocket": DoorType.POCKET,
        }
        return mapping.get(value, DoorType.SINGLE)

    # ── 窗构建 ────────────────────────────────────────────────────────────────

    def _build_windows(
        self,
        cad_windows: List[dict],
        floor_height: float,
        valid_wall_ids: set,
    ) -> List[WindowConfig]:
        """将 CAD 窗转换为 WindowConfig 列表。"""
        windows: List[WindowConfig] = []
        for w in cad_windows:
            win_id = w.get("id") or f"win_{uuid.uuid4().hex[:8]}"
            wall_id = w.get("wall_id", "")

            if wall_id not in valid_wall_ids:
                wall_id = wall_id or "wall_unknown"

            center = w.get("center", {})
            sill_height = float(w.get("sill_height", 900.0))

            windows.append(
                WindowConfig(
                    id=win_id,
                    wall_id=wall_id,
                    position=Point3D(
                        x=float(center.get("x", 0)),
                        y=float(center.get("y", 0)),
                        z=sill_height,
                    ),
                    width=float(w.get("width", 1500.0)),
                    height=float(w.get("height", 1200.0)),
                    sill_height=sill_height,
                    window_type=self._parse_window_type(
                        w.get("window_type", "casement")
                    ),
                    glass_material="mat_glass_clear",
                    frame_material="mat_window_frame",
                    has_curtain=True,
                    curtain_material="mat_curtain_white",
                )
            )
        logger.debug(f"[SceneAssembler] 生成窗 {len(windows)} 个")
        return windows

    def _parse_window_type(self, value: str) -> WindowType:
        """解析窗的类型。"""
        mapping = {
            "casement": WindowType.CASEMENT,
            "sliding": WindowType.SLIDING,
            "fixed": WindowType.FIXED,
            "awning": WindowType.AWNING,
            "bay": WindowType.BAY,
            "skylight": WindowType.SKYLIGHT,
            "french": WindowType.FRENCH,
        }
        return mapping.get(value, WindowType.CASEMENT)

    # ── 家具构建 ──────────────────────────────────────────────────────────────

    def _build_furniture(
        self,
        cad_rooms: List[dict],
        room_designs: dict,
        global_style: str,
    ) -> List[FurnitureConfig]:
        """根据 room_designs 和房间几何信息生成家具配置。"""
        furniture: List[FurnitureConfig] = []
        fur_counter = 0

        for room in cad_rooms:
            room_id = room.get("id", "")
            room_type = room.get("room_type", "other")
            design = room_designs.get(room_type)
            if not design or not isinstance(design, dict):
                continue

            furniture_list = design.get("furniture_list", [])
            if not furniture_list:
                continue

            # 计算房间几何
            boundary = [
                (p.get("x", 0), p.get("y", 0)) for p in room.get("boundary", [])
            ]
            if len(boundary) < 3:
                continue

            center_x, center_y = self._calc_centroid(boundary)
            bounds = self._calc_bounds(boundary)  # (min_x, min_y, max_x, max_y)
            width = bounds[2] - bounds[0]
            depth = bounds[3] - bounds[1]

            # 按家具类型计算位置
            placed_positions = self._plan_furniture_positions(
                room_type, furniture_list, center_x, center_y, bounds, width, depth
            )

            for idx, fur_item in enumerate(furniture_list):
                category_str = fur_item.get("category", "decoration")
                category = _CATEGORY_MAP.get(category_str, FurnitureCategory.DECORATION)
                style = fur_item.get("style", global_style)
                color_hex = fur_item.get("color", "#A0A0A0")

                # 获取家具位置
                if idx < len(placed_positions):
                    pos_x, pos_y = placed_positions[idx]
                else:
                    # 超出预算的家具放在房间中心附近（随机偏移）
                    offset = idx * 200
                    pos_x = center_x + (offset % 600 - 300)
                    pos_y = center_y + (offset // 600 * 200 - 200)

                fur_counter += 1
                fur_id = f"fur_{fur_counter:04d}"

                # 家具尺寸
                fur_size = _FURNITURE_SIZE.get(category_str, (600, 600, 800))

                # 计算旋转（朝向房间中心）
                rotation_z = self._calc_furniture_rotation(
                    pos_x, pos_y, center_x, center_y, category_str
                )

                furniture.append(
                    FurnitureConfig(
                        id=fur_id,
                        category=category,
                        asset_id=f"pending_{category_str}_{style}",
                        room_id=room_id,
                        position=Point3D(x=pos_x, y=pos_y, z=0.0),
                        rotation=Rotation3D(x=0, y=0, z=rotation_z),
                        scale=Scale3D(x=1.0, y=1.0, z=1.0),
                        material_overrides={
                            "main": f"mat_fur_{category_str}_{style}",
                        },
                    )
                )

        logger.debug(f"[SceneAssembler] 生成家具 {len(furniture)} 件")
        return furniture

    def _plan_furniture_positions(
        self,
        room_type: str,
        furniture_list: List[dict],
        cx: float,
        cy: float,
        bounds: Tuple[float, float, float, float],
        width: float,
        depth: float,
    ) -> List[Tuple[float, float]]:
        """
        根据房间类型和家具列表计算每件家具的布置位置。

        Returns:
            [(x, y), ...] 列表，与 furniture_list 等长
        """
        min_x, min_y, max_x, max_y = bounds
        positions = []

        if room_type == "living_room":
            # 客厅布局：
            # 沙发靠深度方向的后墙（min_y 或 max_y，取较大的一面）
            # 电视柜在沙发对面
            # 茶几在中央
            sofa_y = min_y + min(depth * 0.2, 800)
            tv_y = max_y - min(depth * 0.15, 600)

            layout = {
                "sofa": (cx, sofa_y),
                "coffee_table": (cx, cy - depth * 0.05),
                "tv_stand": (cx, tv_y),
                "tv_cabinet": (cx, tv_y),
                "rug": (cx, cy - depth * 0.02),
                "floor_lamp": (max_x - min(width * 0.1, 400), sofa_y + 400),
                "chair": (max_x - min(width * 0.15, 600), cy),
                "plant": (min_x + min(width * 0.05, 200), sofa_y),
                "decoration": (cx, cy),
            }

        elif room_type in ("bedroom", "master_bedroom"):
            # 卧室布局：床头靠后墙
            bed_y = min_y + min(depth * 0.25, 1100)
            wardrobe_x = max_x - min(width * 0.15, 700)

            layout = {
                "bed": (cx, bed_y),
                "table": (cx - min(width * 0.25, 600), bed_y),  # 床头柜
                "cabinet": (wardrobe_x, cy),
                "wardrobe": (wardrobe_x, cy),
                "desk": (min_x + min(width * 0.2, 700), max_y - min(depth * 0.15, 500)),
                "chair": (
                    min_x + min(width * 0.2, 700),
                    max_y - min(depth * 0.25, 800),
                ),
                "decoration": (cx + min(width * 0.25, 600), bed_y),  # 另一侧床头柜
                "plant": (min_x + 200, max_y - 300),
            }

        elif room_type == "dining_room":
            # 餐厅：餐桌居中，椅子环绕
            layout = {
                "dining_table": (cx, cy),
                "table": (cx, cy),
                "chair": (cx, cy + min(depth * 0.2, 600)),
                "cabinet": (min_x + min(width * 0.1, 300), cy),
                "decoration": (cx, min_y + 200),
            }

        elif room_type == "kitchen":
            # 厨房：橱柜沿最长边布置
            layout = {
                "kitchen_cabinet": (cx, min_y + min(depth * 0.15, 400)),
                "appliance": (
                    min_x + min(width * 0.2, 500),
                    min_y + min(depth * 0.15, 400),
                ),
                "decoration": (cx, cy),
            }

        elif room_type == "bathroom":
            # 卫生间：设备沿墙布置
            layout = {
                "appliance": (cx, min_y + min(depth * 0.2, 500)),
                "decoration": (min_x + 200, max_y - 300),
            }

        elif room_type == "study":
            # 书房：桌子靠窗（朝外，通常是 max_y 方向）
            layout = {
                "desk": (cx, max_y - min(depth * 0.2, 500)),
                "chair": (cx, max_y - min(depth * 0.35, 800)),
                "bookshelf": (max_x - min(width * 0.15, 400), cy),
                "cabinet": (min_x + min(width * 0.15, 400), cy),
                "decoration": (min_x + 200, max_y - 400),
            }

        else:
            # 其他房间：居中均匀分布
            layout = {}

        # 按 furniture_list 顺序分配位置
        for fur_item in furniture_list:
            cat = fur_item.get("category", "decoration")
            placement = fur_item.get("placement", "")

            # 从 layout 中取位置，否则用随机偏移中心
            if cat in layout:
                positions.append(layout[cat])
            elif placement == "center":
                positions.append((cx, cy))
            elif placement == "corner":
                positions.append((max_x - 300, min_y + 300))
            elif placement == "main_wall":
                positions.append((cx, min_y + 800))
            elif placement == "opposite_wall":
                positions.append((cx, max_y - 600))
            elif placement == "side_wall":
                positions.append((max_x - 600, cy))
            elif placement == "back_wall":
                positions.append((cx, min_y + 900))
            elif placement == "along_wall":
                positions.append((min_x + 400, cy))
            else:
                # 兜底：在中心区域均匀分散
                idx = len(positions)
                scatter_x = cx + (idx % 3 - 1) * min(width * 0.15, 500)
                scatter_y = cy + (idx // 3 - 1) * min(depth * 0.15, 500)
                positions.append((scatter_x, scatter_y))

        return positions

    def _calc_furniture_rotation(
        self, px: float, py: float, cx: float, cy: float, category: str
    ) -> float:
        """
        计算家具朝向（旋转角度，绕 Z 轴，单位：度）。
        家具朝向房间中心。
        """
        # 部分家具不需要旋转（如地毯）
        if category in ("rug", "decoration", "plant"):
            return 0.0

        dx = cx - px
        dy = cy - py
        if abs(dx) < 1e-6 and abs(dy) < 1e-6:
            return 0.0

        angle_rad = math.atan2(dy, dx)
        angle_deg = math.degrees(angle_rad)
        # 调整为四方向对齐（0/90/180/270）
        snapped = round(angle_deg / 90.0) * 90.0
        return snapped

    # ── 灯光构建 ──────────────────────────────────────────────────────────────

    def _build_lights(
        self,
        cad_rooms: List[dict],
        room_designs: dict,
        floor_height: float,
        render_mood: str,
    ) -> List[LightConfig]:
        """根据 room_designs 的 lighting_scheme 为每个房间生成灯光配置。"""
        lights: List[LightConfig] = []
        light_counter = 0

        for room in cad_rooms:
            room_id = room.get("id", "")
            room_type = room.get("room_type", "other")
            design = room_designs.get(room_type)
            if not design or not isinstance(design, dict):
                continue

            lighting_scheme = design.get("lighting_scheme", {})
            boundary = [
                (p.get("x", 0), p.get("y", 0)) for p in room.get("boundary", [])
            ]
            if len(boundary) < 3:
                continue

            center_x, center_y = self._calc_centroid(boundary)
            bounds = self._calc_bounds(boundary)
            min_x, min_y, max_x, max_y = bounds
            width = max_x - min_x
            depth = max_y - min_y

            ceiling_z = design.get("ceiling_height", floor_height)
            if not ceiling_z:
                ceiling_z = floor_height

            # ── 主照明（筒灯） ────────────────────────────────────────────────
            primary = lighting_scheme.get("primary", {})
            if primary and primary.get("type") == "downlight":
                count = int(primary.get("count", 4))
                color_temp = int(primary.get("color_temp", 3000))
                intensity = float(primary.get("intensity", 500))

                downlight_positions = self._calc_grid_positions(
                    count, center_x, center_y, width, depth
                )
                for pos in downlight_positions:
                    light_counter += 1
                    lights.append(
                        LightConfig(
                            id=f"light_{light_counter:04d}",
                            type=LightType.IES,
                            room_id=room_id,
                            position=Point3D(
                                x=pos[0],
                                y=pos[1],
                                z=ceiling_z - _CEILING_LIGHT_OFFSET,
                            ),
                            rotation=Rotation3D(x=180, y=0, z=0),  # 朝下
                            color_temperature=color_temp,
                            intensity=intensity,
                            cast_shadow=True,
                        )
                    )

            # ── 氛围灯（LED灯带）────────────────────────────────────────────
            accent = lighting_scheme.get("accent", {})
            if accent and accent.get("type") == "led_strip":
                color_temp = int(accent.get("color_temp", 2700))
                intensity = float(accent.get("intensity", 200))

                # 灯带用4个面光源表示（天花板四边各一条）
                strip_positions = [
                    (center_x, min_y + 100),  # 前边
                    (center_x, max_y - 100),  # 后边
                    (min_x + 100, center_y),  # 左边
                    (max_x - 100, center_y),  # 右边
                ]
                for spos in strip_positions:
                    light_counter += 1
                    lights.append(
                        LightConfig(
                            id=f"light_{light_counter:04d}",
                            type=LightType.AREA,
                            room_id=room_id,
                            position=Point3D(
                                x=spos[0],
                                y=spos[1],
                                z=ceiling_z - _CEILING_LIGHT_OFFSET,
                            ),
                            rotation=Rotation3D(x=90, y=0, z=0),
                            color_temperature=color_temp,
                            intensity=intensity * 0.5,
                            size=Point2D(x=min(width, depth) * 0.8, y=100.0),
                            cast_shadow=False,
                        )
                    )

            # ── 装饰灯（吊灯） ────────────────────────────────────────────────
            decorative = lighting_scheme.get("decorative", {})
            if decorative and decorative.get("type") == "pendant":
                count = int(decorative.get("count", 1))
                color_temp = int(decorative.get("color_temp", 2700))
                intensity = float(decorative.get("intensity", 800))

                pendant_z = ceiling_z - _PENDANT_HANG_OFFSET

                if count == 1:
                    light_counter += 1
                    lights.append(
                        LightConfig(
                            id=f"light_{light_counter:04d}",
                            type=LightType.POINT,
                            room_id=room_id,
                            position=Point3D(x=center_x, y=center_y, z=pendant_z),
                            rotation=Rotation3D(x=0, y=0, z=0),
                            color_temperature=color_temp,
                            intensity=intensity,
                            cast_shadow=True,
                        )
                    )
                else:
                    # 多吊灯：均匀排列在中轴线
                    spacing = min(width, depth) / (count + 1)
                    for pi in range(count):
                        px = center_x + (pi - count // 2) * spacing
                        light_counter += 1
                        lights.append(
                            LightConfig(
                                id=f"light_{light_counter:04d}",
                                type=LightType.POINT,
                                room_id=room_id,
                                position=Point3D(x=px, y=center_y, z=pendant_z),
                                rotation=Rotation3D(x=0, y=0, z=0),
                                color_temperature=color_temp,
                                intensity=intensity / count,
                                cast_shadow=True,
                            )
                        )

        logger.debug(f"[SceneAssembler] 生成灯光 {len(lights)} 盏")
        return lights

    def _calc_grid_positions(
        self,
        count: int,
        cx: float,
        cy: float,
        width: float,
        depth: float,
    ) -> List[Tuple[float, float]]:
        """计算筒灯均匀分布的网格位置。"""
        if count <= 0:
            return []

        # 确定网格行列数
        if count <= 2:
            cols, rows = count, 1
        elif count <= 4:
            cols, rows = 2, 2
        elif count <= 6:
            cols, rows = 3, 2
        elif count <= 9:
            cols, rows = 3, 3
        elif count <= 12:
            cols, rows = 4, 3
        else:
            cols = math.ceil(math.sqrt(count))
            rows = math.ceil(count / cols)

        positions = []
        # 均匀分布在房间内（留10%边距）
        margin_x = width * 0.12
        margin_y = depth * 0.12
        usable_w = width - 2 * margin_x
        usable_d = depth - 2 * margin_y

        start_x = cx - usable_w / 2
        start_y = cy - usable_d / 2

        step_x = usable_w / cols if cols > 1 else 0
        step_y = usable_d / rows if rows > 1 else 0

        for row in range(rows):
            for col in range(cols):
                if len(positions) >= count:
                    break
                px = start_x + (col + 0.5) * (usable_w / cols) if cols > 1 else cx
                py = start_y + (row + 0.5) * (usable_d / rows) if rows > 1 else cy
                positions.append((px, py))
            if len(positions) >= count:
                break

        return positions[:count]

    # ── 相机构建 ──────────────────────────────────────────────────────────────

    def _build_cameras(
        self,
        cad_rooms: List[dict],
        room_designs: dict,
        floor_height: float,
        cad_result: dict,
    ) -> List[CameraConfig]:
        """为主要房间和全局鸟瞰生成相机配置。"""
        cameras: List[CameraConfig] = []
        cam_counter = 0
        is_first = True

        # 优先渲染顺序
        priority = [
            "living_room",
            "master_bedroom",
            "dining_room",
            "bedroom",
            "kitchen",
            "study",
            "bathroom",
        ]

        # 按优先级排序
        sorted_rooms = sorted(
            cad_rooms,
            key=lambda r: (
                priority.index(r.get("room_type", "other"))
                if r.get("room_type", "other") in priority
                else 99
            ),
        )

        for room in sorted_rooms:
            room_id = room.get("id", "")
            room_type = room.get("room_type", "other")

            # 跳过不重要的房间（走廊、储藏室）
            if room_type in ("corridor", "storage", "balcony"):
                continue

            boundary = [
                (p.get("x", 0), p.get("y", 0)) for p in room.get("boundary", [])
            ]
            if len(boundary) < 3:
                continue

            center_x, center_y = self._calc_centroid(boundary)
            bounds = self._calc_bounds(boundary)
            min_x, min_y, max_x, max_y = bounds
            width = max_x - min_x
            depth = max_y - min_y

            # 相机位置：从某个角落看向房间中心
            cam_pos, cam_target = self._calc_camera_pose(
                room_type, center_x, center_y, bounds, floor_height
            )

            design = room_designs.get(room_type, {})
            fov = 60 if room_type in ("living_room", "dining_room") else 55

            cam_counter += 1
            cameras.append(
                CameraConfig(
                    id=f"cam_{cam_counter:03d}",
                    room_id=room_id,
                    position=Point3D(**cam_pos),
                    target=Point3D(**cam_target),
                    fov=fov,
                    is_default=is_first,
                )
            )
            is_first = False

        # 全局鸟瞰相机
        bounding_box = cad_result.get("bounding_box", {})
        if bounding_box:
            bb_cx = (bounding_box.get("minx", 0) + bounding_box.get("maxx", 0)) / 2
            bb_cy = (bounding_box.get("miny", 0) + bounding_box.get("maxy", 0)) / 2
            bb_max_dim = max(
                bounding_box.get("maxx", 0) - bounding_box.get("minx", 0),
                bounding_box.get("maxy", 0) - bounding_box.get("miny", 0),
            )
            cam_counter += 1
            cameras.append(
                CameraConfig(
                    id=f"cam_{cam_counter:03d}",
                    room_id=sorted_rooms[0].get("id", "") if sorted_rooms else "",
                    position=Point3D(x=bb_cx, y=bb_cy, z=bb_max_dim * 1.2),
                    target=Point3D(x=bb_cx, y=bb_cy, z=0),
                    fov=60,
                    is_default=False,
                )
            )

        logger.debug(f"[SceneAssembler] 生成相机 {len(cameras)} 个")
        return cameras

    def _calc_camera_pose(
        self,
        room_type: str,
        cx: float,
        cy: float,
        bounds: Tuple[float, float, float, float],
        floor_height: float,
    ) -> Tuple[dict, dict]:
        """
        计算相机位置和目标点。

        Returns:
            (cam_pos_dict, cam_target_dict) 各含 x/y/z 键
        """
        min_x, min_y, max_x, max_y = bounds
        width = max_x - min_x
        depth = max_y - min_y

        # 相机高度
        eye_height = _CAMERA_EYE_HEIGHT

        if room_type == "living_room":
            # 从电视背景墙对面角落，朝向电视墙（min_y 附近）
            cam_x = min_x + width * _CAMERA_CORNER_RATIO
            cam_y = max_y - depth * _CAMERA_CORNER_RATIO
            target_x = cx
            target_y = min_y + depth * 0.1

        elif room_type in ("master_bedroom", "bedroom"):
            # 从门口区域（max_y），看向床头墙（min_y）
            cam_x = cx
            cam_y = max_y - depth * _CAMERA_CORNER_RATIO
            target_x = cx
            target_y = min_y + depth * 0.2

        elif room_type == "dining_room":
            # 从侧面看向餐桌
            cam_x = min_x + width * _CAMERA_CORNER_RATIO
            cam_y = cy
            target_x = cx
            target_y = cy

        elif room_type == "kitchen":
            # 从门口看向橱柜
            cam_x = cx
            cam_y = max_y - depth * _CAMERA_CORNER_RATIO
            target_x = cx
            target_y = min_y + depth * 0.3

        elif room_type == "study":
            # 从角落看向书桌
            cam_x = min_x + width * _CAMERA_CORNER_RATIO
            cam_y = min_y + depth * _CAMERA_CORNER_RATIO
            target_x = cx
            target_y = max_y - depth * 0.2

        else:
            # 默认：从角落看向中心
            cam_x = min_x + width * _CAMERA_CORNER_RATIO
            cam_y = max_y - depth * _CAMERA_CORNER_RATIO
            target_x = cx
            target_y = cy

        return (
            {"x": cam_x, "y": cam_y, "z": eye_height},
            {"x": target_x, "y": target_y, "z": eye_height * 0.7},
        )

    # ── 几何工具 ──────────────────────────────────────────────────────────────

    def _calc_centroid(
        self, boundary: List[Tuple[float, float]]
    ) -> Tuple[float, float]:
        """计算多边形形心。"""
        if not boundary:
            return (0.0, 0.0)
        cx = sum(p[0] for p in boundary) / len(boundary)
        cy = sum(p[1] for p in boundary) / len(boundary)
        return (cx, cy)

    def _calc_bounds(
        self, boundary: List[Tuple[float, float]]
    ) -> Tuple[float, float, float, float]:
        """计算边界框 (min_x, min_y, max_x, max_y)。"""
        min_x = min(p[0] for p in boundary)
        min_y = min(p[1] for p in boundary)
        max_x = max(p[0] for p in boundary)
        max_y = max(p[1] for p in boundary)
        return (min_x, min_y, max_x, max_y)

    # ── 场景全局参数工具 ──────────────────────────────────────────────────────

    def _normalize_renderer(self, renderer_pref: str) -> str:
        """规范化渲染器名称。"""
        mapping = {
            "vray": "vray",
            "v-ray": "vray",
            "corona": "corona",
            "arnold": "arnold",
            "standard": "default",
            "auto": "vray",
        }
        return mapping.get(renderer_pref.lower(), "vray")

    def _get_ambient_intensity(self, render_mood: str) -> float:
        """根据渲染氛围返回环境光强度。"""
        mapping = {
            "day_natural": 0.5,
            "night_warm": 0.1,
            "night_cool": 0.15,
            "dusk": 0.2,
            "bright": 0.7,
        }
        return mapping.get(render_mood, 0.3)

    def _get_bg_color(self, render_mood: str) -> ColorRGB:
        """根据渲染氛围返回背景色。"""
        mapping = {
            "day_natural": ColorRGB(r=220, g=230, b=245),
            "night_warm": ColorRGB(r=20, g=15, b=10),
            "night_cool": ColorRGB(r=10, g=15, b=30),
            "dusk": ColorRGB(r=255, g=160, b=80),
            "bright": ColorRGB(r=255, g=255, b=255),
        }
        return mapping.get(render_mood, ColorRGB(r=255, g=255, b=255))
