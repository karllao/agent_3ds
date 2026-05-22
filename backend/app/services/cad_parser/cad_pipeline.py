"""
CAD 解析主管道。

整合 DXFReader、ScaleDetector、WallDetector、RoomDetector、OpeningDetector，
提供统一的 async process() 接口，返回 CADParseResult。
"""

from __future__ import annotations

import asyncio
import math
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from .dxf_reader import DXFDocument, DXFReader, RawEntity
from .opening_detector import DetectedDoor, DetectedWindow, OpeningDetector
from .room_detector import DetectedRoom, RoomDetector
from .scale_detector import ScaleDetector, ScaleInfo
from .wall_detector import DetectedWall, WallDetector

# ── 警告阈值 ──────────────────────────────────────────────────────────────────
_WARN_MIN_WALLS = 3  # 墙体数量警告阈值
_WARN_MIN_ROOMS = 1  # 房间数量警告阈值
_WARN_MAX_ROOM_AREA_M2 = 200  # 单个房间面积警告阈值
_WARN_MIN_ROOM_AREA_M2 = 2  # 单个房间面积下限警告
_WARN_LOW_CONFIDENCE = 0.5  # 低置信度警告阈值


@dataclass
class CADParseResult:
    """
    CAD 解析结果。

    包含所有识别到的建筑元素和解析元信息，可序列化为 dict。
    """

    walls: List[DetectedWall]
    """识别到的墙体列表"""

    rooms: List[DetectedRoom]
    """识别到的房间列表"""

    doors: List[DetectedDoor]
    """识别到的门列表"""

    windows: List[DetectedWindow]
    """识别到的窗列表"""

    scale_info: ScaleInfo
    """图纸比例信息"""

    raw_entity_count: int
    """原始 DXF 图元总数"""

    layer_names: List[str]
    """所有图层名称列表"""

    bounding_box: Tuple[float, float, float, float]
    """平面图边界框 (minx, miny, maxx, maxy)，单位 mm"""

    parse_warnings: List[str]
    """解析警告信息列表"""

    parse_time_ms: float = 0.0
    """解析总耗时（毫秒）"""

    def to_dict(self) -> Dict[str, Any]:
        """将解析结果转换为可 JSON 序列化的字典。"""
        return {
            "walls": [self._wall_to_dict(w) for w in self.walls],
            "rooms": [self._room_to_dict(r) for r in self.rooms],
            "doors": [self._door_to_dict(d) for d in self.doors],
            "windows": [self._window_to_dict(w) for w in self.windows],
            "scale_info": {
                "unit": self.scale_info.unit,
                "scale_factor": self.scale_info.scale_factor,
                "floor_height": self.scale_info.floor_height,
                "detected_dimensions": self.scale_info.detected_dimensions,
            },
            "raw_entity_count": self.raw_entity_count,
            "layer_names": self.layer_names,
            "bounding_box": {
                "minx": self.bounding_box[0],
                "miny": self.bounding_box[1],
                "maxx": self.bounding_box[2],
                "maxy": self.bounding_box[3],
            },
            "parse_warnings": self.parse_warnings,
            "parse_time_ms": self.parse_time_ms,
            "summary": {
                "wall_count": len(self.walls),
                "room_count": len(self.rooms),
                "door_count": len(self.doors),
                "window_count": len(self.windows),
            },
        }

    # ── 各类型序列化辅助 ──────────────────────────────────────────────────────

    @staticmethod
    def _wall_to_dict(w: DetectedWall) -> dict:
        return {
            "id": w.id,
            "start": {"x": w.start[0], "y": w.start[1]},
            "end": {"x": w.end[0], "y": w.end[1]},
            "thickness": w.thickness,
            "length": w.length,
            "layer": w.layer,
            "confidence": w.confidence,
        }

    @staticmethod
    def _room_to_dict(r: DetectedRoom) -> dict:
        return {
            "id": r.id,
            "name": r.name,
            "room_type": r.room_type,
            "boundary": [{"x": p[0], "y": p[1]} for p in r.boundary],
            "area": r.area,
            "center": {"x": r.center[0], "y": r.center[1]},
            "confidence": r.confidence,
        }

    @staticmethod
    def _door_to_dict(d: DetectedDoor) -> dict:
        return {
            "id": d.id,
            "wall_id": d.wall_id,
            "center": {"x": d.center[0], "y": d.center[1]},
            "width": d.width,
            "height": d.height,
            "floor_offset": d.floor_offset,
            "swing_direction": d.swing_direction,
            "door_type": d.door_type,
        }

    @staticmethod
    def _window_to_dict(w: DetectedWindow) -> dict:
        return {
            "id": w.id,
            "wall_id": w.wall_id,
            "center": {"x": w.center[0], "y": w.center[1]},
            "width": w.width,
            "height": w.height,
            "sill_height": w.sill_height,
            "window_type": w.window_type,
        }


