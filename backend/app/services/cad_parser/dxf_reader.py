"""
DXF 文件读取器。

使用 ezdxf 读取 DXF 文件，将所有图元统一转换为 RawEntity 数据类，
并将坐标单位统一换算为毫米（mm）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import ezdxf
from ezdxf.document import Drawing
from ezdxf.entities import (
    Arc,
    Circle,
    DXFGraphic,
    Insert,
    Line,
    LWPolyline,
    MText,
    Polyline,
    Text,
)
from loguru import logger

# ── 单位换算表（INSUNITS → mm 乘数）────────────────────────────────────────
# DXF 规范：https://help.autodesk.com/view/OARX/2024/ENU/?guid=GUID-A85E8E67-27CD-4C59-BE61-4DC9FADBE74A
_UNIT_SCALE: Dict[int, float] = {
    0: 1.0,  # 无单位，默认 mm
    1: 25.4,  # 英寸
    2: 25.4,  # 英尺（此处简化为英寸，实际应 ×304.8，但 INSUNITS=2 代表英寸）
    3: 1609344.0,  # 英里
    4: 1.0,  # 毫米
    5: 10.0,  # 厘米
    6: 1000.0,  # 米
    7: 1000000.0,  # 千米
    8: 25.4,  # 微英寸
    9: 0.0254,  # 密耳
    10: 914.4,  # 码
    11: 304.8,  # 英尺（修正）
    12: 914400.0,  # 英里（修正）
    13: 1e-6,  # 微米
    14: 0.1,  # 分米（实际 dm=100mm，此处保守）
    15: 100.0,  # 分米
    16: 100000.0,  # 十千米（hm）
    17: 1e9,  # 千兆米
    18: 1e12,  # 太米
    19: 1e-7,  # 埃
    20: 1e-10,  # 纳米（实际 1nm=1e-6 mm）
    21: 1e-4,  # 微米（修正：1µm=0.001mm）
    22: 1e-1,  # 分米（修正）
    23: 1e4,  # 十万米（decameter）
    24: 1e5,  # 百千米（hectometer）
}

# 更精确的映射（覆盖常用值）
_UNIT_SCALE_PRECISE: Dict[int, float] = {
    0: 1.0,  # 无单位 → 默认 mm
    1: 25.4,  # 英寸 → mm
    2: 304.8,  # 英尺 → mm
    4: 1.0,  # mm
    5: 10.0,  # cm → mm
    6: 1000.0,  # m → mm
    7: 1000000.0,  # km → mm
    11: 304.8,  # 英尺 → mm（同 2）
    13: 0.001,  # 微米 → mm
    14: 100.0,  # dm → mm（1 dm = 100 mm）
}


@dataclass
class RawEntity:
    """统一的图元数据类，所有坐标已换算为 mm。"""

    entity_type: str
    """图元类型：LINE / LWPOLYLINE / ARC / CIRCLE / TEXT / MTEXT / INSERT / DIMENSION / POLYLINE"""

    layer: str
    """所在图层名称"""

    color: int
    """颜色号（256 表示随层，0 表示随块）"""

    points: List[Tuple[float, float]]
    """关键点坐标（mm），含义随 entity_type 而异"""

    extra: Dict[str, Any] = field(default_factory=dict)
    """额外属性字典（半径、文字、块名等）"""


@dataclass
class LayerInfo:
    """图层信息"""

    name: str
    color: int
    is_frozen: bool = False
    is_off: bool = False


@dataclass
class DXFDocument:
    """DXF 文档解析结果"""

    units: str
    """图纸单位名称（始终为 'mm'，已换算）"""

    scale_factor: float
    """原始坐标 × scale_factor = mm"""

    layers: Dict[str, LayerInfo]
    """图层字典：图层名 → LayerInfo"""

    entities: Dict[str, List[RawEntity]]
    """图元字典：图层名 → [RawEntity, ...]"""

    blocks: List[Dict[str, Any]]
    """块定义列表"""

    raw_entity_count: int
    """原始图元总数"""


class DXFReader:
    """
    DXF 文件读取器。

    将 DXF 文件解析为统一的 DXFDocument 结构，所有坐标换算为 mm。
    """

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self._scale: float = 1.0

    # ── 公共接口 ─────────────────────────────────────────────────────────────

    def read(self) -> DXFDocument:
        """
        读取 DXF 文件，返回 DXFDocument。

        Raises:
            FileNotFoundError: 文件不存在
            ezdxf.DXFError: DXF 格式错误
        """
        logger.info(f"开始读取 DXF 文件：{self.file_path}")

        try:
            doc: Drawing = ezdxf.readfile(self.file_path)
        except ezdxf.DXFError as exc:
            logger.error(f"DXF 解析失败：{exc}")
            raise
        except FileNotFoundError:
            logger.error(f"文件不存在：{self.file_path}")
            raise

        # 1. 确定单位换算系数
        self._scale = self._resolve_scale(doc)
        logger.debug(f"单位换算系数：{self._scale}")

        # 2. 读取图层
        layers = self._read_layers(doc)
        logger.debug(f"读取到 {len(layers)} 个图层")

        # 3. 读取模型空间图元
        msp = doc.modelspace()
        entities: Dict[str, List[RawEntity]] = {}
        raw_count = 0

        for entity in msp:
            raw_entity = self._parse_entity(entity)
            if raw_entity is None:
                continue
            layer_name = raw_entity.layer
            if layer_name not in entities:
                entities[layer_name] = []
            entities[layer_name].append(raw_entity)
            raw_count += 1

        # 4. 读取块定义
        blocks = self._read_blocks(doc)

        logger.success(
            f"DXF 读取完成：{raw_count} 个图元，{len(layers)} 个图层，"
            f"{len(blocks)} 个块定义"
        )

        return DXFDocument(
            units="mm",
            scale_factor=self._scale,
            layers=layers,
            entities=entities,
            blocks=blocks,
            raw_entity_count=raw_count,
        )

    # ── 私有方法 ─────────────────────────────────────────────────────────────

    def _resolve_scale(self, doc: Drawing) -> float:
        """从 INSUNITS 变量确定换算系数。"""
        try:
            insunits = doc.header.get("$INSUNITS", 0)
            scale = _UNIT_SCALE_PRECISE.get(int(insunits), 1.0)
            logger.debug(f"INSUNITS={insunits}，换算系数={scale}")
            return scale
        except Exception as exc:
            logger.warning(f"无法读取 INSUNITS，默认按 mm 处理：{exc}")
            return 1.0

    def _read_layers(self, doc: Drawing) -> Dict[str, LayerInfo]:
        """读取所有图层信息。"""
        layers: Dict[str, LayerInfo] = {}
        try:
            for layer in doc.layers:
                name = layer.dxf.name
                color = getattr(layer.dxf, "color", 7)
                is_frozen = layer.is_frozen()
                is_off = not layer.is_on()
                layers[name] = LayerInfo(
                    name=name,
                    color=color,
                    is_frozen=is_frozen,
                    is_off=is_off,
                )
        except Exception as exc:
            logger.warning(f"读取图层时出错：{exc}")
        return layers

    def _read_blocks(self, doc: Drawing) -> List[Dict[str, Any]]:
        """读取块定义列表（不含 *Model_Space 和 *Paper_Space）。"""
        blocks = []
        try:
            for block in doc.blocks:
                name = block.name
                if name.startswith("*"):
                    continue
                entity_types = list(
                    {e.dxftype() for e in block if hasattr(e, "dxftype")}
                )
                blocks.append(
                    {
                        "name": name,
                        "entity_types": entity_types,
                        "entity_count": sum(1 for _ in block),
                    }
                )
        except Exception as exc:
            logger.warning(f"读取块定义时出错：{exc}")
        return blocks

    def _s(self, v: float) -> float:
        """将原始坐标值乘以换算系数，得到 mm。"""
        return v * self._scale

    def _pt(self, pt) -> Tuple[float, float]:
        """将 ezdxf 点转换为 (x_mm, y_mm) 元组。"""
        return (self._s(float(pt[0])), self._s(float(pt[1])))

    def _get_color(self, entity: DXFGraphic) -> int:
        """获取图元颜色号。"""
        try:
            return int(entity.dxf.color)
        except Exception:
            return 256  # 随层

    def _get_layer(self, entity: DXFGraphic) -> str:
        """获取图元所在图层名。"""
        try:
            return str(entity.dxf.layer)
        except Exception:
            return "0"

    def _parse_entity(self, entity: DXFGraphic) -> Optional[RawEntity]:
        """将单个 DXF 图元解析为 RawEntity，不支持的类型返回 None。"""
        etype = entity.dxftype()
        try:
            if etype == "LINE":
                return self._parse_line(entity)
            elif etype == "LWPOLYLINE":
                return self._parse_lwpolyline(entity)
            elif etype == "POLYLINE":
                return self._parse_polyline(entity)
            elif etype == "ARC":
                return self._parse_arc(entity)
            elif etype == "CIRCLE":
                return self._parse_circle(entity)
            elif etype == "TEXT":
                return self._parse_text(entity)
            elif etype == "MTEXT":
                return self._parse_mtext(entity)
            elif etype == "INSERT":
                return self._parse_insert(entity)
            elif etype == "DIMENSION":
                return self._parse_dimension(entity)
            else:
                # 忽略不支持的图元类型（HATCH、SOLID 等）
                return None
        except Exception as exc:
            logger.debug(f"解析 {etype} 图元失败（已跳过）：{exc}")
            return None

    def _parse_line(self, entity) -> RawEntity:
        start = self._pt(entity.dxf.start)
        end = self._pt(entity.dxf.end)
        return RawEntity(
            entity_type="LINE",
            layer=self._get_layer(entity),
            color=self._get_color(entity),
            points=[start, end],
            extra={},
        )

    def _parse_lwpolyline(self, entity) -> RawEntity:
        points = [self._pt(pt) for pt in entity.get_points("xy")]
        is_closed = entity.is_closed
        width = 0.0
        try:
            # 常数宽度存在 dxf.const_width
            width = self._s(float(entity.dxf.const_width))
        except Exception:
            # 逐顶点宽度
            try:
                widths = [pt[3] for pt in entity.get_points("xyseb")]
                if widths:
                    width = self._s(max(widths))
            except Exception:
                width = 0.0
        return RawEntity(
            entity_type="LWPOLYLINE",
            layer=self._get_layer(entity),
            color=self._get_color(entity),
            points=points,
            extra={"is_closed": is_closed, "width": width},
        )

    def _parse_polyline(self, entity) -> RawEntity:
        try:
            points = [self._pt(v.dxf.location) for v in entity.vertices]
        except Exception:
            points = []
        is_closed = bool(entity.is_closed)
        return RawEntity(
            entity_type="POLYLINE",
            layer=self._get_layer(entity),
            color=self._get_color(entity),
            points=points,
            extra={"is_closed": is_closed},
        )

    def _parse_arc(self, entity) -> RawEntity:
        center = self._pt(entity.dxf.center)
        radius = self._s(float(entity.dxf.radius))
        start_angle = float(entity.dxf.start_angle)
        end_angle = float(entity.dxf.end_angle)
        # 计算弧线起止点（便于后续几何运算）
        start_pt = (
            center[0] + radius * math.cos(math.radians(start_angle)),
            center[1] + radius * math.sin(math.radians(start_angle)),
        )
        end_pt = (
            center[0] + radius * math.cos(math.radians(end_angle)),
            center[1] + radius * math.sin(math.radians(end_angle)),
        )
        return RawEntity(
            entity_type="ARC",
            layer=self._get_layer(entity),
            color=self._get_color(entity),
            points=[center, start_pt, end_pt],
            extra={
                "radius": radius,
                "start_angle": start_angle,
                "end_angle": end_angle,
            },
        )

    def _parse_circle(self, entity) -> RawEntity:
        center = self._pt(entity.dxf.center)
        radius = self._s(float(entity.dxf.radius))
        return RawEntity(
            entity_type="CIRCLE",
            layer=self._get_layer(entity),
            color=self._get_color(entity),
            points=[center],
            extra={"radius": radius},
        )

    def _parse_text(self, entity) -> RawEntity:
        insert = self._pt(entity.dxf.insert)
        text_str = str(entity.dxf.text) if hasattr(entity.dxf, "text") else ""
        height = (
            self._s(float(entity.dxf.height)) if hasattr(entity.dxf, "height") else 0.0
        )
        rotation = (
            float(entity.dxf.rotation) if hasattr(entity.dxf, "rotation") else 0.0
        )
        return RawEntity(
            entity_type="TEXT",
            layer=self._get_layer(entity),
            color=self._get_color(entity),
            points=[insert],
            extra={"text": text_str, "height": height, "rotation": rotation},
        )

    def _parse_mtext(self, entity) -> RawEntity:
        insert = self._pt(entity.dxf.insert)
        try:
            text_str = entity.plain_mtext()
        except Exception:
            try:
                text_str = str(entity.dxf.text)
            except Exception:
                text_str = ""
        height = 0.0
        try:
            height = self._s(float(entity.dxf.char_height))
        except Exception:
            pass
        return RawEntity(
            entity_type="MTEXT",
            layer=self._get_layer(entity),
            color=self._get_color(entity),
            points=[insert],
            extra={"text": text_str, "height": height},
        )

    def _parse_insert(self, entity) -> RawEntity:
        insert = self._pt(entity.dxf.insert)
        block_name = str(entity.dxf.name) if hasattr(entity.dxf, "name") else ""
        x_scale = float(entity.dxf.xscale) if hasattr(entity.dxf, "xscale") else 1.0
        y_scale = float(entity.dxf.yscale) if hasattr(entity.dxf, "yscale") else 1.0
        rotation = (
            float(entity.dxf.rotation) if hasattr(entity.dxf, "rotation") else 0.0
        )
        return RawEntity(
            entity_type="INSERT",
            layer=self._get_layer(entity),
            color=self._get_color(entity),
            points=[insert],
            extra={
                "block_name": block_name,
                "x_scale": x_scale,
                "y_scale": y_scale,
                "rotation": rotation,
            },
        )

    def _parse_dimension(self, entity) -> RawEntity:
        # DIMENSION 图元的插入点
        try:
            insert = self._pt(entity.dxf.defpoint)
        except Exception:
            try:
                insert = self._pt(entity.dxf.text_midpoint)
            except Exception:
                insert = (0.0, 0.0)

        text_str = ""
        measurement = 0.0
        try:
            text_str = str(entity.dxf.text) if hasattr(entity.dxf, "text") else ""
        except Exception:
            pass
        try:
            measurement = self._s(float(entity.dxf.measurement))
        except Exception:
            pass

        # 尝试获取标注端点
        points = [insert]
        try:
            p1 = self._pt(entity.dxf.defpoint2)
            p2 = self._pt(entity.dxf.defpoint3)
            points = [insert, p1, p2]
        except Exception:
            pass

        return RawEntity(
            entity_type="DIMENSION",
            layer=self._get_layer(entity),
            color=self._get_color(entity),
            points=points,
            extra={"text": text_str, "measurement": measurement},
        )
