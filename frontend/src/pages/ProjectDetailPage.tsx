import { useState, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  ArrowLeft,
  Download,
  Sparkles,
  MessageSquare,
  Loader2,
  AlertCircle,
  RefreshCw,
  Send,
  Info,
  Calendar,
  FileBox,
} from 'lucide-react'
import { cn, formatDate, isProjectBusy } from '@/lib/utils'
import { StatusBadge } from '@/components/project/StatusBadge'
import { ProgressTimeline } from '@/components/project/ProgressTimeline'
import { SceneViewer } from '@/components/viewer/SceneViewer'
import { ChatPanel } from '@/components/chat/ChatPanel'
import { useProjectDetail, useSceneJSON, useGenerateScene, useAnswerQuestion } from '@/hooks/useProject'
import { useJobPolling } from '@/hooks/useJobPolling'
import { useProjectStore } from '@/store/projectStore'
import { downloadMaxFile } from '@/api/projects'
import type { Job } from '@/types'

// ─── Generate Panel ───────────────────────────────────────────────────────────

function GeneratePanel({
  projectId,
  description,
  onGenerate,
  isGenerating,
}: {
  projectId: number
  description: string | null
  onGenerate: (desc: string) => void
  isGenerating: boolean
}) {
  const [desc, setDesc] = useState(description ?? '')

  return (
    <div className="rounded-xl border border-white/5 bg-surface-800 p-4 space-y-3">
      <div className="flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-primary-400" />
        <p className="text-sm font-medium text-white">AI 生成方案</p>
      </div>
      <textarea
        value={desc}
        onChange={(e) => setDesc(e.target.value)}
        placeholder="描述你的设计需求（可修改）…"
        rows={3}
        className="w-full resize-none rounded-xl border border-white/10 bg-surface-900 px-3 py-2 text-sm text-white placeholder-surface-200/30 outline-none transition-colors focus:border-primary-500/50"
      />
      <button
        onClick={() => onGenerate(desc)}
        disabled={isGenerating || !desc.trim()}
        className={cn(
          'flex w-full items-center justify-center gap-2 rounded-xl py-2.5 text-sm font-semibold transition-all',
          !isGenerating && desc.trim()
            ? 'bg-primary-500 text-white hover:bg-primary-600'
            : 'bg-surface-700 text-surface-200/30 cursor-not-allowed',
        )}
      >
        {isGenerating ? (
          <>
            <Loader2 className="h-4 w-4 animate-spin" />
            生成中…
          </>
        ) : (
          <>
            <Sparkles className="h-4 w-4" />
            开始生成
          </>
        )}
      </button>
    </div>
  )
}

// ─── Job Progress Bar ─────────────────────────────────────────────────────────