class CADPipeline:
    """
    CAD 文件解析主管道。

    将 DXF 文件依次经过所有检测器处理，返回完整的 CADParseResult。

    使用示例::

        pipeline = CADPipeline()
        result = await pipeline.process("/path/to/floor_plan.dxf")
        print(result.to_dict())
    """

    def __init__(self) -> None:
        self._reader = DXFReader.__new__(DXFReader)  # 延迟实例化
        self._scale_detector = ScaleDetector()
        self._wall_detector = WallDetector()
        self._room_detector = RoomDetector()
        self._opening_detector = OpeningDetector()

    async def process(self, file_path: str) -> CADParseResult:
        """
        异步处理 CAD 文件，返回 CADParseResult。

        所有 CPU 密集型操作通过 asyncio.get_event_loop().run_in_executor
        在线程池中执行，避免阻塞事件循环。

        Args:
            file_path: DXF 文件绝对路径

        Returns:
            CADParseResult

        Raises:
            FileNotFoundError: 文件不存在
            Exception: DXF 解析失败
        """
        t_start = time.perf_counter()
        logger.info(f"CAD Pipeline 开始处理：{file_path}")

        loop = asyncio.get_event_loop()

        # 在线程池执行同步 I/O 和 CPU 密集操作
        result = await loop.run_in_executor(None, self._process_sync, file_path)

        elapsed_ms = (time.perf_counter() - t_start) * 1000
        result.parse_time_ms = round(elapsed_ms, 1)
        logger.success(f"CAD Pipeline 处理完成，耗时 {elapsed_ms:.1f}ms")

        return result

    def _process_sync(self, file_path: str) -> CADParseResult:
        """
        同步执行完整解析流程（在线程池中调用）。
        """
        warnings: List[str] = []

        # ── Step 1: 读取 DXF 文件 ─────────────────────────────────────────────
        logger.info("Step 1: 读取 DXF 文件")
        reader = DXFReader(file_path)
        try:
            doc: DXFDocument = reader.read()
        except FileNotFoundError:
            raise
        except Exception as exc:
            logger.error(f"DXF 文件读取失败：{exc}")
            raise RuntimeError(f"DXF 文件解析错误：{exc}") from exc

        # 展平所有图元为列表（保留图层信息）
        all_entities: List[RawEntity] = []
        for layer_entities in doc.entities.values():
            all_entities.extend(layer_entities)

        logger.info(
            f"读取完成：{doc.raw_entity_count} 个图元，{len(doc.layers)} 个图层"
        )

        # 检查图层规范性
        layer_names = list(doc.layers.keys())
        if len(layer_names) <= 2:
            warnings.append(
                f"图层数量过少（仅 {len(layer_names)} 个），图纸可能未按标准分层，"
                "墙体和门窗识别准确率可能降低。"
            )

        # ── Step 2: 分析比例 ──────────────────────────────────────────────────
        logger.info("Step 2: 分析图纸比例")
        try:
            scale_info = self._scale_detector.detect(all_entities)
        except Exception as exc:
            logger.warning(f"比例分析失败，使用默认值：{exc}")
            scale_info = ScaleInfo()
            warnings.append(f"图纸比例分析失败，已使用默认层高 2800mm：{exc}")

        # ── Step 3: 识别墙体 ──────────────────────────────────────────────────
        logger.info("Step 3: 识别墙体")
        try:
            walls = self._wall_detector.detect(all_entities, doc.layers)
        except Exception as exc:
            logger.error(f"墙体识别失败：{exc}")
            walls = []
            warnings.append(f"墙体识别过程发生错误：{exc}")

        if len(walls) < _WARN_MIN_WALLS:
            warnings.append(
                f"墙体识别数量过少（仅 {len(walls)} 段），"
                "请检查图层命名是否包含 wall/墙 等关键字，"
                "或图纸是否为标准建筑平面图。"
            )
        else:
            # 检查墙体置信度
            low_conf_walls = [w for w in walls if w.confidence < _WARN_LOW_CONFIDENCE]
            if low_conf_walls:
                warnings.append(
                    f"有 {len(low_conf_walls)} 段墙体置信度低于 {_WARN_LOW_CONFIDENCE}，"
                    "识别结果可能不准确。"
                )

        # ── Step 4: 识别房间 ──────────────────────────────────────────────────
        logger.info("Step 4: 识别房间")
        text_entities = [e for e in all_entities if e.entity_type in ("TEXT", "MTEXT")]
        # 计算 floor_bound（用于约束房间范围）
        floor_bound = self._compute_bounding_box(all_entities)

        try:
            rooms = self._room_detector.detect(walls, text_entities, floor_bound)
        except Exception as exc:
            logger.error(f"房间识别失败：{exc}")
            rooms = []
            warnings.append(f"房间识别过程发生错误：{exc}")

        if len(rooms) < _WARN_MIN_ROOMS:
            warnings.append(
                f"未识别到有效房间（当前 {len(rooms)} 个），"
                "墙体可能未形成封闭区域，或平面图不完整。"
            )
        else:
            # 检查房间面积异常
            abnormal_rooms = [
                r
                for r in rooms
                if r.area > _WARN_MAX_ROOM_AREA_M2 or r.area < _WARN_MIN_ROOM_AREA_M2
            ]
            if abnormal_rooms:
                names = ", ".join(r.name for r in abnormal_rooms[:3])
                warnings.append(
                    f"检测到 {len(abnormal_rooms)} 个面积异常的房间（{names}...），"
                    "请检查图纸比例和单位设置。"
                )

        # ── Step 5: 识别门窗 ──────────────────────────────────────────────────
        logger.info("Step 5: 识别门窗")
        try:
            doors, windows = self._opening_detector.detect(all_entities, walls)
        except Exception as exc:
            logger.error(f"门窗识别失败：{exc}")
            doors, windows = [], []
            warnings.append(f"门窗识别过程发生错误：{exc}")

        if walls and not doors and not windows:
            warnings.append(
                "未识别到任何门或窗，图纸可能缺少门窗图层（door/window）"
                "或未使用标准块引用。"
            )

        # ── Step 6: 计算 bounding_box ────────────────────────────────────────
        logger.info("Step 6: 计算平面图边界")
        bounding_box = (
            self._compute_bounding_box_from_walls(walls)
            or floor_bound
            or (0.0, 0.0, 0.0, 0.0)
        )

        # ── Step 7: 统计汇总与最终警告 ───────────────────────────────────────
        logger.info(
            f"解析汇总：墙体 {len(walls)} 段，房间 {len(rooms)} 个，"
            f"门 {len(doors)} 个，窗 {len(windows)} 个"
        )

        if not warnings:
            logger.info("无解析警告")
        else:
            for w in warnings:
                logger.warning(f"[解析警告] {w}")

        return CADParseResult(
            walls=walls,
            rooms=rooms,
            doors=doors,
            windows=windows,
            scale_info=scale_info,
            raw_entity_count=doc.raw_entity_count,
            layer_names=layer_names,
            bounding_box=bounding_box,
            parse_warnings=warnings,
        )

    # ── 工具方法 ──────────────────────────────────────────────────────────────

    def _compute_bounding_box(
        self,
        entities: List[RawEntity],
    ) -> Tuple[float, float, float, float]:
        """从所有图元坐标计算边界框。"""
        min_x = float("inf")
        min_y = float("inf")
        max_x = float("-inf")
        max_y = float("-inf")

        for entity in entities:
            for pt in entity.points:
                x, y = pt[0], pt[1]
                if not (math.isfinite(x) and math.isfinite(y)):
                    continue
                if x < min_x:
                    min_x = x
                if y < min_y:
                    min_y = y
                if x > max_x:
                    max_x = x
                if y > max_y:
                    max_y = y

        if not math.isfinite(min_x):
            return (0.0, 0.0, 0.0, 0.0)
        return (min_x, min_y, max_x, max_y)

    def _compute_bounding_box_from_walls(
        self,
        walls: List[DetectedWall],
    ) -> Optional[Tuple[float, float, float, float]]:
        """从墙体端点计算边界框。"""
        if not walls:
            return None

        all_pts = []
        for w in walls:
            all_pts.append(w.start)
            all_pts.append(w.end)

        min_x = min(p[0] for p in all_pts)
        min_y = min(p[1] for p in all_pts)
        max_x = max(p[0] for p in all_pts)
        max_y = max(p[1] for p in all_pts)

        return (min_x, min_y, max_x, max_y)
