import { useEffect } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import {
  getProjects,
  getProject,
  createProject,
  deleteProject,
  uploadCADFile,
  parseCAD,
  getCADPreview,
  generateScene,
  answerAgentQuestion,
  getSceneJSON,
  getProjectJobs,
} from '@/api/projects'
import { useProjectStore } from '@/store/projectStore'
import type { UploadProgress } from '@/types'

// ─── Query Keys ───────────────────────────────────────────────────────────────

export const projectKeys = {
  all:     ['projects'] as const,
  lists:   () => [...projectKeys.all, 'list'] as const,
  detail:  (id: number) => ['project', id] as const,
  scene:   (id: number) => ['scene', id] as const,
  preview: (id: number) => ['cad-preview', id] as const,
  jobs:    (id: number) => ['jobs', id] as const,
}

// ─── Hooks ────────────────────────────────────────────────────────────────────

export function useProjects() {
  return useQuery({
    queryKey: projectKeys.lists(),
    queryFn:  getProjects,
    staleTime: 30_000,
  })
}

export function useProjectDetail(id: number) {
  // 用 selector 订阅单个 setter，避免订阅整个 store 触发多余 re-render
  const setCurrentProject = useProjectStore((s) => s.setCurrentProject)

  const query = useQuery({
    queryKey: projectKeys.detail(id),
    queryFn:  () => getProject(id),
    staleTime: 10_000,
    enabled:  !!id,
  })

  // 副作用要放 effect 里：select() 每次渲染都会跑，
  // 在其中调用 setCurrentProject 会触发 Sidebar 重渲染并形成无限循环
  useEffect(() => {
    if (query.data) {
      setCurrentProject(query.data)
    }
  }, [query.data, setCurrentProject])

  return query
}

export function useSceneJSON(projectId: number, enabled = true) {
  return useQuery({
    queryKey: projectKeys.scene(projectId),
    queryFn:  () => getSceneJSON(projectId),
    enabled:  enabled && !!projectId,
    staleTime: Infinity,
    retry: false,
  })
}

export function useCADPreview(projectId: number, enabled = true) {
  return useQuery({
    queryKey: projectKeys.preview(projectId),
    queryFn:  () => getCADPreview(projectId),
    enabled:  enabled && !!projectId,
    staleTime: Infinity,
    retry: false,
  })
}

export function useProjectJobs(projectId: number) {
  return useQuery({
    queryKey: projectKeys.jobs(projectId),
    queryFn:  () => getProjectJobs(projectId),
    staleTime: 5_000,
    enabled:  !!projectId,
  })
}

// ─── Mutations ────────────────────────────────────────────────────────────────

export function useCreateProject() {
  const queryClient = useQueryClient()

  // 不在这里强制跳转，由调用方决定后续动作（如 NewProjectPage 要进 step=1 上传 CAD）
  return useMutation({
    mutationFn: createProject,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: projectKeys.lists() })
    },
  })
}

export function useDeleteProject() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  return useMutation({
    mutationFn: deleteProject,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: projectKeys.lists() })
      navigate('/projects')
    },
  })
}

export function useUploadCAD(
  projectId: number,
  onProgress?: (p: UploadProgress) => void,
) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (file: File) => uploadCADFile(projectId, file, onProgress),
    onSuccess: (project) => {
      queryClient.setQueryData(projectKeys.detail(projectId), project)
      queryClient.invalidateQueries({ queryKey: projectKeys.lists() })
    },
  })
}

export function useParseCAD(projectId: number) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: () => parseCAD(projectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: projectKeys.detail(projectId) })
    },
  })
}

export function useGenerateScene(projectId: number) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (description: string) => generateScene(projectId, description),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: projectKeys.detail(projectId) })
    },
  })
}

export function useAnswerQuestion(projectId: number) {
  const queryClient = useQueryClient()

  return useMutation({
    mutationFn: (answer: string) => answerAgentQuestion(projectId, answer),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: projectKeys.detail(projectId) })
    },
  })
}
