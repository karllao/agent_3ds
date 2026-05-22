// ─── Project ──────────────────────────────────────────────────────────────────

export type ProjectStatus =
  | 'created'
  | 'cad_uploaded'
  | 'parsing'
  | 'parsed'
  | 'generating'
  | 'generated'
  | 'exporting'
  | 'completed'
  | 'failed'

export interface Project {
  id: number
  name: string
  status: ProjectStatus
  user_description: string | null
  cad_file_path: string | null
  scene_json_path: string | null
  max_file_path: string | null
  preview_image_path: string | null
  created_at: string
  updated_at: string
}

// ─── Job ──────────────────────────────────────────────────────────────────────

export type JobStatus = 'pending' | 'running' | 'waiting_user' | 'completed' | 'failed'

export interface Job {
  id: number
  project_id: number
  status: JobStatus
  step: string
  progress: number
  error_message: string | null
  result: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

// ─── CAD Preview ──────────────────────────────────────────────────────────────

export interface CADPreview {
  wall_count: number
  room_count: number
  door_count: number
  window_count: number
  layer_names: string[]
  bounding_box: [number, number, number, number]
  warnings: string[]
}

// ─── Scene JSON ───────────────────────────────────────────────────────────────

export interface SceneObject {
  id: string
  type: 'wall' | 'floor' | 'ceiling' | 'furniture' | 'door' | 'window' | 'other'
  name: string
  position: [number, number, number]
  rotation?: [number, number, number]
  scale?: [number, number, number]
  size: [number, number, number]
  color?: string
  material?: string
  metadata?: Record<string, unknown>
}

export interface SceneRoom {
  id: string
  name: string
  objects: SceneObject[]
  floor_area?: number
}

export interface SceneJSON {
  version: string
  rooms: SceneRoom[]
  global_objects: SceneObject[]
  metadata?: Record<string, unknown>
}

// ─── Chat ─────────────────────────────────────────────────────────────────────

export type MessageRole = 'user' | 'assistant' | 'system'

export interface ChatMessage {
  role: MessageRole
  content: string
  timestamp?: string
}

export interface ChatRequest {
  project_id: number
  message: string
  history: ChatMessage[]
}

export interface ChatResponse {
  message: string
  role: MessageRole
}

// ─── API Response ─────────────────────────────────────────────────────────────

export interface ApiError {
  detail: string
  status_code?: number
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  size: number
}

// ─── UI State ─────────────────────────────────────────────────────────────────

export interface UploadProgress {
  loaded: number
  total: number
  percentage: number
}

export type DialogState = 'closed' | 'confirm-delete' | 'cad-preview'

export interface Notification {
  id: string
  type: 'success' | 'error' | 'warning' | 'info'
  title: string
  message?: string
  duration?: number
}
