import { Suspense, useRef, useMemo, useLayoutEffect } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, Grid, Environment, Text } from '@react-three/drei'
import * as THREE from 'three'
import { cn } from '@/lib/utils'
import type {
  SceneJSON,
  WallConfig,
  DoorConfig,
  WindowConfig,
  FurnitureConfig,
  RoomConfig,
  FurnitureCategory,
  Point2D,
} from '@/types'

// ─── Constants ────────────────────────────────────────────────────────────────

const MM_TO_M = 0.001

// CAD/backend uses Z-up, mm. Three.js uses Y-up, meters.
// Map backend (x, y, z) → three (x, z, -y), then divide by 1000.

const FURNITURE_DEFAULT_SIZE_MM: Record<FurnitureCategory, [number, number, number]> = {
  sofa:            [2000,  900,  800],
  bed:             [2000, 1800,  600],
  table:           [1200,  800,  750],
  chair:           [ 500,  500,  900],
  desk:            [1400,  700,  750],
  wardrobe:        [1500,  600, 2000],
  cabinet:         [ 800,  400,  800],
  bookshelf:       [ 900,  350, 2000],
  tv_stand:        [1500,  400,  500],
  dining_table:    [1400,  800,  750],
  kitchen_cabinet: [ 600,  600,  800],
  appliance:       [ 600,  600,  850],
  decoration:      [ 300,  300,  300],
  plant:           [ 500,  500, 1200],
  other:           [ 500,  500,  500],
}

const FURNITURE_COLOR: Record<FurnitureCategory, string> = {
  sofa:            '#6366f1',
  bed:             '#a855f7',
  table:           '#f59e0b',
  chair:           '#facc15',
  desk:            '#fb923c',
  wardrobe:        '#a16207',
  cabinet:         '#92400e',
  bookshelf:       '#78350f',
  tv_stand:        '#475569',
  dining_table:    '#d97706',
  kitchen_cabinet: '#7c2d12',
  appliance:       '#94a3b8',
  decoration:      '#ec4899',
  plant:           '#22c55e',
  other:           '#9ca3af',
}

// ─── Coordinate Normalization ─────────────────────────────────────────────────

interface BBox {
  cx: number
  cy: number
  sizeMeters: number
}

function computeBBox(scene: SceneJSON): BBox {
  let minX = Infinity, maxX = -Infinity
  let minY = Infinity, maxY = -Infinity
  for (const w of scene.walls) {
    minX = Math.min(minX, w.start.x, w.end.x)
    maxX = Math.max(maxX, w.start.x, w.end.x)
    minY = Math.min(minY, w.start.y, w.end.y)
    maxY = Math.max(maxY, w.start.y, w.end.y)
  }
  if (!isFinite(minX)) {
    for (const f of scene.furniture) {
      minX = Math.min(minX, f.position.x)
      maxX = Math.max(maxX, f.position.x)
      minY = Math.min(minY, f.position.y)
      maxY = Math.max(maxY, f.position.y)
    }
  }
  if (!isFinite(minX)) return { cx: 0, cy: 0, sizeMeters: 20 }
  const cx = (minX + maxX) / 2
  const cy = (minY + maxY) / 2
  const sizeMeters = Math.max(maxX - minX, maxY - minY) * MM_TO_M
  return { cx, cy, sizeMeters }
}

// ─── Walls ────────────────────────────────────────────────────────────────────

function Walls({ walls, bbox }: { walls: WallConfig[]; bbox: BBox }) {
  const ref = useRef<THREE.InstancedMesh>(null)

  useLayoutEffect(() => {
    if (!ref.current || walls.length === 0) return
    const dummy = new THREE.Object3D()
    let writeIdx = 0
    for (let i = 0; i < walls.length; i++) {
      const w = walls[i]
      const sx = (w.start.x - bbox.cx) * MM_TO_M
      const sy = -(w.start.y - bbox.cy) * MM_TO_M
      const ex = (w.end.x - bbox.cx) * MM_TO_M
      const ey = -(w.end.y - bbox.cy) * MM_TO_M
      const dx = ex - sx
      const dz = ey - sy
      const length = Math.hypot(dx, dz)
      if (length < 1e-4) continue
      const angle = Math.atan2(dz, dx)
      const h = w.height * MM_TO_M
      const t = w.thickness * MM_TO_M
      dummy.position.set((sx + ex) / 2, h / 2, (sy + ey) / 2)
      dummy.rotation.set(0, -angle, 0)
      dummy.scale.set(length, h, t)
      dummy.updateMatrix()
      ref.current.setMatrixAt(writeIdx++, dummy.matrix)
    }
    ref.current.count = writeIdx
    ref.current.instanceMatrix.needsUpdate = true
  }, [walls, bbox.cx, bbox.cy])

  if (walls.length === 0) return null
  return (
    <instancedMesh
      ref={ref}
      args={[undefined, undefined, walls.length]}
      castShadow
      receiveShadow
    >
      <boxGeometry args={[1, 1, 1]} />
      <meshStandardMaterial color="#9ca3af" roughness={0.85} metalness={0} />
    </instancedMesh>
  )
}

