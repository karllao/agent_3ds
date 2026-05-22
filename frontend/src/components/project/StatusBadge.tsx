import { cn, PROJECT_STATUS_LABELS, PROJECT_STATUS_COLORS } from '@/lib/utils'
import type { ProjectStatus } from '@/types'

interface StatusBadgeProps {
  status: ProjectStatus
  className?: string
  showDot?: boolean
  size?: 'sm' | 'md'
}

const PULSING_STATUSES: ProjectStatus[] = ['parsing', 'generating', 'exporting']

export function StatusBadge({
  status,
  className,
  showDot = true,
  size = 'md',
}: StatusBadgeProps) {
  const isPulsing = PULSING_STATUSES.includes(status)

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border font-medium',
        size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-xs',
        PROJECT_STATUS_COLORS[status],
        className,
      )}
    >
      {showDot && (
        <span
          className={cn(
            'h-1.5 w-1.5 rounded-full bg-current',
            isPulsing && 'animate-pulse',
          )}
        />
      )}
      {PROJECT_STATUS_LABELS[status]}
    </span>
  )
}
