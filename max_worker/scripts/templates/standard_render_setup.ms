-- ============================================================
-- standard_render_setup.ms
-- 3ds Max 默认扫描线渲染器（Default Scanline Renderer）配置模板
-- 在 base_setup.ms 之后执行（不需要第三方插件）
-- ============================================================

-- ============================================================
-- [1] 确认并设置扫描线渲染器
-- ============================================================

renderers.current = Default_Scanline_Renderer()
local sr = renderers.current

if (classOf sr) != Default_Scanline_Renderer do (
    print "ERROR: Failed to set Default Scanline Renderer"
    throw "Scanline renderer setup failed"
)

print "Default Scanline Renderer set successfully"

-- ============================================================
-- [2] 反锯齿（Anti-aliasing）
-- ============================================================

-- 开启反锯齿
sr.antiAliasing = true

-- 过滤器类型（AAFilter）
-- Blackman / Mitchell-Netravali / Catmull-Rom / Soften / Cook Variable / Blend / Quadratic / Cubic / Video
sr.filter = Catmull_Rom()    -- 锐利，适合建筑和室内

-- 过滤器尺寸（影响模糊程度）
-- sr.filter.size = 4.0  -- Catmull-Rom 不需要调整

-- ============================================================
-- [3] 全局光照（Global Illumination）
-- 扫描线用 Light Tracer 或 Radiosity
-- ============================================================

-- 使用 Light Tracer（适合室内中等质量）
-- Light Tracer 通过修改 Advanced Lighting 面板
-- MAXScript 方式：

try (
    local lt = LightTracer()
    setAdvancedLightingOptions lt
    -- Light Tracer 参数
    lt.globalMultiplier = 1.0
    lt.skyLightsMultiplier = 1.5
    lt.colorBleed = 1.0
    lt.bounces    = 1
    lt.rayspersample = 250
    lt.filterSize = 0.5
    lt.extraAmbient = (color 0 0 0)
    lt.showProgressBar = false
    print "Light Tracer GI enabled"
) catch (
    print "Light Tracer setup failed, using direct lighting only"
)

-- ============================================================
-- [4] 阴影设置
-- ============================================================

sr.shadows = true

-- 设置默认阴影类型：Ray-Traced 或 Shadow Map
-- 通过遍历所有灯光设置
for lt in lights do (
    lt.castShadows   = true
    lt.shadowType    = 1       -- 1 = Shadow Map（快）
    -- lt.shadowType = 0       -- 0 = Ray-Traced（准确但慢）
    if lt.shadowType == 1 do (
        lt.mapSize = 512
        lt.mapBias = 0.005
    )
)

-- ============================================================
-- [5] 自动反射与折射
-- ============================================================

sr.autoReflect       = true
sr.autoRefract       = true
sr.reflectRefractIterations = 3   -- 最大迭代次数

-- ============================================================
-- [6] 线框渲染（关闭）
-- ============================================================

sr.forceWireframe    = false
sr.wireThickness     = 1.0

-- ============================================================
-- [7] 光线追踪（Raytrace，扫描线的反射/折射）
-- ============================================================

-- 全局光线追踪开关
raytraceOptions.enable        = true
raytraceOptions.maxDepth      = 5
raytraceOptions.cutoffThreshold = 0.03
raytraceOptions.globalRayDisable = false

-- ============================================================
-- [8] 运动模糊（关闭，室内静态渲染不需要）
-- ============================================================

sr.objectMotionBlur  = false
sr.imageMotionBlur   = false

-- ============================================================
-- [9] 输出分辨率
-- ============================================================

renderWidth    = 1920
renderHeight   = 1080
rendTimeType   = 1     -- 1 = Single frame
renderFrame    = 0

-- 像素宽高比
renderPixelAspect = 1.0

-- ============================================================
-- [10] 环境与大气效果
-- ============================================================

-- 关闭大气效果（可按需打开）
-- atmospherics = false

-- 开启效果（Glare / Blur 等，可按需打开）
-- renderEffects = false

-- ============================================================
-- [11] 帧缓冲（Frame Buffer）显示设置
-- ============================================================

-- 开启 Dithering（256色 display 仿色，减少色带）
sr.dithering256   = true
sr.ditherTruecolor = false

-- ============================================================
-- [12] 多层反射/折射深度（Materials）
-- ============================================================

sr.maxDepth          = 5     -- 最大反射折射层数
sr.maxKBufferDepth   = 8     -- 最大透明层数

-- ============================================================
-- 完成提示
-- ============================================================

print "=== standard_render_setup.ms complete ==="
print ("  Renderer    : " + (classOf renderers.current as string))
print ("  AA Filter   : Catmull-Rom")
print ("  Shadows     : Shadow Map (512px)")
print ("  Raytrace    : enabled (maxDepth=5)")
print ("  Resolution  : " + renderWidth as string + " x " + renderHeight as string)
