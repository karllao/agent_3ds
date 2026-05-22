"""
墙体识别器。

从 DXF 图元（RawEntity）中识别墙体，返回 DetectedWall 列表。
支持三种识别策略：图层名匹配、双线墙识别、LWPOLYLINE 宽度识别。
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from loguru import logger

from .dxf_reader import RawEntity

# ── 墙体图层名关键字（不区分大小写）──────────────────────────────────────────
_WALL_LAYER_KEYWORDS = {
    "wall",
    "walls",
    "a-wall",
    "s-wall",
    "墙",
    "墙体",
    "墙线",
    "承重墙",
    "隔墙",
    "wall-a",
    "wall-b",
    "ext-wall",
    "int-wall",
    "外墙",
    "内墙",
    "剪力墙",
}

# 双线墙识别参数
_MIN_WALL_THICKNESS = 60.0  # mm，最小合理墙厚
_MAX_WALL_THICKNESS = 400.0  # mm，最大合理墙厚
_PARALLEL_ANGLE_TOL = 2.0  # 度，平行判断角度容差
_MIN_OVERLAP_RATIO = 0.5  # 长度方向最小重叠率
_COLLINEAR_ANGLE_TOL = 1.0  # 度，共线合并角度容差
_COLLINEAR_GAP_TOL = 50.0  # mm，共线合并端点距离容差


@dataclass
class DetectedWall:
    """识别到的墙体信息，坐标单位为 mm。"""

    id: str
    start: Tuple[float, float]
    end: Tuple[float, float]
    thickness: float
    length: float
    layer: str
    confidence: float  # 0.0 - 1.0


class WallDetector:
    """
    墙体识别器。

    按优先级依次使用三种策略识别墙体，并对结果进行去重和合并后处理。
    """

    def detect(
        self,
        entities: List[RawEntity],
        layers: Dict,
    ) -> List[DetectedWall]:
        """
        从图元列表识别墙体。

        Args:
            entities: 所有图元（已换算为 mm）
            layers: 图层字典（图层名 → LayerInfo）

        Returns:
            识别到的墙体列表
        """
        logger.info(f"开始墙体识别，共 {len(entities)} 个图元")
        walls: List[DetectedWall] = []

        # 策略一：图层名匹配
        layer_walls = self._detect_by_layer(entities)
        logger.debug(f"策略一（图层匹配）：识别到 {len(layer_walls)} 段墙")
        walls.extend(layer_walls)

        # 收集已被策略一识别的图元，避免重复处理
        used_entities = {id(e) for e in entities if self._is_wall_layer(e.layer)}

        # 策略二：双线墙识别（仅对未被策略一使用的 LINE 图元）
        remaining_lines = [
            e
            for e in entities
            if e.entity_type == "LINE" and id(e) not in used_entities
        ]
        double_line_walls = self._detect_double_line(remaining_lines)
        logger.debug(f"策略二（双线墙）：识别到 {len(double_line_walls)} 段墙")
        walls.extend(double_line_walls)

        # 策略三：LWPOLYLINE 宽度识别
        poly_walls = self._detect_polyline_walls(entities)
        logger.debug(f"策略三（LWPOLYLINE 宽度）：识别到 {len(poly_walls)} 段墙")
        walls.extend(poly_walls)

        # 后处理：去重 + 合并
        walls = self._post_process(walls)

        logger.success(f"墙体识别完成，最终 {len(walls)} 段墙体")
        return walls

    # ── 策略一：图层名匹配 ────────────────────────────────────────────────────

    def _is_wall_layer(self, layer_name: str) -> bool:
        """判断图层名是否为墙体图层。"""
        lower = layer_name.lower()
        for kw in _WALL_LAYER_KEYWORDS:
            if kw.lower() in lower:
                return True
        return False

    def _detect_by_layer(self, entities: List[RawEntity]) -> List[DetectedWall]:
        """策略一：从墙体图层中提取 LINE / LWPOLYLINE / POLYLINE。"""
        walls: List[DetectedWall] = []
        for entity in entities:
            if not self._is_wall_layer(entity.layer):
                continue
            extracted = self._entity_to_wall_segments(entity, confidence=0.95)
            walls.extend(extracted)
        return walls

    def _entity_to_wall_segments(
        self,
        entity: RawEntity,
        confidence: float,
        thickness: float = 200.0,
    ) -> List[DetectedWall]:
        """将单个图元拆解为墙体线段列表。"""
        segments: List[DetectedWall] = []

        if entity.entity_type == "LINE":
            if len(entity.points) >= 2:
                seg = self._make_wall(
                    entity.points[0],
                    entity.points[1],
                    thickness=thickness,
                    layer=entity.layer,
                    confidence=confidence,
                )
                if seg is not None:
                    segments.append(seg)

        elif entity.entity_type in ("LWPOLYLINE", "POLYLINE"):
            pts = entity.points
            is_closed = entity.extra.get("is_closed", False)
            # 宽度非零时直接当墙处理
            width = entity.extra.get("width", 0.0)
            effective_thickness = width if width > 0 else thickness
            for i in range(len(pts) - 1):
                seg = self._make_wall(
                    pts[i],
                    pts[i + 1],
                    thickness=effective_thickness,
                    layer=entity.layer,
                    confidence=confidence,
                )
                if seg is not None:
                    segments.append(seg)
            if is_closed and len(pts) >= 2:
                seg = self._make_wall(
                    pts[-1],
                    pts[0],
                    thickness=effective_thickness,
                    layer=entity.layer,
                    confidence=confidence,
                )
                if seg is not None:
                    segments.append(seg)

        return segments

    # ── 策略二：双线墙识别 ────────────────────────────────────────────────────

    def _detect_double_line(self, lines: List[RawEntity]) -> List[DetectedWall]:
        """
        扫描所有 LINE 图元，找近似平行且间距在合理墙厚范围内的线段对，
        识别为墙体。
        """
        walls: List[DetectedWall] = []
        used_indices = set()
        n = len(lines)

        for i in range(n):
            if i in used_indices:
                continue
            e1 = lines[i]
            if len(e1.points) < 2:
                continue
            p1s, p1e = e1.points[0], e1.points[1]
            angle1 = self._line_angle(p1s, p1e)
            len1 = self._dist(p1s, p1e)
            if len1 < 100:  # 太短的线段忽略
                continue

            for j in range(i + 1, n):
                if j in used_indices:
                    continue
                e2 = lines[j]
                if len(e2.points) < 2:
                    continue
                p2s, p2e = e2.points[0], e2.points[1]
                angle2 = self._line_angle(p2s, p2e)
                len2 = self._dist(p2s, p2e)
                if len2 < 100:
                    continue

                # 1. 角度差判断平行
                angle_diff = self._angle_diff(angle1, angle2)
                if angle_diff > _PARALLEL_ANGLE_TOL:
                    continue

                # 2. 垂直距离判断墙厚
                perp_dist = self._perpendicular_distance_between_parallel_lines(
                    p1s, p1e, p2s, p2e
                )
                if not (_MIN_WALL_THICKNESS <= perp_dist <= _MAX_WALL_THICKNESS):
                    continue

                # 3. 长度方向重叠判断
                overlap = self._line_overlap_ratio(p1s, p1e, p2s, p2e, angle1)
                if overlap < _MIN_OVERLAP_RATIO:
                    continue

                # 找到一对墙线，取中心线
                center_start, center_end = self._center_line(p1s, p1e, p2s, p2e)
                wall = self._make_wall(
                    center_start,
                    center_end,
                    thickness=perp_dist,
                    layer=e1.layer,
                    confidence=0.80,
                )
                if wall is not None:
                    walls.append(wall)
                    used_indices.add(i)
                    used_indices.add(j)
                break  # 每条线只匹配一次

        return walls

    # ── 策略三：LWPOLYLINE 宽度识别 ───────────────────────────────────────────

    def _detect_polyline_walls(self, entities: List[RawEntity]) -> List[DetectedWall]:
        """从封闭的带宽度 LWPOLYLINE 中识别墙体。"""
        walls: List[DetectedWall] = []
        for entity in entities:
            if entity.entity_type != "LWPOLYLINE":
                continue
            if self._is_wall_layer(entity.layer):
                continue  # 已被策略一处理
            width = entity.extra.get("width", 0.0)
            if width <= 0:
                continue
            is_closed = entity.extra.get("is_closed", False)
            pts = entity.points
            for i in range(len(pts) - 1):
                seg = self._make_wall(
                    pts[i],
                    pts[i + 1],
                    thickness=width,
                    layer=entity.layer,
                    confidence=0.70,
                )
                if seg is not None:
                    walls.append(seg)
            if is_closed and len(pts) >= 2:
                seg = self._make_wall(
                    pts[-1],
                    pts[0],
                    thickness=width,
                    layer=entity.layer,
                    confidence=0.70,
                )
                if seg is not None:
                    walls.append(seg)
        return walls

    # ── 后处理 ────────────────────────────────────────────────────────────────

    def _post_process(self, walls: List[DetectedWall]) -> List[DetectedWall]:
        """合并重复/重叠/共线的墙体，统一方向。"""
        # 1. 统一方向（start 在左/下）
        walls = [self._normalize_direction(w) for w in walls]

        # 2. 去除极短墙体（< 100 mm）
        walls = [w for w in walls if w.length >= 100.0]

        # 3. 合并共线且端点接近的短墙段
        walls = self._merge_collinear(walls)

        # 4. 去重（完全重叠的墙体只保留置信度最高的）
        walls = self._deduplicate(walls)

        return walls

    def _normalize_direction(self, wall: DetectedWall) -> DetectedWall:
        """使 start 在 end 的左下方（标准化方向）。"""
        sx, sy = wall.start
        ex, ey = wall.end
        # 以 x 为主，y 为辅
        if ex < sx or (math.isclose(ex, sx, abs_tol=0.1) and ey < sy):
            wall.start, wall.end = wall.end, wall.start
        return wall

    def _merge_collinear(self, walls: List[DetectedWall]) -> List[DetectedWall]:
        """合并同向、共线、端点接近的墙段。"""
        if not walls:
            return walls

        merged = True
        while merged:
            merged = False
            result: List[DetectedWall] = []
            used = [False] * len(walls)
            for i, w1 in enumerate(walls):
                if used[i]:
                    continue
                current = w1
                for j in range(i + 1, len(walls)):
                    if used[j]:
                        continue
                    w2 = walls[j]
                    if self._can_merge(current, w2):
                        current = self._merge_two_walls(current, w2)
                        used[j] = True
                        merged = True
                result.append(current)
                used[i] = True
            walls = result

        return walls

    def _can_merge(self, w1: DetectedWall, w2: DetectedWall) -> bool:
        """判断两段墙是否可以合并（共线 + 端点接近）。"""
        angle1 = self._line_angle(w1.start, w1.end)
        angle2 = self._line_angle(w2.start, w2.end)
        if self._angle_diff(angle1, angle2) > _COLLINEAR_ANGLE_TOL:
            return False

        # 检查端点距离
        dists = [
            self._dist(w1.end, w2.start),
            self._dist(w1.end, w2.end),
            self._dist(w1.start, w2.start),
            self._dist(w1.start, w2.end),
        ]
        if min(dists) > _COLLINEAR_GAP_TOL:
            return False

        # 检查共线（点到线的距离）
        perp = self._point_to_line_dist(w2.start, w1.start, w1.end)
        if perp > _COLLINEAR_GAP_TOL:
            return False

        return True

    def _merge_two_walls(self, w1: DetectedWall, w2: DetectedWall) -> DetectedWall:
        """合并两段共线墙为一段（取四个端点中距离最远的两个）。"""
        pts = [w1.start, w1.end, w2.start, w2.end]
        max_dist = 0.0
        best_start, best_end = w1.start, w1.end
        for i in range(len(pts)):
            for j in range(i + 1, len(pts)):
                d = self._dist(pts[i], pts[j])
                if d > max_dist:
                    max_dist = d
                    best_start, best_end = pts[i], pts[j]
        thickness = max(w1.thickness, w2.thickness)
        confidence = max(w1.confidence, w2.confidence)
        return DetectedWall(
            id=f"wall_{uuid.uuid4().hex[:8]}",
            start=best_start,
            end=best_end,
            thickness=thickness,
            length=max_dist,
            layer=w1.layer,
            confidence=confidence,
        )

    def _deduplicate(self, walls: List[DetectedWall]) -> List[DetectedWall]:
        """删除高度重叠的重复墙体，保留置信度最高的。"""
        result: List[DetectedWall] = []
        used = [False] * len(walls)
        # 按置信度降序排列
        indexed = sorted(enumerate(walls), key=lambda x: -x[1].confidence)

        for orig_i, w1 in indexed:
            if used[orig_i]:
                continue
            result.append(w1)
            for orig_j, w2 in indexed:
                if orig_j <= orig_i or used[orig_j]:
                    continue
                if self._walls_overlap(w1, w2):
                    used[orig_j] = True
            used[orig_i] = True

        return result

    def _walls_overlap(self, w1: DetectedWall, w2: DetectedWall) -> bool:
        """判断两段墙是否高度重叠（近似判断）。"""
        if self._dist(w1.start, w2.start) < 50 and self._dist(w1.end, w2.end) < 50:
            return True
        if self._dist(w1.start, w2.end) < 50 and self._dist(w1.end, w2.start) < 50:
            return True
        return False

    # ── 工具方法 ──────────────────────────────────────────────────────────────

    def _make_wall(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        thickness: float,
        layer: str,
        confidence: float,
    ) -> Optional[DetectedWall]:
        """根据两端点创建 DetectedWall，长度 < 10mm 时返回 None。"""
        length = self._dist(start, end)
        if length < 10.0:
            return None
        return DetectedWall(
            id=f"wall_{uuid.uuid4().hex[:8]}",
            start=start,
            end=end,
            thickness=max(thickness, 1.0),
            length=length,
            layer=layer,
            confidence=confidence,
        )

    @staticmethod
    def _dist(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
        """两点欧氏距离。"""
        return math.hypot(p2[0] - p1[0], p2[1] - p1[1])

    @staticmethod
    def _line_angle(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
        """线段方向角（度，范围 0-180）。"""
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        angle = math.degrees(math.atan2(dy, dx)) % 180.0
        return angle

    @staticmethod
    def _angle_diff(a1: float, a2: float) -> float:
        """两个方向角之差（度，范围 0-90）。"""
        diff = abs(a1 - a2) % 180.0
        if diff > 90.0:
            diff = 180.0 - diff
        return diff

    @staticmethod
    def _point_to_line_dist(
        p: Tuple[float, float],
        a: Tuple[float, float],
        b: Tuple[float, float],
    ) -> float:
        """点 p 到直线 ab 的距离。"""
        ax, ay = a
        bx, by = b
        px, py = p
        dx, dy = bx - ax, by - ay
        denom = math.hypot(dx, dy)
        if denom < 1e-9:
            return math.hypot(px - ax, py - ay)
        return abs(dx * (ay - py) - dy * (ax - px)) / denom

    def _perpendicular_distance_between_parallel_lines(
        self,
        p1s: Tuple[float, float],
        p1e: Tuple[float, float],
        p2s: Tuple[float, float],
        p2e: Tuple[float, float],
    ) -> float:
        """两条近似平行线之间的垂直距离（取四个端点到对方直线距离的平均）。"""
        d1 = self._point_to_line_dist(p2s, p1s, p1e)
        d2 = self._point_to_line_dist(p2e, p1s, p1e)
        return (d1 + d2) / 2.0

    def _line_overlap_ratio(
        self,
        p1s: Tuple[float, float],
        p1e: Tuple[float, float],
        p2s: Tuple[float, float],
        p2e: Tuple[float, float],
        angle: float,
    ) -> float:
        """
        计算两线段在主方向上的重叠率。

        将两线段投影到方向向量上，计算重叠区间 / 较短线段长度。
        """
        rad = math.radians(angle)
        ux, uy = math.cos(rad), math.sin(rad)

        def proj(p: Tuple[float, float]) -> float:
            return p[0] * ux + p[1] * uy

        prj1s, prj1e = proj(p1s), proj(p1e)
        prj2s, prj2e = proj(p2s), proj(p2e)

        lo1, hi1 = min(prj1s, prj1e), max(prj1s, prj1e)
        lo2, hi2 = min(prj2s, prj2e), max(prj2s, prj2e)

        overlap = max(0.0, min(hi1, hi2) - max(lo1, lo2))
        shorter = min(hi1 - lo1, hi2 - lo2)
        if shorter < 1e-9:
            return 0.0
        return overlap / shorter

    @staticmethod
    def _center_line(
        p1s: Tuple[float, float],
        p1e: Tuple[float, float],
        p2s: Tuple[float, float],
        p2e: Tuple[float, float],
    ) -> Tuple[Tuple[float, float], Tuple[float, float]]:
        """返回两线段的中心线（首尾中点连线）。"""
        # 确保 p2s 与 p1s 在同侧（方向一致）
        d_ss = math.hypot(p2s[0] - p1s[0], p2s[1] - p1s[1])
        d_se = math.hypot(p2e[0] - p1s[0], p2e[1] - p1s[1])
        if d_se < d_ss:
            # p2 方向相反，交换
            p2s, p2e = p2e, p2s
        cs = ((p1s[0] + p2s[0]) / 2, (p1s[1] + p2s[1]) / 2)
        ce = ((p1e[0] + p2e[0]) / 2, (p1e[1] + p2e[1]) / 2)
        return cs, ce
