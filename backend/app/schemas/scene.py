"""
场景数据结构 Pydantic 模型。

这些模型是 AI Agent 输出的核心数据结构，也是传递给
3ds Max Worker 进行自动化建模的 JSON Schema。
"""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator

# ── 通用几何类型 ──────────────────────────────────────────────────────────────


class Point2D(BaseModel):
    """二维平面坐标（单位：毫米）"""

    x: float = Field(..., description="X 轴坐标，单位 mm")
    y: float = Field(..., description="Y 轴坐标，单位 mm")


class Point3D(BaseModel):
    """三维空间坐标（单位：毫米）"""

    x: float = Field(..., description="X 轴坐标，单位 mm")
    y: float = Field(..., description="Y 轴坐标，单位 mm")
    z: float = Field(..., description="Z 轴坐标，单位 mm")


class Rotation3D(BaseModel):
    """欧拉角旋转（单位：度）"""

    x: float = Field(default=0.0, description="绕 X 轴旋转角度")
    y: float = Field(default=0.0, description="绕 Y 轴旋转角度")
    z: float = Field(default=0.0, description="绕 Z 轴旋转角度")


class Scale3D(BaseModel):
    """缩放比例"""

    x: float = Field(default=1.0, gt=0)
    y: float = Field(default=1.0, gt=0)
    z: float = Field(default=1.0, gt=0)


class ColorRGB(BaseModel):
    """RGB 颜色 (0–255)"""

    r: int = Field(..., ge=0, le=255)
    g: int = Field(..., ge=0, le=255)
    b: int = Field(..., ge=0, le=255)


# ── 开口（门洞 / 窗洞）嵌套模型 ──────────────────────────────────────────────


class OpeningType(str, Enum):
    DOOR = "door"
    WINDOW = "window"
    OPENING = "opening"  # 无门窗的通道洞口


class WallOpening(BaseModel):
    """墙体上的开口信息"""

    opening_id: str = Field(..., description="开口唯一 ID")
    opening_type: OpeningType = Field(..., description="开口类型")
    position_along_wall: float = Field(
        ..., ge=0, description="沿墙方向距起点的距离（mm）"
    )
    width: float = Field(..., gt=0, description="开口宽度（mm）")
    height: float = Field(..., gt=0, description="开口高度（mm）")
    floor_offset: float = Field(default=0.0, ge=0, description="底部离地高度（mm）")


# ── 材质 ─────────────────────────────────────────────────────────────────────


class MaterialType(str, Enum):
    STANDARD = "standard"
    PHYSICAL = "physical"
    VRAY_MTL = "vray_mtl"
    ARCH_DESIGN = "arch_design"


class MaterialConfig(BaseModel):
    """材质配置"""

    id: str = Field(..., description="材质唯一 ID，格式建议 mat_xxx")
    name: str = Field(..., description="材质名称（将作为 MAX 材质球名称）")
    type: MaterialType = Field(default=MaterialType.PHYSICAL)
    color: ColorRGB = Field(default_factory=lambda: ColorRGB(r=200, g=200, b=200))
    texture_path: str | None = Field(default=None, description="贴图文件相对路径或 URL")
    roughness: float = Field(default=0.5, ge=0.0, le=1.0, description="粗糙度")
    metallic: float = Field(default=0.0, ge=0.0, le=1.0, description="金属度")
    ior: float = Field(default=1.5, ge=1.0, description="折射率（玻璃等）")
    opacity: float = Field(default=1.0, ge=0.0, le=1.0, description="不透明度")
    bump_strength: float = Field(default=0.5, description="凹凸强度")
    uv_scale: Scale3D = Field(
        default_factory=lambda: Scale3D(x=1.0, y=1.0, z=1.0),
        description="UV 平铺缩放",
    )


# ── 场景全局配置 ─────────────────────────────────────────────────────────────


class UnitSystem(str, Enum):
    MILLIMETER = "mm"
    CENTIMETER = "cm"
    METER = "m"


