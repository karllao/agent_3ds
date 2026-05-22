"""
CAD 解析模块。

提供从 DXF 文件中识别建筑元素（墙体、房间、门、窗）的完整工具链。

主要入口：
    - CADPipeline: 一站式处理管道，async process(file_path) → CADParseResult
    - DXFReader: 底层 DXF 读取器
    - WallDetector: 墙体识别器
    - RoomDetector: 房间识别器
    - OpeningDetector: 门窗识别器
    - ScaleDetector: 图纸比例识别器

快速使用示例::

    import asyncio
    from app.services.cad_parser import CADPipeline

    async def main():
        pipeline = CADPipeline()
        result = await pipeline.process("/path/to/floor_plan.dxf")
        print(result.to_dict())

    asyncio.run(main())
"""

from .cad_pipeline import CADParseResult, CADPipeline
from .dxf_reader import DXFDocument, DXFReader, LayerInfo, RawEntity
from .opening_detector import DetectedDoor, DetectedWindow, OpeningDetector
from .room_detector import DetectedRoom, RoomDetector
from .scale_detector import ScaleDetector, ScaleInfo
from .wall_detector import DetectedWall, WallDetector

__all__ = [
    # 主管道
    "CADPipeline",
    "CADParseResult",
    # 读取器
    "DXFReader",
    "DXFDocument",
    "RawEntity",
    "LayerInfo",
    # 检测器
    "ScaleDetector",
    "ScaleInfo",
    "WallDetector",
    "DetectedWall",
    "RoomDetector",
    "DetectedRoom",
    "OpeningDetector",
    "DetectedDoor",
    "DetectedWindow",
]