// ─── Doors / Windows on Walls ─────────────────────────────────────────────────

function Openings({
  items,
  wallMap,
  bbox,
  color,
  transparent = false,
  opacity = 1,
}: {
  items: (DoorConfig | WindowConfig)[]
  wallMap: Map<string, WallConfig>
  bbox: BBox
  color: string
  transparent?: boolean
  opacity?: number
}) {
  const ref = useRef<THREE.InstancedMesh>(null)

  useLayoutEffect(() => {
    if (!ref.current || items.length === 0) return
    const dummy = new THREE.Object3D()
    let writeIdx = 0
    for (let i = 0; i < items.length; i++) {
      const item = items[i]
      const wall = wallMap.get(item.wall_id)
      const px = (item.position.x - bbox.cx) * MM_TO_M
      const pz = -(item.position.y - bbox.cy) * MM_TO_M
      const py = (item.position.z + item.height / 2) * MM_TO_M
      // Use wall's angle if known, otherwise 0
      let angle = 0
      let thickness = 200 * MM_TO_M
      if (wall) {
        const dx = wall.end.x - wall.start.x
        const dy = -(wall.end.y - wall.start.y)
        angle = Math.atan2(dy, dx)
        thickness = wall.thickness * MM_TO_M * 1.05  // slightly thicker so it pokes through wall
      }
      dummy.position.set(px, py, pz)
      dummy.rotation.set(0, -angle, 0)
      dummy.scale.set(item.width * MM_TO_M, item.height * MM_TO_M, thickness)
      dummy.updateMatrix()
      ref.current.setMatrixAt(writeIdx++, dummy.matrix)
    }
    ref.current.count = writeIdx
    ref.current.instanceMatrix.needsUpdate = true
  }, [items, wallMap, bbox.cx, bbox.cy])

  if (items.length === 0) return null
  return (
    <instancedMesh
      ref={ref}
      args={[undefined, undefined, items.length]}
      castShadow
      receiveShadow
    >
      <boxGeometry args={[1, 1, 1]} />
      <meshStandardMaterial
        color={color}
        roughness={transparent ? 0.1 : 0.6}
        metalness={transparent ? 0 : 0.05}
        transparent={transparent}
        opacity={opacity}
      />
    </instancedMesh>
  )
}

// ─── Furniture (by category) ──────────────────────────────────────────────────

function FurnitureGroup({
  items,
  category,
  bbox,
}: {
  items: FurnitureConfig[]
  category: FurnitureCategory
  bbox: BBox
}) {
  const ref = useRef<THREE.InstancedMesh>(null)
  const [sw, sd, sh] = FURNITURE_DEFAULT_SIZE_MM[category]

  useLayoutEffect(() => {
    if (!ref.current || items.length === 0) return
    const dummy = new THREE.Object3D()
    for (let i = 0; i < items.length; i++) {
      const f = items[i]
      const px = (f.position.x - bbox.cx) * MM_TO_M
      const pz = -(f.position.y - bbox.cy) * MM_TO_M
      const wMeters = sw * (f.scale?.x ?? 1) * MM_TO_M
      const dMeters = sd * (f.scale?.y ?? 1) * MM_TO_M
      const hMeters = sh * (f.scale?.z ?? 1) * MM_TO_M
      const py = (f.position.z * MM_TO_M) + hMeters / 2
      const rotZ = THREE.MathUtils.degToRad(f.rotation?.z ?? 0)
      dummy.position.set(px, py, pz)
      dummy.rotation.set(0, -rotZ, 0)
      dummy.scale.set(wMeters, hMeters, dMeters)
      dummy.updateMatrix()
      ref.current.setMatrixAt(i, dummy.matrix)
    }
    ref.current.instanceMatrix.needsUpdate = true
  }, [items, bbox.cx, bbox.cy, sw, sd, sh])

  if (items.length === 0) return null
  return (
    <instancedMesh
      ref={ref}
      args={[undefined, undefined, items.length]}
      castShadow
      receiveShadow
    >
      <boxGeometry args={[1, 1, 1]} />
      <meshStandardMaterial
        color={FURNITURE_COLOR[category]}
        roughness={0.6}
        metalness={0.05}
      />
    </instancedMesh>
  )
}

