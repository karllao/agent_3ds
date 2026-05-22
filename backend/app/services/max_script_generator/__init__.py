"""
max_script_generator
====================
将结构化场景数据（墙体、地板、材质、灯光、相机、家具）转换为
可在 3ds Max 中直接执行的 MAXScript (.ms) 文件。

Quick Start
-----------
::

    from backend.app.services.max_script_generator import (
        SceneScriptGenerator,
        DoorWindowScriptBuilder,
    )

    # 生成完整场景脚本
    gen = SceneScriptGenerator()
    script = gen.generate(
        scene_data={
            "project_name": "MyApartment",
            "walls": [...],
            "doors": [...],
            "windows": [...],
            "rooms": [...],
            "materials": [...],
            "lights": [...],
            "cameras": [...],
            "furniture": [...],
            "render_settings": {"width": 1920, "height": 1080, "renderer": "vray"},
        },
        output_script_path=r"C:\\output\\scene.ms",
        output_max_path=r"C:\\output\\scene.max",
        asset_library_path=r"D:\\assets\\furniture",
    )

    # 单独生成门窗脚本
    dw_builder = DoorWindowScriptBuilder()
    dw_script = dw_builder.build(
        doors=scene_data["doors"],
        windows=scene_data["windows"],
    )
"""

from .camera_builder import CameraScriptBuilder
from .door_window_builder import DoorWindowScriptBuilder
from .floor_builder import FloorScriptBuilder
from .furniture_builder import FurnitureScriptBuilder
from .light_builder import LightScriptBuilder, color_temp_to_rgb
from .material_builder import MaterialScriptBuilder
from .scene_script_generator import SceneScriptGenerator
from .wall_builder import WallScriptBuilder

__all__ = [
    "SceneScriptGenerator",
    "WallScriptBuilder",
    "FloorScriptBuilder",
    "DoorWindowScriptBuilder",
    "MaterialScriptBuilder",
    "LightScriptBuilder",
    "CameraScriptBuilder",
    "FurnitureScriptBuilder",
    "color_temp_to_rgb",
]
