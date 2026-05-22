import { NavLink, useNavigate } from 'react-router-dom'
import {
  LayoutGrid,
  PlusCircle,
  Box,
  ChevronLeft,
  ChevronRight,
  Settings,
  HelpCircle,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { useProjectStore } from '@/store/projectStore'

interface NavItem {
  to: string
  icon: React.ElementType
  label: string
  end?: boolean
}

const NAV_ITEMS: NavItem[] = [
  { to: '/projects', icon: LayoutGrid, label: '项目列表', end: true },
  { to: '/projects/new', icon: PlusCircle, label: '新建项目' },
]

export function Sidebar() {
  const { sidebarCollapsed, toggleSidebar } = useProjectStore()
  const navigate = useNavigate()

  return (
    <aside
      className={cn(
        'relative flex h-full flex-col border-r border-white/5 bg-surface-850 transition-all duration-300',
        sidebarCollapsed ? 'w-16' : 'w-60',
      )}
    >
      {/* Logo */}
      <div
        className={cn(
          'flex h-16 shrink-0 cursor-pointer items-center gap-3 border-b border-white/5 px-4',
          sidebarCollapsed && 'justify-center px-0',
        )}
        onClick={() => navigate('/projects')}
      >
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-primary-500/20">
          <Box className="h-4 w-4 text-primary-400" />
        </div>
        {!sidebarCollapsed && (
          <div className="min-w-0">
            <p className="truncate text-sm font-bold text-white">Agent 3DS</p>
            <p className="truncate text-[10px] text-surface-200/40">AI 室内设计平台</p>
          </div>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-1 overflow-y-auto p-2">
        {NAV_ITEMS.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              cn(
                'flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-150',
                isActive
                  ? 'bg-primary-500/15 text-primary-400'
                  : 'text-surface-200/50 hover:bg-white/5 hover:text-white',
                sidebarCollapsed && 'justify-center px-0',
              )
            }
            title={sidebarCollapsed ? item.label : undefined}
          >
            <item.icon className="h-4 w-4 shrink-0" />
            {!sidebarCollapsed && <span className="truncate">{item.label}</span>}
          </NavLink>
        ))}
      </nav>

      {/* Bottom actions */}
      <div className="shrink-0 space-y-1 border-t border-white/5 p-2">
        <button
          className={cn(
            'flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-surface-200/40 transition-colors hover:bg-white/5 hover:text-white',
            sidebarCollapsed && 'justify-center px-0',
          )}
          title={sidebarCollapsed ? '帮助' : undefined}
        >
          <HelpCircle className="h-4 w-4 shrink-0" />
          {!sidebarCollapsed && <span>帮助文档</span>}
        </button>

        <button
          className={cn(
            'flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium text-surface-200/40 transition-colors hover:bg-white/5 hover:text-white',
            sidebarCollapsed && 'justify-center px-0',
          )}
          title={sidebarCollapsed ? '设置' : undefined}
        >
          <Settings className="h-4 w-4 shrink-0" />
          {!sidebarCollapsed && <span>设置</span>}
        </button>
      </div>

      {/* Collapse toggle */}
      <button
        onClick={toggleSidebar}
        className="absolute -right-3 top-20 flex h-6 w-6 items-center justify-center rounded-full border border-white/10 bg-surface-800 text-surface-200/40 shadow-card transition-colors hover:bg-surface-700 hover:text-white"
      >
        {sidebarCollapsed ? (
          <ChevronRight className="h-3 w-3" />
        ) : (
          <ChevronLeft className="h-3 w-3" />
        )}
      </button>
    </aside>
  )
}
