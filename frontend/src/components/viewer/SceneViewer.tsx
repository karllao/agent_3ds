import { Suspense, useRef, useMemo } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls, Grid, Environment, Text } from '@react-three/drei'
import * as THREE from 'three'
import { cn } from '@/lib/utils'
import type { SceneJSON, SceneObject } from '@/types'

// ─── Object Colors ────────────────────────────────────────────────────────────

const OBJECT_COLORS: Record<SceneObject['type'], string> = {
  wall:      '#4a5568',
  floor:     '#2d3748',
  ceiling:   '#1a202c',
  furniture: '#3b82f6',
  door:      '#8b5cf6',
  window:    '#06b6d4',
  other:     '#6b7280',
}

// ─── Single Scene Object ──────────────────────────────────────────────────────

function SceneMesh({ obj }: { obj: SceneObject }) {
  const meshRef = useRef<THREE.Mesh>(null)
  const color = obj.color ?? OBJECT_COLORS[obj.type]

  const [w, h, d] = obj.size
  const [px, py, pz] = obj.position
  const [rx, ry, rz] = obj.rotation ?? [0, 0, 0]

  const material = useMemo(() => {
    const mat = new THREE.MeshStandardMaterial({
      color: new THREE.Color(color),
      roughness: obj.type === 'wall' ? 0.8 : 0.6,
      metalness: obj.type === 'furniture' ? 0.1 : 0,
      transparent: obj.type === 'window',
      opacity: obj.type === 'window' ? 0.4 : 1,
    })
    return mat
  }, [color, obj.type])

  return (
    <mesh
      ref={meshRef}
      position={[px, py + h / 2, pz]}
      rotation={[rx, ry, rz]}
      castShadow
      receiveShadow
      material={material}
    >
      <boxGeometry args={[w, h, d]} />
    </mesh>
  )
}

// ─── Floor Plane ──────────────────────────────────────────────────────────────

function FloorPlane({ size = 50 }: { size?: number }) {
  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} receiveShadow position={[0, 0, 0]}>
      <planeGeometry args={[size, size]} />
      <meshStandardMaterial color="#1a1d27" roughness={0.9} metalness={0} />
    </mesh>
  )
}

// ─── Scene Content ────────────────────────────────────────────────────────────

function SceneContent({ sceneData }: { sceneData: SceneJSON }) {
  const allObjects = useMemo(() => {
    const roomObjects = sceneData.rooms.flatMap((room) => room.objects)
    return [...roomObjects, ...(sceneData.global_objects ?? [])]
  }, [sceneData])

  const nonFloorObjects = allObjects.filter(
    (o) => o.type !== 'floor' && o.type !== 'ceiling',
  )
  const floorObjects = allObjects.filter((o) => o.type === 'floor')

  return (
    <>
      {/* Lights */}
      <ambientLight intensity={0.4} />
      <directionalLight
        position={[10, 20, 10]}
        intensity={1.2}
        castShadow
        shadow-mapSize={[2048, 2048]}
        shadow-camera-far={100}
        shadow-camera-left={-30}
        shadow-camera-right={30}
        shadow-camera-top={30}
        shadow-camera-bottom={-30}
      />
      <directionalLight position={[-10, 10, -10]} intensity={0.3} />
      <pointLight position={[0, 10, 0]} intensity={0.5} color="#3b82f6" />

      {/* Floor */}
      {floorObjects.length > 0
        ? floorObjects.map((obj) => <SceneMesh key={obj.id} obj={obj} />)
        : <FloorPlane />}

      {/* Scene objects */}
      {nonFloorObjects.map((obj) => (
        <SceneMesh key={obj.id} obj={obj} />
      ))}

      {/* Room labels */}
      {sceneData.rooms.map((room) => {
        const floorObj = room.objects.find((o) => o.type === 'floor')
        if (!floorObj) return null
        const [px, , pz] = floorObj.position
        return (
          <Text
            key={room.id}
            position={[px, 0.1, pz]}
            rotation={[-Math.PI / 2, 0, 0]}
            fontSize={0.4}
            color="#60a5fa"
            anchorX="center"
            anchorY="middle"
          >
            {room.name}
          </Text>
        )
      })}
    </>
  )
}

// ─── Empty Scene ──────────────────────────────────────────────────────────────

function EmptyScene() {
  return (
    <>
      <ambientLight intensity={0.4} />
      <directionalLight position={[10, 20, 10]} intensity={1} />
      <FloorPlane />
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

// ─── Main Component ───────────────────────────────────────────────────────────

interface SceneViewerProps {
  sceneData?: SceneJSON | null
  isLoading?: boolean
  className?: string
}

export function SceneViewer({ sceneData, isLoading = false, className }: SceneViewerProps) {
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

      <Canvas
        shadows
        camera={{ position: [15, 12, 15], fov: 50, near: 0.1, far: 1000 }}
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
            args={[50, 50]}
            cellSize={1}
            cellThickness={0.5}
            cellColor="#1e2130"
            sectionSize={5}
            sectionThickness={1}
            sectionColor="#252840"
            fadeDistance={40}
            fadeStrength={1}
            position={[0, 0.01, 0]}
          />

          <OrbitControls
            enableDamping
            dampingFactor={0.05}
            minDistance={2}
            maxDistance={80}
            maxPolarAngle={Math.PI / 2.1}
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
