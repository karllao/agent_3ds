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
  const { setCurrentProject } = useProjectStore()

  return useQuery({
    queryKey: projectKeys.detail(id),
    queryFn:  () => getProject(id),
    staleTime: 10_000,
    enabled:  !!id,
    select: (data) => {
      setCurrentProject(data)
      return data
    },
  })
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
  const navigate = useNavigate()

  return useMutation({
    mutationFn: createProject,
    onSuccess: (project) => {
      queryClient.invalidateQueries({ queryKey: projectKeys.lists() })
      navigate(`/projects/${project.id}`)
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
