"""
场景数据验证 Agent（纯代码，不依赖 LLM）。

职责：检查 SceneAssembler 生成的场景数据是否合理，
发现问题时添加 parse_warnings，但不中断流程。

检查项：
1. 所有墙体高度 > 0
2. 所有房间面积 > 0
3. 家具位置在对应房间边界内（使用 Shapely）
4. 门窗关联的 wall_id 有效
5. 灯光位置高度合理（z ≈ ceiling_height - 200 ~ ceiling_height）
6. 相机位置高度合理（z > 0）
7. 场景中至少有一个房间和墙体
"""

from __future__ import annotations

from typing import Dict, List, Tuple

from loguru import logger

from .state import AgentState

# 尝试导入 Shapely（可选依赖，未安装时跳过空间检查）
try:
    from shapely.geometry import Point, Polygon

    _HAS_SHAPELY = True
except ImportError:
    _HAS_SHAPELY = False
    logger.warning("[ValidationAgent] shapely 未安装，家具/相机空间检查将被跳过")

# 验证阈值
_MIN_WALL_HEIGHT = 100.0  # mm，墙体最小高度
_MIN_ROOM_AREA = 0.5  # m²，房间最小面积
_MIN_LIGHT_Z_RATIO = 0.7  # 灯光最低高度比例（相对 floor_height）
_MAX_CAMERA_Z = 100_000.0  # mm，相机最高高度（鸟瞰）
_MIN_CAMERA_Z = 100.0  # mm，相机最低高度（避免在地板以下）


