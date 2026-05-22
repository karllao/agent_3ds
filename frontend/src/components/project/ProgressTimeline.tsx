import { CheckCircle2, Circle, Loader2, XCircle, Clock } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { ProjectStatus } from '@/types'

interface TimelineStep {
  id: string
  label: string
  description: string
  statuses: ProjectStatus[]
  activeStatuses: ProjectStatus[]
  completedStatuses: ProjectStatus[]
}

const TIMELINE_STEPS: TimelineStep[] = [
  {
    id:               'upload',
    label:            '上传 CAD',
    description:      '上传 DXF/DWG 图纸文件',
    statuses:         ['created', 'cad_uploaded'],
    activeStatuses:   ['created'],
    completedStatuses: ['cad_uploaded', 'parsing', 'parsed', 'generating', 'generated', 'exporting', 'completed'],
  },
  {
    id:               'parse',
    label:            '解析图纸',
    description:      '识别墙体、房间、门窗结构',
    statuses:         ['parsing', 'parsed'],
    activeStatuses:   ['parsing'],
    completedStatuses: ['parsed', 'generating', 'generated', 'exporting', 'completed'],
  },
  {
    id:               'generate',
    label:            'AI 生成方案',
    description:      '根据描述生成室内设计方案',
    statuses:         ['generating', 'generated'],
    activeStatuses:   ['generating'],
    completedStatuses: ['generated', 'exporting', 'completed'],
  },
  {
    id:               'export',
    label:            '3ds Max 建模',
    description:      '生成专业 3D 场景文件',
    statuses:         ['exporting'],
    activeStatuses:   ['exporting'],
    completedStatuses: ['completed'],
  },
  {
    id:               'done',
    label:            '完成',
    description:      '下载 .max 文件',
    statuses:         ['completed'],
    activeStatuses:   [],
    completedStatuses: ['completed'],
  },
]

interface ProgressTimelineProps {
  status: ProjectStatus
  className?: string
}

type StepState = 'completed' | 'active' | 'pending' | 'failed'

function getStepState(step: TimelineStep, status: ProjectStatus): StepState {
  if (status === 'failed') {
    if (step.activeStatuses.some((s) => s === status)) return 'failed'
    if (step.completedStatuses.includes(status)) return 'completed'
    return 'pending'
  }
  if (step.completedStatuses.includes(status)) return 'completed'
  if (step.activeStatuses.includes(status)) return 'active'
  return 'pending'
}

export function ProgressTimeline({ status, className }: ProgressTimelineProps) {
  return (
    <div className={cn('space-y-0', className)}>
      {TIMELINE_STEPS.map((step, index) => {
        const state = getStepState(step, status)
        const isLast = index === TIMELINE_STEPS.length - 1

        return (
          <div key={step.id} className="flex gap-3">
            {/* Icon + Line */}
            <div className="flex flex-col items-center">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center">
                {state === 'completed' && (
                  <CheckCircle2 className="h-6 w-6 text-green-400" />
                )}
                {state === 'active' && (
                  <Loader2 className="h-6 w-6 animate-spin text-primary-400" />
                )}
                {state === 'pending' && (
                  <Circle className="h-6 w-6 text-surface-700" />
                )}
                {state === 'failed' && (
                  <XCircle className="h-6 w-6 text-red-400" />
                )}
              </div>
              {!isLast && (
                <div
                  className={cn(
                    'mt-1 w-0.5 flex-1 min-h-[24px]',
                    state === 'completed' ? 'bg-green-400/40' : 'bg-surface-700',
                  )}
                />
              )}
            </div>

            {/* Content */}
            <div className={cn('pb-6', isLast && 'pb-0')}>
              <p
                className={cn(
                  'text-sm font-medium leading-8',
                  state === 'completed' && 'text-green-400',
                  state === 'active' && 'text-primary-400',
                  state === 'pending' && 'text-surface-200/40',
                  state === 'failed' && 'text-red-400',
                )}
              >
                {step.label}
              </p>
              <p
                className={cn(
                  'text-xs leading-relaxed',
                  state === 'pending' ? 'text-surface-200/25' : 'text-surface-200/50',
                )}
              >
                {step.description}
              </p>
              {state === 'active' && (
                <div className="mt-2 flex items-center gap-1.5">
                  <Clock className="h-3 w-3 text-primary-400/70" />
                  <span className="text-xs text-primary-400/70">处理中，请稍候…</span>
                </div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}
