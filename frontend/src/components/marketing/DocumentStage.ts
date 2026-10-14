import {
    ACESFilmicToneMapping,
    AmbientLight,
    BoxGeometry,
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
    const geometry = new BoxGeometry(1, 1, 1)
    const selectedMaterial = new MeshStandardMaterial({ metalness: 0.22, roughness: 0.55 })
    const sideMaterial = new MeshStandardMaterial({ metalness: 0.22, roughness: 0.55 })
    const podiums = [0, 1, 2].map(() => {
        const mesh = new Mesh(geometry, sideMaterial)
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
        selectedMaterial.color.set(prefs.dark ? '#b58b53' : '#254d77')
        sideMaterial.color.set(prefs.dark ? '#47423b' : '#bac9d6')
        light.color.set(prefs.dark ? '#fff0d5' : '#ffffff')
        podiums.forEach((mesh, index) => {
            const offset = (index - prefs.selected + 3) % 3
            const side = offset === 0 ? 0 : offset === 1 ? 1 : -1
            const narrow = width <= 700
            mesh.visible = !narrow || side === 0
            mesh.position.set(
                ((side * width) / 80) * (width <= 1100 ? 0.3 : 0.27),
                -height / 160 + 0.48,
                0
            )
            const paperWidth = narrow
                ? Math.min(360, width - 32)
                : side === 0
                  ? 360
                  : width <= 1100
                    ? 270
                    : 320
            mesh.scale.set((paperWidth + 16) / 80, side === 0 ? 0.22 : 0.14, 1.5)
            mesh.rotation.set(0.32, -side * 0.12, 0)
            mesh.material = side === 0 ? selectedMaterial : sideMaterial
        })
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
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5))
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
        geometry.dispose()
        selectedMaterial.dispose()
        sideMaterial.dispose()
        renderer.dispose()
        renderer.forceContextLoss()
        canvas.remove()
    }
}
