"""
WallScriptBuilder
-----------------
将结构化墙体/门/窗数据转换为可在 3ds Max 中执行的 MAXScript 代码片段。

输入示例
--------
walls = [
    {
        "id": "w1",
        "start": [0, 0],
        "end": [5000, 0],
        "thickness": 200,
        "height": 2800,
        "material": "white_paint",
        "doors": ["d1"],        # 门洞 id 列表
        "windows": ["win1"]     # 窗洞 id 列表
    },
    ...
]

doors = [
    {
        "id": "d1",
        "wall_id": "w1",
        "center_offset": 1200,  # 从 wall_start 沿墙方向的距离 (mm)
        "width": 900,
        "height": 2100
    },
    ...
]

windows = [
    {
        "id": "win1",
        "wall_id": "w1",
        "center_offset": 2500,
        "width": 1500,
        "height": 1200,
        "sill_height": 900
    },
    ...
]
"""

from __future__ import annotations

import math
from typing import Any

from ._normalize import xy as _xy


class WallScriptBuilder:
    """生成建造墙体的 MAXScript 代码段。"""

    # 材质分组映射 (material_key -> group_name)
    MATERIAL_GROUPS: dict[str, str] = {
        "white_paint": "Mat_WhitePaint",
        "light_gray_tile": "Mat_LightGrayTile",
        "wood_floor": "Mat_WoodFloor",
        "marble": "Mat_Marble",
        "dark_wood": "Mat_DarkWood",
        "glass": "Mat_Glass",
        "concrete": "Mat_Concrete",
        "metal": "Mat_Metal",
        "white_ceramic": "Mat_WhiteCeramic",
    }

    def build(
        self,
        walls: list[dict[str, Any]],
        doors: list[dict[str, Any]],
        windows: list[dict[str, Any]],
    ) -> str:
        """
        返回完整的 MAXScript 代码字符串，涵盖：
          - 所有墙体几何体创建
          - 门洞 / 窗洞 Boolean 切割
          - 材质分组
          - 将所有墙体放入 "Walls" Group
        """
        # 建立 id -> 对象 索引
        door_map: dict[str, dict] = {d["id"]: d for d in doors}
        window_map: dict[str, dict] = {w["id"]: w for w in windows}

        lines: list[str] = []
        lines.append("-- ============================================================")
        lines.append("-- [Section] Wall Builder - Auto Generated")
        lines.append("-- ============================================================")
        lines.append("")

        # 用于记录各材质分组下的变量名
        mat_groups: dict[str, list[str]] = {}
        all_wall_vars: list[str] = []

        for idx, wall in enumerate(walls, start=1):
            wall_num = f"{idx:03d}"
            var_name = f"wall_{wall_num}"
            wall_id = wall.get("id", f"w{idx}")
            mat_key = wall.get("material", "white_paint")

            # 解析坐标（兼容 [x,y] / (x,y) / {x,y} 三种 AI 输出格式）
            sx, sy = _xy(wall["start"])
            ex, ey = _xy(wall["end"])
            thickness = float(wall.get("thickness", 200))
            height = float(wall.get("height", 2800))

            wall_len = math.hypot(ex - sx, ey - sy)
            angle_rad = math.atan2(ey - sy, ex - sx)
            cx = (sx + ex) / 2.0
            cy = (sy + ey) / 2.0
            cz = height / 2.0

            lines.append(f"-- ---- Wall {wall_num} (id={wall_id}) ----")
            lines.append(f"local wall_start_{wall_num} = [{sx:.2f}, {sy:.2f}, 0]")
            lines.append(f"local wall_end_{wall_num}   = [{ex:.2f}, {ey:.2f}, 0]")
            lines.append(f"local wall_len_{wall_num}   = {wall_len:.4f}")
            lines.append(f"local wall_ang_{wall_num}   = {math.degrees(angle_rad):.6f}")
            lines.append(
                f"local {var_name} = Box "
                f"length:{thickness:.2f} "
                f"width:wall_len_{wall_num} "
                f"height:{height:.2f}"
            )
            lines.append(f'{var_name}.name = "Wall_{wall_num}"')
            lines.append(f"{var_name}.pos = [{cx:.2f}, {cy:.2f}, {cz:.2f}]")
            lines.append(f"{var_name}.rotation = (EulerAngles 0 0 wall_ang_{wall_num})")

            # --- 门洞布尔切割 ---
            door_ids = wall.get("doors", [])
            for d_id in door_ids:
                if d_id not in door_map:
                    lines.append(f"-- WARNING: door id '{d_id}' not found, skipped")
                    continue
                door = door_map[d_id]
                d_offset = float(door.get("center_offset", 0))
                d_width = float(door.get("width", 900))
                d_height = float(door.get("height", 2100))

                # 门中心世界坐标（沿墙方向偏移）
                d_wx = sx + d_offset * math.cos(angle_rad)
                d_wy = sy + d_offset * math.sin(angle_rad)
                d_wz = d_height / 2.0

                d_var = f"door_cut_{wall_num}_{d_id.replace('-', '_')}"
                lines.append(f"")
                lines.append(f"-- Door opening '{d_id}' on Wall_{wall_num}")
                lines.append(
                    f"local {d_var} = Box "
                    f"length:{thickness + 20:.2f} "
                    f"width:{d_width:.2f} "
                    f"height:{d_height:.2f}"
                )
                lines.append(f"{d_var}.pos = [{d_wx:.2f}, {d_wy:.2f}, {d_wz:.2f}]")
                lines.append(
                    f"{d_var}.rotation = (EulerAngles 0 0 wall_ang_{wall_num})"
                )
                lines.append(self._proboolean_subtract(var_name, d_var))

            # --- 窗洞布尔切割 ---
            window_ids = wall.get("windows", [])
            for w_id in window_ids:
                if w_id not in window_map:
                    lines.append(f"-- WARNING: window id '{w_id}' not found, skipped")
                    continue
                win = window_map[w_id]
                w_offset = float(win.get("center_offset", 0))
                w_width = float(win.get("width", 1500))
                w_height = float(win.get("height", 1200))
                sill_h = float(win.get("sill_height", 900))

                w_wx = sx + w_offset * math.cos(angle_rad)
                w_wy = sy + w_offset * math.sin(angle_rad)
                w_wz = sill_h + w_height / 2.0

                w_var = f"win_cut_{wall_num}_{w_id.replace('-', '_')}"
                lines.append(f"")
                lines.append(f"-- Window opening '{w_id}' on Wall_{wall_num}")
                lines.append(
                    f"local {w_var} = Box "
                    f"length:{thickness + 20:.2f} "
                    f"width:{w_width:.2f} "
                    f"height:{w_height:.2f}"
                )
                lines.append(f"{w_var}.pos = [{w_wx:.2f}, {w_wy:.2f}, {w_wz:.2f}]")
                lines.append(
                    f"{w_var}.rotation = (EulerAngles 0 0 wall_ang_{wall_num})"
                )
                lines.append(self._proboolean_subtract(var_name, w_var))

            lines.append("")

            # 记录材质分组
            group_name = self.MATERIAL_GROUPS.get(mat_key, "Mat_Misc")
            mat_groups.setdefault(group_name, []).append(var_name)
            all_wall_vars.append(var_name)

        # --- 材质分组（Selection Sets） ---
        lines.append("-- ---- Material Selection Sets ----")
        for group_name, var_list in mat_groups.items():
            obj_array = "#(" + ", ".join(var_list) + ")"
            lines.append(f'selectionSets["{group_name}"] = {obj_array}')
        lines.append("")

        # --- 将所有墙体放入 "Walls" Group ---
        lines.append("-- ---- Group all walls ----")
        if all_wall_vars:
            obj_array = "#(" + ", ".join(all_wall_vars) + ")"
            lines.append(f"local walls_group_nodes = {obj_array}")
            lines.append('group walls_group_nodes name:"Walls"')
        else:
            lines.append("-- No walls to group")
        lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 私有辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _proboolean_subtract(base_var: str, cutter_var: str) -> str:
        """
        返回布尔减法操作的 MAXScript 代码（原地修改 base_var）。

        ProBoolean 是 3ds Max 中的 *compound object*，不是 modifier，所以
        不能用 `addModifier`。正确的 API 是先用 ProBoolean.CreateBooleanObject
        把 base 转成 ProBoolean 节点，再用 SetOperandB 添加 cutter 并指定
        操作类型（2 = Subtraction）。

        SetOperandB 签名（3ds Max 帮助文档）:
          ProBoolean.SetOperandB <base> <operand>
              <copyMode:int>      0=Reference 1=Copy 2=Move 3=Instance
              <material:int>      0=Operand Mat  1=Original Mat  2=No Mat
              <subMtl:int>        0=Apply Mat IDs  1=Keep Mat IDs
              <displayMode:int>   0=Result  1=OperandsAndResult …
              <boolOp:int>        0=Union 1=Intersect 2=Subtract 3=Merge …

        如果 ProBoolean 不可用（极少见），用 try/catch 回退到经典 Boolean
        （`boolObj.createBooleanObject`），同样以减法收尾。
        """
        lines = [
            f"-- Boolean subtract: {base_var} -= {cutter_var}",
            f"try (",
            f"    ProBoolean.CreateBooleanObject {base_var}",
            f"    ProBoolean.SetOperandB {base_var} {cutter_var} 2 0 0 0 2",
            f") catch (",
            f'    format "ProBoolean failed (%), fallback to boolObj\\n" '
            f"(getCurrentException())",
            f"    if isValidNode {cutter_var} do (",
            f"        boolObj.createBooleanObject {base_var} {cutter_var}",
            f"        boolObj.setBoolOp {base_var} 3  -- 3 = Subtraction A-B",
            f"    )",
            f")",
        ]
        return "\n".join(lines)
