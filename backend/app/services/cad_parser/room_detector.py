"""
房间识别器。

从墙体中心线网络构建平面图，识别封闭区域作为房间。
使用 Shapely 处理几何运算，使用 networkx 分析图拓扑。
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from loguru import logger

from .dxf_reader import RawEntity
from .wall_detector import DetectedWall

# 尝试导入可选依赖
try:
    import networkx as nx

    _HAS_NX = True
except ImportError:
    _HAS_NX = False
    logger.warning("networkx 未安装，房间识别将使用简化算法")

try:
    from shapely.geometry import LineString, MultiLineString, Point, Polygon
    from shapely.ops import polygonize, unary_union

    _HAS_SHAPELY = True
except ImportError:
    _HAS_SHAPELY = False
    logger.warning("shapely 未安装，房间识别将使用简化算法")

# ── 房间类型映射 ──────────────────────────────────────────────────────────────
_ROOM_NAME_MAP: Dict[str, str] = {
    # 客厅
    "客厅": "living_room",
    "厅": "living_room",
    "起居室": "living_room",
    "living": "living_room",
    "livingroom": "living_room",
    # 卧室
    "卧室": "bedroom",
    "主卧": "bedroom",
    "次卧": "bedroom",
    "儿童房": "bedroom",
    "bedroom": "bedroom",
    "master": "bedroom",
    # 厨房
    "厨房": "kitchen",
    "厨": "kitchen",
    "kitchen": "kitchen",
    # 卫生间
    "卫生间": "bathroom",
    "厕所": "bathroom",
    "洗手间": "bathroom",
    "浴室": "bathroom",
    "卫": "bathroom",
    "bathroom": "bathroom",
    "toilet": "bathroom",
    "wc": "bathroom",
    # 餐厅
    "餐厅": "dining_room",
    "饭厅": "dining_room",
    "dining": "dining_room",
    "diningroom": "dining_room",
    # 阳台
    "阳台": "balcony",
    "balcony": "balcony",
    "露台": "balcony",
    # 走廊
    "走廊": "hallway",
    "过道": "hallway",
    "玄关": "hallway",
    "hallway": "hallway",
    "corridor": "hallway",
    "entrance": "hallway",
    "门廊": "hallway",
    # 书房
    "书房": "study",
    "工作室": "study",
    "study": "study",
    "office": "study",
    # 储藏
    "储藏室": "storage",
    "储物间": "storage",
    "杂物间": "storage",
    "storage": "storage",
    "closet": "storage",
}

# 面积范围推断房间类型（面积单位 m²）
_AREA_TYPE_RULES = [
    (20.0, float("inf"), "living_room"),
    (8.0, 20.0, "bedroom"),
    (4.0, 8.0, "kitchen"),
    (2.0, 4.0, "bathroom"),
]

_MIN_ROOM_AREA_M2 = 1.5  # m²，小于此值忽略
_MAX_ROOM_AREA_M2 = 500.0  # m²，大于此值忽略
_TEXT_SEARCH_RADIUS = 2000.0  # mm，文字与房间质心的最大匹配距离


@dataclass
class DetectedRoom:
    """识别到的房间信息。"""

    id: str
    name: str
    room_type: str  # living_room / bedroom / kitchen / bathroom / dining_room /
    # balcony / hallway / study / storage / unknown
    boundary: List[Tuple[float, float]]  # 轮廓点坐标（mm）
    area: float  # 面积 m²
    center: Tuple[float, float]  # 质心坐标（mm）
    confidence: float


class RoomDetector:
    """
    房间识别器。

    将墙体中心线组成线网络，用 Shapely polygonize 找封闭多边形，
    再根据面积和文字标注判断房间类型。
    """

    def detect(
        self,
        walls: List[DetectedWall],
        texts: List[RawEntity],
        floor_bound: Optional[Tuple[float, float, float, float]] = None,
    ) -> List[DetectedRoom]:
        """
        从墙体和文字标注识别房间。

        Args:
            walls: 识别到的墙体列表
            texts: TEXT / MTEXT 图元列表（用于房间名匹配）
            floor_bound: 平面图范围 (minx, miny, maxx, maxy)，可选

        Returns:
            识别到的房间列表
        """
        logger.info(f"开始房间识别，共 {len(walls)} 段墙，{len(texts)} 个文字标注")

        if not walls:
            logger.warning("没有墙体数据，跳过房间识别")
            return []

        if _HAS_SHAPELY:
            rooms = self._detect_with_shapely(walls, texts)
        else:
            rooms = self._detect_fallback(walls, texts)

        logger.success(f"房间识别完成，共识别到 {len(rooms)} 个房间")
        return rooms

    # ── Shapely 实现 ──────────────────────────────────────────────────────────

    def _detect_with_shapely(
        self,
        walls: List[DetectedWall],
        texts: List[RawEntity],
    ) -> List[DetectedRoom]:
        """使用 Shapely polygonize 从墙体线网络中识别封闭多边形。"""
        # 1. 构建线段集合
        lines: List[LineString] = []
        for wall in walls:
            try:
                line = LineString([wall.start, wall.end])
                if line.length > 0:
                    lines.append(line)
            except Exception as exc:
                logger.debug(f"墙体 {wall.id} 转换为 LineString 失败：{exc}")

        if not lines:
            logger.warning("没有有效线段，跳过多边形识别")
            return []

        # 2. 合并线段（节点捕捉）
        try:
            merged = unary_union(lines)
        except Exception as exc:
            logger.error(f"线段合并失败：{exc}")
            return []

        # 3. 多边形化
        try:
            polygons = list(polygonize(merged))
        except Exception as exc:
            logger.error(f"多边形化失败：{exc}")
            return []

        logger.debug(f"多边形化得到 {len(polygons)} 个候选区域")

        # 4. 过滤面积范围
        valid_polys = []
        for poly in polygons:
            try:
                area_m2 = poly.area / 1_000_000  # mm² → m²
                if _MIN_ROOM_AREA_M2 <= area_m2 <= _MAX_ROOM_AREA_M2:
                    valid_polys.append((poly, area_m2))
            except Exception:
                continue

        logger.debug(f"面积过滤后 {len(valid_polys)} 个区域")

        # 5. 为每个多边形生成房间信息
        rooms: List[DetectedRoom] = []
        for poly, area_m2 in valid_polys:
            try:
                room = self._polygon_to_room(poly, area_m2, texts)
                if room is not None:
                    rooms.append(room)
            except Exception as exc:
                logger.debug(f"多边形转房间失败：{exc}")

        return rooms

    def _polygon_to_room(
        self,
        poly: "Polygon",
        area_m2: float,
        texts: List[RawEntity],
    ) -> Optional[DetectedRoom]:
        """将 Shapely Polygon 转换为 DetectedRoom。"""
        # 获取质心
        try:
            centroid = poly.centroid
            center = (centroid.x, centroid.y)
        except Exception:
            coords = list(poly.exterior.coords)
            xs = [c[0] for c in coords]
            ys = [c[1] for c in coords]
            center = (sum(xs) / len(xs), sum(ys) / len(ys))

        # 获取边界点
        try:
            boundary = [(x, y) for x, y in poly.exterior.coords[:-1]]
        except Exception:
            return None

        if len(boundary) < 3:
            return None

        # 匹配最近文字标注
        name, room_type, text_confidence = self._match_text(center, texts)

        # 如果没有匹配到文字，根据面积推断
        if room_type == "unknown":
            room_type = self._infer_type_by_area(area_m2)
            confidence = 0.50
        else:
            confidence = text_confidence

        return DetectedRoom(
            id=f"room_{uuid.uuid4().hex[:8]}",
            name=name,
            room_type=room_type,
            boundary=boundary,
            area=round(area_m2, 2),
            center=center,
            confidence=confidence,
        )

    # ── 简化 fallback 实现（无 Shapely 时）───────────────────────────────────

    def _detect_fallback(
        self,
        walls: List[DetectedWall],
        texts: List[RawEntity],
    ) -> List[DetectedRoom]:
        """
        无 Shapely 时的简化房间识别：
        直接根据文字标注生成虚拟房间，位置为文字插入点附近。
        """
        logger.warning("使用简化房间识别（仅基于文字标注，精度有限）")
        rooms: List[DetectedRoom] = []
        used_texts = set()

        for i, text_entity in enumerate(texts):
            text = text_entity.extra.get("text", "").strip()
            if not text or i in used_texts:
                continue
            name, room_type, _ = self._classify_text(text)
            if room_type == "unknown":
                continue
            center = text_entity.points[0] if text_entity.points else (0.0, 0.0)
            # 构造伪边界（3m × 3m 矩形）
            cx, cy = center
            hw = 1500.0
            boundary = [
                (cx - hw, cy - hw),
                (cx + hw, cy - hw),
                (cx + hw, cy + hw),
                (cx - hw, cy + hw),
            ]
            rooms.append(
                DetectedRoom(
                    id=f"room_{uuid.uuid4().hex[:8]}",
                    name=name,
                    room_type=room_type,
                    boundary=boundary,
                    area=round((hw * 2) ** 2 / 1_000_000, 2),
                    center=center,
                    confidence=0.40,
                )
            )
            used_texts.add(i)

        return rooms

    # ── 工具方法 ──────────────────────────────────────────────────────────────

    def _match_text(
        self,
        center: Tuple[float, float],
        texts: List[RawEntity],
    ) -> Tuple[str, str, float]:
        """
        在文字标注中找与质心最近的那条，返回 (name, room_type, confidence)。
        找不到时返回 ('未知房间', 'unknown', 0.0)。
        """
        best_dist = float("inf")
        best_name = "未知房间"
        best_type = "unknown"
        best_conf = 0.0

        for entity in texts:
            if not entity.points:
                continue
            text_pt = entity.points[0]
            dist = math.hypot(text_pt[0] - center[0], text_pt[1] - center[1])
            if dist > _TEXT_SEARCH_RADIUS:
                continue
            text_str = entity.extra.get("text", "").strip()
            if not text_str:
                continue
            name, room_type, conf = self._classify_text(text_str)
            if dist < best_dist:
                best_dist = dist
                best_name = name if name else text_str
                best_type = room_type
                best_conf = conf

        return best_name, best_type, best_conf

    def _classify_text(self, text: str) -> Tuple[str, str, float]:
        """
        根据文字内容判断房间类型。

        Returns:
            (显示名称, 类型字符串, 置信度)
        """
        # 标准化
        lower = text.lower().strip()

        # 精确匹配
        for keyword, room_type in _ROOM_NAME_MAP.items():
            if keyword in lower or keyword in text:
                return text, room_type, 0.90

        return text, "unknown", 0.30

    def _infer_type_by_area(self, area_m2: float) -> str:
        """根据面积推断房间类型。"""
        for lo, hi, rtype in _AREA_TYPE_RULES:
            if lo <= area_m2 < hi:
                return rtype
        if area_m2 < _MIN_ROOM_AREA_M2 * 2:
            return "storage"
        return "unknown"
