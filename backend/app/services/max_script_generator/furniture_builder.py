"""
FurnitureScriptBuilder
----------------------
将家具布局数据转换为 MAXScript 代码片段。

输入示例
--------
furniture_list = [
    {
        "id": "furn_001",
        "asset_id": "pending_sofa",       # pending_xxx = 占位盒子
        "type": "sofa",
        "name": "主沙发",
        "position": [3000, 2500, 0],       # mm，底面中心
        "rotation_z": 0,                   # 绕 Z 轴旋转，度
        "scale": [1.0, 1.0, 1.0]          # 缩放（可选）
    },
    {
        "id": "furn_002",
        "asset_id": "asset_coffee_table_oak_1200",   # 真实资产
        "type": "coffee_table",
        "name": "茶几",
        "position": [3000, 3500, 0],
        "rotation_z": 0
    }
]

asset_library_path = r"D:\3dsmax_assets\furniture"
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# 典型家具默认尺寸（length × width × height，单位 mm）
# 3ds Max Box: length = Y轴, width = X轴, height = Z轴
# ---------------------------------------------------------------------------
_FURNITURE_SIZES: dict[str, dict[str, float]] = {
    "sofa": {"l": 900, "w": 2400, "h": 850},
    "sofa_2seat": {"l": 900, "w": 1600, "h": 850},
    "sofa_armchair": {"l": 800, "w": 800, "h": 850},
    "coffee_table": {"l": 600, "w": 1200, "h": 450},
    "tv_cabinet": {"l": 400, "w": 2000, "h": 600},
    "dining_table": {"l": 900, "w": 1600, "h": 760},
    "dining_chair": {"l": 450, "w": 450, "h": 900},
    "bed_single": {"l": 2000, "w": 1000, "h": 500},
    "bed_queen": {"l": 2000, "w": 1600, "h": 500},
    "bed_king": {"l": 2000, "w": 2000, "h": 500},
    "mattress_queen": {"l": 2000, "w": 1600, "h": 300},
    "wardrobe": {"l": 600, "w": 2400, "h": 2200},
    "desk": {"l": 600, "w": 1200, "h": 760},
    "office_chair": {"l": 600, "w": 600, "h": 1100},
    "bookshelf": {"l": 300, "w": 1200, "h": 2000},
    "side_table": {"l": 500, "w": 500, "h": 550},
    "bathtub": {"l": 700, "w": 1700, "h": 600},
    "toilet": {"l": 700, "w": 380, "h": 800},
    "sink": {"l": 500, "w": 600, "h": 850},
    "refrigerator": {"l": 650, "w": 750, "h": 1800},
    "washing_machine": {"l": 600, "w": 600, "h": 850},
}

# 占位盒颜色（灰色）
_PLACEHOLDER_COLOR = (128, 128, 128)


class FurnitureScriptBuilder:
    """生成家具导入和摆放的 MAXScript 代码段。"""

    def build(
        self,
        furniture_list: list[dict[str, Any]],
        asset_library_path: str = "",
    ) -> str:
        """
        返回 MAXScript 字符串：
          - pending 资产：生成占位 Box（灰色，标准尺寸）
          - 真实资产：生成 mergeMaxFile 或 xrefs 代码
          - 设置位置、旋转、命名
          - 所有家具放入 "Furniture" Group
        """
        lines: list[str] = []
        lines.append("-- ============================================================")
        lines.append("-- [Section] Furniture Builder - Auto Generated")
        lines.append("-- ============================================================")
        lines.append("")

        # 资产库路径标准化（MAXScript 使用正斜杠或 @"..." 原始字符串）
        lib_path = asset_library_path.replace("\\", "/").rstrip("/")

        # 占位材质（只创建一次）
        lines.append("-- ---- Placeholder material (gray box) ----")
        lines.append("local furn_placeholder_mat = StandardMaterial()")
        lines.append('furn_placeholder_mat.name = "FurniturePlaceholder"')
        lines.append(
            f"furn_placeholder_mat.diffuse = "
            f"(color {_PLACEHOLDER_COLOR[0]} "
            f"{_PLACEHOLDER_COLOR[1]} "
            f"{_PLACEHOLDER_COLOR[2]})"
        )
        lines.append("furn_placeholder_mat.specularLevel = 15")
        lines.append("furn_placeholder_mat.glossiness = 20")
        lines.append("")

        all_furn_vars: list[str] = []

        for idx, furn in enumerate(furniture_list, start=1):
            furn_num = f"{idx:03d}"
            furn_id = furn.get("id", f"furn_{idx}")
            asset_id: str = furn.get("asset_id", "pending_unknown")
            furn_type: str = furn.get("type", "unknown")
            furn_name: str = furn.get("name", f"{furn_type}_{furn_num}")
            safe_name = furn_name.replace(" ", "_").replace("/", "_").replace("-", "_")
            pos = furn.get("position", [0, 0, 0])
            px, py, pz = float(pos[0]), float(pos[1]), float(pos[2])
            rot_z = float(furn.get("rotation_z", 0))
            scale = furn.get("scale", [1.0, 1.0, 1.0])
            sx, sy, sz = float(scale[0]), float(scale[1]), float(scale[2])

            var = f"furn_{furn_num}"
            lines.append(
                f"-- ---- Furniture {furn_num}: {furn_name} "
                f"(type={furn_type}, asset={asset_id}) ----"
            )

            is_pending = asset_id.startswith("pending")

            if is_pending:
                lines += self._build_placeholder(
                    var, furn_type, safe_name, px, py, pz, rot_z, sx, sy, sz
                )
            else:
                lines += self._build_real_asset(
                    var,
                    asset_id,
                    furn_type,
                    safe_name,
                    lib_path,
                    px,
                    py,
                    pz,
                    rot_z,
                    sx,
                    sy,
                    sz,
                )

            all_furn_vars.append(var)
            lines.append("")

        # ---- Group: Furniture ----
        lines.append("-- ---- Group all furniture ----")
        if all_furn_vars:
            arr = "#(" + ", ".join(all_furn_vars) + ")"
            lines.append(f"local furn_group_nodes = {arr}")
            lines.append('group furn_group_nodes name:"Furniture"')
        else:
            lines.append("-- No furniture to group")
        lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 私有构建方法
    # ------------------------------------------------------------------

    def _build_placeholder(
        self,
        var: str,
        furn_type: str,
        safe_name: str,
        px: float,
        py: float,
        pz: float,
        rot_z: float,
        sx: float,
        sy: float,
        sz: float,
    ) -> list[str]:
        """生成占位 Box 代码。"""
        size = _FURNITURE_SIZES.get(furn_type, {"l": 800, "w": 800, "h": 800})
        fl = size["l"] * sy  # Box length = Y 方向
        fw = size["w"] * sx  # Box width  = X 方向
        fh = size["h"] * sz  # Box height = Z 方向

        # 放置在底面中心（pz = 地面），Box 默认以底面为原点
        center_z = pz + fh / 2.0

        return [
            f"-- Placeholder box for '{safe_name}' ({furn_type})",
            f"-- Actual size: {size['w']:.0f}w x {size['l']:.0f}l x {size['h']:.0f}h mm",
            f"local {var} = Box length:{fl:.2f} width:{fw:.2f} height:{fh:.2f}",
            f"{var}.pos = [{px:.2f}, {py:.2f}, {center_z:.2f}]",
            f"{var}.rotation = (EulerAngles 0 0 {rot_z:.4f})",
            f"{var}.material = furn_placeholder_mat",
            f'{var}.name = "Furniture_{safe_name}"',
            f"-- NOTE: Replace this placeholder with actual asset when available",
        ]

    def _build_real_asset(
        self,
        var: str,
        asset_id: str,
        furn_type: str,
        safe_name: str,
        lib_path: str,
        px: float,
        py: float,
        pz: float,
        rot_z: float,
        sx: float,
        sy: float,
        sz: float,
    ) -> list[str]:
        """生成 mergeMaxFile 导入真实资产的代码。"""
        # 资产文件路径推断（约定：lib_path/furn_type/asset_id.max）
        if lib_path:
            asset_path = f"{lib_path}/{furn_type}/{asset_id}.max"
        else:
            asset_path = f"$(userAssets)/{furn_type}/{asset_id}.max"

        size = _FURNITURE_SIZES.get(furn_type, {"l": 800, "w": 800, "h": 800})
        fh = size["h"] * sz
        center_z = pz + fh / 2.0

        return [
            f"-- Import real asset: {asset_id}",
            f'local asset_file_{var} = "{asset_path}"',
            f"if doesFileExist asset_file_{var} then (",
            f"    -- Record nodes before merge",
            f"    local pre_merge_nodes_{var} = #()",
            f"    for obj in objects do append pre_merge_nodes_{var} obj",
            f"",
            f"    mergeMaxFile asset_file_{var} #select #mergeDups quiet:true",
            f"",
            f"    -- Find newly merged nodes",
            f"    local merged_nodes_{var} = #()",
            f"    for obj in selection do (",
            f"        if findItem pre_merge_nodes_{var} obj == 0 do (",
            f"            append merged_nodes_{var} obj",
            f"        )",
            f"    )",
            f"",
            f"    -- Get root node (top-level parent)",
            f"    local {var} = undefined",
            f"    for n in merged_nodes_{var} do (",
            f"        if n.parent == undefined do {var} = n",
            f"    )",
            f"    if {var} == undefined and merged_nodes_{var}.count > 0 do (",
            f"        {var} = merged_nodes_{var}[1]",
            f"    )",
            f"",
            f"    if {var} != undefined do (",
            f"        {var}.pos = [{px:.2f}, {py:.2f}, {pz:.2f}]",
            f"        {var}.rotation = (EulerAngles 0 0 {rot_z:.4f})",
            f"        {var}.scale = [{sx:.4f}, {sy:.4f}, {sz:.4f}]",
            f'        {var}.name = "Furniture_{safe_name}"',
            f"    )",
            f") else (",
            f'    print ("WARNING: Asset file not found: " + asset_file_{var})',
            f"    -- Fallback to placeholder",
            self._placeholder_fallback(
                var, furn_type, safe_name, px, py, center_z, rot_z
            ),
            f")",
        ]

    def _placeholder_fallback(
        self,
        var: str,
        furn_type: str,
        safe_name: str,
        px: float,
        py: float,
        center_z: float,
        rot_z: float,
    ) -> str:
        """资产文件不存在时的回退占位盒（单行）。"""
        size = _FURNITURE_SIZES.get(furn_type, {"l": 800, "w": 800, "h": 800})
        return (
            f"    local {var} = Box length:{size['l']:.0f} "
            f"width:{size['w']:.0f} height:{size['h']:.0f}; "
            f"{var}.pos = [{px:.2f}, {py:.2f}, {center_z:.2f}]; "
            f"{var}.rotation = (EulerAngles 0 0 {rot_z:.4f}); "
            f"{var}.material = furn_placeholder_mat; "
            f'{var}.name = "Furniture_{safe_name}_MISSING"'
        )
