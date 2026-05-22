import { useNavigate } from 'react-router-dom'
import {
  Trash2,
  ExternalLink,
  Download,
  MessageSquare,
  Calendar,
  FileBox,
} from 'lucide-react'
import { cn, formatRelativeTime } from '@/lib/utils'
import { StatusBadge } from './StatusBadge'
import { downloadMaxFile, getPreviewImageUrl } from '@/api/projects'
import type { Project } from '@/types'

interface ProjectCardProps {
  project: Project
  onDelete: (project: Project) => void
}

export function ProjectCard({ project, onDelete }: ProjectCardProps) {
  const navigate = useNavigate()
  const hasPreview = !!project.preview_image_path
  const isCompleted = project.status === 'completed'
  const isFailed = project.status === 'failed'

  const handleDownload = async (e: React.MouseEvent) => {
    e.stopPropagation()
    try {
      await downloadMaxFile(project.id)
    } catch (err) {
      console.error('下载失败:', err)
    }
  }

  return (
    <div
      onClick={() => navigate(`/projects/${project.id}`)}
      className={cn(
        'group relative flex cursor-pointer flex-col overflow-hidden rounded-2xl border',
        'bg-surface-800 border-white/5 shadow-card',
        'transition-all duration-200 hover:border-primary-500/30 hover:shadow-card-lg hover:-translate-y-0.5',
      )}
    >
      {/* Preview Image / Placeholder */}
      <div className="relative h-40 overflow-hidden bg-surface-900">
        {hasPreview ? (
          <img
            src={getPreviewImageUrl(project.id)}
            alt={project.name}
            className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
          />
        ) : (
          <div className="flex h-full items-center justify-center">
            <FileBox className="h-12 w-12 text-surface-700" />
          </div>
        )}

        {/* Status overlay */}
        <div className="absolute left-3 top-3">
          <StatusBadge status={project.status} size="sm" />
        </div>

        {/* Failed overlay */}
        {isFailed && (
          <div className="absolute inset-0 flex items-center justify-center bg-red-900/20">
            <span className="text-xs text-red-400">生成失败</span>
          </div>
        )}
      </div>

      {/* Content */}
      <div className="flex flex-1 flex-col gap-3 p-4">
        <div>
          <h3 className="truncate text-sm font-semibold text-white group-hover:text-primary-300 transition-colors">
            {project.name}
          </h3>
          {project.user_description && (
            <p className="mt-1 line-clamp-2 text-xs text-surface-200/50">
              {project.user_description}
            </p>
          )}
        </div>

        <div className="flex items-center gap-1.5 text-xs text-surface-200/40">
          <Calendar className="h-3 w-3" />
          <span>{formatRelativeTime(project.created_at)}</span>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2 border-t border-white/5 pt-3">
          <button
            onClick={(e) => {
              e.stopPropagation()
              navigate(`/projects/${project.id}`)
            }}
            className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-primary-500/10 px-3 py-1.5 text-xs font-medium text-primary-400 transition-colors hover:bg-primary-500/20"
          >
            <ExternalLink className="h-3.5 w-3.5" />
            查看详情
          </button>

          <button
            onClick={(e) => {
              e.stopPropagation()
              navigate(`/projects/${project.id}/chat`)
            }}
            className="flex items-center justify-center gap-1.5 rounded-lg bg-white/5 px-3 py-1.5 text-xs font-medium text-surface-200/60 transition-colors hover:bg-white/10 hover:text-white"
          >
            <MessageSquare className="h-3.5 w-3.5" />
          </button>

          {isCompleted && (
            <button
              onClick={handleDownload}
              className="flex items-center justify-center gap-1.5 rounded-lg bg-green-500/10 px-3 py-1.5 text-xs font-medium text-green-400 transition-colors hover:bg-green-500/20"
            >
              <Download className="h-3.5 w-3.5" />
            </button>
          )}

          <button
            onClick={(e) => {
              e.stopPropagation()
              onDelete(project)
            }}
            className="flex items-center justify-center rounded-lg bg-white/5 px-3 py-1.5 text-xs font-medium text-surface-200/40 transition-colors hover:bg-red-500/10 hover:text-red-400"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </div>
  )
}