function JobProgressBar({ progress, step }: { progress: number; step: string }) {
  return (
    <div className="rounded-xl border border-primary-500/20 bg-primary-500/5 p-4 space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Loader2 className="h-4 w-4 animate-spin text-primary-400" />
          <p className="text-sm font-medium text-primary-400">{step}</p>
        </div>
        <span className="text-xs text-primary-400/70">{progress}%</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-surface-700">
        <div
          className="h-full rounded-full bg-primary-500 transition-all duration-500"
          style={{ width: `${progress}%` }}
        />
      </div>
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>()
  const projectId = Number(id)
  const navigate = useNavigate()
  const { addNotification, latestJob, pendingQuestion, setPendingQuestion } =
    useProjectStore()

  const [activeJobId, setActiveJobId] = useState<number | null>(null)
  const [showChat, setShowChat] = useState(false)

  const {
    data: project,
    isLoading,
    isError,
    error,
    refetch,
  } = useProjectDetail(projectId)

  const { data: sceneData, isLoading: isSceneLoading } = useSceneJSON(
    projectId,
    project?.status === 'completed' || project?.status === 'generated',
  )

  const generateMutation = useGenerateScene(projectId)
  const answerMutation = useAnswerQuestion(projectId)

  // Job polling
  useJobPolling({
    jobId: activeJobId,
    projectId,
    onComplete: (job: Job) => {
      addNotification({
        type: 'success',
        title: '任务完成',
        message: `步骤「${job.step}」已完成`,
      })
      setActiveJobId(null)
      refetch()
    },
    onFailed: (job: Job) => {
      addNotification({
        type: 'error',
        title: '任务失败',
        message: job.error_message ?? '请查看详情',
      })
      setActiveJobId(null)
    },
    onWaitingUser: () => {
      setShowChat(true)
    },
  })

  const handleGenerate = useCallback(
    async (description: string) => {
      try {
        const job = await generateMutation.mutateAsync(description)
        setActiveJobId(job.id)
        addNotification({
          type: 'info',
          title: 'AI 生成已启动',
          message: '正在分析设计需求…',
        })
      } catch (err) {
        addNotification({
          type: 'error',
          title: '启动失败',
          message: err instanceof Error ? err.message : '请重试',
        })
      }
    },
    [generateMutation, addNotification],
  )

  const handleAnswer = useCallback(
    async (answer: string) => {
      try {
        const job = await answerMutation.mutateAsync(answer)
        setActiveJobId(job.id)
        setPendingQuestion(null)
      } catch (err) {
        addNotification({
          type: 'error',
          title: '提交失败',
          message: err instanceof Error ? err.message : '请重试',
        })
      }
    },
    [answerMutation, addNotification, setPendingQuestion],
  )

  const handleDownload = async () => {
    try {
      await downloadMaxFile(projectId)
      addNotification({ type: 'success', title: '下载已开始' })
    } catch (err) {
      addNotification({
        type: 'error',
        title: '下载失败',
        message: err instanceof Error ? err.message : '请重试',
      })
    }
  }

  // ── Loading / Error ──────────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="h-8 w-8 animate-spin text-primary-400" />
          <p className="text-sm text-surface-200/50">加载项目…</p>
        </div>
      </div>
    )
  }

  if (isError || !project) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-4">
        <AlertCircle className="h-10 w-10 text-red-400" />
        <p className="text-sm text-white">
          {error instanceof Error ? error.message : '项目不存在'}
        </p>
        <button
          onClick={() => navigate('/projects')}
          className="flex items-center gap-2 rounded-xl bg-white/5 px-4 py-2 text-sm text-surface-200/70 hover:bg-white/10 hover:text-white transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          返回列表
        </button>
      </div>
    )
  }

  const isBusy = isProjectBusy(project.status) || !!activeJobId
  const isCompleted = project.status === 'completed'
  const canGenerate =
    (project.status === 'cad_uploaded' || project.status === 'parsed') && !isBusy
  const hasFailed = project.status === 'failed'

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <header className="flex h-16 shrink-0 items-center gap-4 border-b border-white/5 px-6">
        <button
          onClick={() => navigate('/projects')}
          className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-surface-200/50 transition-colors hover:bg-white/10 hover:text-white"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>

        <div className="flex flex-1 items-center gap-3 min-w-0">
          <h1 className="truncate text-lg font-bold text-white">{project.name}</h1>
          <StatusBadge status={project.status} />
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowChat(!showChat)}
            className={cn(
              'flex items-center gap-2 rounded-xl px-3 py-2 text-sm font-medium transition-colors',
              showChat
                ? 'bg-primary-500/20 text-primary-400'
                : 'bg-white/5 text-surface-200/50 hover:bg-white/10 hover:text-white',
            )}
          >
            <MessageSquare className="h-4 w-4" />
            对话
          </button>

          <button
            onClick={() => refetch()}
            className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-surface-200/50 transition-colors hover:bg-white/10 hover:text-white"
            title="刷新"
          >
            <RefreshCw className="h-4 w-4" />
          </button>

          {isCompleted && (
            <button
              onClick={handleDownload}
              className="flex items-center gap-2 rounded-xl bg-green-500/20 px-4 py-2 text-sm font-medium text-green-400 transition-colors hover:bg-green-500/30"
            >
              <Download className="h-4 w-4" />
              下载 .max
            </button>
          )}
        </div>
      </header>

      {/* Main content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left panel: Info + Timeline */}
        <aside className="flex w-72 shrink-0 flex-col gap-4 overflow-y-auto border-r border-white/5 p-4">
          {/* Project info */}
          <div className="rounded-xl border border-white/5 bg-surface-800 p-4 space-y-3">
            <div className="flex items-center gap-2">
              <FileBox className="h-4 w-4 text-surface-200/40" />
              <p className="text-xs font-medium text-surface-200/50">项目信息</p>
            </div>

            {project.user_description && (
              <p className="text-xs text-surface-200/60 leading-relaxed">
                {project.user_description}
              </p>
            )}

            <div className="flex items-center gap-1.5 text-xs text-surface-200/30">
              <Calendar className="h-3 w-3" />
              <span>创建于 {formatDate(project.created_at)}</span>
            </div>

            {project.cad_file_path && (
              <div className="flex items-center gap-1.5 text-xs text-surface-200/40">
                <Info className="h-3 w-3" />
                <span className="truncate">
                  {project.cad_file_path.split('/').pop() ?? 'CAD 文件'}
                </span>
              </div>
            )}
          </div>

          {/* Job progress */}
          {latestJob && isBusy && (
            <JobProgressBar
              progress={latestJob.progress}
              step={latestJob.step}
            />
          )}

          {/* Failed message */}
          {hasFailed && (
            <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-4">
              <div className="flex items-center gap-2 mb-2">
                <AlertCircle className="h-4 w-4 text-red-400" />
                <p className="text-sm font-medium text-red-400">生成失败</p>
              </div>
              <p className="text-xs text-red-400/70">
                请检查 CAD 文件格式或修改描述后重试
              </p>
            </div>
          )}

          {/* Generate panel */}
          {canGenerate && (
            <GeneratePanel
              projectId={projectId}
              description={project.user_description}
              onGenerate={handleGenerate}
              isGenerating={generateMutation.isPending}
            />
          )}

          {/* Retry after failure */}
          {hasFailed && (
            <GeneratePanel
              projectId={projectId}
              description={project.user_description}
              onGenerate={handleGenerate}
              isGenerating={generateMutation.isPending}
            />
          )}

          {/* Progress timeline */}
          <div className="rounded-xl border border-white/5 bg-surface-800 p-4">
            <p className="mb-4 text-xs font-medium text-surface-200/50">生成进度</p>
            <ProgressTimeline status={project.status} />
          </div>
        </aside>

        {/* Center: 3D Viewer */}
        <div className="relative flex flex-1 flex-col overflow-hidden">
          <SceneViewer
            sceneData={sceneData}
            isLoading={isSceneLoading}
            className="flex-1"
          />

          {/* Overlay: waiting for user */}
          {pendingQuestion && (
            <div className="absolute inset-x-0 bottom-0 flex items-end justify-center p-4">
              <div className="w-full max-w-lg rounded-2xl border border-amber-500/20 bg-surface-800/95 p-4 backdrop-blur-sm shadow-card-lg">
                <div className="flex items-start gap-3">
                  <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-amber-500/10">
                    <MessageSquare className="h-4 w-4 text-amber-400" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-medium text-amber-400 mb-1">Agent 追问</p>
                    <p className="text-sm text-white">{pendingQuestion}</p>
                  </div>
                </div>
                <button
                  onClick={() => setShowChat(true)}
                  className="mt-3 flex w-full items-center justify-center gap-2 rounded-xl bg-amber-500/10 py-2 text-sm font-medium text-amber-400 transition-colors hover:bg-amber-500/20"
                >
                  <Send className="h-4 w-4" />
                  回答问题
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Right panel: Chat */}
        {showChat && (
          <aside className="flex w-80 shrink-0 flex-col border-l border-white/5">
            <div className="flex h-12 shrink-0 items-center justify-between border-b border-white/5 px-4">
              <p className="text-sm font-medium text-white">AI 对话</p>
              <button
                onClick={() => setShowChat(false)}
                className="text-xs text-surface-200/40 hover:text-white transition-colors"
              >
                收起
              </button>
            </div>
            <ChatPanel
              projectId={projectId}
              pendingQuestion={pendingQuestion}
              onAnswer={handleAnswer}
              className="flex-1 overflow-hidden"
            />
          </aside>
        )}
      </div>
    </div>
  )
}
