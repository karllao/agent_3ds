import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Plus,
  RefreshCw,
  Search,
  FolderOpen,
  AlertCircle,
  Loader2,
  X,
  Trash2,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import { ProjectCard } from '@/components/project/ProjectCard'
import { useProjects, useDeleteProject } from '@/hooks/useProject'
import { useProjectStore } from '@/store/projectStore'
import type { Project } from '@/types'

// ─── Confirm Delete Dialog ────────────────────────────────────────────────────

function ConfirmDeleteDialog({
  project,
  onConfirm,
  onCancel,
  isDeleting,
}: {
  project: Project
  onConfirm: () => void
  onCancel: () => void
  isDeleting: boolean
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onCancel}
      />

      {/* Dialog */}
      <div className="relative w-full max-w-md rounded-2xl border border-white/10 bg-surface-800 p-6 shadow-card-lg animate-slide-up">
        <button
          onClick={onCancel}
          className="absolute right-4 top-4 rounded-lg p-1.5 text-surface-200/40 transition-colors hover:bg-white/5 hover:text-white"
        >
          <X className="h-4 w-4" />
        </button>

        <div className="flex items-center gap-3 mb-4">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-red-500/10">
            <Trash2 className="h-5 w-5 text-red-400" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-white">删除项目</h3>
            <p className="text-xs text-surface-200/50">此操作不可撤销</p>
          </div>
        </div>

        <p className="text-sm text-surface-200/70 mb-6">
          确定要删除项目{' '}
          <span className="font-semibold text-white">「{project.name}」</span>
          {' '}吗？所有相关文件和数据将被永久删除。
        </p>

        <div className="flex gap-3">
          <button
            onClick={onCancel}
            className="flex-1 rounded-xl border border-white/10 bg-white/5 px-4 py-2.5 text-sm font-medium text-surface-200/70 transition-colors hover:bg-white/10 hover:text-white"
          >
            取消
          </button>
          <button
            onClick={onConfirm}
            disabled={isDeleting}
            className="flex flex-1 items-center justify-center gap-2 rounded-xl bg-red-500/20 px-4 py-2.5 text-sm font-medium text-red-400 transition-colors hover:bg-red-500/30 disabled:opacity-50"
          >
            {isDeleting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                删除中…
              </>
            ) : (
              <>
                <Trash2 className="h-4 w-4" />
                确认删除
              </>
            )}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Main Page ────────────────────────────────────────────────────────────────

export function ProjectListPage() {
  const navigate = useNavigate()
  const { data: projects, isLoading, isError, error, refetch } = useProjects()
  const deleteMutation = useDeleteProject()
  const { addNotification } = useProjectStore()

  const [searchQuery, setSearchQuery] = useState('')
  const [projectToDelete, setProjectToDelete] = useState<Project | null>(null)

  const filteredProjects = (projects ?? []).filter((p) =>
    p.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
    p.user_description?.toLowerCase().includes(searchQuery.toLowerCase()),
  )

  const handleDeleteConfirm = async () => {
    if (!projectToDelete) return
    try {
      await deleteMutation.mutateAsync(projectToDelete.id)
      addNotification({
        type: 'success',
        title: '项目已删除',
        message: `「${projectToDelete.name}」已成功删除`,
      })
      setProjectToDelete(null)
    } catch (err) {
      addNotification({
        type: 'error',
        title: '删除失败',
        message: err instanceof Error ? err.message : '请稍后重试',
      })
    }
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <header className="flex h-16 shrink-0 items-center justify-between border-b border-white/5 px-6">
        <div>
          <h1 className="text-lg font-bold text-white">我的项目</h1>
          <p className="text-xs text-surface-200/40">
            {projects ? `共 ${projects.length} 个项目` : '加载中…'}
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => refetch()}
            className="flex h-9 w-9 items-center justify-center rounded-xl border border-white/10 bg-white/5 text-surface-200/50 transition-colors hover:bg-white/10 hover:text-white"
            title="刷新"
          >
            <RefreshCw className={cn('h-4 w-4', isLoading && 'animate-spin')} />
          </button>

          <button
            onClick={() => navigate('/projects/new')}
            className="flex items-center gap-2 rounded-xl bg-primary-500 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-primary-600"
          >
            <Plus className="h-4 w-4" />
            新建项目
          </button>
        </div>
      </header>

      {/* Search */}
      <div className="shrink-0 border-b border-white/5 px-6 py-3">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-surface-200/30" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="搜索项目名称或描述…"
            className="w-full rounded-xl border border-white/10 bg-surface-800 py-2 pl-9 pr-4 text-sm text-white placeholder-surface-200/30 outline-none transition-colors focus:border-primary-500/50"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-surface-200/40 hover:text-white"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-6">
        {isLoading ? (
          <div className="flex h-64 items-center justify-center">
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="h-8 w-8 animate-spin text-primary-400" />
              <p className="text-sm text-surface-200/50">加载项目列表…</p>
            </div>
          </div>
        ) : isError ? (
          <div className="flex h-64 flex-col items-center justify-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-red-500/10">
              <AlertCircle className="h-7 w-7 text-red-400" />
            </div>
            <div className="text-center">
              <p className="text-sm font-medium text-white">加载失败</p>
              <p className="mt-1 text-xs text-surface-200/50">
                {error instanceof Error ? error.message : '请检查后端服务是否正常运行'}
              </p>
            </div>
            <button
              onClick={() => refetch()}
              className="flex items-center gap-2 rounded-xl bg-white/5 px-4 py-2 text-sm text-surface-200/70 transition-colors hover:bg-white/10 hover:text-white"
            >
              <RefreshCw className="h-4 w-4" />
              重试
            </button>
          </div>
        ) : filteredProjects.length === 0 ? (
          <div className="flex h-64 flex-col items-center justify-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-surface-700/50">
              <FolderOpen className="h-7 w-7 text-surface-200/30" />
            </div>
            <div className="text-center">
              <p className="text-sm font-medium text-white">
                {searchQuery ? '未找到匹配的项目' : '还没有项目'}
              </p>
              <p className="mt-1 text-xs text-surface-200/40">
                {searchQuery
                  ? '尝试修改搜索关键词'
                  : '点击「新建项目」开始你的第一个 3D 室内设计'}
              </p>
            </div>
            {!searchQuery && (
              <button
                onClick={() => navigate('/projects/new')}
                className="flex items-center gap-2 rounded-xl bg-primary-500/20 px-4 py-2 text-sm font-medium text-primary-400 transition-colors hover:bg-primary-500/30"
              >
                <Plus className="h-4 w-4" />
                新建第一个项目
              </button>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {filteredProjects.map((project) => (
              <ProjectCard
                key={project.id}
                project={project}
                onDelete={setProjectToDelete}
              />
            ))}
          </div>
        )}
      </div>

      {/* Delete dialog */}
      {projectToDelete && (
        <ConfirmDeleteDialog
          project={projectToDelete}
          onConfirm={handleDeleteConfirm}
          onCancel={() => setProjectToDelete(null)}
          isDeleting={deleteMutation.isPending}
        />
      )}
    </div>
  )
}
