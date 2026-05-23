"""
DoorWindowScriptBuilder
-----------------------
将门/窗数据转换为 3ds Max 简模的 MAXScript 代码片段。

门简模由三部分组成：
  - 门框：左、右、上三根 Box 围成门框
  - 门扇：一个薄 Box（厚 40mm），带木质材质
  - 门把手：一个小球体，位于门扇侧面

窗简模由两部分组成：
  - 窗框：四根 Box 围成矩形窗框
  - 玻璃：一个极薄 Box（厚 8mm），半透明材质（opacity 85）

所有门/窗根据 center（世界坐标）和 wall_rotation（绕 Z 轴的角度，度）
正确定位和旋转。

输入示例
--------
doors = [
    {
        "id": "d1",
        "center": [1200.0, 0.0, 0.0],   # 门洞中心世界坐标 (mm)
        "width": 900.0,                  # 门洞净宽 (mm)
        "height": 2100.0,                # 门洞净高 (mm)
        "wall_rotation": 0.0,            # 所在墙体绕 Z 轴的旋转角度 (度)
        "swing_direction": "left"        # 开启方向: "left" | "right"（可选）
    },
    ...
]

windows = [
    {
        "id": "win1",
        "center": [2500.0, 0.0, 900.0], # 窗洞中心世界坐标 (mm)，Z 为窗中心高度
        "width": 1500.0,
        "height": 1200.0,
        "wall_rotation": 0.0,
        "frame_depth": 80.0             # 窗框深度 (mm)，可选，默认 80
    },
    ...
]
"""

from __future__ import annotations

import math
from typing import Any

from ._normalize import xyz as _xyz

# ── 门框尺寸常量 ─────────────────────────────────────────────
_DOOR_FRAME_WIDTH: float = 60.0  # 门框截面宽度 (mm)
_DOOR_FRAME_DEPTH: float = 120.0  # 门框截面深度（墙厚方向，mm）
_DOOR_PANEL_THICKNESS: float = 40.0  # 门扇厚度 (mm)
_DOOR_PANEL_GAP: float = 5.0  # 门扇与门框的间隙 (mm)
_DOOR_HANDLE_RADIUS: float = 15.0  # 门把手球半径 (mm)
_DOOR_HANDLE_OFFSET_H: float = 100.0  # 把手距门扇侧边的水平偏移 (mm)
_DOOR_HANDLE_HEIGHT: float = 1050.0  # 把手距地面高度 (mm)

# ── 窗框尺寸常量 ─────────────────────────────────────────────
_WIN_FRAME_WIDTH: float = 60.0  # 窗框截面宽度 (mm)
_WIN_GLASS_THICKNESS: float = 8.0  # 玻璃厚度 (mm)
_WIN_GLASS_OPACITY: int = 85  # 玻璃不透明度（0=全透明，100=不透明）


