-- ============================================================
-- vray_setup.ms
-- V-Ray 渲染器完整配置模板
-- 适用于 V-Ray 5 / 6（Autodesk 3ds Max 2022-2025）
-- 在 base_setup.ms 之后执行
-- ============================================================

-- ============================================================
-- [1] 确认当前渲染器是 V-Ray
-- ============================================================

local vr = renderers.current
local vr_classname = classOf vr as string

if not ((vr_classname) contains "VRay") then (
    print "ERROR: Current renderer is not V-Ray. Aborting vray_setup.ms"
    throw "VRay not active"
)

print ("V-Ray renderer confirmed: " + vr_classname)

-- ============================================================
-- [2] 图像采样器（Image Sampler）
-- ============================================================

-- 采样器类型：
--   0 = Fixed
--   1 = Adaptive DMC
--   2 = Adaptive Subdivision
--   3 = Progressive
vr.imageSampler_type = 3   -- Progressive（适合交互预览）

-- Progressive 设置
vr.progressive_minSubdivs   = 1
vr.progressive_maxSubdivs   = 100
vr.progressive_renderTime   = 60    -- 渲染时间限制（秒），0 = 无限制
vr.progressive_noiseThreshold = 0.005

-- 反锯齿过滤
-- 0=None 1=Box 2=Area 3=Triangle 4=Gaussian 5=MitchellNetravali 6=SincBlackman 7=CatmullRom
vr.filter_on   = true
vr.filter_type = 6   -- Sinc Blackman（适合建筑渲染）

-- ============================================================
-- [3] 全局照明（GI）
-- ============================================================

vr.gi_on = true

-- 主 GI 算法：
--   0 = Irradiance Map
--   1 = Photon Map
--   2 = Brute Force
--   3 = Light Cache (不推荐作主)
vr.gi_primary_type  = 0   -- Irradiance Map
vr.gi_primary_mult  = 1.0

-- 次级 GI 算法：
--   2 = Brute Force
--   3 = Light Cache
vr.gi_secondary_type = 3  -- Light Cache
vr.gi_secondary_mult = 1.0

-- ============================================================
-- [4] Irradiance Map 设置（主 GI）
-- ============================================================

-- 预设质量：
--   -5 = Very Low  -4 = Low  -3 = Medium Low
--   -2 = Medium    -1 = High  0 = Very High
vr.adv_irradmap_minRate     = -3   -- Medium Low（适合中等质量出图）
vr.adv_irradmap_maxRate     = -1
vr.adv_irradmap_clrThresh   = 0.3
vr.adv_irradmap_nrmThresh   = 0.1
vr.adv_irradmap_distThresh  = 0.1
vr.adv_irradmap_interpSamples = 20
vr.adv_irradmap_showCalcPhase = false
vr.adv_irradmap_showDirectLight = false
vr.adv_irradmap_showSamples  = false

-- ============================================================
-- [5] Light Cache 设置（次级 GI）
-- ============================================================

vr.adv_lightCache_subdivs       = 1000    -- 细分数（越高质量越好，速度越慢）
vr.adv_lightCache_sampleSize    = 0.02    -- 采样尺寸（相对于场景大小）
vr.adv_lightCache_numPasses     = 4       -- 多线程 passes
vr.adv_lightCache_storeDirectLight = true
vr.adv_lightCache_showCalcPhase = false
vr.adv_lightCache_retrace       = false
vr.adv_lightCache_retraceBounces = 2

-- ============================================================
-- [6] 颜色映射（Color Mapping / Tone Mapping）
-- ============================================================

-- 映射类型：
--   0 = Linear      1 = Exponential   2 = HSV Exponential
--   3 = Intensity Exp  4 = Reinhard   5 = Gamma Correction
vr.colorMapping_type         = 4   -- Reinhard（适合室内，防止过曝）
vr.colorMapping_gamma        = 2.2
vr.colorMapping_dark_mult    = 1.0
vr.colorMapping_bright_mult  = 1.0
vr.colorMapping_burn         = 0.85   -- Reinhard burn value

-- 仅影响渲染不影响材质的模式
-- 0 = Color and density  1 = Color only  2 = No color
vr.colorMapping_affectBackground = true
vr.colorMapping_linearWorkflow   = false   -- 已通过 Gamma 2.2 处理

-- ============================================================
-- [7] 输出分辨率与保存
-- ============================================================

renderWidth    = 1920
renderHeight   = 1080
rendTimeType   = 1     -- Single frame
renderFrame    = 0

-- V-Ray 帧缓冲（VFB）设置
vr.output_saveRawFile   = false
vr.output_rawFileName   = ""

-- ============================================================
-- [8] V-Ray 系统设置
-- ============================================================

-- 动态内存限制（MB），建议设为物理内存的 60-70%
vr.system_raytrace_ram_limit = 8000

-- 光线最大深度
vr.options_maxDepth = 5

-- 隐藏灯光（发光材质）
vr.options_lightsOn = true

-- 阴影
vr.options_shadowsOn = true

-- 渲染区域（0 = 图像，2 = 选定对象）
vr.render_region_xmin = 0
vr.render_region_xmax = renderWidth
vr.render_region_ymin = 0
vr.render_region_ymax = renderHeight

-- ============================================================
-- [9] 降噪器（Denoiser）- V-Ray 5+
-- ============================================================

-- 使用 V-Ray Denoiser（需要 V-Ray 5 或更高版本）
try (
    vr.denoiser_on    = true
    vr.denoiser_type  = 0   -- 0 = V-Ray, 1 = NVIDIA AI, 2 = Intel Open Image Denoise
    vr.denoiser_strength = 0.5
    vr.denoiser_radius   = 10
    print "V-Ray Denoiser enabled"
) catch (
    print "Denoiser not available in this V-Ray version"
)

-- ============================================================
-- [10] 材质覆盖（调试用，生产时注释掉）
-- ============================================================

-- vr.override_mtl_on = true
-- vr.override_mtl_mtl = undefined   -- 设为具体材质可覆盖全场景

-- ============================================================
-- 完成提示
-- ============================================================

print "=== vray_setup.ms complete ==="
print ("  GI Primary   : Irradiance Map")
print ("  GI Secondary : Light Cache (subdivs=" + vr.adv_lightCache_subdivs as string + ")")
print ("  Color Mapping: Reinhard (burn=0.85, gamma=2.2)")
print ("  Resolution   : " + renderWidth as string + " x " + renderHeight as string)
