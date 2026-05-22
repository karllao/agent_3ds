import { useEffect, useRef, useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { getJob } from '@/api/jobs'
import { getProject } from '@/api/projects'
import { useProjectStore } from '@/store/projectStore'
import { isJobTerminal } from '@/lib/utils'
import type { Job } from '@/types'

interface UseJobPollingOptions {
  jobId: number | null
  projectId?: number
  intervalMs?: number
  onComplete?: (job: Job) => void
  onFailed?: (job: Job) => void
  onWaitingUser?: (job: Job) => void
}

export function useJobPolling({
  jobId,
  projectId,
  intervalMs = 3000,
  onComplete,
  onFailed,
  onWaitingUser,
}: UseJobPollingOptions) {
  const queryClient = useQueryClient()
  const { setLatestJob, setActiveJobId, updateCurrentProject, setPendingQuestion } =
    useProjectStore()

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const isMountedRef = useRef(true)

  const stopPolling = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const poll = useCallback(async () => {
    if (!jobId || !isMountedRef.current) return

    try {
      const job = await getJob(jobId)

      if (!isMountedRef.current) return

      setLatestJob(job)

      // 如果 Agent 在等待用户输入
      if (job.status === 'waiting_user') {
        const question =
          (job.result as Record<string, string> | null)?.question ?? '请提供更多信息'
        setPendingQuestion(question)
        onWaitingUser?.(job)
        // 继续轮询，等待用户回答后状态变化
        timerRef.current = setTimeout(poll, intervalMs)
        return
      }

      // 刷新项目数据
      if (projectId) {
        const updatedProject = await getProject(projectId)
        if (isMountedRef.current) {
          updateCurrentProject(updatedProject)
          queryClient.setQueryData(['project', projectId], updatedProject)
          queryClient.invalidateQueries({ queryKey: ['projects'] })
        }
      }

      if (isJobTerminal(job.status)) {
        stopPolling()
        setActiveJobId(null)

        if (job.status === 'completed') {
          setPendingQuestion(null)
          onComplete?.(job)
          if (projectId) {
            queryClient.invalidateQueries({ queryKey: ['project', projectId] })
            queryClient.invalidateQueries({ queryKey: ['scene', projectId] })
          }
        } else if (job.status === 'failed') {
          onFailed?.(job)
        }
      } else {
        timerRef.current = setTimeout(poll, intervalMs)
      }
    } catch (err) {
      console.error('[useJobPolling] 轮询出错:', err)
      if (isMountedRef.current) {
        timerRef.current = setTimeout(poll, intervalMs * 2)
      }
    }
  }, [
    jobId,
    projectId,
    intervalMs,
    onComplete,
    onFailed,
    onWaitingUser,
    setLatestJob,
    setActiveJobId,
    updateCurrentProject,
    setPendingQuestion,
    stopPolling,
    queryClient,
  ])

  useEffect(() => {
    isMountedRef.current = true

    if (jobId) {
      setActiveJobId(jobId)
      poll()
    }

    return () => {
      isMountedRef.current = false
      stopPolling()
    }
  }, [jobId]) // eslint-disable-line react-hooks/exhaustive-deps

  return { stopPolling }
}
