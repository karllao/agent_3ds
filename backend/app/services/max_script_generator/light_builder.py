"""
LightScriptBuilder
------------------
将灯光数据转换为 MAXScript 代码片段。

输入示例
--------
lights = [
    {
        "id": "lt_001",
        "type": "downlight",
        "position": [3000, 2500, 2750],  # mm，天花板位置
        "color_temp": 3000,              # Kelvin
        "intensity": 0.5,                # multiplier
        "name": "主卧筒灯"
    },
    {
        "id": "lt_002",
        "type": "led_strip",
        "path": [[0, 0, 2750], [6000, 0, 2750]],  # 灯带路径点
        "color_temp": 2700,
        "intensity": 0.2,
        "spacing": 200,   # 每隔 200mm 放一个点光源
        "name": "客厅灯带"
    },
    {
        "id": "lt_003",
        "type": "pendant",
        "position": [3000, 3000, 2400],
        "color_temp": 2700,
        "intensity": 0.8,
        "name": "餐厅吊灯"
    },
    {
        "id": "lt_004",
        "type": "area_light",
        "position": [1000, 1000, 2700],
        "width": 600,
        "height": 300,
        "color_temp": 4000,
        "intensity": 1.0,
        "name": "厨房面光"
    },
    {
        "id": "lt_005",
        "type": "sunlight",
        "azimuth": 135,    # 方位角（度）
        "altitude": 45,    # 仰角（度）
        "intensity": 1.0,
        "name": "自然采光"
    }
]
"""

from __future__ import annotations

import math
from typing import Any

# ---------------------------------------------------------------------------
# 色温转 RGB（Planckian locus 近似）
# ---------------------------------------------------------------------------


def color_temp_to_rgb(kelvin: int) -> tuple[int, int, int]:
    """
    将色温（K）转换为近似 RGB 值（0-255）。
    基于 Tanner Helland 的分段近似算法。
    参考: https://tannerhelland.com/2012/09/18/convert-temperature-rgb-algorithm-code.html
    """
    temp = max(1000, min(40000, kelvin)) / 100.0

    # --- Red ---
    if temp <= 66:
        red = 255
    else:
        red = 329.698727446 * ((temp - 60) ** -0.1332047592)
        red = max(0.0, min(255.0, red))

    # --- Green ---
    if temp <= 66:
        green = 99.4708025861 * math.log(temp) - 161.1195681661
    else:
        green = 288.1221695283 * ((temp - 60) ** -0.0755148492)
    green = max(0.0, min(255.0, green))

    # --- Blue ---
    if temp >= 66:
        blue = 255.0
    elif temp <= 19:
        blue = 0.0
    else:
        blue = 138.5177312231 * math.log(temp - 10) - 305.0447927307
        blue = max(0.0, min(255.0, blue))

    return int(round(red)), int(round(green)), int(round(blue))


