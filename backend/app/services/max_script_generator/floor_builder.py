"""
FloorScriptBuilder
------------------
将房间多边形数据转换为地板 / 天花板 MAXScript 代码。

输入示例
--------
rooms = [
    {
        "id": "room_living",
        "name": "客厅",
        "boundary": [          # 顺序顶点列表，单位 mm
            [0, 0],
            [6000, 0],
            [6000, 5000],
            [0, 5000]
        ],
        "floor_height": 0,     # 地板底面 Z（通常为 0）
        "ceiling_height": 2800,# 天花板底面 Z
        "floor_material": "wood_floor",
        "ceiling_material": "white_paint"
    },
    ...
]
"""

from __future__ import annotations

from typing import Any


class FloorScriptBuilder:
    """生成地板和天花板的 MAXScript 代码段。"""

    FLOOR_THICKNESS = 5.0  # mm
    CEILING_THICKNESS = 5.0  # mm

    def build(self, rooms: list[dict[str, Any]]) -> str:
        """
        返回 MAXScript 字符串：
          - 每个房间生成一个地板（SplineShape + Extrude）
          - 每个房间生成一个天花板（同形状，Z 偏移至层高）
          - 地板放入 "Floors" Group，天花板放入 "Ceilings" Group
        """
        lines: list[str] = []
        lines.append("-- ============================================================")
        lines.append("-- [Section] Floor / Ceiling Builder - Auto Generated")
        lines.append("-- ============================================================")
        lines.append("")

        floor_vars: list[str] = []
        ceiling_vars: list[str] = []

        for idx, room in enumerate(rooms, start=1):
            room_num = f"{idx:03d}"
            room_name = room.get("name", f"Room{idx}")
            room_id = room.get("id", f"room_{idx}")
            boundary: list[list[float]] = room.get("boundary", [])
            floor_z = float(room.get("floor_height", 0))
            ceiling_z = float(room.get("ceiling_height", 2800))
            floor_mat = room.get("floor_material", "wood_floor")
            ceiling_mat = room.get("ceiling_material", "white_paint")

            if len(boundary) < 3:
                lines.append(
                    f"-- WARNING: room '{room_id}' boundary has < 3 points, skipped"
                )
                continue

            safe_name = room_name.replace(" ", "_").replace("/", "_")

            # ---- 地板 ----
            floor_spline_var = f"floor_spline_{room_num}"
            floor_var = f"floor_{room_num}"
            lines.append(f"-- ---- Floor: {room_name} ----")
            lines += self._spline_from_boundary(
                var_name=floor_spline_var,
                boundary=boundary,
                z_offset=floor_z,
            )
            lines.append(
                f"addModifier {floor_spline_var} "
                f"(Extrude amount:{self.FLOOR_THICKNESS:.1f} capping:true)"
            )
            lines.append(
                f"local {floor_var} = maxOps.CollapseNodeTo {floor_spline_var} 1 false"
            )
            lines.append(f'{floor_var}.name = "Floor_{safe_name}"')
            lines.append(f"-- floor material key: {floor_mat}")
            lines.append("")
            floor_vars.append(floor_var)

            # ---- 天花板 ----
            ceil_spline_var = f"ceil_spline_{room_num}"
            ceil_var = f"ceiling_{room_num}"
            ceil_bottom_z = ceiling_z  # 天花板板底
            lines.append(f"-- ---- Ceiling: {room_name} ----")
            lines += self._spline_from_boundary(
                var_name=ceil_spline_var,
                boundary=boundary,
                z_offset=ceil_bottom_z,
            )
            lines.append(
                f"addModifier {ceil_spline_var} "
                f"(Extrude amount:{self.CEILING_THICKNESS:.1f} capping:true)"
            )
            lines.append(
                f"local {ceil_var} = maxOps.CollapseNodeTo {ceil_spline_var} 1 false"
            )
            lines.append(f'{ceil_var}.name = "Ceiling_{safe_name}"')
            lines.append(f"-- ceiling material key: {ceiling_mat}")
            lines.append("")
            ceiling_vars.append(ceil_var)

        # ---- Group: Floors ----
        lines.append("-- ---- Group Floors ----")
        if floor_vars:
            arr = "#(" + ", ".join(floor_vars) + ")"
            lines.append(f"local floor_group_nodes = {arr}")
            lines.append('group floor_group_nodes name:"Floors"')
        else:
            lines.append("-- No floors to group")
        lines.append("")

        # ---- Group: Ceilings ----
        lines.append("-- ---- Group Ceilings ----")
        if ceiling_vars:
            arr = "#(" + ", ".join(ceiling_vars) + ")"
            lines.append(f"local ceiling_group_nodes = {arr}")
            lines.append('group ceiling_group_nodes name:"Ceilings"')
        else:
            lines.append("-- No ceilings to group")
        lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 私有辅助
    # ------------------------------------------------------------------

    def _spline_from_boundary(
        self,
        var_name: str,
        boundary: list[list[float]],
        z_offset: float,
    ) -> list[str]:
        """
        生成 MAXScript SplineShape + addKnot 代码，将多边形边界转为样条曲线。
        顶点均被设置为 Corner 类型（直角），适合室内平面轮廓。
        """
        lines: list[str] = []
        lines.append(f"local {var_name} = SplineShape()")
        lines.append(f"{var_name}.pos = [0, 0, {z_offset:.2f}]")
        lines.append(f"local splineIdx_{var_name} = addNewSpline {var_name}")

        for pt in boundary:
            px = float(pt[0])
            py = float(pt[1])
            lines.append(
                f"addKnot {var_name} splineIdx_{var_name} #corner #line "
                f"[{px:.2f}, {py:.2f}, 0]"
            )

        lines.append(f"close {var_name} splineIdx_{var_name}")
        lines.append(f"updateShape {var_name}")
        return lines
