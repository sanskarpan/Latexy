import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ProjectEvidence } from '@/lib/api-client'

// Exercise actual component trees, handlers and effects using the repository's
// node-only render harness; these checks do not substitute for browser coverage.
type Element = { type: unknown; props: Record<string, unknown> }
type Slot = { value?: unknown; deps?: unknown[]; cleanup?: () => void }
const MOCKS = ['react', 'react/jsx-runtime', 'react/jsx-dev-runtime', 'react-dom', 'framer-motion', 'lucide-react', '@/contexts/EntitlementsContext', '@/lib/api-client', 'sonner', '@/components/icons/brand-icons', '@/components/ats/ATSCategoryScoreCard', '@/components/ats/ATSRadarChart', '@/components/ScoreHistoryChart']
const PROJECT: ProjectEvidence = {
  source: 'url', title: 'Admitted project', description: 'Preserved description',
  tech: ['TypeScript'], metrics: { stars: 0, forks: 0 }, dates: { last_active: null },
  url: 'https://example.test/project', suggested_bullets: ['Preserved bullet'], raw_excerpt: '',
}
const ANALYSIS = { overall_score: 87, overall_feedback: 'Preserved analysis', sections: [], tokens_used: 123, analysis_time: 1.2 }
function elements(value: unknown): Element[] {
  if (Array.isArray(value)) return value.flatMap(elements)
  if (!value || typeof value !== 'object' || !('props' in value)) return []
  const node = value as Element
  return [node, ...elements(node.props.children)]
}
function text(value: unknown): string {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.map(text).join(' ')
  return value && typeof value === 'object' && 'props' in value ? text((value as Element).props.children) : ''
}
function button(tree: unknown, label: string) {
  const node = elements(tree).find((item) => item.type === 'button' && (text(item).trim() === label || item.props['aria-label'] === label))
  expect(node, label).toBeDefined()
  return node!
}
function hasButton(tree: unknown, label: string) {
  return elements(tree).some((item) => item.type === 'button' && text(item).trim() === label)
}
function field(tree: unknown, name: string) {
  const node = elements(tree).find((item) => item.props.placeholder === name || item.props['aria-label'] === name || item.props.type === name)
  expect(node, name).toBeDefined()
  return node!
}
function click(node: Element) { return (node.props.onClick as () => unknown)() }
function change(node: Element, value: string) { (node.props.onChange as (event: unknown) => void)({ target: { value } }) }
function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}
async function settle() { for (let i = 0; i < 6; i += 1) await Promise.resolve() }

