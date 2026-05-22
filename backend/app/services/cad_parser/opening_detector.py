"""
门窗识别器。

从 DXF 图元中识别门和窗，并关联到最近的墙体。
支持多种识别策略：图层名、圆弧+线段、块引用、墙体缺口检测。
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from loguru import logger

from .dxf_reader import RawEntity
from .wall_detector import DetectedWall

# ── 识别参数 ──────────────────────────────────────────────────────────────────
# 门
_DOOR_LAYER_KEYWORDS = {"door", "门", "a-door", "d-door", "门洞"}
_DOOR_ARC_RADIUS_MIN = 600.0  # mm，最小门扇弧半径
_DOOR_ARC_RADIUS_MAX = 1200.0  # mm，最大门扇弧半径
_DOOR_GAP_MIN = 600.0  # mm，墙缺口最小宽度（门）
_DOOR_GAP_MAX = 1500.0  # mm，墙缺口最大宽度（门）
_DOOR_DEFAULT_WIDTH = 900.0
_DOOR_DEFAULT_HEIGHT = 2100.0

# 窗
_WIN_LAYER_KEYWORDS = {"window", "窗", "a-window", "窗户", "窗洞"}
_WIN_GAP_MIN = 1000.0  # mm，墙缺口最小宽度（窗）
_WIN_GAP_MAX = 3000.0  # mm，墙缺口最大宽度（窗）
_WIN_DEFAULT_WIDTH = 1500.0
_WIN_DEFAULT_HEIGHT = 1500.0
_WIN_DEFAULT_SILL = 900.0

# 关联墙体最大距离
_MAX_WALL_ASSOC_DIST = 500.0  # mm，门/窗中心到最近墙体的最大距离


@dataclass
class DetectedDoor:
    """识别到的门信息。"""

    id: str
    wall_id: str
    center: Tuple[float, float]
    width: float = _DOOR_DEFAULT_WIDTH
    height: float = _DOOR_DEFAULT_HEIGHT
    floor_offset: float = 0.0
    swing_direction: str = "unknown"  # left/right/double/sliding/unknown
    door_type: str = "single"  # single/double/sliding/pocket/unknown


@dataclass
class DetectedWindow:
    """识别到的窗信息。"""

    id: str
    wall_id: str
    center: Tuple[float, float]
    width: float = _WIN_DEFAULT_WIDTH
    height: float = _WIN_DEFAULT_HEIGHT
    sill_height: float = _WIN_DEFAULT_SILL
    window_type: str = "unknown"  # fixed/casement/sliding/bay/curtain_wall/unknown


class OpeningDetector:
    """
    门窗识别器。

    多策略识别后统一关联到最近墙体。
    """

    def detect(
        self,
        entities: List[RawEntity],
        walls: List[DetectedWall],
    ) -> Tuple[List[DetectedDoor], List[DetectedWindow]]:
        """
        从图元中识别门窗。

        Args:
            entities: 所有 DXF 图元
            walls: 已识别的墙体列表

        Returns:
            (doors, windows)
        """
        logger.info(f"开始门窗识别，共 {len(entities)} 个图元，{len(walls)} 段墙")

        doors: List[DetectedDoor] = []
        windows: List[DetectedWindow] = []

        # ── 门识别 ────────────────────────────────────────────────────────────

        # 策略 D1：图层名含门关键字
        layer_doors = self._detect_doors_by_layer(entities, walls)
        logger.debug(f"策略D1（图层）：{len(layer_doors)} 个门")
        doors.extend(layer_doors)

        # 策略 D2：圆弧（门扇弧）+ 附近线段
        used_arc_indices = set()
        arc_doors, used_arc_indices = self._detect_doors_by_arc(
            entities, walls, used_arc_indices
        )
        logger.debug(f"策略D2（圆弧）：{len(arc_doors)} 个门")
        doors.extend(arc_doors)

        # 策略 D3：INSERT 块名含门关键字
        block_doors = self._detect_doors_by_block(entities, walls)
        logger.debug(f"策略D3（块引用）：{len(block_doors)} 个门")
        doors.extend(block_doors)

        # 策略 D4：墙体缺口（相邻墙端点间距 600-1500mm）
        gap_doors = self._detect_doors_by_gap(walls)
        logger.debug(f"策略D4（墙缺口）：{len(gap_doors)} 个门")
        doors.extend(gap_doors)

        # ── 窗识别 ────────────────────────────────────────────────────────────

        # 策略 W1：图层名含窗关键字
        layer_wins = self._detect_windows_by_layer(entities, walls)
        logger.debug(f"策略W1（图层）：{len(layer_wins)} 个窗")
        windows.extend(layer_wins)

        # 策略 W2：INSERT 块名含窗关键字
        block_wins = self._detect_windows_by_block(entities, walls)
        logger.debug(f"策略W2（块引用）：{len(block_wins)} 个窗")
        windows.extend(block_wins)

        # 策略 W3：墙体缺口（1000-3000mm）
        gap_wins = self._detect_windows_by_gap(walls)
        logger.debug(f"策略W3（墙缺口）：{len(gap_wins)} 个窗")
        windows.extend(gap_wins)

        # 去重
        doors = self._dedup_openings(doors)
        windows = self._dedup_windows(windows)

        # 过滤掉没有有效 wall_id 的条目
        doors = [d for d in doors if d.wall_id]
        windows = [w for w in windows if w.wall_id]

        logger.success(f"门窗识别完成：{len(doors)} 个门，{len(windows)} 个窗")
        return doors, windows

    # ── 门识别策略 ────────────────────────────────────────────────────────────

    def _detect_doors_by_layer(
        self,
        entities: List[RawEntity],
        walls: List[DetectedWall],
    ) -> List[DetectedDoor]:
        """策略 D1：从门图层的 LINE/LWPOLYLINE 中提取门。"""
        doors = []
        for entity in entities:
            if not self._is_door_layer(entity.layer):
                continue
            center = self._entity_center(entity)
            if center is None:
                continue
            wall_id = self._find_nearest_wall_id(center, walls)
            width = self._estimate_door_width(entity)
            swing = self._estimate_swing(entity)
            doors.append(
                DetectedDoor(
                    id=f"door_{uuid.uuid4().hex[:8]}",
                    wall_id=wall_id,
                    center=center,
                    width=width,
                    swing_direction=swing,
                    door_type="single",
                )
            )
        return doors

    def _detect_doors_by_arc(
        self,
        entities: List[RawEntity],
        walls: List[DetectedWall],
        used_arc_indices: set,
    ) -> Tuple[List[DetectedDoor], set]:
        """
        策略 D2：找 ARC 图元，半径在典型门扇范围内，
        且附近有线段（门框） → 识别为门。
        """
        doors = []
        arcs = [
            (i, e)
            for i, e in enumerate(entities)
            if e.entity_type == "ARC" and i not in used_arc_indices
        ]

        for arc_idx, arc_entity in arcs:
            radius = arc_entity.extra.get("radius", 0.0)
            if not (_DOOR_ARC_RADIUS_MIN <= radius <= _DOOR_ARC_RADIUS_MAX):
                continue

            center = arc_entity.points[0] if arc_entity.points else None
            if center is None:
                continue

            # 检查附近是否有线段（门框线）
            has_nearby_line = self._has_nearby_line(center, entities, radius * 1.5)
            if not has_nearby_line:
                continue

            wall_id = self._find_nearest_wall_id(center, walls)
            width = radius  # 弧半径即门宽

            # 判断开启方向（根据圆弧角度范围）
            start_angle = arc_entity.extra.get("start_angle", 0.0)
            end_angle = arc_entity.extra.get("end_angle", 90.0)
            swing = self._arc_to_swing(start_angle, end_angle)

            doors.append(
                DetectedDoor(
                    id=f"door_{uuid.uuid4().hex[:8]}",
                    wall_id=wall_id,
                    center=center,
                    width=width,
                    swing_direction=swing,
                    door_type="single",
                )
            )
            used_arc_indices.add(arc_idx)

        return doors, used_arc_indices

    def _detect_doors_by_block(
        self,
        entities: List[RawEntity],
        walls: List[DetectedWall],
    ) -> List[DetectedDoor]:
        """策略 D3：INSERT 块名含门关键字。"""
        doors = []
        for entity in entities:
            if entity.entity_type != "INSERT":
                continue
            block_name = entity.extra.get("block_name", "").lower()
            if not any(kw in block_name for kw in ("door", "门")):
                continue
            center = entity.points[0] if entity.points else None
            if center is None:
                continue
            wall_id = self._find_nearest_wall_id(center, walls)
            x_scale = entity.extra.get("x_scale", 1.0)
            width = _DOOR_DEFAULT_WIDTH * abs(x_scale)
            swing = "unknown"
            door_type = (
                "double" if "double" in block_name or "双" in block_name else "single"
            )
            if "sliding" in block_name or "推拉" in block_name:
                door_type = "sliding"
                swing = "sliding"
            doors.append(
                DetectedDoor(
                    id=f"door_{uuid.uuid4().hex[:8]}",
                    wall_id=wall_id,
                    center=center,
                    width=width,
                    swing_direction=swing,
                    door_type=door_type,
                )
            )
        return doors

    def _detect_doors_by_gap(
        self,
        walls: List[DetectedWall],
    ) -> List[DetectedDoor]:
        """
        策略 D4：墙体端点之间的缺口。

        两段墙端点距离在 600-1500mm，且方向大致相同 → 可能是门洞。
        """
        doors = []
        n = len(walls)
        for i in range(n):
            w1 = walls[i]
            for j in range(i + 1, n):
                w2 = walls[j]
                # 只检查同图层（或相邻方向）的墙
                gap, gap_center = self._wall_gap(w1, w2)
                if gap is None:
                    continue
                if _DOOR_GAP_MIN <= gap <= _DOOR_GAP_MAX:
                    # 更接近门的尺寸时，创建门（已被窗策略可能覆盖，这里保守处理）
                    # 检查两墙是否共线
                    if not self._are_collinear(w1, w2):
                        continue
                    wall_id = w1.id  # 关联到第一段墙
                    doors.append(
                        DetectedDoor(
                            id=f"door_{uuid.uuid4().hex[:8]}",
                            wall_id=wall_id,
                            center=gap_center,
                            width=gap,
                            swing_direction="unknown",
                            door_type="single",
                        )
                    )
        return doors

    # ── 窗识别策略 ────────────────────────────────────────────────────────────

    def _detect_windows_by_layer(
        self,
        entities: List[RawEntity],
        walls: List[DetectedWall],
    ) -> List[DetectedWindow]:
        """策略 W1：从窗图层的图元提取窗户。"""
        windows = []
        for entity in entities:
            if not self._is_window_layer(entity.layer):
                continue
            center = self._entity_center(entity)
            if center is None:
                continue
            wall_id = self._find_nearest_wall_id(center, walls)
            width = self._estimate_window_width(entity)
            win_type = self._estimate_window_type(entity)
            windows.append(
                DetectedWindow(
                    id=f"win_{uuid.uuid4().hex[:8]}",
                    wall_id=wall_id,
                    center=center,
                    width=width,
                    window_type=win_type,
                )
            )
        return windows

    def _detect_windows_by_block(
        self,
        entities: List[RawEntity],
        walls: List[DetectedWall],
    ) -> List[DetectedWindow]:
        """策略 W2：INSERT 块名含窗关键字。"""
        windows = []
        for entity in entities:
            if entity.entity_type != "INSERT":
                continue
            block_name = entity.extra.get("block_name", "").lower()
            if not any(kw in block_name for kw in ("window", "窗")):
                continue
            center = entity.points[0] if entity.points else None
            if center is None:
                continue
            wall_id = self._find_nearest_wall_id(center, walls)
            x_scale = entity.extra.get("x_scale", 1.0)
            width = _WIN_DEFAULT_WIDTH * abs(x_scale)
            win_type = "casement"
            if "sliding" in block_name or "推拉" in block_name:
                win_type = "sliding"
            elif "fixed" in block_name or "固定" in block_name:
                win_type = "fixed"
            elif "bay" in block_name or "飘" in block_name:
                win_type = "bay"
            windows.append(
                DetectedWindow(
                    id=f"win_{uuid.uuid4().hex[:8]}",
                    wall_id=wall_id,
                    center=center,
                    width=width,
                    window_type=win_type,
                )
            )
        return windows

    def _detect_windows_by_gap(
        self,
        walls: List[DetectedWall],
    ) -> List[DetectedWindow]:
        """
        策略 W3：墙体端点之间 1000-3000mm 的缺口，识别为窗。
        """
        windows = []
        n = len(walls)
        for i in range(n):
            w1 = walls[i]
            for j in range(i + 1, n):
                w2 = walls[j]
                gap, gap_center = self._wall_gap(w1, w2)
                if gap is None:
                    continue
                if _WIN_GAP_MIN <= gap <= _WIN_GAP_MAX:
                    if not self._are_collinear(w1, w2):
                        continue
                    # 如果大小更像窗
                    if gap > _DOOR_GAP_MAX or gap < _DOOR_GAP_MIN:
                        wall_id = w1.id
                        windows.append(
                            DetectedWindow(
                                id=f"win_{uuid.uuid4().hex[:8]}",
                                wall_id=wall_id,
                                center=gap_center,
                                width=gap,
                                window_type="casement",
                            )
                        )
        return windows

    # ── 工具方法 ──────────────────────────────────────────────────────────────

    def _is_door_layer(self, layer_name: str) -> bool:
        lower = layer_name.lower()
        return any(kw in lower for kw in _DOOR_LAYER_KEYWORDS)

    def _is_window_layer(self, layer_name: str) -> bool:
        lower = layer_name.lower()
        return any(kw in lower for kw in _WIN_LAYER_KEYWORDS)

    def _entity_center(self, entity: RawEntity) -> Optional[Tuple[float, float]]:
        """计算图元的几何中心。"""
        if not entity.points:
            return None
        xs = [p[0] for p in entity.points]
        ys = [p[1] for p in entity.points]
        return (sum(xs) / len(xs), sum(ys) / len(ys))

    def _find_nearest_wall_id(
        self,
        center: Tuple[float, float],
        walls: List[DetectedWall],
    ) -> str:
        """找到离 center 最近的墙体，返回其 id（超过最大距离时返回空串）。"""
        best_dist = float("inf")
        best_id = ""
        for wall in walls:
            dist = self._point_to_segment_dist(center, wall.start, wall.end)
            if dist < best_dist:
                best_dist = dist
                best_id = wall.id
        if best_dist > _MAX_WALL_ASSOC_DIST:
            # 放宽：如果有墙，总要关联一个
            if walls:
                best_id = min(
                    walls,
                    key=lambda w: self._point_to_segment_dist(center, w.start, w.end),
                ).id
        return best_id

    def _estimate_door_width(self, entity: RawEntity) -> float:
        """根据图元尺寸估算门宽。"""
        if entity.entity_type == "LINE" and len(entity.points) >= 2:
            return self._dist(entity.points[0], entity.points[1])
        if entity.entity_type in ("LWPOLYLINE", "POLYLINE") and len(entity.points) >= 2:
            # 取最长边
            max_len = 0.0
            for i in range(len(entity.points) - 1):
                d = self._dist(entity.points[i], entity.points[i + 1])
                if d > max_len:
                    max_len = d
            return (
                max_len
                if _DOOR_GAP_MIN <= max_len <= _DOOR_GAP_MAX
                else _DOOR_DEFAULT_WIDTH
            )
        return _DOOR_DEFAULT_WIDTH

    def _estimate_window_width(self, entity: RawEntity) -> float:
        """根据图元尺寸估算窗宽。"""
        if entity.entity_type == "LINE" and len(entity.points) >= 2:
            d = self._dist(entity.points[0], entity.points[1])
            return d if _WIN_GAP_MIN <= d <= _WIN_GAP_MAX else _WIN_DEFAULT_WIDTH
        if entity.entity_type in ("LWPOLYLINE", "POLYLINE") and len(entity.points) >= 2:
            max_len = 0.0
            for i in range(len(entity.points) - 1):
                d = self._dist(entity.points[i], entity.points[i + 1])
                if d > max_len:
                    max_len = d
            return (
                max_len
                if _WIN_GAP_MIN <= max_len <= _WIN_GAP_MAX
                else _WIN_DEFAULT_WIDTH
            )
        return _WIN_DEFAULT_WIDTH

    def _estimate_swing(self, entity: RawEntity) -> str:
        """根据 LINE 方向粗略判断开启方向。"""
        if entity.entity_type == "LINE" and len(entity.points) >= 2:
            dx = entity.points[1][0] - entity.points[0][0]
            return "right" if dx >= 0 else "left"
        return "unknown"

    def _arc_to_swing(self, start_angle: float, end_angle: float) -> str:
        """根据圆弧角度范围判断开门方向。"""
        # 简单规则：0-90 度 → 右开，90-180 → 左开，其余 → unknown
        span = (end_angle - start_angle) % 360.0
        if math.isclose(span, 90.0, abs_tol=10.0):
            mid = (start_angle + end_angle) / 2 % 360.0
            if 315 <= mid or mid <= 45:
                return "right"
            elif 45 < mid <= 135:
                return "right"
            elif 135 < mid <= 225:
                return "left"
            else:
                return "left"
        elif math.isclose(span, 180.0, abs_tol=10.0):
            return "double"
        return "unknown"

    def _estimate_window_type(self, entity: RawEntity) -> str:
        """根据图元特征估算窗类型。"""
        if entity.entity_type == "CIRCLE":
            return "fixed"
        if entity.entity_type == "ARC":
            return "casement"
        # 4 条短线段组成的窗 → casement
        if entity.entity_type in ("LWPOLYLINE", "POLYLINE"):
            if len(entity.points) >= 4:
                return "casement"
        return "unknown"

    def _has_nearby_line(
        self,
        center: Tuple[float, float],
        entities: List[RawEntity],
        radius: float,
    ) -> bool:
        """检查在 center 周围 radius 范围内是否有 LINE 图元。"""
        for entity in entities:
            if entity.entity_type != "LINE":
                continue
            if not entity.points:
                continue
            for pt in entity.points:
                if self._dist(center, pt) <= radius:
                    return True
        return False

    def _wall_gap(
        self,
        w1: DetectedWall,
        w2: DetectedWall,
    ) -> Tuple[Optional[float], Tuple[float, float]]:
        """
        计算两段墙端点之间最小的缺口距离和缺口中心。

        Returns:
            (gap_mm, center) 或 (None, (0,0)) 表示不符合条件
        """
        candidates = [
            (self._dist(w1.end, w2.start), w1.end, w2.start),
            (self._dist(w1.end, w2.end), w1.end, w2.end),
            (self._dist(w1.start, w2.start), w1.start, w2.start),
            (self._dist(w1.start, w2.end), w1.start, w2.end),
        ]
        best = min(candidates, key=lambda x: x[0])
        gap, pa, pb = best
        center = ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)
        return gap, center

    def _are_collinear(self, w1: DetectedWall, w2: DetectedWall) -> bool:
        """
        粗略判断两段墙是否共线（方向接近，且一段墙的端点到另一段的距离较小）。
        """
        # 方向角差
        angle1 = self._line_angle(w1.start, w1.end)
        angle2 = self._line_angle(w2.start, w2.end)
        angle_diff = abs(angle1 - angle2) % 180.0
        if angle_diff > 90.0:
            angle_diff = 180.0 - angle_diff
        if angle_diff > 5.0:  # 允许 5 度偏差
            return False

        # 点到直线距离判断
        perp = self._point_to_line_dist(w2.start, w1.start, w1.end)
        return perp < 100.0  # 100mm 内认为共线

    @staticmethod
    def _dist(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
        return math.hypot(p2[0] - p1[0], p2[1] - p1[1])

    @staticmethod
    def _line_angle(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        return math.degrees(math.atan2(dy, dx)) % 180.0

    @staticmethod
    def _point_to_segment_dist(
        p: Tuple[float, float],
        a: Tuple[float, float],
        b: Tuple[float, float],
    ) -> float:
        """点到线段的最短距离。"""
        ax, ay = a
        bx, by = b
        px, py = p
        dx, dy = bx - ax, by - ay
        seg_len_sq = dx * dx + dy * dy
        if seg_len_sq < 1e-12:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len_sq))
        proj_x = ax + t * dx
        proj_y = ay + t * dy
        return math.hypot(px - proj_x, py - proj_y)

    @staticmethod
    def _point_to_line_dist(
        p: Tuple[float, float],
        a: Tuple[float, float],
        b: Tuple[float, float],
    ) -> float:
        """点到直线（非线段）的距离。"""
        ax, ay = a
        bx, by = b
        px, py = p
        dx, dy = bx - ax, by - ay
        denom = math.hypot(dx, dy)
        if denom < 1e-9:
            return math.hypot(px - ax, py - ay)
        return abs(dx * (ay - py) - dy * (ax - px)) / denom

    def _dedup_openings(self, doors: List[DetectedDoor]) -> List[DetectedDoor]:
        """去除中心坐标极其接近的重复门。"""
        result: List[DetectedDoor] = []
        for door in doors:
            is_dup = False
            for existing in result:
                if self._dist(door.center, existing.center) < 200.0:
                    is_dup = True
                    break
            if not is_dup:
                result.append(door)
        return result

    def _dedup_windows(self, windows: List[DetectedWindow]) -> List[DetectedWindow]:
        """去除中心坐标极其接近的重复窗。"""
        result: List[DetectedWindow] = []
        for win in windows:
            is_dup = False
            for existing in result:
                if self._dist(win.center, existing.center) < 200.0:
                    is_dup = True
                    break
            if not is_dup:
                result.append(win)
        return result
