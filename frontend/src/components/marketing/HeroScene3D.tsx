'use client'

import { useMemo, useRef } from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { Float, PointMaterial, Points } from '@react-three/drei'
import * as THREE from 'three'

function EnergyCore() {
  const meshRef = useRef<THREE.Mesh>(null)

  useFrame((state, delta) => {
    const mesh = meshRef.current
    if (!mesh) return
    mesh.rotation.x += delta * 0.22
    mesh.rotation.y += delta * 0.35
    mesh.position.x = Math.sin(state.clock.elapsedTime * 0.45) * 0.08
    mesh.position.y = Math.cos(state.clock.elapsedTime * 0.35) * 0.06
  })

  return (
    <mesh ref={meshRef}>
      <icosahedronGeometry args={[0.9, 4]} />
      <meshStandardMaterial
        color="#ff845d"
        emissive="#ff6f47"
        emissiveIntensity={1.4}
        roughness={0.28}
        metalness={0.12}
        wireframe
      />
    </mesh>
  )
}

function ParticleShell() {
  const pointsRef = useRef<THREE.Points>(null)

  const positions = useMemo(() => {
    const count = 700
    const arr = new Float32Array(count * 3)

    for (let i = 0; i < count; i++) {
      const radius = 1.1 + Math.random() * 1.65
      const theta = Math.random() * Math.PI * 2
      const phi = Math.acos(2 * Math.random() - 1)

      arr[i * 3] = radius * Math.sin(phi) * Math.cos(theta)
      arr[i * 3 + 1] = radius * Math.cos(phi)
      arr[i * 3 + 2] = radius * Math.sin(phi) * Math.sin(theta)
    }

    return arr
  }, [])

  useFrame((state, delta) => {
    const points = pointsRef.current
    if (!points) return

    points.rotation.y += delta * 0.08
    points.rotation.x += delta * 0.03
    points.position.x = Math.sin(state.clock.elapsedTime * 0.28) * 0.05
    points.position.y = Math.cos(state.clock.elapsedTime * 0.22) * 0.05
  })

  return (
    <Points ref={pointsRef} positions={positions} stride={3} frustumCulled>
      <PointMaterial transparent color="#ff9c7d" size={0.02} sizeAttenuation depthWrite={false} opacity={0.72} />
    </Points>
  )
}

export default function HeroScene3D() {
  return (
    <div className="pointer-events-none absolute inset-0 z-0">
      <Canvas camera={{ position: [0, 0, 4], fov: 48 }} dpr={[1, 1.6]} gl={{ antialias: false }}>
        <ambientLight intensity={0.52} />
        <pointLight position={[2.8, 2.3, 2.2]} intensity={1.8} color="#ff8a68" />
        <pointLight position={[-2.8, -1.8, -2]} intensity={0.5} color="#ffd6c7" />

        <Float speed={0.9} rotationIntensity={0.28} floatIntensity={0.4}>
          <EnergyCore />
        </Float>
        <ParticleShell />
      </Canvas>
    </div>
  )
}
