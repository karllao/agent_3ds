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

// ─── Scene JSON (mirrors backend app/schemas/scene.py FullSceneData) ─────────

export interface Point2D { x: number; y: number }
export interface Point3D { x: number; y: number; z: number }
export interface Rotation3D { x: number; y: number; z: number }
export interface Scale3D { x: number; y: number; z: number }
export interface ColorRGB { r: number; g: number; b: number }

export interface SceneConfig {
  scene_name: string
  unit_system: 'mm' | 'cm' | 'm'
  floor_height: number
  style: string
  renderer: 'vray' | 'corona' | 'arnold' | 'default'
  ambient_light_intensity: number
  background_color: ColorRGB
}

export interface WallOpening {
  opening_id: string
  opening_type: 'door' | 'window' | 'opening'
  position_along_wall: number
  width: number
  height: number
  floor_offset: number
}

export interface WallConfig {
  id: string
  start: Point2D
  end: Point2D
  thickness: number
  height: number
  room_side_a: string | null
  room_side_b: string | null
  material: string
  openings: WallOpening[]
  is_exterior: boolean
}

export interface RoomConfig {
  id: string
  name: string
  type: string
  boundary: Point2D[]
  area: number
  floor_material: string
  ceiling_material: string
  ceiling_type: string
  ceiling_height: number | null
  style: string | null
}

export interface DoorConfig {
  id: string
  wall_id: string
  position: Point3D
  width: number
  height: number
  floor_offset: number
  swing_direction: string
  door_type: string
  material: string
  frame_material: string
  asset_id: string | null
}

export interface WindowConfig {
  id: string
  wall_id: string
  position: Point3D
  width: number
  height: number
  sill_height: number
  window_type: string
  glass_material: string
  frame_material: string
  has_curtain: boolean
  curtain_material: string | null
  asset_id: string | null
}

export type FurnitureCategory =
  | 'sofa' | 'bed' | 'table' | 'chair' | 'desk'
  | 'wardrobe' | 'cabinet' | 'bookshelf' | 'tv_stand'
  | 'dining_table' | 'kitchen_cabinet' | 'appliance'
  | 'decoration' | 'plant' | 'other'

export interface FurnitureConfig {
  id: string
  category: FurnitureCategory
  asset_id: string
  room_id: string
  position: Point3D
  rotation: Rotation3D
  scale: Scale3D
  material_overrides: Record<string, string>
}

export interface MaterialConfig {
  id: string
  name: string
  type: string
  color: ColorRGB
  texture_path: string | null
  roughness: number
  metallic: number
  ior: number
  opacity: number
}

export interface SceneJSON {
  version: string
  scene_config: SceneConfig
  materials: MaterialConfig[]
  walls: WallConfig[]
  rooms: RoomConfig[]
  doors: DoorConfig[]
  windows: WindowConfig[]
  furniture: FurnitureConfig[]
  lights: unknown[]
  cameras: unknown[]
  extra: Record<string, unknown>
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