class LightScriptBuilder:
    """生成各类灯光的 MAXScript 代码段。"""

    def build(self, lights: list[dict[str, Any]]) -> str:
        """
        返回 MAXScript 字符串，支持：
          - downlight（筒灯）
          - led_strip（灯带）
          - pendant（吊灯）
          - area_light（面光源）
          - sunlight（日光）
        所有灯光放入 "Lights" Group。
        """
        lines: list[str] = []
        lines.append("-- ============================================================")
        lines.append("-- [Section] Light Builder - Auto Generated")
        lines.append("-- ============================================================")
        lines.append("")

        all_light_vars: list[str] = []

        for idx, light in enumerate(lights, start=1):
            lt_num = f"{idx:03d}"
            lt_type = light.get("type", "downlight")
            lt_id = light.get("id", f"lt_{idx}")
            lt_name = light.get("name", f"Light_{lt_num}")
            safe_lt_name = lt_name.replace(" ", "_").replace("/", "_")
            color_temp = int(light.get("color_temp", 3000))
            intensity = float(light.get("intensity", 0.5))
            rgb = color_temp_to_rgb(color_temp)

            lines.append(f"-- ---- Light {lt_num}: {lt_name} (type={lt_type}) ----")
            lines.append(
                f"-- Color temp: {color_temp}K -> RGB({rgb[0]}, {rgb[1]}, {rgb[2]})"
            )

            if lt_type == "downlight":
                var_list = self._build_downlight(
                    lt_num, lt_name, safe_lt_name, light, rgb, intensity
                )
            elif lt_type == "led_strip":
                var_list = self._build_led_strip(
                    lt_num, lt_name, safe_lt_name, light, rgb, intensity
                )
            elif lt_type == "pendant":
                var_list = self._build_pendant(
                    lt_num, lt_name, safe_lt_name, light, rgb, intensity
                )
            elif lt_type == "area_light":
                var_list = self._build_area_light(
                    lt_num, lt_name, safe_lt_name, light, rgb, intensity
                )
            elif lt_type == "sunlight":
                var_list = self._build_sunlight(
                    lt_num, lt_name, safe_lt_name, light, intensity
                )
            else:
                lines.append(f"-- WARNING: unknown light type '{lt_type}', skipped")
                lines.append("")
                continue

            lines += var_list["code"]
            all_light_vars += var_list["vars"]
            lines.append("")

        # ---- Group: Lights ----
        lines.append("-- ---- Group all lights ----")
        if all_light_vars:
            arr = "#(" + ", ".join(all_light_vars) + ")"
            lines.append(f"local lights_group_nodes = {arr}")
            lines.append('group lights_group_nodes name:"Lights"')
        else:
            lines.append("-- No lights to group")
        lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 各类灯光的私有构建方法
    # ------------------------------------------------------------------

    def _build_downlight(
        self,
        num: str,
        name: str,
        safe_name: str,
        light: dict,
        rgb: tuple[int, int, int],
        intensity: float,
    ) -> dict:
        """筒灯：FreeSpot，向下照射，暖色温。"""
        pos = light.get("position", [0, 0, 2750])
        px, py, pz = float(pos[0]), float(pos[1]), float(pos[2])
        hotspot = float(light.get("hotspot", 40))
        falloff = float(light.get("falloff", 60))
        var = f"lt_downlight_{num}"

        code = [
            f"local {var} = FreeSpot()",
            f"{var}.pos = [{px:.2f}, {py:.2f}, {pz:.2f}]",
            f"{var}.rotation = (EulerAngles 0 -90 0)",  # 向下
            f"{var}.multiplier = {intensity:.3f}",
            f"{var}.hotspot = {hotspot:.1f}",
            f"{var}.falloff = {falloff:.1f}",
            f"{var}.rgb = (color {rgb[0]} {rgb[1]} {rgb[2]})",
            f"{var}.castShadows = true",
            f"{var}.shadowType = 1",  # 1 = Shadow Map
            f'{var}.name = "Downlight_{safe_name}"',
        ]
        return {"code": code, "vars": [var]}

    def _build_led_strip(
        self,
        num: str,
        name: str,
        safe_name: str,
        light: dict,
        rgb: tuple[int, int, int],
        intensity: float,
    ) -> dict:
        """灯带：沿路径每隔 spacing mm 放一个 Omni，低强度。"""
        path_pts: list[list[float]] = light.get("path", [[0, 0, 2750], [1000, 0, 2750]])
        spacing = float(light.get("spacing", 200))

        code: list[str] = []
        vars_out: list[str] = []
        strip_intensity = intensity * 0.15  # 灯带单个点光源强度很低

        code.append(f"-- LED strip '{name}': {len(path_pts) - 1} segment(s)")

        pt_idx = 0
        for seg_i in range(len(path_pts) - 1):
            p0 = [float(v) for v in path_pts[seg_i]]
            p1 = [float(v) for v in path_pts[seg_i + 1]]
            seg_len = math.dist(p0, p1)
            if seg_len < 1:
                continue
            n_pts = max(2, int(seg_len / spacing) + 1)
            for j in range(n_pts):
                t = j / max(1, n_pts - 1)
                px = p0[0] + t * (p1[0] - p0[0])
                py = p0[1] + t * (p1[1] - p0[1])
                pz = p0[2] + t * (p1[2] - p0[2])
                var = f"lt_strip_{num}_{pt_idx:03d}"
                code.append(f"local {var} = Omnilight()")
                code.append(f"{var}.pos = [{px:.2f}, {py:.2f}, {pz:.2f}]")
                code.append(f"{var}.multiplier = {strip_intensity:.4f}")
                code.append(f"{var}.rgb = (color {rgb[0]} {rgb[1]} {rgb[2]})")
                code.append(f"{var}.castShadows = false")
                code.append(f'{var}.name = "LEDStrip_{safe_name}_{pt_idx:03d}"')
                vars_out.append(var)
                pt_idx += 1

        return {"code": code, "vars": vars_out}

    def _build_pendant(
        self,
        num: str,
        name: str,
        safe_name: str,
        light: dict,
        rgb: tuple[int, int, int],
        intensity: float,
    ) -> dict:
        """吊灯：Omni + 球体 mesh 作为灯泡形状。"""
        pos = light.get("position", [0, 0, 2400])
        px, py, pz = float(pos[0]), float(pos[1]), float(pos[2])
        bulb_radius = float(light.get("bulb_radius", 60))  # mm
        var_omni = f"lt_pendant_{num}"
        var_bulb = f"lt_pendant_bulb_{num}"

        code = [
            f"-- Pendant omni light",
            f"local {var_omni} = Omnilight()",
            f"{var_omni}.pos = [{px:.2f}, {py:.2f}, {pz:.2f}]",
            f"{var_omni}.multiplier = {intensity:.3f}",
            f"{var_omni}.rgb = (color {rgb[0]} {rgb[1]} {rgb[2]})",
            f"{var_omni}.castShadows = true",
            f"{var_omni}.shadowType = 1",
            f'{var_omni}.name = "Pendant_{safe_name}"',
            f"",
            f"-- Bulb mesh (sphere)",
            f"local {var_bulb} = Sphere radius:{bulb_radius:.1f} segs:12",
            f"{var_bulb}.pos = [{px:.2f}, {py:.2f}, {pz:.2f}]",
            f"local pendant_bulb_mat_{num} = StandardMaterial()",
            f"pendant_bulb_mat_{num}.selfIllumAmount = 100",
            f"pendant_bulb_mat_{num}.diffuse = (color {rgb[0]} {rgb[1]} {rgb[2]})",
            f"{var_bulb}.material = pendant_bulb_mat_{num}",
            f'{var_bulb}.name = "PendantBulb_{safe_name}"',
        ]
        return {"code": code, "vars": [var_omni, var_bulb]}

    def _build_area_light(
        self,
        num: str,
        name: str,
        safe_name: str,
        light: dict,
        rgb: tuple[int, int, int],
        intensity: float,
    ) -> dict:
        """
        面光源：优先使用 mr Area Light；
        在注释中提供 VRayLight 版本。
        """
        pos = light.get("position", [0, 0, 2700])
        px, py, pz = float(pos[0]), float(pos[1]), float(pos[2])
        a_width = float(light.get("width", 600))
        a_height = float(light.get("height", 300))
        var = f"lt_area_{num}"

        code = [
            f"-- Area light (mr Area Light). VRay alternative in comments below.",
            f"-- VRay: local {var} = VRayLight()",
            f"-- VRay: {var}.type = 0  -- plane",
            f"-- VRay: {var}.size1 = {a_width:.1f}",
            f"-- VRay: {var}.size2 = {a_height:.1f}",
            f"-- VRay: {var}.multiplier = {intensity:.3f}",
            f"-- VRay: {var}.color = (color {rgb[0]} {rgb[1]} {rgb[2]})",
            f"-- VRay: {var}.pos = [{px:.2f}, {py:.2f}, {pz:.2f}]",
            f"",
            f"local {var} = mr_Area_Light()",
            f"{var}.pos = [{px:.2f}, {py:.2f}, {pz:.2f}]",
            f"{var}.rotation = (EulerAngles 0 -90 0)",  # 向下
            f"{var}.multiplier = {intensity:.3f}",
            f"{var}.rgb = (color {rgb[0]} {rgb[1]} {rgb[2]})",
            f"{var}.width = {a_width:.1f}",
            f"{var}.height = {a_height:.1f}",
            f"{var}.castShadows = true",
            f'{var}.name = "AreaLight_{safe_name}"',
        ]
        return {"code": code, "vars": [var]}

    def _build_sunlight(
        self,
        num: str,
        name: str,
        safe_name: str,
        light: dict,
        intensity: float,
    ) -> dict:
        """
        日光：Directional Light 模拟（简单可靠）。
        也提供 Sunlight System 创建注释。
        """
        azimuth = float(light.get("azimuth", 135))  # 方位角，度
        altitude = float(light.get("altitude", 45))  # 仰角，度

        # 将球面角转换为方向向量（3ds Max Z-up）
        az_rad = math.radians(azimuth)
        alt_rad = math.radians(altitude)
        dx = math.cos(alt_rad) * math.sin(az_rad)
        dy = math.cos(alt_rad) * math.cos(az_rad)
        dz = -math.sin(alt_rad)

        # 光源放在很远处（10万mm = 100m），用平行光模拟太阳
        dist = 100_000.0
        sx = -dx * dist
        sy = -dy * dist
        sz = -dz * dist

        var = f"lt_sun_{num}"

        code = [
            f"-- Sunlight (Directional Light). azimuth={azimuth:.1f}deg, altitude={altitude:.1f}deg",
            f"-- Alternative: use Sunlight System for accurate solar positioning",
            f"-- ss = sunlight(); ss.position = [0,0,0]; ss.time = ...",
            f"local {var} = Directionallight()",
            f"{var}.pos = [{sx:.2f}, {sy:.2f}, {sz:.2f}]",
            f"{var}.target.pos = [0, 0, 0]",
            f"{var}.multiplier = {intensity:.3f}",
            f"{var}.rgb = (color 255 250 240)",  # 日光近似色
            f"{var}.hotspot = 150000",
            f"{var}.falloff = 160000",
            f"{var}.castShadows = true",
            f"{var}.shadowType = 0",  # 0 = Ray-Traced
            f'{var}.name = "Sunlight_{safe_name}"',
        ]
        return {"code": code, "vars": [var]}
