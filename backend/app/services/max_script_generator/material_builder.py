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
        返回 MAXScript 字符串：
          - 创建所有所需材质（StandardMaterial）
          - 将材质放入 meditMaterials 槽
          - 提供根据对象名称应用材质的辅助函数
          - 在注释中给出对应的 V-Ray 版本参数
        """
        lines: list[str] = []
        lines.append("-- ============================================================")
        lines.append("-- [Section] Material Builder - Auto Generated")
        lines.append("-- ============================================================")
        lines.append("")

        # 收集本场景用到的材质类型（去重）
        used_types: dict[str, str] = {}  # type_key -> var_name

        # 从 materials 列表收集
        for mat in materials:
            mat_type = mat.get("type", "white_paint")
            if mat_type not in used_types:
                used_types[mat_type] = f"mat_{mat_type}"

        # 从 rooms 推断额外材质
        for room in rooms:
            for field in ("floor_material", "ceiling_material", "wall_material"):
                mat_type = room.get(field, "")
                if mat_type and mat_type not in used_types:
                    used_types[mat_type] = f"mat_{mat_type}"

        if not used_types:
            lines.append("-- No materials requested")
            return "\n".join(lines)

        lines.append("-- ---- Material declarations ----")
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

            lines.append(f"")
            lines.append(f"-- Material: {label} ({mat_type})")
            lines.append(vray_comment)
            lines.append(f"local {var_name} = StandardMaterial()")
            lines.append(f'{var_name}.name = "{label}"')
            lines.append(f"{var_name}.diffuse = (color {r} {g} {b})")
            lines.append(f"{var_name}.specularLevel = {spec}")
            lines.append(f"{var_name}.glossiness = {gloss}")
            lines.append(f"{var_name}.opacity = {opacity}")

            # 伪反射：用 Self-Illumination 近似（扫描线不支持真实反射）
            if refl > 0:
                lines.append(
                    f"-- Reflection approximated via specular (scanline limitation)"
                )
                lines.append(f"{var_name}.specularLevel = {min(100, spec + refl)}")

            # 放入 meditMaterials 槽
            if slot_idx <= 24:
                lines.append(f"meditMaterials[{slot_idx}] = {var_name}")
                slot_idx += 1

            # UVW Mapping 修改器（将在几何体创建后由应用函数添加）
            if recipe.get("uvw"):
                tile_l = recipe.get("uvw_length", 1000)
                tile_w = recipe.get("uvw_width", 1000)
                lines.append(
                    f"-- UVW: length={tile_l}mm width={tile_w}mm "
                    f"(apply via applyMaterial helper below)"
                )

        lines.append("")

        # ---- 辅助函数：按对象名前缀应用材质 + UVW ----
        lines.append("-- ---- Material application helper function ----")
        lines.append(
            "fn applyMaterialByNamePrefix obj_name_prefix mat_ref uvw_l uvw_w = ("
        )
        lines.append("    for obj in objects do (")
        lines.append(
            '        if matchPattern obj.name pattern:(obj_name_prefix + "*") do ('
        )
        lines.append("            obj.material = mat_ref")
        lines.append("            if uvw_l > 0 do (")
        lines.append(
            "                addModifier obj (UVWMap maptype:0 length:uvw_l width:uvw_w height:uvw_w)"
        )
        lines.append("            )")
        lines.append("        )")
        lines.append("    )")
        lines.append(")")
        lines.append("")

        # ---- 自动应用材质 ----
        lines.append("-- ---- Apply materials to scene objects ----")
        for mat_type, var_name in used_types.items():
            recipe = _MATERIAL_RECIPES.get(mat_type)
            if recipe is None:
                continue
            tile_l = recipe.get("uvw_length", 0) if recipe.get("uvw") else 0
            tile_w = recipe.get("uvw_width", 0) if recipe.get("uvw") else 0
            label = recipe["label"]

            # Wall 材质应用
            lines.append(
                f'applyMaterialByNamePrefix "Wall_" {var_name} 0 0'
                if mat_type == "white_paint"
                else f"-- apply {label}: call applyMaterialByNamePrefix with correct prefix"
            )

            # Floor/Ceiling 材质应用（按注释生成，真实场景中需要精确匹配对象名）
            if mat_type == "wood_floor":
                lines.append(
                    f'applyMaterialByNamePrefix "Floor_" {var_name} {tile_l:.0f} {tile_w:.0f}'
                )
            elif mat_type == "light_gray_tile":
                lines.append(
                    f'applyMaterialByNamePrefix "Floor_" {var_name} {tile_l:.0f} {tile_w:.0f}'
                )
            elif mat_type == "white_paint" and "white_paint" in used_types:
                lines.append(f'applyMaterialByNamePrefix "Ceiling_" {var_name} 0 0')

        lines.append("")

        return "\n".join(lines)
