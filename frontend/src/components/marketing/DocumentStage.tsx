'use client'

import {
    Component,
    useEffect,
    useRef,
    useState,
    type MutableRefObject,
    type ReactNode,
} from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { MathUtils, type Group } from 'three'

type StageProps = {
    dark: boolean
    selected: number
    reducedMotion: boolean
    pointer: MutableRefObject<{ x: number; y: number }>
    invalidateRef: MutableRefObject<(() => void) | null>
}

// WebGL is an enhancement. The complete, selectable HTML documents remain
// rendered by DocumentGallery if canvas creation fails or the context is lost.
class StageBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
    state = { failed: false }
    static getDerivedStateFromError() {
        return { failed: true }
    }
    render() {
        return this.state.failed ? null : this.props.children
    }
}

function Podiums({ dark, selected, reducedMotion, pointer, invalidateRef }: StageProps) {
    const group = useRef<Group>(null)
    const { viewport, invalidate, gl } = useThree()
    useEffect(() => {
        invalidateRef.current = invalidate
        return () => {
            invalidateRef.current = null
        }
    }, [invalidate, invalidateRef])
    useEffect(() => {
        const lost = () => {
            // Stop the enhancement; the native document scene stays usable.
            gl.setAnimationLoop(null)
            gl.domElement.style.visibility = 'hidden'
        }
        gl.domElement.addEventListener('webglcontextlost', lost)
        return () => gl.domElement.removeEventListener('webglcontextlost', lost)
    }, [gl])
    useFrame((_, delta) => {
        if (!group.current) return
        const target = reducedMotion ? 0 : pointer.current.x * 0.035
        group.current.rotation.y = reducedMotion
            ? 0
            : MathUtils.damp(group.current.rotation.y, target, 14, Math.min(delta, 0.05))
        if (Math.abs(group.current.rotation.y - target) > 0.0001) invalidate()
    })
    const narrow = viewport.width < 8
    return (
        <>
            <ambientLight intensity={1.8} />
            <directionalLight
                position={[-4, 7, 8]}
                intensity={3}
                color={dark ? '#fff0d5' : '#ffffff'}
            />
            <group ref={group}>
                {[0, 1, 2].map(index => {
                    const offset = (index - selected + 3) % 3
                    const side = offset === 0 ? 0 : offset === 1 ? 1 : -1
                    if (narrow && side !== 0) return null
                    return (
                        <mesh
                            key={index}
                            position={[
                                side * viewport.width * 0.27,
                                -viewport.height / 2 + 0.48,
                                0,
                            ]}
                            rotation={[0.32, -side * 0.12, 0]}
                        >
                            <boxGeometry
                                args={[
                                    narrow ? viewport.width * 0.82 : side === 0 ? 4.1 : 3.7,
                                    side === 0 ? 0.22 : 0.14,
                                    1.5,
                                ]}
                            />
                            <meshStandardMaterial
                                color={
                                    dark
                                        ? side === 0
                                            ? '#b58b53'
                                            : '#47423b'
                                        : side === 0
                                          ? '#254d77'
                                          : '#bac9d6'
                                }
                                metalness={0.22}
                                roughness={0.55}
                            />
                        </mesh>
                    )
                })}
            </group>
        </>
    )
}

export default function DocumentStage(props: StageProps) {
    const [available, setAvailable] = useState(false)
    useEffect(() => {
        const probe = document.createElement('canvas')
        const context = probe.getContext('webgl2')
        setAvailable(Boolean(context))
        context?.getExtension('WEBGL_lose_context')?.loseContext()
    }, [])
    if (!available) return null
    return (
        <StageBoundary>
            <Canvas
                orthographic
                camera={{ position: [0, 0, 12], zoom: 80, near: 0.1, far: 30 }}
                dpr={[1, 1.5]}
                frameloop="demand"
                gl={{ alpha: true, antialias: true, powerPreference: 'low-power' }}
                fallback={null}
                onCreated={({ gl }) => gl.setClearColor(0, 0)}
            >
                <Podiums {...props} />
            </Canvas>
        </StageBoundary>
    )
}
