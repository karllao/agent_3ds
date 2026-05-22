import { Bot, User } from 'lucide-react'
import { cn, formatDate } from '@/lib/utils'
import type { ChatMessage } from '@/types'

interface MessageBubbleProps {
  message: ChatMessage
  isLatest?: boolean
}

export function MessageBubble({ message, isLatest = false }: MessageBubbleProps) {
  const isUser = message.role === 'user'
  const isSystem = message.role === 'system'

  if (isSystem) {
    return (
      <div className="flex justify-center py-2">
        <span className="rounded-full bg-surface-700/50 px-3 py-1 text-xs text-surface-200/40">
          {message.content}
        </span>
      </div>
    )
  }

  return (
    <div
      className={cn(
        'flex gap-3 animate-slide-up',
        isUser ? 'flex-row-reverse' : 'flex-row',
      )}
    >
      {/* Avatar */}
      <div
        className={cn(
          'flex h-8 w-8 shrink-0 items-center justify-center rounded-full',
          isUser ? 'bg-primary-500/20' : 'bg-surface-700',
        )}
      >
        {isUser ? (
          <User className="h-4 w-4 text-primary-400" />
        ) : (
          <Bot className="h-4 w-4 text-surface-200/60" />
        )}
      </div>

      {/* Bubble */}
      <div className={cn('flex max-w-[80%] flex-col gap-1', isUser && 'items-end')}>
        <div
          className={cn(
            'rounded-2xl px-4 py-3 text-sm leading-relaxed',
            isUser
              ? 'rounded-tr-sm bg-primary-500/20 text-white'
              : 'rounded-tl-sm bg-surface-700/60 text-surface-200/90',
            isLatest && !isUser && 'border border-primary-500/20',
          )}
        >
          {/* Render newlines */}
          {message.content.split('\n').map((line, i) => (
            <span key={i}>
              {line}
              {i < message.content.split('\n').length - 1 && <br />}
            </span>
          ))}
        </div>

        {message.timestamp && (
          <span className="text-[10px] text-surface-200/30">
            {formatDate(message.timestamp)}
          </span>
        )}
      </div>
    </div>
  )
}

// ─── Typing Indicator ─────────────────────────────────────────────────────────

export function TypingIndicator() {
  return (
    <div className="flex gap-3">
      <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface-700">
        <Bot className="h-4 w-4 text-surface-200/60" />
      </div>
      <div className="flex items-center gap-1.5 rounded-2xl rounded-tl-sm bg-surface-700/60 px-4 py-3">
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-surface-200/40 [animation-delay:0ms]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-surface-200/40 [animation-delay:150ms]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-surface-200/40 [animation-delay:300ms]" />
      </div>
    </div>
  )
}
