import { create } from 'zustand'
import { devtools } from 'zustand/middleware'
import type { Project, Job, Notification } from '@/types'
import { generateId } from '@/lib/utils'

interface ProjectState {
  // 当前选中的项目
  currentProject: Project | null
  setCurrentProject: (project: Project | null) => void
  updateCurrentProject: (updates: Partial<Project>) => void

  // 活跃的 Job 轮询
  activeJobId: number | null
  setActiveJobId: (jobId: number | null) => void

  // 最新 Job 信息
  latestJob: Job | null
  setLatestJob: (job: Job | null) => void

  // Agent 追问内容
  pendingQuestion: string | null
  setPendingQuestion: (question: string | null) => void

  // 全局通知
  notifications: Notification[]
  addNotification: (notification: Omit<Notification, 'id'>) => void
  removeNotification: (id: string) => void

  // 侧边栏折叠状态
  sidebarCollapsed: boolean
  toggleSidebar: () => void
}

export const useProjectStore = create<ProjectState>()(
  devtools(
    (set) => ({
      // ── Current Project ──────────────────────────────────────────────────
      currentProject: null,
      setCurrentProject: (project) => set({ currentProject: project }),
      updateCurrentProject: (updates) =>
        set((state) => ({
          currentProject: state.currentProject
            ? { ...state.currentProject, ...updates }
            : null,
        })),

      // ── Active Job ───────────────────────────────────────────────────────
      activeJobId: null,
      setActiveJobId: (jobId) => set({ activeJobId: jobId }),

      latestJob: null,
      setLatestJob: (job) => set({ latestJob: job }),

      // ── Pending Question ─────────────────────────────────────────────────
      pendingQuestion: null,
      setPendingQuestion: (question) => set({ pendingQuestion: question }),

      // ── Notifications ────────────────────────────────────────────────────
      notifications: [],
      addNotification: (notification) =>
        set((state) => ({
          notifications: [
            ...state.notifications,
            { ...notification, id: generateId() },
          ],
        })),
      removeNotification: (id) =>
        set((state) => ({
          notifications: state.notifications.filter((n) => n.id !== id),
        })),

      // ── Sidebar ──────────────────────────────────────────────────────────
      sidebarCollapsed: false,
      toggleSidebar: () =>
        set((state) => ({ sidebarCollapsed: !state.sidebarCollapsed })),
    }),
    { name: 'project-store' },
  ),
)