async function harness(kind: 'deep' | 'imports', features = ['g02', 'g03', 'g04', 'd19']) {
  vi.resetModules()
  let index = 0
  let grants = new Set(features)
  const slots: Slot[] = []
  let effects: Array<() => void> = []
  const sameDeps = (a?: unknown[], b?: unknown[]) => Boolean(a && b && a.length === b.length && a.every((value, i) => Object.is(value, b[i])))
  vi.doMock('react', () => ({
    useRef: (initial: unknown) => { const slot = index++; slots[slot] ??= { value: { current: initial } }; return slots[slot].value },
    useState: (initial: unknown) => {
      const slot = index++
      slots[slot] ??= { value: typeof initial === 'function' ? (initial as () => unknown)() : initial }
      return [slots[slot].value, (next: unknown) => {
        slots[slot].value = typeof next === 'function' ? (next as (previous: unknown) => unknown)(slots[slot].value) : next
      }]
    },
    useCallback: (callback: unknown, deps: unknown[]) => {
      const slot = index++
      if (!slots[slot] || !sameDeps(slots[slot].deps, deps)) slots[slot] = { value: callback, deps }
      return slots[slot].value
    },
    useEffect: (effect: () => void | (() => void), deps?: unknown[]) => {
      const slot = index++
      const previous = slots[slot]
      if (previous && sameDeps(previous.deps, deps)) return
      const next = { deps, cleanup: previous?.cleanup }
      slots[slot] = next
      effects.push(() => { next.cleanup?.(); next.cleanup = effect() || undefined })
    },
  }))
  const jsx = (type: unknown, props: Record<string, unknown>) => ({ type, props })
  vi.doMock('react/jsx-runtime', () => ({ jsx, jsxs: jsx, Fragment: 'Fragment' }))
  vi.doMock('react/jsx-dev-runtime', () => ({ jsxDEV: jsx, Fragment: 'Fragment' }))
  vi.doMock('react-dom', () => ({ createPortal: (children: unknown) => children }))
  vi.doMock('framer-motion', () => ({ AnimatePresence: 'AnimatePresence', motion: { div: 'div' } }))
  vi.doMock('lucide-react', () => Object.fromEntries(['Brain', 'X', 'AlertCircle', 'Zap', 'ChevronDown', 'TrendingUp', 'Tag', 'CheckCircle2', 'ExternalLink', 'FileUp', 'Globe', 'Loader2', 'Star'].map((name) => [name, name])))
  vi.doMock('@/components/icons/brand-icons', () => ({ Github: 'Github' }))
  vi.doMock('@/components/ats/ATSCategoryScoreCard', () => ({ default: 'ATSCategoryScoreCard' }))
  vi.doMock('@/components/ats/ATSRadarChart', () => ({ default: 'ATSRadarChart' }))
  vi.doMock('@/components/ScoreHistoryChart', () => ({ default: 'ScoreHistoryChart' }))
  vi.doMock('@/contexts/EntitlementsContext', () => ({ useEntitlements: () => {
    const snapshot = grants
    return { can: (feature: string) => snapshot.has(feature) }
  } }))
  const api = {
    getGitHubStatus: vi.fn().mockResolvedValue({ connected: false }),
    importGitHubProjects: vi.fn().mockResolvedValue({ job_id: 'admitted-job' }),
    getGitHubImportResult: vi.fn().mockResolvedValue({ status: 'completed', projects: [PROJECT] }),
    startGitHubOAuth: vi.fn().mockResolvedValue({ authorization_url: 'https://github.com/login/oauth/authorize?state=test' }),
    importFromUrl: vi.fn().mockResolvedValue({ projects: [PROJECT] }),
    importLinkedIn: vi.fn().mockResolvedValue({ projects: [PROJECT] }),
  }
  vi.doMock('@/lib/api-client', () => ({ apiClient: api }))
  vi.doMock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
  const browser = { innerHeight: 900, location: { pathname: '/try', assign: vi.fn() } }
  vi.stubGlobal('window', browser)
  vi.stubGlobal('document', { body: {}, addEventListener: vi.fn(), removeEventListener: vi.fn() })
  vi.stubGlobal('localStorage', { getItem: vi.fn(), setItem: vi.fn(), removeItem: vi.fn() })
  const Component = kind === 'deep' ? (await import('@/components/ats/DeepAnalysisPanel')).default : (await import('@/components/ImportProjectsModal')).default
  const onRun = vi.fn(), onClose = vi.fn(), onInsert = vi.fn()
  const props: Record<string, unknown> = { isOpen: true, onClose, onRun, onInsert, isLoading: false, isRunning: false, analysis: null, error: null, usesRemaining: null, resumeId: 'saved-resume' }
  const render = (updates: Record<string, unknown> = {}) => {
    Object.assign(props, updates); index = 0
    return (Component as (props: unknown) => unknown)(props)
  }
  const flush = async () => { const queued = effects; effects = []; queued.forEach((effect) => effect()); await settle() }
  return {
    api, browser, onRun, onClose, onInsert, render, flush,
    grants: (next: string[]) => { grants = new Set(next) },
    mount: async (updates: Record<string, unknown> = {}) => {
      render(updates); await flush(); render(); await flush(); render(); await flush()
      return render()
    },
    unmount: () => slots.forEach((slot) => slot.cleanup?.()),
  }
}

afterEach(() => {
  MOCKS.forEach((name) => vi.doUnmock(name))
  vi.unstubAllGlobals(); vi.useRealTimers(); vi.resetModules()
})

