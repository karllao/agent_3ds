"""
SceneScriptGenerator
--------------------
将完整场景数据 (scene_data) 转换为可在 3ds Max 中一次性执行的 .ms 脚本文件，
并同步生成供 3ds Max Python API 使用的 _py.py 版本。

scene_data 结构（所有字段均可选）
----------------------------------
{
    "project_name": "SampleProject",
    "rooms": [ ... ],          # FloorScriptBuilder 输入
    "walls": [ ... ],          # WallScriptBuilder 输入
    "doors": [ ... ],
    "windows": [ ... ],
    "materials": [ ... ],      # MaterialScriptBuilder 输入
    "lights": [ ... ],         # LightScriptBuilder 输入
    "cameras": [ ... ],        # CameraScriptBuilder 输入
    "furniture": [ ... ],      # FurnitureScriptBuilder 输入
    "render_settings": {
        "width": 1920,
        "height": 1080,
        "renderer": "scanline"  # "scanline" | "vray" | "corona"
    }
}
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .camera_builder import CameraScriptBuilder
from .door_window_builder import DoorWindowScriptBuilder
from .floor_builder import FloorScriptBuilder
from .furniture_builder import FurnitureScriptBuilder
from .light_builder import LightScriptBuilder
from .material_builder import MaterialScriptBuilder
from .wall_builder import WallScriptBuilder


class SceneScriptGenerator:
    """
    主生成器，将所有子生成器的输出拼接成完整 MAXScript 文件，
    并同步输出 Python API 版本。
    """

    def __init__(self) -> None:
        self._wall_builder = WallScriptBuilder()
        self._floor_builder = FloorScriptBuilder()
        self._door_window_builder = DoorWindowScriptBuilder()
        self._mat_builder = MaterialScriptBuilder()
        self._light_builder = LightScriptBuilder()
        self._cam_builder = CameraScriptBuilder()
        self._furn_builder = FurnitureScriptBuilder()

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def generate(
        self,
        scene_data: dict[str, Any],
        output_script_path: str,
        output_max_path: str,
        asset_library_path: str = "",
    ) -> str:
        """
        生成完整 MAXScript (.ms) 文件，并同步写出 Python 版本 (_py.py)。

        Parameters
        ----------
        scene_data          : 场景数据字典
        output_script_path  : 输出 .ms 文件的完整路径
        output_max_path     : 3ds Max 将把 .max 文件保存到的路径
        asset_library_path  : 家具资产库根目录

        Returns
        -------
        str : 生成的 MAXScript 文本内容
        """
        script_content = self._build_maxscript(
            scene_data, output_max_path, asset_library_path
        )
        py_content = self._build_python_script(
            scene_data, output_max_path, asset_library_path
        )

        # 写出 .ms 文件
        output_ms = Path(output_script_path)
        output_ms.parent.mkdir(parents=True, exist_ok=True)
        output_ms.write_text(script_content, encoding="utf-8")

        # 写出 _py.py 文件（同目录，同名加 _py 后缀）
        py_path = output_ms.with_name(output_ms.stem + "_py.py")
        py_path.write_text(py_content, encoding="utf-8")

        return script_content

    # ------------------------------------------------------------------
    # MAXScript 生成
    # ------------------------------------------------------------------

    def _build_maxscript(
        self,
        scene_data: dict[str, Any],
        output_max_path: str,
        asset_library_path: str,
    ) -> str:
        project_name = scene_data.get("project_name", "UnnamedProject")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        render_cfg = scene_data.get("render_settings", {})
        render_width = int(render_cfg.get("width", 1920))
        render_height = int(render_cfg.get("height", 1080))
        renderer_type = render_cfg.get("renderer", "scanline").lower()

        # 路径转义（MAXScript 使用 @"..." 原始字符串避免反斜杠问题）
        max_path_escaped = output_max_path.replace("\\", "\\\\")

        sections: list[str] = []

        # ---- 文件头注释 ----
        sections.append(self._header(project_name, now_str))

        # ---- [1] 场景初始化 ----
        sections.append(self._section_init(renderer_type))

        # ---- [2] 材质库（仅声明 + 辅助函数；应用调用放到所有几何之后） ----
        sections.append(
            self._mat_builder.build_declarations(
                materials=scene_data.get("materials", []),
                rooms=scene_data.get("rooms", []),
            )
        )

        # ---- [3] 墙体 ----
        sections.append(
            self._wall_builder.build(
                walls=scene_data.get("walls", []),
                doors=scene_data.get("doors", []),
                windows=scene_data.get("windows", []),
            )
        )

        # ---- [4] 地面和天花板 ----
        sections.append(
            self._floor_builder.build(
                rooms=scene_data.get("rooms", []),
            )
        )

        # ---- [5] 门和窗 ----
        sections.append(
            self._door_window_builder.build(
                doors=scene_data.get("doors", []),
                windows=scene_data.get("windows", []),
            )
        )

        # ---- [6] 灯光 ----
        sections.append(
            self._light_builder.build(
                lights=scene_data.get("lights", []),
            )
        )

        # ---- [7] 相机 ----
        sections.append(
            self._cam_builder.build(
                cameras=scene_data.get("cameras", []),
            )
        )

        # ---- [8] 家具 ----
        sections.append(
            self._furn_builder.build(
                furniture_list=scene_data.get("furniture", []),
                asset_library_path=asset_library_path,
            )
        )

        # ---- [8.5] 材质应用（必须在所有几何之后） ----
        sections.append(
            self._mat_builder.build_applications(
                materials=scene_data.get("materials", []),
                rooms=scene_data.get("rooms", []),
            )
        )

        # ---- [9] 渲染设置 ----
        sections.append(
            self._section_render_settings(render_width, render_height, renderer_type)
        )

        # ---- [9] 最终处理 ----
        sections.append(self._section_finalize())

        # ---- [10] 保存文件 ----
        sections.append(self._section_save(max_path_escaped))

        # 所有可执行段必须包裹在一个 ( ... ) 块内：
        # MAXScript 顶层不允许 `local` 声明（会报 "Call needs ... got: local x ="），
        # 而 block 内是合法的。各 builder 大量用 `local` 命名几何/材质变量；
        # 一律放进同一个大 block 既保留 local 语义，又允许跨 section 引用。
        # header（纯注释）留在 block 之外作为文件顶部说明。
        header_text = sections[0]
        body_text = "\n\n".join(sections[1:])
        return header_text + "\n\n(\n\n" + body_text + "\n\n)\n"

    # ------------------------------------------------------------------
    # 各 Section 生成
    # ------------------------------------------------------------------

    @staticmethod
    def _header(project_name: str, now_str: str) -> str:
        return "\n".join(
            [
                "-- ============================================================",
                "-- Auto-generated by CAD-to-MAX Agent",
                f"-- Generated at: {now_str}",
                f"-- Project: {project_name}",
                "-- ============================================================",
                "--",
                "-- IMPORTANT: Run this script in 3ds Max via",
                "--   MAXScript > Run Script  OR",
                "--   3dsmaxbatch.exe -sceneFile <this_file.ms>",
                "-- ============================================================",
            ]
        )

    @staticmethod
    def _section_init(renderer_type: str) -> str:
        lines = [
            "-- ============================================================",
            "-- [1] Scene Initialization",
            "-- ============================================================",
            "",
            "-- Reset scene without prompt",
            "resetMaxFile #noPrompt",
            "",
            "-- Set units to millimeters",
            "units.SystemType = #Millimeters",
            "units.SystemScale = 1.0",
            "units.DisplayType = #Metric",
            "units.MetricType = #Millimeters",
            "",
            "-- Animation range",
            "animationRange = interval 0 100",
            "frameRate = 25",
            "",
            "-- Gamma / LUT correction (2.2) — guarded for older Max versions",
            "try (",
            "    colorCorrectionMode = #gamma",
            "    displayGamma = 2.2",
            "    fileInGamma = 2.2",
            "    fileOutGamma = 2.2",
            ") catch (",
            '    format "Gamma setup skipped: %\\n" (getCurrentException())',
            ")",
            "",
            "-- Background color (neutral gray)",
            "backgroundColor = (color 128 128 128)",
            "",
            "-- Viewport layout (no-op in 3dsmaxbatch; guarded)",
            "try (viewport.setLayout #layout_4) catch ()",
        ]

        # 渲染器检测
        if renderer_type == "vray":
            lines += [
                "",
                "-- ---- Set V-Ray renderer ----",
                'local vray_cls = rendererByName "V_Ray_6"',
                'if vray_cls == undefined do vray_cls = rendererByName "V_Ray"',
                'if vray_cls == undefined do vray_cls = rendererByName "V_Ray_adv"',
                "if vray_cls != undefined then (",
                "    renderers.current = vray_cls()",
                '    print "V-Ray renderer set successfully"',
                ") else (",
                '    print "WARNING: V-Ray not found, using default scanline renderer"',
                ")",
            ]
        elif renderer_type == "corona":
            lines += [
                "",
                "-- ---- Set Corona renderer ----",
                'local corona_cls = rendererByName "Corona"',
                'if corona_cls == undefined do corona_cls = rendererByName "CoronaRenderer"',
                "if corona_cls != undefined then (",
                "    renderers.current = corona_cls()",
                '    print "Corona renderer set successfully"',
                ") else (",
                '    print "WARNING: Corona not found, using default scanline renderer"',
                ")",
            ]
        else:
            lines += [
                "",
                "-- ---- Use Default Scanline renderer ----",
                "renderers.current = Default_Scanline_Renderer()",
            ]

        return "\n".join(lines)

    @staticmethod
    def _section_render_settings(width: int, height: int, renderer_type: str) -> str:
        lines = [
            "-- ============================================================",
            "-- [8] Render Settings",
            "-- ============================================================",
            "",
            f"renderWidth = {width}",
            f"renderHeight = {height}",
            "rendTimeType = 1",  # 1 = Single frame
            "renderFrame = 0",
            "",
        ]

        if renderer_type == "vray":
            lines += [
                "-- V-Ray specific settings (applied only if V-Ray is active)",
                'if (classOf renderers.current as string) contains "VRay" do (',
                "    -- Image sampler: Progressive",
                "    renderers.current.imageSampler_type = 3",
                "    -- Min/Max subdivs",
                "    renderers.current.minSubdivs = 1",
                "    renderers.current.maxSubdivs = 4",
                "    -- Color mapping: Reinhard",
                "    renderers.current.colorMapping_type = 4",
                "    renderers.current.colorMapping_gamma = 2.2",
                "    -- GI: Irradiance Map + Light Cache",
                "    renderers.current.gi_on = true",
                "    renderers.current.gi_primary_type = 0   -- Irradiance Map",
                "    renderers.current.gi_secondary_type = 3  -- Light Cache",
                "    -- Light cache subdivs",
                "    renderers.current.lightCache_subdivs = 1000",
                "    renderers.current.lightCache_sampleSize = 0.02",
                '    print "V-Ray settings applied"',
                ")",
            ]
        else:
            # 3ds Max 2018+ 把 scanline renderer 标为 Legacy，部分属性在 2025 已被
            # 移除（如 `filter` 改名 / 删除）；任何一行 unknown property 会让整段
            # 评估中断，所以每个赋值独立 try/catch，最差也只是跳过该属性。
            lines += [
                "-- Scanline: Anti-aliasing (每行独立 try/catch，单个属性不可用不影响其它)",
                "if (classOf renderers.current) == Default_Scanline_Renderer do (",
                "    try ( renderers.current.antiAliasing = true ) catch ()",
                "    try ( renderers.current.filter = Catmull_Rom() ) catch ()",
                "    try ( renderers.current.shadows = true ) catch ()",
                "    try ( renderers.current.autoReflect = true ) catch ()",
                "    try ( renderers.current.forceWireframe = false ) catch ()",
                '    print "Scanline settings applied"',
                ")",
            ]

        return "\n".join(lines)

    @staticmethod
    def _section_finalize() -> str:
        return "\n".join(
            [
                "-- ============================================================",
                "-- [9] Finalize Scene",
                "-- ============================================================",
                "",
                "-- Select all objects and zoom extents (guarded for batch mode)",
                "try (",
                "    max select all",
                "    max zoomext sel all",
                "    clearSelection()",
                ") catch (",
                '    format "Finalize selection step skipped: %\\n" '
                "(getCurrentException())",
                ")",
                "",
                "-- Update viewports (no-op in batch mode, guard against errors)",
                "try (",
                "    viewport.setLayout #layout_4",
                "    viewport.setType #view_top index:1",
                "    viewport.setType #view_front index:2",
                "    viewport.setType #view_left index:3",
                "    viewport.setType #view_persp_user index:4",
                "    redrawViews()",
                ") catch (",
                '    format "Viewport setup skipped (batch mode): %\\n" '
                "(getCurrentException())",
                ")",
                "",
                'print "Scene generation completed - all sections processed."',
            ]
        )

    @staticmethod
    def _section_save(max_path_escaped: str) -> str:
        return "\n".join(
            [
                "-- ============================================================",
                "-- [10] Save Max File",
                "-- ============================================================",
                "",
                f'local save_path = @"{max_path_escaped}"',
                "local save_dir = getFilenamePath save_path",
                "if not doesFileExist save_dir do makeDir save_dir",
                "",
                "local save_result = saveMaxFile save_path quiet:true",
                "if save_result then (",
                '    print ("Scene saved successfully: " + save_path)',
                ") else (",
                '    print ("ERROR: Failed to save scene to: " + save_path)',
                ")",
                "",
                "-- Script execution complete",
                'print "=== CAD-to-MAX Agent Script DONE ==="',
            ]
        )

    # ------------------------------------------------------------------
    # Python API 版本生成
    # ------------------------------------------------------------------

    def _build_python_script(
        self,
        scene_data: dict[str, Any],
        output_max_path: str,
        asset_library_path: str,
    ) -> str:
        """
        生成供 3ds Max 内置 Python 解释器（MAXScript python 桥接）使用的
        Python 脚本。核心逻辑与 MAXScript 版本相同，通过 pymxs 模块操作。
        """
        project_name = scene_data.get("project_name", "UnnamedProject")
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        render_cfg = scene_data.get("render_settings", {})
        render_width = int(render_cfg.get("width", 1920))
        render_height = int(render_cfg.get("height", 1080))
        renderer_type = render_cfg.get("renderer", "scanline").lower()

        walls = scene_data.get("walls", [])
        rooms = scene_data.get("rooms", [])
        doors = scene_data.get("doors", [])
        windows = scene_data.get("windows", [])
        lights = scene_data.get("lights", [])
        cameras = scene_data.get("cameras", [])
        furniture = scene_data.get("furniture", [])
        materials = scene_data.get("materials", [])

        # 将 MAXScript 片段嵌入 Python 的 rt.execute() 调用
        mat_ms = self._mat_builder.build(materials, rooms)
        wall_ms = self._wall_builder.build(walls, doors, windows)
        floor_ms = self._floor_builder.build(rooms)
        door_window_ms = self._door_window_builder.build(doors, windows)
        light_ms = self._light_builder.build(lights)
        cam_ms = self._cam_builder.build(cameras)
        furn_ms = self._furn_builder.build(furniture, asset_library_path)

        def ms_block(ms_code: str) -> str:
            """将多行 MAXScript 转为 Python 三重引号字符串并调用 rt.execute()。"""
            escaped = ms_code.replace('"""', '\\"\\"\\"')
            return f'rt.execute("""\n{escaped}\n""")'

        lines: list[str] = [
            '"""',
            "Auto-generated 3ds Max Python API Script",
            f"Generated at: {now_str}",
            f"Project: {project_name}",
            "",
            "Run inside 3ds Max Python interpreter:",
            "  MAXScript > Python > Run Script",
            '"""',
            "",
            "import pymxs",
            "from pymxs import runtime as rt",
            "import os",
            "",
            "",
            "def main() -> None:",
            '    """Execute full scene generation."""',
            "",
            "    # [1] Initialize scene",
            "    rt.resetMaxFile(rt.Name('noPrompt'))",
            "    rt.units.SystemType = rt.Name('Millimeters')",
            "    rt.units.DisplayType = rt.Name('Metric')",
            "    rt.units.MetricType = rt.Name('Millimeters')",
            f"    rt.renderWidth = {render_width}",
            f"    rt.renderHeight = {render_height}",
            "",
        ]

        # 渲染器设置
        if renderer_type == "vray":
            lines += [
                "    # Set V-Ray renderer",
                "    try:",
                "        vray_cls = rt.rendererByName('V_Ray_6') or rt.rendererByName('V_Ray')",
                "        if vray_cls:",
                "            rt.renderers.current = vray_cls()",
                "            print('V-Ray renderer set')",
                "        else:",
                "            print('WARNING: V-Ray not found, using scanline')",
                "    except Exception as exc:",
                "        print(f'Renderer setup error: {exc}')",
                "",
            ]
        else:
            lines += [
                "    # Use default scanline renderer",
                "    rt.renderers.current = rt.Default_Scanline_Renderer()",
                "",
            ]

        # 嵌入各 MAXScript 片段
        for section_name, ms_code in [
            ("[2] Materials", mat_ms),
            ("[3] Walls", wall_ms),
            ("[4] Floors & Ceilings", floor_ms),
            ("[5] Doors & Windows", door_window_ms),
            ("[6] Lights", light_ms),
            ("[7] Cameras", cam_ms),
            ("[8] Furniture", furn_ms),
        ]:
            lines.append(f"    # {section_name}")
            lines.append(f"    {ms_block(ms_code)}")
            lines.append("")

        # 最终处理 + 保存
        max_path_py = output_max_path.replace("\\", "\\\\")
        lines += [
            "    # [9] Finalize",
            "    rt.execute('select all; max zoomext sel all; deselect all')",
            "    rt.redrawViews()",
            "",
            "    # [10] Save",
            f'    save_path = r"{output_max_path}"',
            "    os.makedirs(os.path.dirname(save_path), exist_ok=True)",
            "    result = rt.saveMaxFile(save_path, quiet=True)",
            "    if result:",
            "        print(f'Scene saved: {save_path}')",
            "    else:",
            "        print(f'ERROR: Failed to save: {save_path}')",
            "",
            "",
            "if __name__ == '__main__':",
            "    main()",
        ]

        return "\n".join(lines)