// ─── Floor Plane ──────────────────────────────────────────────────────────────

function FloorPlane({ size }: { size: number }) {
  const planeSize = Math.max(size * 1.2, 20)
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow position={[0, 0, 0]}>
      <planeGeometry args={[planeSize, planeSize]} />
      <meshStandardMaterial color="#1a1d27" roughness={0.95} metalness={0} />
    </mesh>
  )
}

// ─── Room Labels ──────────────────────────────────────────────────────────────

function centroid(points: Point2D[]): Point2D {
  let sx = 0, sy = 0
  for (const p of points) { sx += p.x; sy += p.y }
  return { x: sx / points.length, y: sy / points.length }
}

function RoomLabels({ rooms, bbox }: { rooms: RoomConfig[]; bbox: BBox }) {
  // Limit to top-N rooms by area to keep label count manageable
  const topRooms = useMemo(
    () => [...rooms].sort((a, b) => (b.area ?? 0) - (a.area ?? 0)).slice(0, 40),
    [rooms],
  )
  // Scale font with scene size so labels stay readable
  const fontSize = useMemo(() => Math.max(0.25, bbox.sizeMeters / 120), [bbox.sizeMeters])

  return (
    <>
      {topRooms.map((room) => {
        if (!room.boundary || room.boundary.length < 3) return null
        const c = centroid(room.boundary)
        const px = (c.x - bbox.cx) * MM_TO_M
        const pz = -(c.y - bbox.cy) * MM_TO_M
        return (
          <Text
            key={room.id}
            position={[px, 0.05, pz]}
            rotation={[-Math.PI / 2, 0, 0]}
            fontSize={fontSize}
            color="#93c5fd"
            anchorX="center"
            anchorY="middle"
            outlineWidth={0.02}
            outlineColor="#0f1117"
          >
            {room.name}
          </Text>
        )
      })}
    </>
  )
}

// ─── Scene Content ────────────────────────────────────────────────────────────

function SceneContent({ sceneData }: { sceneData: SceneJSON }) {
  const bbox = useMemo(() => computeBBox(sceneData), [sceneData])

  const wallMap = useMemo(() => {
    const m = new Map<string, WallConfig>()
    for (const w of sceneData.walls ?? []) m.set(w.id, w)
    return m
  }, [sceneData.walls])

  const furnitureByCategory = useMemo(() => {
    const map = new Map<FurnitureCategory, FurnitureConfig[]>()
    for (const f of sceneData.furniture ?? []) {
      const cat = (f.category ?? 'other') as FurnitureCategory
      const arr = map.get(cat) ?? []
      arr.push(f)
      map.set(cat, arr)
    }
    return map
  }, [sceneData.furniture])

  const lightTarget = useMemo<[number, number, number]>(() => [0, 0, 0], [])

  return (
    <>
      {/* Lights */}
      <ambientLight intensity={0.5} />
      <directionalLight
        position={[bbox.sizeMeters, bbox.sizeMeters * 1.5, bbox.sizeMeters]}
        intensity={1.1}
        castShadow={false}
        target-position={lightTarget}
      />
      <directionalLight
        position={[-bbox.sizeMeters, bbox.sizeMeters, -bbox.sizeMeters]}
        intensity={0.35}
      />

      <FloorPlane size={bbox.sizeMeters} />

      <Walls walls={sceneData.walls ?? []} bbox={bbox} />

      <Openings
        items={sceneData.doors ?? []}
        wallMap={wallMap}
        bbox={bbox}
        color="#7c3aed"
      />
      <Openings
        items={sceneData.windows ?? []}
        wallMap={wallMap}
        bbox={bbox}
        color="#22d3ee"
        transparent
        opacity={0.45}
      />

      {Array.from(furnitureByCategory.entries()).map(([category, items]) => (
        <FurnitureGroup
          key={category}
          category={category}
          items={items}
          bbox={bbox}
        />
      ))}

      <RoomLabels rooms={sceneData.rooms ?? []} bbox={bbox} />
    </>
  )
}

// ─── Empty Scene ──────────────────────────────────────────────────────────────

