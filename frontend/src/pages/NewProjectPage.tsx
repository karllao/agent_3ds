import { useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  ArrowRight,
  Sparkles,
  Loader2,
  CheckCircle2,
  Eye,
  ChevronRight,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { CADUploader } from '@/components/upload/CADUploader'
import { useCreateProject, useUploadCAD, useParseCAD, useCADPreview } from '@/hooks/useProject'
import { useProjectStore } from '@/store/projectStore'
import type { UploadProgress } from '@/types'

// ─── Step Indicator ───────────────────────────────────────────────────────────

function StepIndicator({ current, total }: { current: number; total: number }) {
  return (
    <div className="flex items-center gap-2">
      {Array.from({ length: total }, (_, i) => (
        <div key={i} className="flex items-center gap-2">
          <div
            className={cn(
              'flex h-7 w-7 items-center justify-center rounded-full text-xs font-bold transition-all',
              i < current
                ? 'bg-green-500/20 text-green-400'
                : i === current
                ? 'bg-primary-500 text-white'
                : 'bg-surface-700 text-surface-200/40',
            )}
          >
            {i < current ? <CheckCircle2 className="h-4 w-4" /> : i + 1}
          </div>
          {i < total - 1 && (
            <ChevronRight
              className={cn(
                'h-4 w-4',
                i < current ? 'text-green-400/50' : 'text-surface-700',
              )}
            />
          )}
        </div>
      ))}
    </div>
  )
}

// ─── CAD Preview Modal ────────────────────────────────────────────────────────

function CADPreviewModal({
  projectId,
  onClose,
}: {
  projectId: number
  onClose: () => void
}) {
  const { data: preview, isLoading } = useCADPreview(projectId, true)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-lg rounded-2xl border border-white/10 bg-surface-800 p-6 shadow-card-lg animate-slide-up">
        <h3 className="mb-4 text-base font-semibold text-white">CAD 解析结果</h3>

        {isLoading ? (
          <div className="flex h-32 items-center justify-center">
            <Loader2 className="h-6 w-6 animate-spin text-primary-400" />
          </div>
        ) : preview ? (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              {[
                { label: '墙体数量', value: preview.wall_count },
                { label: '房间数量', value: preview.room_count },
                { label: '门数量',   value: preview.door_count },
                { label: '窗数量',   value: preview.window_count },
              ].map((item) => (
                <div key={item.label} className="rounded-xl bg-surface-900 p-3">
                  <p className="text-xs text-surface-200/50">{item.label}</p>
                  <p className="mt-1 text-2xl font-bold text-white">{item.value}</p>
                </div>
              ))}
            </div>

            {preview.layer_names.length > 0 && (
              <div>
                <p className="mb-2 text-xs font-medium text-surface-200/50">图层</p>
                <div className="flex flex-wrap gap-1.5">
                  {preview.layer_names.map((name) => (
                    <span
                      key={name}
                      className="rounded-lg bg-surface-700/50 px-2 py-1 text-xs text-surface-200/70"
                    >
                      {name}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {preview.warnings.length > 0 && (
              <div className="rounded-xl bg-amber-500/5 border border-amber-500/20 p-3">
                <p className="mb-1.5 text-xs font-medium text-amber-400">警告</p>
                {preview.warnings.map((w, i) => (
                  <p key={i} className="text-xs text-amber-400/70">{w}</p>
                ))}
              </div>
            )}
          </div>
        ) : (
          <p className="text-sm text-surface-200/50">暂无解析结果</p>
        )}

        <button
          onClick={onClose}
          className="mt-6 w-full rounded-xl bg-white/5 py-2.5 text-sm font-medium text-surface-200/70 transition-colors hover:bg-white/10 hover:text-white"
        >
          关闭
        </button>
      </div>
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

const DESCRIPTION_PLACEHOLDER = `例如：
• 现代简约风格，客厅暖色灯光
• 卧室木地板，北欧风家具
• 开放式厨房，岛台设计
• 主卧需要大衣柜和梳妆台
• 整体色调偏冷，蓝灰色系`

export function NewProjectPage() {
  const navigate = useNavigate()
  const { addNotification } = useProjectStore()

  const [step, setStep] = useState(0)
  const [projectName, setProjectName] = useState('')
  const [description, setDescription] = useState('')
  const [createdProjectId, setCreatedProjectId] = useState<number | null>(null)
  const [uploadedFile, setUploadedFile] = useState<File | null>(null)
  const [uploadProgress, setUploadProgress] = useState<UploadProgress | null>(null)
  const [showCADPreview, setShowCADPreview] = useState(false)

  const createMutation = useCreateProject()
  const uploadMutation = useUploadCAD(
    createdProjectId ?? 0,
    (p) => setUploadProgress(p),
  )
  const parseMutation = useParseCAD(createdProjectId ?? 0)

  // Step 0 → 1: 创建项目
  const handleCreateProject = async () => {
    if (!projectName.trim()) return
    try {
      const project = await createMutation.mutateAsync({
        name: projectName.trim(),
        user_description: description.trim() || undefined,
      })
      setCreatedProjectId(project.id)
      setStep(1)
    } catch (err) {
      addNotification({
        type: 'error',
        title: '创建失败',
        message: err instanceof Error ? err.message : '请稍后重试',
      })
    }
  }

  // Step 1: 上传 CAD
  const handleFileSelect = useCallback((file: File) => {
    setUploadedFile(file)
  }, [])

  const handleUpload = useCallback(
    async (file: File) => {
      if (!createdProjectId) return
      try {
        await uploadMutation.mutateAsync(file)
        addNotification({
          type: 'success',
          title: 'CAD 文件上传成功',
          message: file.name,
        })
      } catch (err) {
        addNotification({
          type: 'error',
          title: '上传失败',
          message: err instanceof Error ? err.message : '请重试',
        })
      }
    },
    [createdProjectId, uploadMutation, addNotification],
  )

  const handleParseCAD = async () => {
    if (!createdProjectId) return
    try {
      await parseMutation.mutateAsync()
      addNotification({
        type: 'info',
        title: 'CAD 解析已启动',
        message: '解析完成后可查看识别结果',
      })
    } catch (err) {
      addNotification({
        type: 'error',
        title: '解析失败',
        message: err instanceof Error ? err.message : '请重试',
      })
    }
  }

  const handleStartGenerate = () => {
    if (createdProjectId) {
      navigate(`/projects/${createdProjectId}`)
    }
  }

  const isStep0Valid = projectName.trim().length >= 2
  const isUploaded = uploadMutation.isSuccess
  const isCreating = createMutation.isPending
  const isUploading = uploadMutation.isPending

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <header className="flex h-16 shrink-0 items-center gap-4 border-b border-white/5 px-6">
        <button
          onClick={() => (step > 0 ? setStep(step - 1) : navigate('/projects'))}
          className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-surface-200/50 transition-colors hover:bg-white/10 hover:text-white"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>

        <div className="flex-1">
          <h1 className="text-lg font-bold text-white">新建项目</h1>
        </div>

        <StepIndicator current={step} total={2} />
      </header>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-2xl px-6 py-8">
          {/* ── Step 0: 基本信息 ── */}
          {step === 0 && (
            <div className="space-y-6 animate-fade-in">
              <div>
                <h2 className="text-xl font-bold text-white">项目基本信息</h2>
                <p className="mt-1 text-sm text-surface-200/50">
                  填写项目名称和设计需求描述，AI 将根据这些信息生成专属方案
                </p>
              </div>

              {/* Project Name */}
              <div className="space-y-2">
                <label className="text-sm font-medium text-surface-200/70">
                  项目名称 <span className="text-red-400">*</span>
                </label>
                <input
                  type="text"
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  placeholder="例如：三居室现代简约改造"
                  maxLength={50}
                  className="w-full rounded-xl border border-white/10 bg-surface-800 px-4 py-3 text-sm text-white placeholder-surface-200/30 outline-none transition-colors focus:border-primary-500/50"
                />
                <p className="text-right text-xs text-surface-200/30">
                  {projectName.length}/50
                </p>
              </div>

              {/* Description */}
              <div className="space-y-2">
                <label className="text-sm font-medium text-surface-200/70">
                  设计需求描述
                  <span className="ml-2 text-xs text-surface-200/30">（可选，但越详细效果越好）</span>
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder={DESCRIPTION_PLACEHOLDER}
                  rows={8}
                  maxLength={2000}
                  className="w-full resize-none rounded-xl border border-white/10 bg-surface-800 px-4 py-3 text-sm text-white placeholder-surface-200/20 outline-none transition-colors focus:border-primary-500/50"
                />
                <p className="text-right text-xs text-surface-200/30">
                  {description.length}/2000
                </p>
              </div>

              {/* Tips */}
              <div className="rounded-xl border border-primary-500/10 bg-primary-500/5 p-4">
                <div className="flex items-center gap-2 mb-2">
                  <Sparkles className="h-4 w-4 text-primary-400" />
                  <p className="text-xs font-medium text-primary-400">描述越详细，AI 生成效果越好</p>
                </div>
                <ul className="space-y-1 text-xs text-surface-200/50">
                  <li>• 说明整体风格（现代、北欧、中式、工业风等）</li>
                  <li>• 描述各房间的功能需求和家具布置</li>
                  <li>• 提及材质偏好（木地板、大理石、地毯等）</li>
                  <li>• 说明灯光氛围（暖色、冷色、自然光等）</li>
                </ul>
              </div>

              <button
                onClick={handleCreateProject}
                disabled={!isStep0Valid || isCreating}
                className={cn(
                  'flex w-full items-center justify-center gap-2 rounded-xl py-3 text-sm font-semibold transition-all',
                  isStep0Valid && !isCreating
                    ? 'bg-primary-500 text-white hover:bg-primary-600'
                    : 'bg-surface-700 text-surface-200/30 cursor-not-allowed',
                )}
              >
                {isCreating ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" />
                    创建中…
                  </>
                ) : (
                  <>
                    下一步：上传 CAD 图纸
                    <ArrowRight className="h-4 w-4" />
                  </>
                )}
              </button>
            </div>
          )}

          {/* ── Step 1: 上传 CAD ── */}
          {step === 1 && (
            <div className="space-y-6 animate-fade-in">
              <div>
                <h2 className="text-xl font-bold text-white">上传 CAD 图纸</h2>
                <p className="mt-1 text-sm text-surface-200/50">
                  上传平面图 CAD 文件，AI 将自动识别墙体、房间、门窗结构
                </p>
              </div>

              <CADUploader
                onFileSelect={handleFileSelect}
                onUpload={handleUpload}
                isUploading={isUploading}
                uploadProgress={uploadProgress}
                uploadedFile={isUploaded ? uploadedFile : null}
                error={uploadMutation.error instanceof Error ? uploadMutation.error.message : null}
              />

              {/* Parse CAD button */}
              {isUploaded && (
                <div className="rounded-xl border border-white/5 bg-surface-800 p-4 space-y-3">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm font-medium text-white">预览识别结果</p>
                      <p className="text-xs text-surface-200/50">
                        触发 CAD 解析，查看墙体、房间识别情况
                      </p>
                    </div>
                    <button
                      onClick={handleParseCAD}
                      disabled={parseMutation.isPending}
                      className="flex items-center gap-2 rounded-xl bg-cyan-500/10 px-4 py-2 text-sm font-medium text-cyan-400 transition-colors hover:bg-cyan-500/20 disabled:opacity-50"
                    >
                      {parseMutation.isPending ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        <Eye className="h-4 w-4" />
                      )}
                      {parseMutation.isPending ? '解析中…' : '解析预览'}
                    </button>
                  </div>

                  {parseMutation.isSuccess && (
                    <button
                      onClick={() => setShowCADPreview(true)}
                      className="flex items-center gap-2 text-xs text-primary-400 hover:text-primary-300 transition-colors"
                    >
                      <CheckCircle2 className="h-3.5 w-3.5" />
                      解析完成，点击查看结果
                    </button>
                  )}
                </div>
              )}

              {/* Action buttons */}
              <div className="flex gap-3">
                <button
                  onClick={() => setStep(0)}
                  className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/5 px-4 py-3 text-sm font-medium text-surface-200/70 transition-colors hover:bg-white/10 hover:text-white"
                >
                  <ArrowLeft className="h-4 w-4" />
                  上一步
                </button>

                <button
                  onClick={handleStartGenerate}
                  disabled={!isUploaded}
                  className={cn(
                    'flex flex-1 items-center justify-center gap-2 rounded-xl py-3 text-sm font-semibold transition-all',
                    isUploaded
                      ? 'bg-primary-500 text-white hover:bg-primary-600'
                      : 'bg-surface-700 text-surface-200/30 cursor-not-allowed',
                  )}
                >
                  <Sparkles className="h-4 w-4" />
                  开始 AI 生成
                </button>
              </div>

              <p className="text-center text-xs text-surface-200/30">
                上传 CAD 后即可开始生成，解析步骤可选
              </p>
            </div>
          )}
        </div>
      </div>

      {/* CAD Preview Modal */}
      {showCADPreview && createdProjectId && (
        <CADPreviewModal
          projectId={createdProjectId}
          onClose={() => setShowCADPreview(false)}
        />
      )}
    </div>
  )
}
