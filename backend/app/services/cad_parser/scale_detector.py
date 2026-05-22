"""
图纸比例与尺寸识别器。

从 DIMENSION 图元和 TEXT 中推断图纸比例（scale_factor）和层高。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from loguru import logger

from .dxf_reader import RawEntity

# ── 正则：数字提取 ───────────────────────────────────────────────────────────
# 匹配类似 "2800"、"3600"、"H=3000"、"高度=2800" 等
_RE_PLAIN_NUMBER = re.compile(r"(?<![.\d])(\d{3,5})(?![.\d])")
_RE_HEIGHT_KW = re.compile(
    r"(?:H|h|高度?|层高|净高)\s*[=＝:：]\s*(\d{3,5})", re.UNICODE
)
_RE_SCALE_KW = re.compile(r"1\s*[:/]\s*(\d+)", re.UNICODE)

# 典型建筑层高范围（mm）
_FLOOR_HEIGHT_MIN = 2400.0
_FLOOR_HEIGHT_MAX = 6000.0
_FLOOR_HEIGHT_DEFAULT = 2800.0

# 典型房间尺寸（mm），用于推断比例
_TYPICAL_ROOM_DIM_MIN = 2000.0  # 2m
_TYPICAL_ROOM_DIM_MAX = 15000.0  # 15m

# 标注线段长度（原始坐标）与标注数值的比值若在此范围内认为合理
_SCALE_RATIO_MIN = 0.01
_SCALE_RATIO_MAX = 100.0


@dataclass
class ScaleInfo:
    """图纸比例信息。"""

    unit: str = "mm"
    """坐标单位（始终为 mm，已由 DXFReader 换算）"""

    scale_factor: float = 1.0
    """坐标 × scale_factor = 真实毫米（DXFReader 已处理单位，此处通常为 1.0）"""

    floor_height: float = _FLOOR_HEIGHT_DEFAULT
    """识别到的层高（mm）"""

    detected_dimensions: List[dict] = field(default_factory=list)
    """识别到的标注信息列表"""


class ScaleDetector:
    """
    图纸比例与层高识别器。

    从 DIMENSION 图元和 TEXT/MTEXT 标注中推断：
    1. 图纸比例（坐标是否需要额外缩放）
    2. 建筑层高
    """

    def detect(self, entities: List[RawEntity]) -> ScaleInfo:
        """
        分析所有图元，返回 ScaleInfo。

        Args:
            entities: 所有图元（已由 DXFReader 换算为 mm）

        Returns:
            ScaleInfo
        """
        logger.info(f"开始比例分析，共 {len(entities)} 个图元")

        detected_dims: List[dict] = []
        floor_height = _FLOOR_HEIGHT_DEFAULT
        scale_factor = 1.0

        # ── 1. 收集所有文字标注内容 ──────────────────────────────────────────
        text_entities = [
            e for e in entities if e.entity_type in ("TEXT", "MTEXT", "DIMENSION")
        ]
        logger.debug(f"文字/标注图元：{len(text_entities)} 个")

        # ── 2. 从 DIMENSION 图元推断比例 ─────────────────────────────────────
        dim_scale_factors: List[float] = []
        for entity in entities:
            if entity.entity_type != "DIMENSION":
                continue
            result = self._analyze_dimension(entity)
            if result:
                detected_dims.append(result)
                if "inferred_scale" in result:
                    dim_scale_factors.append(result["inferred_scale"])

        if dim_scale_factors:
            # 取众数（最常见的比例值）
            scale_factor = self._mode_value(dim_scale_factors)
            logger.debug(
                f"从 DIMENSION 推断比例：{scale_factor}（共 {len(dim_scale_factors)} 个样本）"
            )

        # ── 3. 从文字推断层高和比例 ──────────────────────────────────────────
        heights_from_text: List[float] = []
        scale_from_text: Optional[float] = None

        for entity in text_entities:
            text = entity.extra.get("text", "").strip()
            if not text:
                continue

            # 3a. 层高识别
            h = self._extract_floor_height(text)
            if h is not None:
                heights_from_text.append(h)
                detected_dims.append(
                    {
                        "source": "text",
                        "text": text,
                        "type": "floor_height",
                        "value_mm": h,
                    }
                )
                logger.debug(f"从文字提取层高：{h}mm（文字：'{text}'）")

            # 3b. 图纸比例识别（如 "1:100"）
            if scale_from_text is None:
                s = self._extract_scale_from_text(text)
                if s is not None:
                    scale_from_text = s
                    detected_dims.append(
                        {
                            "source": "text",
                            "text": text,
                            "type": "drawing_scale",
                            "value": f"1:{int(s)}",
                            "scale_factor": 1.0,  # 图纸比例不影响坐标（ezdxf 已处理）
                        }
                    )
                    logger.debug(f"识别到图纸比例：1:{int(s)}")

        # ── 4. 确定最终层高 ───────────────────────────────────────────────────
        if heights_from_text:
            # 取最常见值
            floor_height = self._mode_value(heights_from_text)
            logger.debug(f"最终层高：{floor_height}mm")
        else:
            # 尝试从 DIMENSION 标注数值中识别层高（竖向标注，值在合理范围内）
            for dim in detected_dims:
                val = dim.get("measurement_mm", 0.0)
                if _FLOOR_HEIGHT_MIN <= val <= _FLOOR_HEIGHT_MAX:
                    floor_height = val
                    logger.debug(f"从 DIMENSION 推断层高：{floor_height}mm")
                    break

        logger.success(
            f"比例分析完成：scale_factor={scale_factor:.4f}，"
            f"floor_height={floor_height}mm，"
            f"共 {len(detected_dims)} 个标注"
        )

        return ScaleInfo(
            unit="mm",
            scale_factor=scale_factor,
            floor_height=floor_height,
            detected_dimensions=detected_dims,
        )

    # ── 私有方法 ──────────────────────────────────────────────────────────────

    def _analyze_dimension(self, entity: RawEntity) -> Optional[dict]:
        """
        分析单个 DIMENSION 图元，推断比例。

        通过比较标注文字数值与对应线段实际长度（原始坐标差），
        推断 scale_factor = 文字数值 / 线段长度（原始坐标单位）。
        """
        text = entity.extra.get("text", "").strip()
        measurement_mm = entity.extra.get("measurement", 0.0)

        # 提取标注文字中的数字
        text_value = self._extract_number_from_text(text) if text else None

        result: dict = {
            "source": "dimension",
            "text": text,
            "measurement_mm": measurement_mm,
        }

        # 如果 measurement 本身合理（ezdxf 返回的是原始坐标单位的标注值）
        # 我们已经在 DXFReader 中乘以 scale 换算，所以 measurement_mm 已是 mm
        if measurement_mm > 0:
            result["measurement_mm"] = measurement_mm

        # 如果文字和 measurement 都有，且 measurement 已是 mm，
        # 则比较文字数值与 measurement_mm 推断额外缩放
        if text_value is not None and measurement_mm > 0:
            ratio = text_value / measurement_mm
            if _SCALE_RATIO_MIN <= ratio <= _SCALE_RATIO_MAX:
                result["inferred_scale"] = ratio
                result["text_value"] = text_value

        # 如果有两个端点，计算线段长度
        if len(entity.points) >= 3:
            p1 = entity.points[1]
            p2 = entity.points[2]
            segment_len = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
            result["segment_length_mm"] = segment_len
            if text_value is not None and segment_len > 0:
                ratio2 = text_value / segment_len
                if _SCALE_RATIO_MIN <= ratio2 <= _SCALE_RATIO_MAX:
                    result["inferred_scale"] = ratio2

        return result if (text or measurement_mm > 0) else None

    def _extract_floor_height(self, text: str) -> Optional[float]:
        """
        从文字中提取层高数值（mm）。

        识别 "H=2800"、"高=3000"、"层高2800" 等格式。
        """
        # 优先匹配 H= 或 高= 格式
        m = _RE_HEIGHT_KW.search(text)
        if m:
            val = float(m.group(1))
            if _FLOOR_HEIGHT_MIN <= val <= _FLOOR_HEIGHT_MAX:
                return val

        # 文字中直接出现 "层高" 或 "净高" 后跟数字
        for pattern in (
            r"层高\s*(\d{3,5})",
            r"净高\s*(\d{3,5})",
            r"高度\s*(\d{3,5})",
        ):
            m2 = re.search(pattern, text, re.UNICODE)
            if m2:
                val = float(m2.group(1))
                if _FLOOR_HEIGHT_MIN <= val <= _FLOOR_HEIGHT_MAX:
                    return val

        return None

    def _extract_scale_from_text(self, text: str) -> Optional[float]:
        """
        从文字中提取图纸比例分母（如 "1:100" → 100.0）。
        """
        m = _RE_SCALE_KW.search(text)
        if m:
            denominator = float(m.group(1))
            if 1 <= denominator <= 5000:
                return denominator
        return None

    def _extract_number_from_text(self, text: str) -> Optional[float]:
        """
        从标注文字中提取主要数字。

        优先匹配整数（建筑尺寸一般为整数），范围 100-99999mm。
        """
        # 去除特殊前缀（如 "%%d"、"<>" 等 DXF 占位符）
        clean = re.sub(r"<%>|<>|%%[a-zA-Z]", "", text).strip()
        clean = re.sub(r"[^0-9.]", " ", clean)

        # 找所有数字
        numbers = []
        for token in clean.split():
            try:
                val = float(token)
                if 100 <= val <= 99999:
                    numbers.append(val)
            except ValueError:
                continue

        if not numbers:
            return None
        # 返回最大的合理数字
        return max(numbers)

    @staticmethod
    def _mode_value(values: List[float]) -> float:
        """
        计算浮点列表的众数（近似）。

        将值四舍五入到 1 位小数后计数，返回最多的值。
        若列表为空，返回 1.0。
        """
        if not values:
            return 1.0
        freq: Dict[float, int] = {}
        for v in values:
            key = round(v, 1)
            freq[key] = freq.get(key, 0) + 1
        best = max(freq, key=lambda k: freq[k])
        return best
