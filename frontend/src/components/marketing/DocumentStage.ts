import {
    ACESFilmicToneMapping,
    AmbientLight,
    BufferGeometry,
    DoubleSide,
    Float32BufferAttribute,
    DirectionalLight,
    Group,
    MathUtils,
    Mesh,
    MeshStandardMaterial,
    OrthographicCamera,
    Scene,
    SRGBColorSpace,
    WebGLRenderer,
} from 'three'

export type DocumentStageState = { dark: boolean; selected: number; reducedMotion: boolean }
type Ref<T> = { current: T }

/** Optional graphics only: HTML papers and controls are owned by DocumentGallery. */
export function mountDocumentStage(
    host: HTMLDivElement,
    state: Ref<DocumentStageState>,
    pointer: Ref<{ x: number; y: number }>,
    invalidateRef: Ref<(() => void) | null>
) {
    const canvas = document.createElement('canvas')
    const unavailable = () => {
        host.dataset.renderer = 'unavailable'
    }
    let context: WebGL2RenderingContext | null
    try {
        context = canvas.getContext('webgl2', {
            alpha: true,
            antialias: true,
            powerPreference: 'low-power',
        })
    } catch {
        unavailable()
        return () => {}
    }
    if (!context) {
        unavailable()
        return () => {}
    }
    let renderer: WebGLRenderer
    try {
        renderer = new WebGLRenderer({
            canvas,
            context,
            alpha: true,
            antialias: true,
            powerPreference: 'low-power',
        })
    } catch {
        context.getExtension('WEBGL_lose_context')?.loseContext()
        unavailable()
        return () => {}
    }
    renderer.setClearColor(0, 0)
    renderer.outputColorSpace = SRGBColorSpace
    renderer.toneMapping = ACESFilmicToneMapping
    canvas.style.width = '100%'
    canvas.style.height = '100%'
    canvas.style.display = 'block'
    host.appendChild(canvas)
    host.dataset.renderer = 'three'

    const scene = new Scene()
    const camera = new OrthographicCamera(-1, 1, 1, -1, 0.1, 30)
    camera.position.z = 12
    const light = new DirectionalLight('#ffffff', 3)
    light.position.set(-4, 7, 8)
    scene.add(new AmbientLight('#ffffff', 1.8), light)
    const group = new Group()
    const materials = [0, 1, 2].map(() => new MeshStandardMaterial({
        metalness: 0.12, roughness: 0.68, side: DoubleSide,
    }))
    // Six folded surfaces, rather than a plinth beneath flat picture frames.
    // Coordinates are rebuilt in CSS pixels on resize, keeping the HTML papers
    // and the architectural surround in the same orthographic composition.
    const folds = [0, 1, 2, 3, 4, 5].map((index) => {
        const mesh = new Mesh(new BufferGeometry(), materials[index % 3])
        group.add(mesh)
        return mesh
    })
    scene.add(group)
    let width = 1
    let height = 1
    let frame: number | null = null
    let previousTime = 0
    let active = true
    let visible = true

    const request = () => {
        if (active && visible && !document.hidden && frame === null)
            frame = requestAnimationFrame(draw)
    }
    const stop = () => {
        if (frame !== null) cancelAnimationFrame(frame)
        frame = null
    }
    const fail = () => {
        active = false
        stop()
        canvas.hidden = true
        unavailable()
    }
    function draw(time: number) {
        frame = null
        if (!active || !visible || document.hidden) return
        const prefs = state.current
        const delta = Math.min((time - previousTime) / 1000 || 1 / 60, 0.05)
        previousTime = time
        const target = prefs.reducedMotion ? 0 : pointer.current.x * 0.035
        group.rotation.y = prefs.reducedMotion
            ? 0
            : MathUtils.damp(group.rotation.y, target, 14, delta)
        materials[0].color.set(prefs.dark ? '#947044' : '#173a60')
        materials[1].color.set(prefs.dark ? '#b18a55' : '#254f77')
        materials[2].color.set(prefs.dark ? '#60482c' : '#102c4b')
        light.color.set(prefs.dark ? '#fff0d5' : '#ffffff')
        try {
            renderer.render(scene, camera)
        } catch {
            fail()
            return
        }
        if (Math.abs(group.rotation.y - target) > 0.0001) request()
    }
    const resize = () => {
        width = Math.max(host.clientWidth, 1)
        height = Math.max(host.clientHeight, 1)
        camera.left = -width / 160
        camera.right = width / 160
        camera.top = height / 160
        camera.bottom = -height / 160
        camera.updateProjectionMatrix()
        type Point = [number, number, number]
        const panel = (index: number, points: Point[]) => {
            const positions = points.flatMap(([x, y, z]) => [
                (x - 0.5) * width / 80, (0.5 - y) * height / 80, z,
            ])
            const geometry = new BufferGeometry()
            geometry.setAttribute('position', new Float32BufferAttribute(positions, 3))
            geometry.setIndex([0, 1, 2, 0, 2, 3])
            geometry.computeVertexNormals()
            folds[index].geometry.dispose()
            folds[index].geometry = geometry
        }
        const narrow = width <= 1000
        const innerLeft = narrow ? 0.16 : 0.37
        const innerRight = 1 - innerLeft
        // Tall open-book wings, a folded floor, and its two visible edges.
        panel(0, [[0.025, 0.10, 0], [innerLeft, 0.16, -0.6], [innerLeft, 0.90, -0.6], [0.025, 0.86, 0]])
        panel(1, [[innerRight, 0.16, -0.6], [0.975, 0.10, 0], [0.975, 0.86, 0], [innerRight, 0.90, -0.6]])
        panel(2, [[0.025, 0.86, 0], [innerLeft, 0.90, -0.6], [0.5, 0.95, 0.9], [0, 0.94, 0.9]])
        panel(3, [[innerRight, 0.90, -0.6], [0.975, 0.86, 0], [1, 0.94, 0.9], [0.5, 0.95, 0.9]])
        panel(4, [[0, 0.94, 0.9], [0.5, 0.95, 0.9], [0.5, 0.97, 0.9], [0, 0.985, 0.9]])
        panel(5, [[0.5, 0.95, 0.9], [1, 0.94, 0.9], [1, 0.985, 0.9], [0.5, 0.97, 0.9]])
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2))
        renderer.setSize(width, height, false)
        request()
    }
    const size = new ResizeObserver(resize)
    size.observe(host)
    const intersection = new IntersectionObserver(entries => {
        visible = entries[0].isIntersecting
        if (visible) request()
        else stop()
    })
    intersection.observe(host)
    const visibility = () => {
        if (document.hidden) stop()
        else request()
    }
    document.addEventListener('visibilitychange', visibility)
    window.addEventListener('resize', resize)
    canvas.addEventListener('webglcontextlost', fail)
    invalidateRef.current = request
    resize()

    return () => {
        active = false
        stop()
        if (invalidateRef.current === request) invalidateRef.current = null
        size.disconnect()
        intersection.disconnect()
        document.removeEventListener('visibilitychange', visibility)
        window.removeEventListener('resize', resize)
        canvas.removeEventListener('webglcontextlost', fail)
        folds.forEach(mesh => mesh.geometry.dispose())
        materials.forEach(material => material.dispose())
        renderer.dispose()
        renderer.forceContextLoss()
        canvas.remove()
    }
}
