import { Outlet } from 'react-router-dom'
import { useEffect } from 'react'
import { Sidebar } from './Sidebar'
import { useProjectStore } from '@/store/projectStore'
import { cn } from '@/lib/utils'
import { X, CheckCircle2, AlertCircle, Info, AlertTriangle } from 'lucide-react'
import type { Notification } from '@/types'

// ─── Notification Toast ───────────────────────────────────────────────────────

function NotificationToast({ notification, onClose }: {
  notification: Notification
  onClose: () => void
}) {
  useEffect(() => {
    const duration = notification.duration ?? 4000
    const timer = setTimeout(onClose, duration)
    return () => clearTimeout(timer)
  }, [notification.duration, onClose])

  const icons = {
    success: <CheckCircle2 className="h-4 w-4 text-green-400" />,
    error:   <AlertCircle className="h-4 w-4 text-red-400" />,
    warning: <AlertTriangle className="h-4 w-4 text-amber-400" />,
    info:    <Info className="h-4 w-4 text-blue-400" />,
  }

  const borders = {
    success: 'border-green-500/20',
    error:   'border-red-500/20',
    warning: 'border-amber-500/20',
    info:    'border-blue-500/20',
  }

  return (
    <div
      className={cn(
        'flex items-start gap-3 rounded-xl border bg-surface-800 p-4 shadow-card-lg animate-slide-up',
        borders[notification.type],
      )}
    >
      <div className="shrink-0 mt-0.5">{icons[notification.type]}</div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-white">{notification.title}</p>
        {notification.message && (
          <p className="mt-0.5 text-xs text-surface-200/60">{notification.message}</p>
        )}
      </div>
      <button
        onClick={onClose}
        className="shrink-0 rounded-lg p-1 text-surface-200/40 transition-colors hover:bg-white/5 hover:text-white"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  )
}

// ─── App Layout ───────────────────────────────────────────────────────────────

export function AppLayout() {
  const { notifications, removeNotification } = useProjectStore()

  return (
    <div className="flex h-screen overflow-hidden bg-surface-900">
      <Sidebar />

      {/* Main content */}
      <main className="flex flex-1 flex-col overflow-hidden">
        <Outlet />
      </main>

      {/* Notification stack */}
      {notifications.length > 0 && (
        <div className="fixed bottom-6 right-6 z-50 flex flex-col gap-2 w-80">
          {notifications.map((n) => (
            <NotificationToast
              key={n.id}
              notification={n}
              onClose={() => removeNotification(n.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