function EmptyScene() {
  return (
    <>
      <ambientLight intensity={0.4} />
      <directionalLight position={[10, 20, 10]} intensity={1} />
      <FloorPlane size={20} />
      <mesh position={[0, 1, 0]}>
        <boxGeometry args={[2, 2, 2]} />
        <meshStandardMaterial color="#2a2d3e" wireframe />
      </mesh>
    </>
  )
}

// ─── Loading Spinner ──────────────────────────────────────────────────────────

function LoadingBox() {
  const meshRef = useRef<THREE.Mesh>(null)
  useFrame((_, delta) => {
    if (meshRef.current) {
      meshRef.current.rotation.x += delta * 0.5
      meshRef.current.rotation.y += delta * 0.8
    }
  })
  return (
    <mesh ref={meshRef}>
      <boxGeometry args={[1.5, 1.5, 1.5]} />
      <meshStandardMaterial color="#3b82f6" wireframe />
    </mesh>
  )
}

// ─── Stats Overlay ────────────────────────────────────────────────────────────

function StatsOverlay({ sceneData }: { sceneData: SceneJSON }) {
  const stats = [
    { label: '墙体', n: sceneData.walls?.length ?? 0 },
    { label: '房间', n: sceneData.rooms?.length ?? 0 },
    { label: '门',   n: sceneData.doors?.length ?? 0 },
    { label: '窗',   n: sceneData.windows?.length ?? 0 },
    { label: '家具', n: sceneData.furniture?.length ?? 0 },
  ]
  return (
    <div className="absolute left-3 top-3 z-10 flex flex-col gap-1 rounded-lg bg-surface-900/70 px-3 py-2 text-[11px] text-surface-200/70 backdrop-blur-sm">
      {stats.map((s) => (
        <div key={s.label} className="flex gap-2">
          <span className="w-7 text-surface-200/50">{s.label}</span>
          <span className="font-mono text-primary-300">{s.n}</span>
        </div>
      ))}
    </div>
  )
}

// ─── Main Component ───────────────────────────────────────────────────────────

interface SceneViewerProps {
  sceneData?: SceneJSON | null
  isLoading?: boolean
  className?: string
}

export function SceneViewer({ sceneData, isLoading = false, className }: SceneViewerProps) {
  const sceneStats = useMemo(() => {
    if (!sceneData) {
      return { sizeMeters: 40, camPos: [15, 12, 15] as [number, number, number], far: 1000, maxDist: 200 }
    }
    const bbox = computeBBox(sceneData)
    const d = Math.max(bbox.sizeMeters * 0.9, 8)
    return {
      sizeMeters: bbox.sizeMeters,
      camPos: [d, d * 0.8, d] as [number, number, number],
      far: Math.max(bbox.sizeMeters * 8, 200),
      maxDist: Math.max(bbox.sizeMeters * 4, 200),
    }
  }, [sceneData])

  return (
    <div
      className={cn(
        'relative overflow-hidden rounded-xl bg-surface-900',
        className,
      )}
    >
      {isLoading && (
        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 bg-surface-900/80 backdrop-blur-sm">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary-500 border-t-transparent" />
          <p className="text-xs text-surface-200/60">加载场景中…</p>
        </div>
      )}

      {sceneData && <StatsOverlay sceneData={sceneData} />}

      <Canvas
        shadows={false}
        camera={{ position: sceneStats.camPos, fov: 50, near: 0.1, far: sceneStats.far }}
        gl={{ antialias: true, alpha: false }}
        style={{ background: '#0f1117' }}
      >
        <Suspense
          fallback={
            <>
              <ambientLight intensity={0.4} />
              <LoadingBox />
            </>
          }
        >
          {sceneData ? <SceneContent sceneData={sceneData} /> : <EmptyScene />}

          <Grid
            args={[200, 200]}
            cellSize={1}
            cellThickness={0.5}
            cellColor="#1e2130"
            sectionSize={5}
            sectionThickness={1}
            sectionColor="#252840"
            fadeDistance={Math.max(sceneStats.sizeMeters * 1.2, 40)}
            fadeStrength={1}
            position={[0, 0.01, 0]}
          />

          <OrbitControls
            enableDamping
            dampingFactor={0.05}
            minDistance={1}
            maxDistance={sceneStats.maxDist}
            maxPolarAngle={Math.PI / 2.05}
            target={[0, 0, 0]}
          />

          <Environment preset="city" />
        </Suspense>
      </Canvas>

      {/* Overlay controls hint */}
      <div className="absolute bottom-3 right-3 flex flex-col gap-1 text-right">
        <span className="text-[10px] text-surface-200/30">左键旋转 · 右键平移 · 滚轮缩放</span>
      </div>
    </div>
  )
}