class ValidationAgent:
    """
    场景数据验证 Agent。

    纯代码实现，检查 FullSceneData 的合理性，
    将问题添加到 full_scene_data["extra"]["warnings"] 中。
    """

    async def run(self, state: AgentState) -> AgentState:
        """
        执行场景数据验证。

        Args:
            state: 当前 LangGraph 状态

        Returns:
            更新了 full_scene_data.extra.warnings 的状态
        """
        logger.info(
            f"[ValidationAgent] 开始验证场景数据，项目 {state.get('project_id')}"
        )

        full_scene_data = state.get("full_scene_data")
        if not full_scene_data:
            logger.warning("[ValidationAgent] full_scene_data 为空，跳过验证")
            state["current_step"] = "done"
            return state

        warnings: List[str] = []

        try:
            # 提取 floor_height
            scene_config = full_scene_data.get("scene_config", {})
            floor_height = float(scene_config.get("floor_height", 2800.0))

            # ── 1. 验证基础结构 ────────────────────────────────────────────────
            self._validate_structure(full_scene_data, warnings)

            # ── 2. 验证墙体 ────────────────────────────────────────────────────
            walls = full_scene_data.get("walls", [])
            valid_wall_ids = self._validate_walls(walls, floor_height, warnings)

            # ── 3. 验证房间 ────────────────────────────────────────────────────
            rooms = full_scene_data.get("rooms", [])
            room_polygons = self._validate_rooms(rooms, warnings)

            # ── 4. 验证门窗 wall_id ─────────────────────────────────────────────
            doors = full_scene_data.get("doors", [])
            windows = full_scene_data.get("windows", [])
            self._validate_openings(doors, windows, valid_wall_ids, warnings)

            # ── 5. 验证家具位置 ────────────────────────────────────────────────
            furniture = full_scene_data.get("furniture", [])
            self._validate_furniture(furniture, room_polygons, warnings)

            # ── 6. 验证灯光位置 ────────────────────────────────────────────────
            lights = full_scene_data.get("lights", [])
            self._validate_lights(lights, floor_height, warnings)

            # ── 7. 验证相机位置 ────────────────────────────────────────────────
            cameras = full_scene_data.get("cameras", [])
            self._validate_cameras(cameras, room_polygons, warnings)

            # ── 8. 验证材质引用完整性 ───────────────────────────────────────────
            materials = full_scene_data.get("materials", [])
            self._validate_material_refs(full_scene_data, materials, warnings)

        except Exception as e:
            logger.error(
                f"[ValidationAgent] 验证过程发生异常（不影响流程）：{e}", exc_info=True
            )
            warnings.append(f"验证过程异常（部分检查未完成）：{e}")

        # 将警告写入 extra
        if "extra" not in full_scene_data:
            full_scene_data["extra"] = {}
        existing_warnings = full_scene_data["extra"].get("warnings", [])
        full_scene_data["extra"]["warnings"] = existing_warnings + warnings

        if warnings:
            logger.warning(
                f"[ValidationAgent] 发现 {len(warnings)} 个警告：\n"
                + "\n".join(f"  - {w}" for w in warnings)
            )
        else:
            logger.success("[ValidationAgent] 场景数据验证通过，无警告")

        state["full_scene_data"] = full_scene_data
        state["current_step"] = "done"
        return state

    # ── 各项验证方法 ──────────────────────────────────────────────────────────

    def _validate_structure(self, scene_data: dict, warnings: List[str]) -> None:
        """验证场景数据的基础结构完整性。"""
        walls = scene_data.get("walls", [])
        rooms = scene_data.get("rooms", [])
        materials = scene_data.get("materials", [])

        if not walls:
            warnings.append(
                "场景中没有墙体数据，可能是 CAD 解析失败或 DXF 文件不包含有效墙体图层。"
            )
        if not rooms:
            warnings.append(
                "场景中没有房间数据，可能是 CAD 解析失败或墙体未形成封闭区域。"
            )
        if not materials:
            warnings.append("场景中没有材质定义，建模后需手动指定材质。")
        if not scene_data.get("cameras"):
            warnings.append("场景中没有相机，渲染时将使用默认视角。")

    def _validate_walls(
        self, walls: List[dict], floor_height: float, warnings: List[str]
    ) -> set:
        """
        验证墙体配置。

        Returns:
            有效 wall_id 集合
        """
        valid_ids = set()
        zero_height_count = 0

        for wall in walls:
            wall_id = wall.get("id", "?")
            height = float(wall.get("height", 0))

            if height < _MIN_WALL_HEIGHT:
                zero_height_count += 1
            else:
                valid_ids.add(wall_id)

            # 检查墙体长度（start != end）
            start = wall.get("start", {})
            end = wall.get("end", {})
            dx = float(end.get("x", 0)) - float(start.get("x", 0))
            dy = float(end.get("y", 0)) - float(start.get("y", 0))
            length = (dx**2 + dy**2) ** 0.5
            if length < 10.0:
                warnings.append(
                    f"墙体 {wall_id} 长度过短（{length:.1f}mm < 10mm），可能是解析噪点。"
                )
            else:
                valid_ids.add(wall_id)

        if zero_height_count > 0:
            warnings.append(
                f"有 {zero_height_count} 段墙体高度不足 {_MIN_WALL_HEIGHT}mm，"
                f"请检查层高设置（当前层高 {floor_height}mm）。"
            )

        logger.debug(
            f"[ValidationAgent] 墙体验证：{len(walls)} 段，有效 {len(valid_ids)} 段"
        )
        return valid_ids

    def _validate_rooms(
        self, rooms: List[dict], warnings: List[str]
    ) -> Dict[str, "Polygon"]:
        """
        验证房间配置。

        Returns:
            room_id → Shapely Polygon 的映射（用于后续空间检查）
        """
        room_polygons: Dict[str, "Polygon"] = {}
        small_room_count = 0

        for room in rooms:
            room_id = room.get("id", "?")
            area = float(room.get("area", 0))
            boundary = room.get("boundary", [])

            if area < _MIN_ROOM_AREA:
                small_room_count += 1
                warnings.append(
                    f"房间 {room_id}（{room.get('name', '?')}）面积过小 "
                    f"（{area:.2f}m² < {_MIN_ROOM_AREA}m²），可能是误识别。"
                )

            # 构建 Shapely Polygon
            if _HAS_SHAPELY and len(boundary) >= 3:
                try:
                    pts = [
                        (float(p.get("x", 0)), float(p.get("y", 0))) for p in boundary
                    ]
                    poly = Polygon(pts)
                    if not poly.is_valid:
                        poly = poly.buffer(0)  # 修复自交多边形
                    room_polygons[room_id] = poly
                except Exception as e:
                    warnings.append(
                        f"房间 {room_id} 边界多边形构建失败：{e}，空间检查将跳过该房间。"
                    )

        logger.debug(
            f"[ValidationAgent] 房间验证：{len(rooms)} 个，构建多边形 {len(room_polygons)} 个"
        )
        return room_polygons

    def _validate_openings(
        self,
        doors: List[dict],
        windows: List[dict],
        valid_wall_ids: set,
        warnings: List[str],
    ) -> None:
        """验证门窗关联的 wall_id 是否有效。"""
        invalid_door_count = 0
        invalid_win_count = 0

        for door in doors:
            wall_id = door.get("wall_id", "")
            if wall_id and wall_id != "wall_unknown" and wall_id not in valid_wall_ids:
                invalid_door_count += 1

        for win in windows:
            wall_id = win.get("wall_id", "")
            if wall_id and wall_id != "wall_unknown" and wall_id not in valid_wall_ids:
                invalid_win_count += 1

        if invalid_door_count > 0:
            warnings.append(
                f"有 {invalid_door_count} 扇门关联到了不存在的墙体 ID，"
                "门的位置可能不正确，需要手动调整。"
            )
        if invalid_win_count > 0:
            warnings.append(
                f"有 {invalid_win_count} 扇窗关联到了不存在的墙体 ID，"
                "窗的位置可能不正确，需要手动调整。"
            )

        logger.debug(
            f"[ValidationAgent] 门窗验证：门 {len(doors)} 扇，窗 {len(windows)} 扇"
        )

    def _validate_furniture(
        self,
        furniture: List[dict],
        room_polygons: Dict[str, "Polygon"],
        warnings: List[str],
    ) -> None:
        """
        验证家具位置是否在对应房间边界内。
        需要 Shapely 支持。
        """
        if not _HAS_SHAPELY or not room_polygons:
            return

        out_of_room_count = 0
        total_checked = 0

        for fur in furniture:
            room_id = fur.get("room_id", "")
            poly = room_polygons.get(room_id)
            if poly is None:
                continue

            position = fur.get("position", {})
            px = float(position.get("x", 0))
            py = float(position.get("y", 0))

            total_checked += 1
            pt = Point(px, py)

            # 允许有少量误差（家具边缘可能略微超出边界）
            if not poly.buffer(200).contains(pt):
                out_of_room_count += 1
                fur_id = fur.get("id", "?")
                fur_cat = fur.get("category", "?")
                logger.debug(
                    f"[ValidationAgent] 家具 {fur_id}({fur_cat}) 可能在房间 {room_id} 边界外"
                    f"（位置 x={px:.0f}, y={py:.0f}）"
                )

        if out_of_room_count > 0:
            warnings.append(
                f"有 {out_of_room_count}/{total_checked} 件家具的摆放位置可能超出房间边界，"
                "建议在 3ds Max 中手动调整布局。"
            )
        logger.debug(
            f"[ValidationAgent] 家具位置验证：检查 {total_checked} 件，"
            f"{out_of_room_count} 件可能越界"
        )

    def _validate_lights(
        self,
        lights: List[dict],
        floor_height: float,
        warnings: List[str],
    ) -> None:
        """验证灯光高度是否在合理范围内（天花板附近）。"""
        abnormal_count = 0
        min_light_z = floor_height * _MIN_LIGHT_Z_RATIO

        for light in lights:
            position = light.get("position", {})
            lz = float(position.get("z", 0))
            light_type = light.get("type", "")

            # 鸟瞰方向光等特殊灯光跳过
            if light_type in ("directional", "ambient"):
                continue

            if lz < min_light_z:
                abnormal_count += 1
                logger.debug(
                    f"[ValidationAgent] 灯光 {light.get('id', '?')} 高度偏低 "
                    f"（z={lz:.0f}mm，期望 ≥ {min_light_z:.0f}mm）"
                )

        if abnormal_count > 0:
            warnings.append(
                f"有 {abnormal_count} 盏灯光高度低于层高的 {_MIN_LIGHT_Z_RATIO * 100:.0f}%，"
                f"可能不在天花板附近，请检查灯光位置（层高 {floor_height}mm）。"
            )

        logger.debug(
            f"[ValidationAgent] 灯光验证：共 {len(lights)} 盏，{abnormal_count} 盏位置异常"
        )

    def _validate_cameras(
        self,
        cameras: List[dict],
        room_polygons: Dict[str, "Polygon"],
        warnings: List[str],
    ) -> None:
        """验证相机位置高度合理性。"""
        abnormal_count = 0

        for cam in cameras:
            position = cam.get("position", {})
            cz = float(position.get("z", 0))

            if cz < _MIN_CAMERA_Z:
                abnormal_count += 1
                logger.debug(
                    f"[ValidationAgent] 相机 {cam.get('id', '?')} 高度过低（z={cz:.0f}mm）"
                )
            elif cz > _MAX_CAMERA_Z:
                # 可能是鸟瞰相机，不报警告
                pass

        if abnormal_count > 0:
            warnings.append(
                f"有 {abnormal_count} 个相机高度低于 {_MIN_CAMERA_Z}mm，"
                "相机可能位于地板以下，请检查相机位置。"
            )

        # 检查是否有默认相机
        default_cams = [c for c in cameras if c.get("is_default")]
        if cameras and not default_cams:
            warnings.append(
                "没有设置默认渲染相机（is_default=True），"
                "渲染时将使用第一个相机作为默认视角。"
            )

        logger.debug(
            f"[ValidationAgent] 相机验证：共 {len(cameras)} 个，{abnormal_count} 个位置异常"
        )

    def _validate_material_refs(
        self,
        scene_data: dict,
        materials: List[dict],
        warnings: List[str],
    ) -> None:
        """
        验证场景中引用的材质 ID 是否都在 materials 列表中定义。
        仅检查 walls/rooms 的主材质引用。
        """
        defined_mat_ids = {m.get("id") for m in materials if m.get("id")}
        missing_refs = set()

        # 检查墙体材质引用
        for wall in scene_data.get("walls", []):
            mat_id = wall.get("material")
            if mat_id and mat_id not in defined_mat_ids:
                missing_refs.add(mat_id)

        # 检查房间材质引用
        for room in scene_data.get("rooms", []):
            for key in ("floor_material", "ceiling_material"):
                mat_id = room.get(key)
                if mat_id and mat_id not in defined_mat_ids:
                    missing_refs.add(mat_id)

        if missing_refs:
            warnings.append(
                f"有 {len(missing_refs)} 个材质 ID 被引用但未在 materials 中定义："
                f"{', '.join(sorted(missing_refs)[:5])}{'...' if len(missing_refs) > 5 else ''}。"
                "3ds Max 脚本会使用默认材质替代。"
            )

        logger.debug(
            f"[ValidationAgent] 材质引用验证：定义 {len(defined_mat_ids)} 个，"
            f"缺失引用 {len(missing_refs)} 个"
        )
