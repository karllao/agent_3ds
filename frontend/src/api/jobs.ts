import apiClient from './client'
import type { Job } from '@/types'

export async function getJob(jobId: number): Promise<Job> {
  const res = await apiClient.get<Job>(`/jobs/${jobId}`)
  return res.data
}

export async function getProjectJobs(projectId: number): Promise<Job[]> {
  const res = await apiClient.get<Job[]>(`/projects/${projectId}/jobs`)
  return res.data
}
