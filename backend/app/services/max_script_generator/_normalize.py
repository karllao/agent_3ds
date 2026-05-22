"""
坐标格式归一化工具。

AI Agent 输出的点坐标可能是以下任一形式，builder 必须统一接受：
  - list / tuple: [x, y] 或 [x, y, z]
  - dict: {"x": ..., "y": ..., "z": ...}
  - 数值键 dict: {0: ..., 1: ..., 2: ...}

z 在 2D 场景或省略时默认为 0。
"""

from __future__ import annotations

from typing import Any


def _extract(point: Any, k_idx: int, k_name: str) -> Any:
    if isinstance(point, dict):
        if k_name in point:
            return point[k_name]
        if k_idx in point:
            return point[k_idx]
        # 字符串 key
        if str(k_idx) in point:
            return point[str(k_idx)]
        return None
    # list / tuple：越界时返回 None 让上层走默认值
    try:
        return point[k_idx]
    except (IndexError, KeyError, TypeError):
        return None


def xy(point: Any) -> tuple[float, float]:
    """Accept [x,y] / (x,y) / {'x':,'y':}. Returns (x, y) floats."""
    if point is None:
        raise ValueError("coordinate point is None")
    x = _extract(point, 0, "x")
    y = _extract(point, 1, "y")
    if x is None or y is None:
        raise ValueError(f"cannot extract x/y from {point!r}")
    return float(x), float(y)


def xyz(point: Any, *, default_z: float = 0.0) -> tuple[float, float, float]:
    """Accept [x,y,z] / [x,y] / (x,y,z) / {'x':,'y':,'z':}. z optional → default_z."""
    if point is None:
        raise ValueError("coordinate point is None")
    x = _extract(point, 0, "x")
    y = _extract(point, 1, "y")
    z = _extract(point, 2, "z")
    if x is None or y is None:
        raise ValueError(f"cannot extract x/y from {point!r}")
    return float(x), float(y), float(z if z is not None else default_z)


def rgb(color: Any) -> tuple[float, float, float]:
    """Accept [r,g,b] or {'r':,'g':,'b':} (0-255)."""
    if color is None:
        return 128.0, 128.0, 128.0
    if isinstance(color, dict):
        r = color.get("r", color.get(0, 128))
        g = color.get("g", color.get(1, 128))
        b = color.get("b", color.get(2, 128))
        return float(r), float(g), float(b)
    return float(color[0]), float(color[1]), float(color[2])
