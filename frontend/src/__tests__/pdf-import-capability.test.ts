import { afterEach, describe, expect, it, vi } from 'vitest'
import { isValidElement, type ReactElement, type ReactNode } from 'react'
import { apiClient } from '@/lib/api-client'
import PdfImportWizard from '@/components/PdfImportWizard'
import type { EngineCapability } from '@/lib/engine-capability'

type HookRuntime = {
  refs: Array<{ current: unknown }>; values: unknown[]; refCursor: number; stateCursor: number
  effects: Array<() => void | (() => void)>; effectInitialized: boolean
}
const grants = () => ({ b06: true, b08: true, b04: true, b01: true, c01: true })
const state = vi.hoisted(() => ({
  capability: { status: 'loading' } as EngineCapability | { status: 'loading' },
  admitted: { current: null as unknown }, features: {} as Record<string, boolean>, runtime: null as HookRuntime | null,
}))
vi.mock('react', async original => {
  const actual = await original<typeof import('react')>()
  return { ...actual,
    useRef: (initial: unknown) => {
      if (!state.runtime) return state.admitted
      const index = state.runtime.refCursor++
      return state.runtime.refs[index] ??= { current: initial }
    },
    useState: (initial: unknown) => {
      if (!state.runtime) return actual.useState(initial)
      const runtime = state.runtime; const index = runtime.stateCursor++
      if (!(index in runtime.values)) runtime.values[index] = typeof initial === 'function' ? initial() : initial
      return [runtime.values[index], (next: unknown) => {
        runtime.values[index] = typeof next === 'function' ? next(runtime.values[index]) : next
      }]
    },
    useEffect: (effect: () => void | (() => void)) => {
      if (!state.runtime) return actual.useEffect(effect)
      if (!state.runtime.effectInitialized) state.runtime.effects.push(effect)
    },
  }
})
vi.mock('@/contexts/EntitlementsContext', () => ({ useEntitlements: () => {
  const features = state.features
  return { can: (key: string) => features[key] === true }
} }))
vi.mock('@/hooks/useArtifactPreview', () => ({ sha256Bytes: vi.fn(async () => 'fixture-file-sha') }))
vi.mock('@/lib/api-client', () => ({ apiClient: {
  getAuthToken: vi.fn(() => 'fixture-owner-token'), uploadPdfImport: vi.fn(),
  downloadPdfImportOriginal: vi.fn(), adaptPdfImport: vi.fn(),
} }))
vi.mock('@/hooks/useEngineCapability', () => ({ useEngineCapability: () => ({ ...state.capability, checking: state.capability.status === 'loading', retry: vi.fn() }) }))
vi.mock('@/components/PDFPreview', () => ({ default: () => null }))
state.features = grants()
afterEach(() => {
  state.admitted.current = null; state.capability = { status: 'loading' }; state.features = grants(); state.runtime = null
  vi.clearAllMocks()
})

const file = new File(['synthetic PDF'], 'resume.pdf', { type: 'application/pdf' })
const props = { file, title: 'Keep my title', ownerId: 'owner-a', onCreated: vi.fn(), onCancel: vi.fn() }
function wizard(overrides: Partial<typeof props> = {}) {
  const tree = PdfImportWizard({ ...props, ...overrides })
  return tree.props.children[1] as ReactElement<{ enabled?: boolean; uploadEnabled?: boolean; file?: File; title?: string }>
}

describe('PDF import staged rollout gate', () => {
  it.each([{ status: 'loading' }, { status: 'unsupported' }, { status: 'error', reason: 'authorization' }, { status: 'error', reason: 'unavailable' }] as const)('does not mount the uploading wizard for $status', capability => {
    state.capability = capability
    expect(wizard().type).toBe('section')
  })
  it.each(['b06', 'b08'])('does not mount an uploading wizard when %s is denied', feature => {
    state.capability = { status: 'supported' }; state.features = { ...grants(), [feature]: false }
    expect(wizard().type).toBe('section')
  })
  it.each(['b06', 'b08', 'b04', 'b01', 'c01'])('retains reviewed state but disables adaptation when %s is denied', feature => {
    state.capability = { status: 'supported' }
    const original = wizard()
    state.features = { ...grants(), [feature]: false }
    const denied = wizard()
    expect(denied.type).toBe(original.type)
    expect(denied.props.enabled).toBe(false)
    expect(denied.props.uploadEnabled).toBe(!['b06', 'b08'].includes(feature))
  })
  it('passes the exact selected file and title only after support is confirmed', () => {
    state.capability = { status: 'supported' }
    expect(wizard().props).toMatchObject({ file, title: 'Keep my title', enabled: true })
  })
  it('preserves reviewed field state across a same-file recheck while disabling adaptation', () => {
    state.capability = { status: 'supported' }
    const original = wizard()
    state.capability = { status: 'error', reason: 'authorization' }
    expect(wizard().type).toBe(original.type)
    expect(wizard().props.enabled).toBe(false)
    state.capability = { status: 'supported' }
    expect(wizard().type).toBe(original.type)
    expect(wizard().props.enabled).toBe(true)
  })
  it('does not inherit admission for a different account or selected file', () => {
    state.capability = { status: 'supported' }; wizard()
    state.capability = { status: 'unsupported' }
    expect(wizard({ ownerId: 'owner-b' }).type).toBe('section')
    expect(wizard({ file: new File(['other PDF'], 'other.pdf') }).type).toBe('section')
  })
})