describe('deep analysis admission', () => {
  it.each([
    ['Run Deep Analysis', {}], ['Try again', { error: 'Preserved error' }], ['Re-analyse', { analysis: ANALYSIS }],
  ])('hides %s and rejects its retained handler while keeping Close and history', async (label, props) => {
    const h = await harness('deep')
    const oldRun = button(h.render(props), label)
    const denied = h.render({ allowNewActions: false })
    expect(hasButton(denied, label)).toBe(false)
    expect(hasButton(denied, 'General (auto-detect)')).toBe(false)
    await click(oldRun)
    expect(h.onRun).not.toHaveBeenCalled()
    click(button(denied, 'Close')); click(button(denied, 'Score History'))
    expect(h.onClose).toHaveBeenCalledOnce()
    expect(elements(h.render()).some((item) => item.type === 'ScoreHistoryChart')).toBe(true)
    if ('analysis' in props) expect(text(denied)).toContain('Preserved analysis')
    if ('error' in props) expect(text(denied)).toContain('Preserved error')
    await click(button(h.render({ allowNewActions: true }), label))
    expect(h.onRun).toHaveBeenCalledOnce()
  })

  it.each([
    ['Run Deep Analysis', {}], ['Try again', { error: 'Retry this run' }], ['Re-analyse', { analysis: ANALYSIS }],
  ])('keeps %s available with a generic override when D19 is revoked', async (label, props) => {
    const h = await harness('deep', ['d19'])
    const initial = await h.mount()
    const trigger = button(initial, 'General (auto-detect)')
    ;(trigger.props.ref as { current: unknown }).current = { getBoundingClientRect: () => ({ top: 20, bottom: 40, left: 10, width: 300 }) }
    click(trigger)
    const menu = h.render()
    const staleOption = button(menu, 'Healthcare / Clinical')
    click(button(menu, 'Finance / Banking'))
    const oldRun = button(h.render(props), label)
    h.grants([])
    const denied = h.render()
    expect(hasButton(denied, 'Finance / Banking')).toBe(false)
    expect(hasButton(denied, label)).toBe(true)
    click(staleOption)
    await click(oldRun)
    expect(h.onRun).toHaveBeenLastCalledWith(undefined)
    h.grants(['d19'])
    await click(button(h.render(), label))
    expect(h.onRun).toHaveBeenLastCalledWith('finance_banking')
    if ('analysis' in props) expect(text(h.render())).toContain('Preserved analysis')
  })

  it('keeps an admitted analysis visible through completion and re-enable', async () => {
    const h = await harness('deep')
    click(button(h.render(), 'Run Deep Analysis'))
    expect(h.onRun).toHaveBeenCalledOnce()
    expect(text(h.render({ allowNewActions: false, isRunning: true }))).toContain('Analysing your resume')
    const completed = h.render({ isRunning: false, analysis: ANALYSIS })
    expect(text(completed)).toContain('Preserved analysis')
    expect(hasButton(completed, 'Re-analyse')).toBe(false)
    expect(text(h.render({ allowNewActions: true }))).toContain('Preserved analysis')
  })
})