class SceneConfig(BaseModel):
    """场景全局配置"""

    scene_name: str = Field(..., description="场景名称")
    unit_system: UnitSystem = Field(
        default=UnitSystem.MILLIMETER, description="场景单位系统"
    )
    floor_height: float = Field(default=2800.0, gt=0, description="标准层高（mm）")
    style: str = Field(
        default="modern",
        description="室内风格：modern / nordic / chinese / industrial / luxury 等",
    )
    renderer: Literal["vray", "corona", "arnold", "default"] = Field(
        default="vray", description="渲染器类型"
    )
    ambient_light_intensity: float = Field(default=0.3, ge=0.0)
    background_color: ColorRGB = Field(
        default_factory=lambda: ColorRGB(r=255, g=255, b=255)
    )


# ── 墙体 ─────────────────────────────────────────────────────────────────────


class WallConfig(BaseModel):
    """墙体配置"""

    id: str = Field(..., description="墙体唯一 ID，格式 wall_xxx")
    start: Point2D = Field(..., description="墙体起点（平面坐标，mm）")
    end: Point2D = Field(..., description="墙体终点（平面坐标，mm）")
    thickness: float = Field(default=240.0, gt=0, description="墙体厚度（mm）")
    height: float = Field(default=2800.0, gt=0, description="墙体高度（mm）")
    room_side_a: str | None = Field(default=None, description="墙体 A 侧的房间 ID")
    room_side_b: str | None = Field(
        default=None, description="墙体 B 侧的房间 ID（外墙时为 None）"
    )
    material: str = Field(
        default="mat_wall_white", description="墙面材质 ID（引用 MaterialConfig.id）"
    )
    openings: list[WallOpening] = Field(
        default_factory=list, description="该墙上的门洞 / 窗洞列表"
    )
    is_exterior: bool = Field(default=False, description="是否是外墙")


# ── 房间 ─────────────────────────────────────────────────────────────────────


class RoomType(str, Enum):
    LIVING_ROOM = "living_room"
    BEDROOM = "bedroom"
    MASTER_BEDROOM = "master_bedroom"
    KITCHEN = "kitchen"
    BATHROOM = "bathroom"
    DINING_ROOM = "dining_room"
    STUDY = "study"
    BALCONY = "balcony"
    CORRIDOR = "corridor"
    STORAGE = "storage"
    OTHER = "other"


class CeilingType(str, Enum):
    FLAT = "flat"
    SUSPENDED = "suspended"  # 吊顶
    COFFERED = "coffered"  # 格栅吊顶
    VAULTED = "vaulted"  # 拱形
    EXPOSED = "exposed"  # 裸露混凝土


class RoomConfig(BaseModel):
    """房间配置"""

    id: str = Field(..., description="房间唯一 ID，格式 room_xxx")
    name: str = Field(..., description="房间名称，如 主卧、客厅")
    type: RoomType = Field(default=RoomType.OTHER)
    boundary: list[Point2D] = Field(
        ..., min_length=3, description="房间轮廓多边形顶点（顺时针或逆时针）"
    )
    area: float = Field(..., gt=0, description="房间面积（m²）")
    floor_material: str = Field(default="mat_floor_wood", description="地板材质 ID")
    ceiling_material: str = Field(
        default="mat_ceiling_white", description="天花板材质 ID"
    )
    ceiling_type: CeilingType = Field(default=CeilingType.FLAT)
    ceiling_height: float | None = Field(
        default=None,
        description="吊顶高度（mm），None 表示使用 SceneConfig.floor_height",
    )
    style: str | None = Field(
        default=None,
        description="房间个性化风格，覆盖全局 SceneConfig.style",
    )

    @field_validator("boundary")
    @classmethod
    def _validate_boundary(cls, v: list[Point2D]) -> list[Point2D]:
        if len(v) < 3:
            raise ValueError("房间轮廓至少需要 3 个顶点")
        return v


# ── 门 ───────────────────────────────────────────────────────────────────────


