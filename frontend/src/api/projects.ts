import apiClient from './client'
import type { Project, CADPreview, SceneJSON, Job, UploadProgress } from '@/types'

// ─── Projects CRUD ────────────────────────────────────────────────────────────

export async function getProjects(): Promise<Project[]> {
  const res = await apiClient.get<Project[]>('/projects')
  return res.data
}

export async function getProject(id: number): Promise<Project> {
  const res = await apiClient.get<Project>(`/projects/${id}`)
  return res.data
}

export async function createProject(payload: {
  name: string
  user_description?: string
}): Promise<Project> {
  const res = await apiClient.post<Project>('/projects', payload)
  return res.data
}

export async function deleteProject(id: number): Promise<void> {
  await apiClient.delete(`/projects/${id}`)
}

// ─── CAD File ─────────────────────────────────────────────────────────────────

export async function uploadCADFile(
  projectId: number,
  file: File,
  onProgress?: (progress: UploadProgress) => void,
): Promise<Project> {
  const formData = new FormData()
  formData.append('file', file)

  const res = await apiClient.post<Project>(
    `/projects/${projectId}/upload_cad`,
    formData,
    {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (evt) => {
        if (onProgress && evt.total) {
          onProgress({
            loaded: evt.loaded,
            total: evt.total,
            percentage: Math.round((evt.loaded / evt.total) * 100),
          })
        }
      },
    },
  )
  return res.data
}

export async function parseCAD(projectId: number): Promise<Job> {
  const res = await apiClient.post<Job>(`/projects/${projectId}/parse_cad`)
  return res.data
}

export async function getCADPreview(projectId: number): Promise<CADPreview> {
  const res = await apiClient.get<CADPreview>(`/projects/${projectId}/cad_preview`)
  return res.data
}

// ─── Generation ───────────────────────────────────────────────────────────────

export async function generateScene(
  projectId: number,
  userDescription: string,
): Promise<Job> {
  const res = await apiClient.post<Job>(`/projects/${projectId}/generate`, {
    user_description: userDescription,
  })
  return res.data
}

export async function answerAgentQuestion(
  projectId: number,
  answer: string,
): Promise<Job> {
  const res = await apiClient.post<Job>(`/projects/${projectId}/answer`, {
    answer,
  })
  return res.data
}

// ─── Scene & Download ─────────────────────────────────────────────────────────

export async function getSceneJSON(projectId: number): Promise<SceneJSON> {
  const res = await apiClient.get<SceneJSON>(`/projects/${projectId}/scene_json`)
  return res.data
}

export async function downloadMaxFile(projectId: number): Promise<void> {
  const res = await apiClient.get(`/projects/${projectId}/download`, {
    responseType: 'blob',
  })
  const blob = new Blob([res.data], { type: 'application/octet-stream' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `project_${projectId}.max`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

export function getPreviewImageUrl(projectId: number): string {
  return `/api/v1/projects/${projectId}/preview`
}

// ─── Jobs ─────────────────────────────────────────────────────────────────────

export async function getProjectJobs(projectId: number): Promise<Job[]> {
  const res = await apiClient.get<Job[]>(`/projects/${projectId}/jobs`)
  return res.data
}

// ─── Chat ─────────────────────────────────────────────────────────────────────

export async function sendChatMessage(payload: {
  project_id: number
  message: string
  history: Array<{ role: string; content: string }>
}): Promise<{ message: string; role: string }> {
  const res = await apiClient.post('/chat/completions', payload)
  return res.data
}