describe('project import admission', () => {
  it('does no initial GitHub work while OFF and restores source controls on re-enable', async () => {
    const h = await harness('imports')
    const denied = await h.mount({ allowNewActions: false })
    expect(h.api.getGitHubStatus).not.toHaveBeenCalled()
    expect(h.api.importGitHubProjects).not.toHaveBeenCalled()
    for (const label of ['GitHub', 'Website', 'LinkedIn']) expect(hasButton(denied, label)).toBe(false)
    click(button(denied, 'Cancel')); click(button(denied, 'Close import projects'))
    expect(h.onClose).toHaveBeenCalledTimes(2)
    const enabled = await h.mount({ allowNewActions: true })
    expect(h.api.getGitHubStatus).toHaveBeenCalledOnce()
    expect(hasButton(enabled, 'Connect public GitHub projects')).toBe(true)
  })

  it.each(['resolve', 'reject'] as const)('cannot start an import from a GitHub check that %ss after OFF/re-enable', async (outcome) => {
    const h = await harness('imports', ['g02'])
    const status = deferred<{ connected: boolean }>()
    h.api.getGitHubStatus.mockReturnValueOnce(status.promise)
    await h.mount(); await h.mount({ allowNewActions: false }); await h.mount({ allowNewActions: true })
    if (outcome === 'resolve') status.resolve({ connected: true })
    else status.reject(new Error('old status failed'))
    await settle()
    expect(h.api.importGitHubProjects).not.toHaveBeenCalled()
    expect(h.api.getGitHubImportResult).not.toHaveBeenCalled()
    expect(h.api.getGitHubStatus).toHaveBeenCalledTimes(2)
  })

  it('blocks a retained OAuth button and late navigation after OFF/re-enable', async () => {
    const h = await harness('imports', ['g02'])
    const connect = button(await h.mount(), 'Connect public GitHub projects')
    h.render({ allowNewActions: false }); await click(connect)
    expect(h.api.startGitHubOAuth).not.toHaveBeenCalled()
    await h.mount({ allowNewActions: true })
    const authorization = deferred<{ authorization_url: string }>()
    h.api.startGitHubOAuth.mockReturnValueOnce(authorization.promise)
    const pending = click(button(h.render(), 'Connect public GitHub projects'))
    await h.mount({ allowNewActions: false }); await h.mount({ allowNewActions: true })
    authorization.resolve({ authorization_url: 'https://github.com/login/oauth/authorize?state=old' }); await pending
    expect(h.browser.location.assign).not.toHaveBeenCalled()
  })

  it('preserves admitted GitHub POST completion and polling through OFF without starting another job', async () => {
    vi.useFakeTimers()
    const h = await harness('imports', ['g02'])
    const admitted = deferred<{ job_id: string }>()
    h.api.getGitHubStatus.mockResolvedValue({ connected: true })
    h.api.importGitHubProjects.mockReturnValueOnce(admitted.promise)
    await h.mount(); await h.mount({ allowNewActions: false })
    admitted.resolve({ job_id: 'admitted-job' }); await settle(); await vi.advanceTimersByTimeAsync(2500)
    const completed = h.render()
    expect(field(completed, 'Project title 1').props.value).toBe('Admitted project')
    expect(h.api.getGitHubImportResult).toHaveBeenCalledWith('admitted-job')
    expect(button(completed, 'Insert into resume').props.disabled).toBe(false)
    await h.mount({ allowNewActions: true })
    expect(h.api.importGitHubProjects).toHaveBeenCalledOnce()
    expect(field(h.render(), 'Project title 1').props.value).toBe('Admitted project')
    h.unmount()
  })

  it.each(['url', 'linkedin'] as const)('hides %s starts, rejects stale handlers, and retains admitted output for insertion', async (source) => {
    const h = await harness('imports', [source === 'url' ? 'g03' : 'g04'])
    let tree = await h.mount()
    if (source === 'url') { change(field(tree, 'url'), 'https://example.test'); tree = h.render() }
    const action = source === 'url' ? () => click(button(tree, 'Import'))
      : () => (field(tree, 'file').props.onChange as (event: unknown) => unknown)({ target: { files: [new File(['resume'], 'resume.pdf')] } })
    const api = source === 'url' ? h.api.importFromUrl : h.api.importLinkedIn
    const denied = h.render({ allowNewActions: false })
    expect(elements(denied).some((item) => item.props.type === 'url' || item.props.type === 'file')).toBe(false)
    await action(); expect(api).not.toHaveBeenCalled()
    await h.mount({ allowNewActions: true })
    const response = deferred<{ projects: ProjectEvidence[] }>()
    api.mockReturnValueOnce(response.promise)
    const pending = action()
    await h.mount({ allowNewActions: false })
    response.resolve({ projects: [PROJECT] }); await pending; await settle()
    const completed = h.render()
    expect(field(completed, 'Project title 1').props.value).toBe('Admitted project')
    change(field(completed, 'Project bullet 1.1'), 'Edited admitted bullet')
    await h.mount({ allowNewActions: true })
    expect(field(h.render(), 'Project bullet 1.1').props.value).toBe('Edited admitted bullet')
    click(button(await h.mount({ allowNewActions: false }), 'Insert into resume'))
    expect(h.onInsert).toHaveBeenCalledOnce()
    expect(h.onInsert.mock.calls[0][0]).toContain('Edited admitted bullet')
    expect(api).toHaveBeenCalledOnce()
  })

  it('rejects late imports after a source switch or source-grant revocation', async () => {
    const h = await harness('imports', ['g03', 'g04'])
    await h.mount(); change(field(h.render(), 'url'), 'https://example.test')
    const response = deferred<{ projects: ProjectEvidence[] }>()
    h.api.importFromUrl.mockReturnValueOnce(response.promise)
    const pending = click(button(h.render(), 'Import'))
    click(button(h.render(), 'LinkedIn')); await h.mount()
    response.resolve({ projects: [PROJECT] }); await pending
    expect(elements(h.render()).some((item) => item.props['aria-label'] === 'Project title 1')).toBe(false)
    const fileResponse = deferred<{ projects: ProjectEvidence[] }>()
    h.api.importLinkedIn.mockReturnValueOnce(fileResponse.promise)
    ;(field(h.render(), 'file').props.onChange as (event: unknown) => void)({ target: { files: [new File(['resume'], 'resume.pdf')] } })
    h.grants([]); await h.mount()
    fileResponse.resolve({ projects: [PROJECT] }); await settle()
    expect(elements(h.render()).some((item) => item.props['aria-label'] === 'Project title 1')).toBe(false)
    expect(button(h.render(), 'Insert into resume').props.disabled).toBe(true)
  })

  it('hides retry while OFF and rejects its retained handler without losing the error', async () => {
    const h = await harness('imports', ['g03'])
    await h.mount(); change(field(h.render(), 'url'), 'https://example.test')
    h.api.importFromUrl.mockRejectedValueOnce(new Error('Preserved import error'))
    await click(button(h.render(), 'Import'))
    const retry = button(h.render(), 'Try again')
    const denied = h.render({ allowNewActions: false })
    expect(text(denied)).toContain('Preserved import error')
    expect(hasButton(denied, 'Try again')).toBe(false)
    await click(retry)
    expect(text(h.render())).toContain('Preserved import error')
    expect(hasButton(h.render({ allowNewActions: true }), 'Try again')).toBe(true)
  })
})