type TestElement = ReactElement<{
  children?: ReactNode; disabled?: boolean; revisionLabel?: string; value?: string; onClick?: () => Promise<void>
  onChange?: (event: { target: { value: string } }) => void
}>
function findElement(tree: ReactNode, matches: (node: TestElement) => boolean): TestElement | undefined {
  if (Array.isArray(tree)) return tree.map(child => findElement(child, matches)).find(Boolean)
  if (!isValidElement(tree)) return
  const node = tree as TestElement
  return matches(node) ? node : findElement(node.props.children, matches)
}
function availableHarness() {
  state.capability = { status: 'supported' }
  const selected = wizard()
  const Available = selected.type as (props: typeof selected.props) => ReactElement
  const runtime: HookRuntime = { refs: [], values: [], refCursor: 0, stateCursor: 0, effects: [], effectInitialized: false }
  state.runtime = runtime
  return {
    render(overrides: { enabled?: boolean; uploadEnabled?: boolean } = {}) {
      runtime.refCursor = 0; runtime.stateCursor = 0
      const tree = Available({ ...selected.props, ...overrides })
      runtime.effectInitialized = true
      return tree
    },
    runEffects() { return runtime.effects.map(effect => effect()) },
  }
}

describe('PDF import live mutation admission', () => {
  it.each(['b06', 'b08'])('rechecks %s after file hashing before sending any upload', async feature => {
    let release!: (bytes: ArrayBuffer) => void
    const bytes = new Promise<ArrayBuffer>(resolve => { release = resolve })
    const arrayBuffer = vi.spyOn(file, 'arrayBuffer').mockReturnValue(bytes)
    const harness = availableHarness()
    harness.render()
    const cleanups = harness.runEffects()
    try {
      state.features = { ...grants(), [feature]: false }
      harness.render({ uploadEnabled: false })
      release(new ArrayBuffer(file.size))
      await vi.waitFor(() => {
        const alert = findElement(harness.render({ uploadEnabled: false }), node => node.props.children === 'PDF import is unavailable for your current plan or feature settings.')
        expect(alert).toBeDefined()
      })
      expect(apiClient.uploadPdfImport).not.toHaveBeenCalled()
    } finally {
      cleanups.forEach(cleanup => { if (cleanup) cleanup() })
      arrayBuffer.mockRestore()
    }
  })

  it.each(['b06', 'b08', 'b04', 'b01', 'c01'])('blocks an already-rendered create callback after %s is revoked', async feature => {
    vi.mocked(apiClient.uploadPdfImport).mockResolvedValue({
      import_id: 'fixture-import', original: { filename: file.name, mime_type: 'application/pdf', size_bytes: file.size, sha256: 'fixture-file-sha', preview_url: '/fixture-original' },
      extraction: { status: 'partial', warnings: [], fields: [{ field_id: 'basics.name', node_revision: 'name-revision', label: 'Name', text: 'Reviewed Name', confidence: 'unknown', warnings: [] }] },
      supported_templates: [{ template_id: 'fixture-layout', name: 'Fixture layout', category: 'professional' }], expires_at: null,
    })
    vi.mocked(apiClient.downloadPdfImportOriginal).mockResolvedValue(new Blob(['synthetic PDF'], { type: 'application/pdf' }))
    vi.mocked(apiClient.adaptPdfImport).mockResolvedValue({
      resume_id: 'restored-resume', latex_content: 'Reviewed Name',
      document: { document_id: 'restored-resume', source_mode: 'managed', content_revision: 1, source_sha256: 'adapted-source-sha', structured_version: 1, template_id: 'fixture-layout', nodes: [], opaque_blocks: [] },
      original: { filename: file.name, mime_type: 'application/pdf', size_bytes: file.size, sha256: 'fixture-file-sha', preview_url: '/fixture-original' },
    })
    const harness = availableHarness()
    harness.render()
    const cleanups = harness.runEffects()
    try {
      await vi.waitFor(() => expect(findElement(harness.render(), node => node.type === 'select')).toBeDefined())
      findElement(harness.render(), node => node.type === 'select')!.props.onChange!({ target: { value: 'fixture-layout' } })
      await vi.waitFor(() => expect(findElement(harness.render(), node => node.type === 'button' && node.props.children === 'Create editable resume')!.props.disabled).toBe(false))
      const create = findElement(harness.render(), node => node.type === 'button' && node.props.children === 'Create editable resume')!
      state.features = { ...grants(), [feature]: false }
      const deniedTree = harness.render({ enabled: false, uploadEnabled: !['b06', 'b08'].includes(feature) })
      expect(findElement(deniedTree, node => node.type === 'button' && node.props.children === 'Create editable resume')).toBeUndefined()
      expect(findElement(deniedTree, node => node.type === 'textarea')!.props.value).toBe('Reviewed Name')
      expect(findElement(deniedTree, node => node.type === 'select')).toBeDefined()
      expect(findElement(deniedTree, node => node.props.revisionLabel === 'Original upload · read-only')).toBeDefined()
      await create.props.onClick!()
      expect(apiClient.adaptPdfImport).not.toHaveBeenCalled()
      expect(props.onCreated).not.toHaveBeenCalled()
      state.features = grants()
      harness.render({ enabled: true, uploadEnabled: true })
      await create.props.onClick!()
      expect(apiClient.adaptPdfImport).toHaveBeenCalledOnce()
      expect(apiClient.adaptPdfImport).toHaveBeenCalledWith('fixture-import', expect.objectContaining({
        title: 'Keep my title', template_id: 'fixture-layout', expected_original_sha256: 'fixture-file-sha',
      }), expect.objectContaining({ authToken: 'fixture-owner-token' }))
      expect(props.onCreated).toHaveBeenCalledWith('restored-resume')
    } finally { cleanups.forEach(cleanup => { if (cleanup) cleanup() }) }
  })
})
