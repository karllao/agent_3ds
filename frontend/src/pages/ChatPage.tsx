import { useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, Loader2, AlertCircle, ExternalLink } from 'lucide-react'
import { StatusBadge } from '@/components/project/StatusBadge'
import { ChatPanel } from '@/components/chat/ChatPanel'
import { useProjectDetail, useAnswerQuestion } from '@/hooks/useProject'
import { useJobPolling } from '@/hooks/useJobPolling'
import { useProjectStore } from '@/store/projectStore'
import { JOB_STATUS_LABELS } from '@/lib/utils'
import type { Job } from '@/types'
import { useState } from 'react'

export function ChatPage() {
  const { id } = useParams<{ id: string }>()
  const projectId = Number(id)
  const navigate = useNavigate()
  const { addNotification, latestJob, pendingQuestion, setPendingQuestion } =
    useProjectStore()

  const [activeJobId, setActiveJobId] = useState<number | null>(null)

  const { data: project, isLoading, isError, error } = useProjectDetail(projectId)
  const answerMutation = useAnswerQuestion(projectId)

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
    },
    onFailed: (job: Job) => {
      addNotification({
        type: 'error',
        title: '任务失败',
        message: job.error_message ?? '请查看详情',
      })
      setActiveJobId(null)
    },
  })

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

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary-400" />
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

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <header className="flex h-16 shrink-0 items-center gap-4 border-b border-white/5 px-6">
        <button
          onClick={() => navigate(`/projects/${projectId}`)}
          className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-surface-200/50 transition-colors hover:bg-white/10 hover:text-white"
        >
          <ArrowLeft className="h-4 w-4" />
        </button>

        <div className="flex flex-1 items-center gap-3 min-w-0">
          <div className="min-w-0">
            <h1 className="truncate text-sm font-bold text-white">{project.name}</h1>
            <p className="text-xs text-surface-200/40">AI 对话</p>
          </div>
          <StatusBadge status={project.status} size="sm" />
        </div>

        {/* Job status */}
        {latestJob && activeJobId && (
          <div className="flex items-center gap-2 rounded-xl bg-primary-500/10 px-3 py-1.5">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-primary-400" />
            <span className="text-xs text-primary-400">
              {JOB_STATUS_LABELS[latestJob.status]} · {latestJob.progress}%
            </span>
          </div>
        )}

        <button
          onClick={() => navigate(`/projects/${projectId}`)}
          className="flex items-center gap-2 rounded-xl bg-white/5 px-3 py-2 text-sm text-surface-200/50 transition-colors hover:bg-white/10 hover:text-white"
        >
          <ExternalLink className="h-4 w-4" />
          查看详情
        </button>
      </header>

      {/* Chat */}
      <ChatPanel
        projectId={projectId}
        pendingQuestion={pendingQuestion}
        onAnswer={handleAnswer}
        className="flex-1 overflow-hidden"
      />
    </div>
  )
}