class DoorWindowScriptBuilder:
    """
    生成门窗简模的 MAXScript 代码段。

    调用方式::

        builder = DoorWindowScriptBuilder()
        script = builder.build(doors=scene["doors"], windows=scene["windows"])
    """

    def build(
        self,
        doors: list[dict[str, Any]],
        windows: list[dict[str, Any]],
    ) -> str:
        """
        返回完整的 MAXScript 代码字符串，包含：
          - 门框、门扇、门把手几何体
          - 窗框、玻璃几何体
          - 材质定义（木门材质、玻璃材质）
          - 将所有门放入 "Doors" Group，所有窗放入 "Windows" Group

        Parameters
        ----------
        doors:
            门数据列表，每项包含 id, center, width, height, wall_rotation
        windows:
            窗数据列表，每项包含 id, center, width, height, wall_rotation

        Returns
        -------
        str
            可直接在 3ds Max 中执行的 MAXScript 字符串
        """
        lines: list[str] = []

        lines.append("-- ============================================================")
        lines.append("-- [Section] Door & Window Builder - Auto Generated")
        lines.append("-- ============================================================")
        lines.append("")

        # ── 共享材质定义 ────────────────────────────────────────
        lines += self._build_shared_materials()
        lines.append("")

        # ── 门 ──────────────────────────────────────────────────
        all_door_group_vars: list[str] = []
        if doors:
            lines.append(
                "-- ============================================================"
            )
            lines.append("-- Doors")
            lines.append(
                "-- ============================================================"
            )
            lines.append("")
            for idx, door in enumerate(doors, start=1):
                group_var, door_lines = self._build_door(idx, door)
                lines += door_lines
                all_door_group_vars.append(group_var)
                lines.append("")

        # ── 窗 ──────────────────────────────────────────────────
        all_window_group_vars: list[str] = []
        if windows:
            lines.append(
                "-- ============================================================"
            )
            lines.append("-- Windows")
            lines.append(
                "-- ============================================================"
            )
            lines.append("")
            for idx, win in enumerate(windows, start=1):
                group_var, win_lines = self._build_window(idx, win)
                lines += win_lines
                all_window_group_vars.append(group_var)
                lines.append("")

        # ── 顶层分组 ────────────────────────────────────────────
        lines += self._build_top_groups(all_door_group_vars, all_window_group_vars)

        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────
    # 共享材质
    # ──────────────────────────────────────────────────────────────

    def _build_shared_materials(self) -> list[str]:
        """定义门扇木质材质和玻璃材质（只创建一次）。"""
        return [
            "-- ---- Shared Materials ----",
            "",
            "-- 门扇木质材质",
            "local door_wood_mat = StandardMaterial()",
            'door_wood_mat.name = "DoorWood"',
            "door_wood_mat.diffuse = (color 180 140 100)",
            "door_wood_mat.specularLevel = 30",
            "door_wood_mat.glossiness = 25",
            "",
            "-- 门框材质（白色哑光）",
            "local door_frame_mat = StandardMaterial()",
            'door_frame_mat.name = "DoorFrame"',
            "door_frame_mat.diffuse = (color 240 238 235)",
            "door_frame_mat.specularLevel = 10",
            "door_frame_mat.glossiness = 15",
            "",
            "-- 门把手材质（金属）",
            "local door_handle_mat = StandardMaterial()",
            'door_handle_mat.name = "DoorHandle"',
            "door_handle_mat.diffuse = (color 200 180 120)",
            "door_handle_mat.specularLevel = 80",
            "door_handle_mat.glossiness = 70",
            "try ( door_handle_mat.specularColor = (color 255 240 180) ) catch ()",
            "",
            "-- 窗框材质（白色）",
            "local win_frame_mat = StandardMaterial()",
            'win_frame_mat.name = "WindowFrame"',
            "win_frame_mat.diffuse = (color 245 245 245)",
            "win_frame_mat.specularLevel = 20",
            "win_frame_mat.glossiness = 30",
            "",
            "-- 玻璃材质（半透明）",
            "local win_glass_mat = StandardMaterial()",
            'win_glass_mat.name = "WindowGlass"',
            "win_glass_mat.diffuse = (color 200 220 240)",
            f"win_glass_mat.opacity = {_WIN_GLASS_OPACITY}",
            "win_glass_mat.specularLevel = 90",
            "win_glass_mat.glossiness = 85",
            "win_glass_mat.twoSided = true",
            "try ( win_glass_mat.filterColor = (color 180 210 240) ) catch ()",
        ]

    # ──────────────────────────────────────────────────────────────
    # 门
    # ──────────────────────────────────────────────────────────────

    def _build_door(
        self,
        idx: int,
        door: dict[str, Any],
    ) -> tuple[str, list[str]]:
        """
        生成单扇门的 MAXScript 代码。

        Returns
        -------
        tuple[str, list[str]]
            (group_var_name, code_lines)
        """
        num = f"{idx:03d}"
        door_id = door.get("id", f"d{idx}")

        # ── 解析参数 ────────────────────────────────────────────
        center = door.get("center", [0.0, 0.0, 0.0])
        cx, cy, cz = _xyz(center)
        width = float(door.get("width", 900.0))
        height = float(door.get("height", 2100.0))
        rot_deg = float(door.get("wall_rotation", 0.0))
        swing = door.get("swing_direction", "left")

        # 门洞底部 Z（cz 通常为 0，即地面）
        floor_z = cz

        # 变量前缀
        pfx = f"door_{num}"
        group_var = f"{pfx}_grp"

        lines: list[str] = []
        lines.append(f"-- ---- Door {num} (id={door_id}) ----")
        lines.append(
            f"-- center=({cx:.1f}, {cy:.1f}, {floor_z:.1f}), "
            f"w={width:.0f}, h={height:.0f}, rot={rot_deg:.1f}deg"
        )
        lines.append("")

        # ── 门框：左柱 ──────────────────────────────────────────
        # 门框左柱：沿墙方向（X 轴）偏移 -(width/2 + frame_w/2)
        # 在局部坐标系中计算，最后旋转到世界坐标
        fw = _DOOR_FRAME_WIDTH
        fd = _DOOR_FRAME_DEPTH

        # 左柱局部偏移（沿墙方向 = X 轴）
        left_local_x = -(width / 2.0 + fw / 2.0)
        left_local_y = 0.0
        left_local_z = floor_z + height / 2.0

        left_wx, left_wy = self._rotate_2d(left_local_x, left_local_y, rot_deg)
        left_wx += cx
        left_wy += cy

        frame_left_var = f"{pfx}_frame_left"
        lines.append("-- 门框左柱")
        lines.append(
            f"local {frame_left_var} = Box "
            f"length:{fd:.2f} width:{fw:.2f} height:{height:.2f}"
        )
        lines.append(
            f"{frame_left_var}.pos = [{left_wx:.2f}, {left_wy:.2f}, {left_local_z:.2f}]"
        )
        lines.append(f"{frame_left_var}.rotation = (EulerAngles 0 0 {rot_deg:.4f})")
        lines.append(f"{frame_left_var}.material = door_frame_mat")
        lines.append(f'{frame_left_var}.name = "Door_{num}_FrameLeft"')
        lines.append("")

        # ── 门框：右柱 ──────────────────────────────────────────
        right_local_x = width / 2.0 + fw / 2.0
        right_local_y = 0.0
        right_local_z = left_local_z

        right_wx, right_wy = self._rotate_2d(right_local_x, right_local_y, rot_deg)
        right_wx += cx
        right_wy += cy

        frame_right_var = f"{pfx}_frame_right"
        lines.append("-- 门框右柱")
        lines.append(
            f"local {frame_right_var} = Box "
            f"length:{fd:.2f} width:{fw:.2f} height:{height:.2f}"
        )
        lines.append(
            f"{frame_right_var}.pos = [{right_wx:.2f}, {right_wy:.2f}, {right_local_z:.2f}]"
        )
        lines.append(f"{frame_right_var}.rotation = (EulerAngles 0 0 {rot_deg:.4f})")
        lines.append(f"{frame_right_var}.material = door_frame_mat")
        lines.append(f'{frame_right_var}.name = "Door_{num}_FrameRight"')
        lines.append("")

        # ── 门框：上横梁 ────────────────────────────────────────
        top_beam_width = width + 2.0 * fw  # 横梁总宽（含两侧门框）
        top_local_x = 0.0
        top_local_y = 0.0
        top_local_z = floor_z + height + fw / 2.0

        top_wx, top_wy = self._rotate_2d(top_local_x, top_local_y, rot_deg)
        top_wx += cx
        top_wy += cy

        frame_top_var = f"{pfx}_frame_top"
        lines.append("-- 门框上横梁")
        lines.append(
            f"local {frame_top_var} = Box "
            f"length:{fd:.2f} width:{top_beam_width:.2f} height:{fw:.2f}"
        )
        lines.append(
            f"{frame_top_var}.pos = [{top_wx:.2f}, {top_wy:.2f}, {top_local_z:.2f}]"
        )
        lines.append(f"{frame_top_var}.rotation = (EulerAngles 0 0 {rot_deg:.4f})")
        lines.append(f"{frame_top_var}.material = door_frame_mat")
        lines.append(f'{frame_top_var}.name = "Door_{num}_FrameTop"')
        lines.append("")

        # ── 门扇 ────────────────────────────────────────────────
        # 门扇净尺寸（减去间隙）
        panel_w = width - 2.0 * _DOOR_PANEL_GAP
        panel_h = height - _DOOR_PANEL_GAP  # 底部留间隙，顶部贴门框
        panel_t = _DOOR_PANEL_THICKNESS

        # 门扇中心：默认居中，偏移半个厚度到墙面一侧
        panel_local_x = 0.0
        panel_local_y = fd / 2.0 - panel_t / 2.0  # 靠近墙面一侧
        panel_local_z = floor_z + panel_h / 2.0 + _DOOR_PANEL_GAP

        panel_wx, panel_wy = self._rotate_2d(panel_local_x, panel_local_y, rot_deg)
        panel_wx += cx
        panel_wy += cy

        panel_var = f"{pfx}_panel"
        lines.append(f"-- 门扇（厚 {panel_t:.0f}mm）")
        lines.append(
            f"local {panel_var} = Box "
            f"length:{panel_t:.2f} width:{panel_w:.2f} height:{panel_h:.2f}"
        )
        lines.append(
            f"{panel_var}.pos = [{panel_wx:.2f}, {panel_wy:.2f}, {panel_local_z:.2f}]"
        )
        lines.append(f"{panel_var}.rotation = (EulerAngles 0 0 {rot_deg:.4f})")
        lines.append(f"{panel_var}.material = door_wood_mat")
        lines.append(f'{panel_var}.name = "Door_{num}_Panel"')
        lines.append("")

        # ── 门把手 ──────────────────────────────────────────────
        # 把手位置：门扇侧面（根据开启方向决定左/右），距地 1050mm
        handle_side_sign = -1.0 if swing == "left" else 1.0
        handle_local_x = handle_side_sign * (panel_w / 2.0 - _DOOR_HANDLE_OFFSET_H)
        handle_local_y = panel_local_y - panel_t / 2.0 - _DOOR_HANDLE_RADIUS
        handle_local_z = floor_z + _DOOR_HANDLE_HEIGHT

        handle_wx, handle_wy = self._rotate_2d(handle_local_x, handle_local_y, rot_deg)
        handle_wx += cx
        handle_wy += cy

        handle_var = f"{pfx}_handle"
        lines.append(f"-- 门把手（球体，r={_DOOR_HANDLE_RADIUS:.0f}mm）")
        lines.append(
            f"local {handle_var} = Sphere radius:{_DOOR_HANDLE_RADIUS:.2f} segs:12"
        )
        lines.append(
            f"{handle_var}.pos = [{handle_wx:.2f}, {handle_wy:.2f}, {handle_local_z:.2f}]"
        )
        lines.append(f"{handle_var}.material = door_handle_mat")
        lines.append(f'{handle_var}.name = "Door_{num}_Handle"')
        lines.append("")

        # ── 将门的所有部件组合为 Group ──────────────────────────
        parts = [frame_left_var, frame_right_var, frame_top_var, panel_var, handle_var]
        parts_array = "#(" + ", ".join(parts) + ")"
        lines.append(f"-- 将 Door_{num} 所有部件放入 Group")
        lines.append(f"local {group_var}_nodes = {parts_array}")
        lines.append(f'local {group_var} = group {group_var}_nodes name:"Door_{num}"')
        lines.append("")

        return group_var, lines

    # ──────────────────────────────────────────────────────────────
    # 窗
    # ──────────────────────────────────────────────────────────────

    def _build_window(
        self,
        idx: int,
        win: dict[str, Any],
    ) -> tuple[str, list[str]]:
        """
        生成单扇窗的 MAXScript 代码。

        Returns
        -------
        tuple[str, list[str]]
            (group_var_name, code_lines)
        """
        num = f"{idx:03d}"
        win_id = win.get("id", f"win{idx}")

        # ── 解析参数 ────────────────────────────────────────────
        center = win.get("center", [0.0, 0.0, 0.0])
        cx, cy, cz = _xyz(center)
        width = float(win.get("width", 1500.0))
        height = float(win.get("height", 1200.0))
        rot_deg = float(win.get("wall_rotation", 0.0))
        frame_depth = float(win.get("frame_depth", 80.0))

        fw = _WIN_FRAME_WIDTH
        gt = _WIN_GLASS_THICKNESS

        pfx = f"win_{num}"
        group_var = f"{pfx}_grp"

        lines: list[str] = []
        lines.append(f"-- ---- Window {num} (id={win_id}) ----")
        lines.append(
            f"-- center=({cx:.1f}, {cy:.1f}, {cz:.1f}), "
            f"w={width:.0f}, h={height:.0f}, rot={rot_deg:.1f}deg"
        )
        lines.append("")

        # ── 窗框：下横梁 ────────────────────────────────────────
        bottom_local_x = 0.0
        bottom_local_y = 0.0
        bottom_local_z = cz - height / 2.0 + fw / 2.0

        bottom_wx, bottom_wy = self._rotate_2d(bottom_local_x, bottom_local_y, rot_deg)
        bottom_wx += cx
        bottom_wy += cy

        frame_bottom_var = f"{pfx}_frame_bottom"
        lines.append("-- 窗框下横梁")
        lines.append(
            f"local {frame_bottom_var} = Box "
            f"length:{frame_depth:.2f} width:{width:.2f} height:{fw:.2f}"
        )
        lines.append(
            f"{frame_bottom_var}.pos = [{bottom_wx:.2f}, {bottom_wy:.2f}, {bottom_local_z:.2f}]"
        )
        lines.append(f"{frame_bottom_var}.rotation = (EulerAngles 0 0 {rot_deg:.4f})")
        lines.append(f"{frame_bottom_var}.material = win_frame_mat")
        lines.append(f'{frame_bottom_var}.name = "Window_{num}_FrameBottom"')
        lines.append("")

        # ── 窗框：上横梁 ────────────────────────────────────────
        top_local_x = 0.0
        top_local_y = 0.0
        top_local_z = cz + height / 2.0 - fw / 2.0

        top_wx, top_wy = self._rotate_2d(top_local_x, top_local_y, rot_deg)
        top_wx += cx
        top_wy += cy

        frame_top_var = f"{pfx}_frame_top"
        lines.append("-- 窗框上横梁")
        lines.append(
            f"local {frame_top_var} = Box "
            f"length:{frame_depth:.2f} width:{width:.2f} height:{fw:.2f}"
        )
        lines.append(
            f"{frame_top_var}.pos = [{top_wx:.2f}, {top_wy:.2f}, {top_local_z:.2f}]"
        )
        lines.append(f"{frame_top_var}.rotation = (EulerAngles 0 0 {rot_deg:.4f})")
        lines.append(f"{frame_top_var}.material = win_frame_mat")
        lines.append(f'{frame_top_var}.name = "Window_{num}_FrameTop"')
        lines.append("")

        # ── 窗框：左竖梁 ────────────────────────────────────────
        inner_height = height - 2.0 * fw  # 左右竖梁的净高（夹在上下横梁之间）

        left_local_x = -(width / 2.0 - fw / 2.0)
        left_local_y = 0.0
        left_local_z = cz

        left_wx, left_wy = self._rotate_2d(left_local_x, left_local_y, rot_deg)
        left_wx += cx
        left_wy += cy

        frame_left_var = f"{pfx}_frame_left"
        lines.append("-- 窗框左竖梁")
        lines.append(
            f"local {frame_left_var} = Box "
            f"length:{frame_depth:.2f} width:{fw:.2f} height:{inner_height:.2f}"
        )
        lines.append(
            f"{frame_left_var}.pos = [{left_wx:.2f}, {left_wy:.2f}, {left_local_z:.2f}]"
        )
        lines.append(f"{frame_left_var}.rotation = (EulerAngles 0 0 {rot_deg:.4f})")
        lines.append(f"{frame_left_var}.material = win_frame_mat")
        lines.append(f'{frame_left_var}.name = "Window_{num}_FrameLeft"')
        lines.append("")

        # ── 窗框：右竖梁 ────────────────────────────────────────
        right_local_x = width / 2.0 - fw / 2.0
        right_local_y = 0.0
        right_local_z = cz

        right_wx, right_wy = self._rotate_2d(right_local_x, right_local_y, rot_deg)
        right_wx += cx
        right_wy += cy

        frame_right_var = f"{pfx}_frame_right"
        lines.append("-- 窗框右竖梁")
        lines.append(
            f"local {frame_right_var} = Box "
            f"length:{frame_depth:.2f} width:{fw:.2f} height:{inner_height:.2f}"
        )
        lines.append(
            f"{frame_right_var}.pos = [{right_wx:.2f}, {right_wy:.2f}, {right_local_z:.2f}]"
        )
        lines.append(f"{frame_right_var}.rotation = (EulerAngles 0 0 {rot_deg:.4f})")
        lines.append(f"{frame_right_var}.material = win_frame_mat")
        lines.append(f'{frame_right_var}.name = "Window_{num}_FrameRight"')
        lines.append("")

        # ── 玻璃 ────────────────────────────────────────────────
        glass_w = width - 2.0 * fw
        glass_h = height - 2.0 * fw

        glass_local_x = 0.0
        glass_local_y = 0.0
        glass_local_z = cz

        glass_wx, glass_wy = self._rotate_2d(glass_local_x, glass_local_y, rot_deg)
        glass_wx += cx
        glass_wy += cy

        glass_var = f"{pfx}_glass"
        lines.append(f"-- 玻璃（厚 {gt:.0f}mm，opacity={_WIN_GLASS_OPACITY}）")
        lines.append(
            f"local {glass_var} = Box "
            f"length:{gt:.2f} width:{glass_w:.2f} height:{glass_h:.2f}"
        )
        lines.append(
            f"{glass_var}.pos = [{glass_wx:.2f}, {glass_wy:.2f}, {glass_local_z:.2f}]"
        )
        lines.append(f"{glass_var}.rotation = (EulerAngles 0 0 {rot_deg:.4f})")
        lines.append(f"{glass_var}.material = win_glass_mat")
        lines.append(f'{glass_var}.name = "Window_{num}_Glass"')
        lines.append("")

        # ── 将窗的所有部件组合为 Group ──────────────────────────
        parts = [
            frame_bottom_var,
            frame_top_var,
            frame_left_var,
            frame_right_var,
            glass_var,
        ]
        parts_array = "#(" + ", ".join(parts) + ")"
        lines.append(f"-- 将 Window_{num} 所有部件放入 Group")
        lines.append(f"local {group_var}_nodes = {parts_array}")
        lines.append(f'local {group_var} = group {group_var}_nodes name:"Window_{num}"')
        lines.append("")

        return group_var, lines

    # ──────────────────────────────────────────────────────────────
    # 顶层分组
    # ──────────────────────────────────────────────────────────────

    def _build_top_groups(
        self,
        door_group_vars: list[str],
        window_group_vars: list[str],
    ) -> list[str]:
        """
        将所有门 Group 放入 "Doors" 顶层 Group，
        将所有窗 Group 放入 "Windows" 顶层 Group。
        """
        lines: list[str] = []
        lines.append("-- ============================================================")
        lines.append("-- Top-level Groups")
        lines.append("-- ============================================================")
        lines.append("")

        if door_group_vars:
            arr = "#(" + ", ".join(door_group_vars) + ")"
            lines.append("-- 将所有门放入 'Doors' Group")
            lines.append(f"local all_doors_nodes = {arr}")
            lines.append('group all_doors_nodes name:"Doors"')
        else:
            lines.append("-- No doors to group")
        lines.append("")

        if window_group_vars:
            arr = "#(" + ", ".join(window_group_vars) + ")"
            lines.append("-- 将所有窗放入 'Windows' Group")
            lines.append(f"local all_windows_nodes = {arr}")
            lines.append('group all_windows_nodes name:"Windows"')
        else:
            lines.append("-- No windows to group")
        lines.append("")

        return lines

    # ──────────────────────────────────────────────────────────────
    # 工具方法
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _rotate_2d(x: float, y: float, angle_deg: float) -> tuple[float, float]:
        """
        将 (x, y) 绕原点旋转 angle_deg 度（逆时针），返回旋转后的 (rx, ry)。

        用于将局部坐标系中的偏移量转换为世界坐标系偏移量，
        以便正确定位沿任意方向墙体上的门窗部件。
        """
        if angle_deg == 0.0:
            return x, y
        rad = math.radians(angle_deg)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        rx = x * cos_a - y * sin_a
        ry = x * sin_a + y * cos_a
        return rx, ry
