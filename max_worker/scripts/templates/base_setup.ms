-- ============================================================
-- base_setup.ms
-- 3ds Max 场景基础初始化模板
-- 适用于所有渲染器（在具体渲染器 setup 脚本之前执行）
-- ============================================================

-- ============================================================
-- [1] 场景重置
-- ============================================================

resetMaxFile #noPrompt

-- ============================================================
-- [2] 单位系统（毫米）
-- ============================================================

units.SystemType    = #Millimeters
units.SystemScale   = 1.0
units.DisplayType   = #Metric
units.MetricType    = #Millimeters

print "Units set to Millimeters"

-- ============================================================
-- [3] 动画范围与帧率
-- ============================================================

animationRange = interval 0 100
frameRate      = 25
timeDisplayMode = #SMPTE

-- ============================================================
-- [4] Gamma / LUT 颜色校正
-- ============================================================

-- 开启线性工作流 (Gamma 2.2)
colorCorrectionMode = #gamma
displayGamma        = 2.2
fileInGamma         = 2.2
fileOutGamma        = 2.2

-- 开启 Auto-Gamma（仅 2020+）
-- preferenceOptions.gammaEnable = true

print "Gamma correction set to 2.2"

-- ============================================================
-- [5] 背景与环境
-- ============================================================

-- 背景颜色（中性灰，适合室内渲染调光）
backgroundColor = (color 128 128 128)

-- 环境亮度（默认关闭自发光环境）
environmentMap = undefined

-- ============================================================
-- [6] 视口布局
-- ============================================================

viewport.setLayout #layout_4
viewport.setType #view_top        index:1
viewport.setType #view_front      index:2
viewport.setType #view_left       index:3
viewport.setType #view_persp_user index:4

-- 视口显示设置
for i = 1 to 4 do (
    viewport.setActiveViewport i
    viewport.setGridVisibility i false
    -- showEdges 在高版本 Max 中通过 ShowEndResult 控制
)

viewport.setActiveViewport 4
redrawViews()

-- ============================================================
-- [7] 渲染器自动检测与设置
-- ============================================================

local renderer_set = false

-- 尝试 V-Ray
local vray_cls = undefined
try ( vray_cls = rendererByName "V_Ray_6"    ) catch ()
if vray_cls == undefined do try ( vray_cls = rendererByName "V_Ray_5"  ) catch ()
if vray_cls == undefined do try ( vray_cls = rendererByName "V_Ray_adv") catch ()
if vray_cls == undefined do try ( vray_cls = rendererByName "V_Ray"    ) catch ()

if vray_cls != undefined then (
    renderers.current = vray_cls()
    renderer_set = true
    print ("Renderer: V-Ray -> " + (classOf renderers.current as string))
)

-- 若没有 V-Ray，尝试 Corona
if not renderer_set do (
    local corona_cls = undefined
    try ( corona_cls = rendererByName "Corona"         ) catch ()
    if corona_cls == undefined do try ( corona_cls = rendererByName "CoronaRenderer" ) catch ()

    if corona_cls != undefined then (
        renderers.current = corona_cls()
        renderer_set = true
        print ("Renderer: Corona -> " + (classOf renderers.current as string))
    )
)

-- 最终回退：默认扫描线
if not renderer_set do (
    renderers.current = Default_Scanline_Renderer()
    print "Renderer: Default Scanline (fallback)"
)

-- ============================================================
-- [8] 渲染输出基础参数（由具体 setup 脚本覆盖）
-- ============================================================

renderWidth    = 1920
renderHeight   = 1080
rendTimeType   = 1     -- 1 = Single frame
renderFrame    = 0

-- ============================================================
-- [9] 场景统计输出
-- ============================================================

print ("=== base_setup.ms complete ===")
print ("  Renderer  : " + (classOf renderers.current as string))
print ("  Units     : " + (units.SystemType as string))
print ("  Resolution: " + renderWidth as string + "x" + renderHeight as string)
