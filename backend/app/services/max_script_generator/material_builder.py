"""
MaterialScriptBuilder
---------------------
生成完整的材质创建 + 应用 MAXScript 代码。

输入示例
--------
materials = [
    {
        "id": "mat_white_paint",
        "type": "white_paint",
        "name": "白色乳胶漆"
    },
    {
        "id": "mat_wood",
        "type": "wood_floor",
        "name": "木地板"
    }
]

rooms = [
    {
        "id": "room_living",
        "name": "客厅",
        "floor_material": "wood_floor",
        "ceiling_material": "white_paint",
        "wall_material": "white_paint"
    }
]
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# 材质配方表
# ---------------------------------------------------------------------------

_MATERIAL_RECIPES: dict[str, dict[str, Any]] = {
    "white_paint": {
        "label": "WhitePaint",
        "diffuse": (245, 245, 240),
        "specular_level": 10,
        "glossiness": 30,
        "reflection": 0,
        "opacity": 100,
        "uvw": False,
        "vray_comment": "-- VRay: VRayMtl diffuse=(245,245,240) reflect=0.04 reflGloss=0.3",
    },
    "light_gray_tile": {
        "label": "LightGrayTile",
        "diffuse": (208, 204, 202),
        "specular_level": 40,
        "glossiness": 60,
        "reflection": 10,
        "opacity": 100,
        "uvw": True,
        "uvw_length": 600,
        "uvw_width": 600,
        "vray_comment": "-- VRay: VRayMtl diffuse=(208,204,202) reflect=0.15 reflGloss=0.7 fresnel=on",
    },
    "wood_floor": {
        "label": "WoodFloor",
        "diffuse": (196, 148, 74),
        "specular_level": 20,
        "glossiness": 50,
        "reflection": 5,
        "opacity": 100,
        "uvw": True,
        "uvw_length": 1200,
        "uvw_width": 200,
        "vray_comment": "-- VRay: VRayMtl diffuse=(196,148,74) reflect=0.08 reflGloss=0.6 anisotropy=0.3",
    },
    "marble": {
        "label": "Marble",
        "diffuse": (232, 228, 224),
        "specular_level": 80,
        "glossiness": 85,
        "reflection": 20,
        "opacity": 100,
        "uvw": True,
        "uvw_length": 800,
        "uvw_width": 800,
        "vray_comment": "-- VRay: VRayMtl diffuse=(232,228,224) reflect=0.25 reflGloss=0.95 fresnel=on IOR=1.55",
    },
    "dark_wood": {
        "label": "DarkWood",
        "diffuse": (92, 58, 30),
        "specular_level": 25,
        "glossiness": 45,
        "reflection": 8,
        "opacity": 100,
        "uvw": True,
        "uvw_length": 1000,
        "uvw_width": 200,
        "vray_comment": "-- VRay: VRayMtl diffuse=(92,58,30) reflect=0.1 reflGloss=0.55",
    },
    "glass": {
        "label": "Glass",
        "diffuse": (200, 230, 240),
        "specular_level": 95,
        "glossiness": 95,
        "reflection": 15,
        "opacity": 10,  # 10% 不透明 = 90% 透明
        "uvw": False,
        "vray_comment": "-- VRay: VRayMtl diffuse=(200,230,240) reflect=0.95 refract=0.92 IOR=1.52 fogColor=(200,230,240)",
    },
    "concrete": {
        "label": "Concrete",
        "diffuse": (160, 160, 160),
        "specular_level": 5,
        "glossiness": 15,
        "reflection": 0,
        "opacity": 100,
        "uvw": True,
        "uvw_length": 2000,
        "uvw_width": 2000,
        "vray_comment": "-- VRay: VRayMtl diffuse=(160,160,160) reflect=0.02 reflGloss=0.2",
    },
    "metal": {
        "label": "Metal",
        "diffuse": (180, 180, 180),
        "specular_level": 90,
        "glossiness": 90,
        "reflection": 70,
        "opacity": 100,
        "uvw": False,
        "vray_comment": "-- VRay: VRayMtl diffuse=(10,10,10) reflect=(200,200,200) reflGloss=0.85 fresnel=off metalness=1",
    },
    "white_ceramic": {
        "label": "WhiteCeramic",
        "diffuse": (240, 239, 235),
        "specular_level": 70,
        "glossiness": 80,
        "reflection": 15,
        "opacity": 100,
        "uvw": True,
        "uvw_length": 300,
        "uvw_width": 300,
        "vray_comment": "-- VRay: VRayMtl diffuse=(240,239,235) reflect=0.2 reflGloss=0.9 fresnel=on IOR=1.6",
    },
}


class MaterialScriptBuilder:
    """生成材质库和材质应用的 MAXScript 代码段。"""

    def build(
        self,
        materials: list[dict[str, Any]],
        rooms: list[dict[str, Any]],
    ) -> str:
        """
        返回 MAXScript 字符串：声明 + 立即应用（旧入口，保留向后兼容）。

        新代码推荐分两段输出：
          - `build_declarations(...)` 在所有几何体之前执行（创建 mat_* 变量、定义辅助函数）
          - `build_applications(...)` 在所有几何体之后执行（按名前缀应用材质 + UVW）

        旧入口保留是因为：单元测试 / 调用方可能依赖原行为；本次重构不破坏接口。
        """
        used_types = self._collect_used_types(materials, rooms)
        if not used_types:
            return "\n".join(self._header_lines("-- No materials requested"))

        lines = self._header_lines()
        lines += self._build_declarations_block(used_types)
        lines += self._build_helper_function()
        lines += self._build_application_block(used_types)
        return "\n".join(lines)

    # ── 新接口：声明与应用分离 ─────────────────────────────────────────────

    def build_declarations(
        self,
        materials: list[dict[str, Any]],
        rooms: list[dict[str, Any]],
    ) -> str:
        """
        仅输出材质声明 + 通用 applyMaterialByNamePrefix 辅助函数。
        在所有几何 builder 之前调用。
        """
        used_types = self._collect_used_types(materials, rooms)
        lines = self._header_lines(
            "" if used_types else "-- No materials requested"
        )
        if not used_types:
            return "\n".join(lines)
        lines += self._build_declarations_block(used_types)
        lines += self._build_helper_function()
        return "\n".join(lines)

    def build_applications(
        self,
        materials: list[dict[str, Any]],
        rooms: list[dict[str, Any]],
    ) -> str:
        """
        仅输出材质应用调用（applyMaterialByNamePrefix）。
        必须在所有几何 builder 之后调用，否则场景里没有可匹配的对象。
        """
        used_types = self._collect_used_types(materials, rooms)
        if not used_types:
            return "-- [Section] Material Applications - No materials to apply"
        lines: list[str] = [
            "-- ============================================================",
            "-- [Section] Material Applications - Auto Generated",
            "-- (runs AFTER all geometry exists so name-prefix matches work)",
            "-- ============================================================",
            "",
        ]
        lines += self._build_application_block(used_types)
        return "\n".join(lines)

    # ── 内部 ───────────────────────────────────────────────────────────────

    @staticmethod
    def _header_lines(footer: str = "") -> list[str]:
        out = [
            "-- ============================================================",
            "-- [Section] Material Builder - Auto Generated",
            "-- ============================================================",
            "",
        ]
        if footer:
            out.append(footer)
        return out

    @staticmethod
    def _collect_used_types(
        materials: list[dict[str, Any]],
        rooms: list[dict[str, Any]],
    ) -> dict[str, str]:
        used_types: dict[str, str] = {}
        for mat in materials:
            mat_type = mat.get("type", "white_paint")
            if mat_type not in used_types:
                used_types[mat_type] = f"mat_{mat_type}"
        for room in rooms:
            for field in ("floor_material", "ceiling_material", "wall_material"):
                mat_type = room.get(field, "")
                if mat_type and mat_type not in used_types:
                    used_types[mat_type] = f"mat_{mat_type}"
        return used_types

    @staticmethod
    def _build_declarations_block(used_types: dict[str, str]) -> list[str]:
        lines: list[str] = ["-- ---- Material declarations ----"]
        slot_idx = 1
        for mat_type, var_name in used_types.items():
            recipe = _MATERIAL_RECIPES.get(mat_type)
            if recipe is None:
                lines.append(f"-- WARNING: unknown material type '{mat_type}', skipped")
                continue

            r, g, b = recipe["diffuse"]
            spec = recipe["specular_level"]
            gloss = recipe["glossiness"]
            opacity = recipe["opacity"]
            refl = recipe["reflection"]
            label = recipe["label"]
            vray_comment = recipe["vray_comment"]

            lines.append("")
            lines.append(f"-- Material: {label} ({mat_type})")
            lines.append(vray_comment)
            lines.append(f"global {var_name} = StandardMaterial()")
            lines.append(f'{var_name}.name = "{label}"')
            lines.append(f"{var_name}.diffuse = (color {r} {g} {b})")
            lines.append(f"{var_name}.specularLevel = {spec}")
            lines.append(f"{var_name}.glossiness = {gloss}")
            lines.append(f"{var_name}.opacity = {opacity}")

            if refl > 0:
                lines.append(
                    "-- Reflection approximated via specular (scanline limitation)"
                )
                lines.append(f"{var_name}.specularLevel = {min(100, spec + refl)}")

            if slot_idx <= 24:
                lines.append(f"meditMaterials[{slot_idx}] = {var_name}")
                slot_idx += 1

            if recipe.get("uvw"):
                tile_l = recipe.get("uvw_length", 1000)
                tile_w = recipe.get("uvw_width", 1000)
                lines.append(
                    f"-- UVW: length={tile_l}mm width={tile_w}mm "
                    f"(apply via applyMaterial helper below)"
                )

        lines.append("")
        return lines

    @staticmethod
    def _build_helper_function() -> list[str]:
        return [
            "-- ---- Material application helper function ----",
            "-- Declared as global so it survives until the application section runs.",
            "global applyMaterialByNamePrefix",
            "fn applyMaterialByNamePrefix obj_name_prefix mat_ref uvw_l uvw_w = (",
            "    for obj in objects do (",
            '        if matchPattern obj.name pattern:(obj_name_prefix + "*") do (',
            "            obj.material = mat_ref",
            "            if uvw_l > 0 do (",
            "                addModifier obj (UVWMap maptype:0 "
            "length:uvw_l width:uvw_w height:uvw_w)",
            "            )",
            "        )",
            "    )",
            ")",
            "",
        ]

    @staticmethod
    def _build_application_block(used_types: dict[str, str]) -> list[str]:
        lines: list[str] = ["-- ---- Apply materials to scene objects ----"]
        for mat_type, var_name in used_types.items():
            recipe = _MATERIAL_RECIPES.get(mat_type)
            if recipe is None:
                continue
            tile_l = recipe.get("uvw_length", 0) if recipe.get("uvw") else 0
            tile_w = recipe.get("uvw_width", 0) if recipe.get("uvw") else 0
            label = recipe["label"]

            if mat_type == "white_paint":
                # 默认墙面与天花用白色乳胶漆
                lines.append(
                    f'applyMaterialByNamePrefix "Wall_" {var_name} 0 0'
                )
                lines.append(
                    f'applyMaterialByNamePrefix "Ceiling_" {var_name} 0 0'
                )
            elif mat_type in ("wood_floor", "light_gray_tile", "marble"):
                lines.append(
                    f'applyMaterialByNamePrefix "Floor_" {var_name} '
                    f'{tile_l:.0f} {tile_w:.0f}'
                )
            else:
                lines.append(
                    f"-- {label}: no auto-prefix rule; apply manually if needed"
                )
        lines.append("")
        return lines