class SwingDirection(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    DOUBLE = "double"
    SLIDING = "sliding"
    FOLDING = "folding"


class DoorType(str, Enum):
    SINGLE = "single"
    DOUBLE = "double"
    SLIDING = "sliding"
    POCKET = "pocket"
    BARN = "barn"
    REVOLVING = "revolving"


class DoorConfig(BaseModel):
    """门配置"""

    id: str = Field(..., description="门唯一 ID，格式 door_xxx")
    wall_id: str = Field(..., description="所在墙体 ID")
    position: Point3D = Field(..., description="门的安装位置（世界坐标，mm）")
    width: float = Field(default=900.0, gt=0, description="门宽（mm）")
    height: float = Field(default=2100.0, gt=0, description="门高（mm）")
    floor_offset: float = Field(default=0.0, ge=0, description="门底距地高度（mm）")
    swing_direction: SwingDirection = Field(default=SwingDirection.LEFT)
    door_type: DoorType = Field(default=DoorType.SINGLE)
    material: str = Field(default="mat_door_wood", description="门体材质 ID")
    frame_material: str = Field(default="mat_door_frame", description="门框材质 ID")
    asset_id: str | None = Field(
        default=None, description="3D 资产库中的门模型 ID（可选，优先使用）"
    )


# ── 窗 ───────────────────────────────────────────────────────────────────────


class WindowType(str, Enum):
    CASEMENT = "casement"  # 平开窗
    SLIDING = "sliding"  # 推拉窗
    FIXED = "fixed"  # 固定窗
    AWNING = "awning"  # 悬窗
    BAY = "bay"  # 飘窗
    SKYLIGHT = "skylight"  # 天窗
    FRENCH = "french"  # 落地窗


class WindowConfig(BaseModel):
    """窗配置"""

    id: str = Field(..., description="窗唯一 ID，格式 win_xxx")
    wall_id: str = Field(..., description="所在墙体 ID")
    position: Point3D = Field(..., description="窗的安装位置（世界坐标，mm）")
    width: float = Field(default=1500.0, gt=0, description="窗宽（mm）")
    height: float = Field(default=1200.0, gt=0, description="窗高（mm）")
    sill_height: float = Field(default=900.0, ge=0, description="窗台高度（mm）")
    window_type: WindowType = Field(default=WindowType.CASEMENT)
    glass_material: str = Field(default="mat_glass_clear", description="玻璃材质 ID")
    frame_material: str = Field(default="mat_window_frame", description="窗框材质 ID")
    has_curtain: bool = Field(default=True, description="是否生成窗帘")
    curtain_material: str | None = Field(
        default="mat_curtain_white", description="窗帘材质 ID"
    )
    asset_id: str | None = Field(
        default=None, description="3D 资产库中的窗模型 ID（可选）"
    )


# ── 家具 ─────────────────────────────────────────────────────────────────────


class FurnitureCategory(str, Enum):
    SOFA = "sofa"
    BED = "bed"
    TABLE = "table"
    CHAIR = "chair"
    DESK = "desk"
    WARDROBE = "wardrobe"
    CABINET = "cabinet"
    BOOKSHELF = "bookshelf"
    TV_STAND = "tv_stand"
    DINING_TABLE = "dining_table"
    KITCHEN_CABINET = "kitchen_cabinet"
    APPLIANCE = "appliance"
    DECORATION = "decoration"
    PLANT = "plant"
    OTHER = "other"


class FurnitureConfig(BaseModel):
    """家具配置"""

    id: str = Field(..., description="家具唯一 ID，格式 fur_xxx")
    category: FurnitureCategory = Field(..., description="家具分类")
    asset_id: str = Field(..., description="3D 资产库中的家具模型 ID")
    room_id: str = Field(..., description="所在房间 ID")
    position: Point3D = Field(..., description="家具位置（世界坐标，mm）")
    rotation: Rotation3D = Field(
        default_factory=Rotation3D, description="家具旋转（欧拉角，度）"
    )
    scale: Scale3D = Field(default_factory=Scale3D, description="家具缩放比例")
    material_overrides: dict[str, str] = Field(
        default_factory=dict,
        description="材质覆盖映射：{子物体名称: 材质 ID}",
    )


# ── 灯光 ─────────────────────────────────────────────────────────────────────


class LightType(str, Enum):
    POINT = "point"  # 点光源
    SPOT = "spot"  # 聚光灯
    AREA = "area"  # 面光源
    DIRECTIONAL = "directional"  # 方向光
    IES = "ies"  # IES 光域网
    AMBIENT = "ambient"  # 环境光


class LightConfig(BaseModel):
    """灯光配置"""

    id: str = Field(..., description="灯光唯一 ID，格式 light_xxx")
    type: LightType = Field(..., description="灯光类型")
    room_id: str = Field(..., description="所在房间 ID")
    position: Point3D = Field(..., description="灯光位置（世界坐标，mm）")
    rotation: Rotation3D = Field(
        default_factory=Rotation3D, description="灯光旋转（度）"
    )
    color_temperature: int = Field(
        default=4000, ge=1000, le=12000, description="色温（K）"
    )
    intensity: float = Field(
        default=1000.0, ge=0, description="光照强度（单位随渲染器而异，默认 lm）"
    )
    size: Point2D | None = Field(
        default=None, description="面光源尺寸宽 x 高（mm），仅 area 类型使用"
    )
    target: Point3D | None = Field(
        default=None, description="聚光灯目标点，仅 spot 类型使用"
    )
    ies_path: str | None = Field(
        default=None, description="IES 文件路径，仅 ies 类型使用"
    )
    cast_shadow: bool = Field(default=True)
    enabled: bool = Field(default=True)


# ── 相机 ─────────────────────────────────────────────────────────────────────


class CameraConfig(BaseModel):
    """相机配置（用于渲染视角）"""

    id: str = Field(..., description="相机唯一 ID，格式 cam_xxx")
    room_id: str = Field(..., description="主要拍摄的房间 ID")
    position: Point3D = Field(..., description="相机位置（mm）")
    target: Point3D = Field(..., description="相机目标点（mm）")
    fov: float = Field(default=50.0, ge=1.0, le=180.0, description="视野角度（度）")
    near_clip: float = Field(default=1.0, gt=0, description="近裁剪面（mm）")
    far_clip: float = Field(default=100000.0, gt=0, description="远裁剪面（mm）")
    is_default: bool = Field(default=False, description="是否作为默认渲染相机")


# ── 顶层完整场景数据 ─────────────────────────────────────────────────────────


class FullSceneData(BaseModel):
    """
    完整的场景数据对象。

    由 AI Agent 生成并序列化为 JSON，传递给：
    1. 前端 Three.js 进行实时预览
    2. 3ds Max Worker 进行自动化建模
    """

    version: str = Field(default="1.0.0", description="Schema 版本号")
    scene_config: SceneConfig = Field(..., description="全局场景配置")
    materials: list[MaterialConfig] = Field(
        default_factory=list, description="场景所有材质定义"
    )
    walls: list[WallConfig] = Field(default_factory=list, description="所有墙体")
    rooms: list[RoomConfig] = Field(default_factory=list, description="所有房间")
    doors: list[DoorConfig] = Field(default_factory=list, description="所有门")
    windows: list[WindowConfig] = Field(default_factory=list, description="所有窗")
    furniture: list[FurnitureConfig] = Field(
        default_factory=list, description="所有家具"
    )
    lights: list[LightConfig] = Field(default_factory=list, description="所有灯光")
    cameras: list[CameraConfig] = Field(
        default_factory=list, description="所有渲染相机"
    )
    extra: dict[str, Any] = Field(
        default_factory=dict,
        description="扩展字段，用于存储特定渲染器或插件的额外参数",
    )

    def get_material_by_id(self, mat_id: str) -> MaterialConfig | None:
        """按 ID 查找材质"""
        return next((m for m in self.materials if m.id == mat_id), None)

    def get_room_by_id(self, room_id: str) -> RoomConfig | None:
        """按 ID 查找房间"""
        return next((r for r in self.rooms if r.id == room_id), None)

    def get_walls_for_room(self, room_id: str) -> list[WallConfig]:
        """获取某房间的所有墙体"""
        return [
            w
            for w in self.walls
            if w.room_side_a == room_id or w.room_side_b == room_id
        ]
