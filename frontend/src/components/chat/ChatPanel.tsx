import { useState, useRef, useEffect, useCallback } from 'react'
import { Send, AlertCircle } from 'lucide-react'
import { cn } from '@/lib/utils'
import { MessageBubble, TypingIndicator } from './MessageBubble'
import { sendChatMessage } from '@/api/projects'
import type { ChatMessage } from '@/types'

interface ChatPanelProps {
  projectId: number
  pendingQuestion?: string | null
  onAnswer?: (answer: string) => void
  className?: string
  initialMessages?: ChatMessage[]
}

export function ChatPanel({
  projectId,
  pendingQuestion,
  onAnswer,
  className,
  initialMessages = [],
}: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>(() => {
    const msgs: ChatMessage[] = []
    if (initialMessages.length > 0) {
      msgs.push(...initialMessages)
    } else {
      msgs.push({
        role: 'assistant',
        content: '你好！我是 Agent 3DS，你的 AI 室内设计助手。\n\n请告诉我你的设计需求，或者上传 CAD 图纸开始生成 3D 场景。',
        timestamp: new Date().toISOString(),
      })
    }
    return msgs
  })

  const [input, setInput] = useState('')
  const [isTyping, setIsTyping] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  // 当 Agent 有追问时，自动添加到消息列表
  useEffect(() => {
    if (pendingQuestion) {
      setMessages((prev) => {
        const alreadyExists = prev.some(
          (m) => m.role === 'assistant' && m.content === pendingQuestion,
        )
        if (alreadyExists) return prev
        return [
          ...prev,
          {
            role: 'assistant',
            content: pendingQuestion,
            timestamp: new Date().toISOString(),
          },
        ]
      })
    }
  }, [pendingQuestion])

  // 滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, isTyping])

  const handleSend = useCallback(async () => {
    const text = input.trim()
    if (!text || isTyping) return

    setInput('')
    setError(null)

    const userMsg: ChatMessage = {
      role: 'user',
      content: text,
      timestamp: new Date().toISOString(),
    }

    setMessages((prev) => [...prev, userMsg])
    setIsTyping(true)

    // 如果是回答 Agent 追问
    if (pendingQuestion) {
      onAnswer?.(text)
      setIsTyping(false)
      return
    }

    // 否则走普通对话
    try {
      const history = messages.map((m) => ({ role: m.role, content: m.content }))
      const response = await sendChatMessage({
        project_id: projectId,
        message: text,
        history,
      })

      setMessages((prev) => [
        ...prev,
        {
          role: response.role as ChatMessage['role'],
          content: response.message,
          timestamp: new Date().toISOString(),
        },
      ])
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : '发送失败，请重试'
      setError(errMsg)
    } finally {
      setIsTyping(false)
    }
  }, [input, isTyping, messages, pendingQuestion, projectId, onAnswer])

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className={cn('flex flex-col', className)}>
      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-4 p-4 scrollbar-thin scrollbar-track-transparent scrollbar-thumb-surface-700">
        {messages.map((msg, i) => (
          <MessageBubble
            key={i}
            message={msg}
            isLatest={i === messages.length - 1 && msg.role === 'assistant'}
          />
        ))}

        {isTyping && <TypingIndicator />}

        {error && (
          <div className="flex items-center gap-2 rounded-lg bg-red-500/10 px-3 py-2">
            <AlertCircle className="h-4 w-4 shrink-0 text-red-400" />
            <p className="text-xs text-red-400">{error}</p>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Pending question indicator */}
      {pendingQuestion && (
        <div className="mx-4 mb-2 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2">
          <p className="text-xs text-amber-400">
            ⚡ Agent 正在等待你的回答
          </p>
        </div>
      )}

      {/* Input */}
      <div className="border-t border-white/5 p-4">
        <div className="flex items-end gap-3 rounded-xl border border-white/10 bg-surface-900 p-3 focus-within:border-primary-500/50 transition-colors">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              pendingQuestion
                ? '输入你的回答…'
                : '描述你的设计需求，或提问…（Shift+Enter 换行）'
            }
            rows={1}
            className="flex-1 resize-none bg-transparent text-sm text-white placeholder-surface-200/30 outline-none"
            style={{ maxHeight: '120px', overflowY: 'auto' }}
            onInput={(e) => {
              const el = e.currentTarget
              el.style.height = 'auto'
              el.style.height = `${Math.min(el.scrollHeight, 120)}px`
            }}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || isTyping}
            className={cn(
              'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg transition-all',
              input.trim() && !isTyping
                ? 'bg-primary-500 text-white hover:bg-primary-600'
                : 'bg-surface-700 text-surface-200/30 cursor-not-allowed',
            )}
          >
            <Send className="h-4 w-4" />
          </button>
        </div>
        <p className="mt-1.5 text-center text-[10px] text-surface-200/20">
          Enter 发送 · Shift+Enter 换行
        </p>
      </div>
    </div>
  )
}
