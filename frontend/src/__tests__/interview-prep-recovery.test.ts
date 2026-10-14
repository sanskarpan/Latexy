import { readFileSync } from 'node:fs'
import { afterEach, expect, it, vi } from 'vitest'
import type { AccountPreferenceRequestContext } from '@/lib/api-client'
import type { InterviewPrepScope } from '@/components/InterviewPrepPanel'
import type { AccountContentScope } from '@/contexts/AccountContentScope'

type Element = { type: unknown; key?: unknown; props: Record<string, unknown> }
function elements(value: unknown): Element[] {
  if (Array.isArray(value)) return value.flatMap(elements)
  if (!value || typeof value !== 'object' || !('props' in value)) return []
  const node = value as Element
  return [node, ...elements(node.props.children)]
}
function label(value: unknown): string {
  if (typeof value === 'string' || typeof value === 'number') return String(value)
  if (Array.isArray(value)) return value.map(label).join(' ')
  return value && typeof value === 'object' && 'props' in value ? label((value as Element).props.children) : ''
}
const button = (tree: unknown, name: string) => elements(tree).find(node => node.type === 'button' && label(node).replace(/\s+/g, ' ').trim() === name)
const click = (node: Element) => (node.props.onClick as () => unknown)()
const session = (owner = 'owner-a', name = owner) => ({ id: 'prep', resume_id: 'resume', user_id: owner, questions: [{ question: `${name} private question`, category: 'behavioral' }], role_title: name, company_name: null, job_description: null, generation_job_id: null, created_at: '2026-10-13T00:00:00Z', updated_at: '2026-10-13T00:00:00Z' })
type Hooks = { slots: Array<{ value?: unknown; deps?: unknown[]; cleanup?: () => void; effect?: () => void | (() => void) }>; effects: Array<() => void>; mounted: boolean }
async function harness(configure?: (api: Record<string, ReturnType<typeof vi.fn>>) => void) {
  vi.resetModules()
  let index = 0
  let grants = new Set(['e02', 'e03']); let loading = false
  const createHooks = (): Hooks => ({ slots: [], effects: [], mounted: true })
  let hooks = createHooks()
  let inner: { key: unknown; hooks: Hooks } | undefined
  const boundaryHooks = createHooks()
  let accountScope: AccountContentScope | null = null
  const initialSession = { user: { id: 'owner-a' }, session: { token: 'token-a' } }
  let auth = { data: initialSession as typeof initialSession | null, isPending: false, isRefetching: false, error: null as unknown }
  let pathname = '/workspace/resume/edit'
  vi.doMock('@/lib/auth-client', () => ({ useSession: () => auth }))
  vi.doMock('next/navigation', () => ({ usePathname: () => pathname }))
  const sameDeps = (a?: unknown[], b?: unknown[]) => Boolean(a && b && a.length === b.length && a.every((item, i) => Object.is(item, b[i])))
  vi.doMock('react', async importOriginal => ({
    ...await importOriginal<typeof import('react')>(),
    useContext: () => accountScope,
    useRef: (initial: unknown) => { const slot = index++; hooks.slots[slot] ??= { value: { current: initial } }; return hooks.slots[slot].value },
    useState: (initial: unknown) => {
      const state = hooks; const slot = index++
      state.slots[slot] ??= { value: typeof initial === 'function' ? (initial as () => unknown)() : initial }
      return [state.slots[slot].value, (next: unknown) => {
        if (state.mounted) state.slots[slot].value = typeof next === 'function' ? (next as (previous: unknown) => unknown)(state.slots[slot].value) : next
      }]
    },
    useCallback: (callback: unknown, deps: unknown[]) => {
      const slot = index++
      if (!hooks.slots[slot] || !sameDeps(hooks.slots[slot].deps, deps)) hooks.slots[slot] = { value: callback, deps }
      return hooks.slots[slot].value
    },
    useEffect: (effect: () => void | (() => void), deps?: unknown[]) => {
      const slot = index++; const state = hooks; const previous = state.slots[slot]
      if (!previous || !sameDeps(previous.deps, deps)) {
        const next = { deps, cleanup: previous?.cleanup, effect }; state.slots[slot] = next
        state.effects.push(() => { next.cleanup?.(); next.cleanup = effect() || undefined })
      }
    },
  }))
  vi.doMock('@/contexts/EntitlementsContext', () => ({ useEntitlements: () => { const snapshot = grants; return { can: (key: string) => snapshot.has(key), loading } } }))
  const stream = { status: 'idle', message: '', percent: 0 }
  const jobStreams = new Map<string, typeof stream>()
  vi.doMock('@/hooks/useJobStream', () => ({ useJobStream: (jobId: string | null) => ({ state: jobId ? jobStreams.get(jobId) ?? stream : { ...stream, status: 'idle' } }) }))
  vi.doMock('@/components/InterviewSimulation', () => ({ default: 'simulation' }))
  const toast = { success: vi.fn(), error: vi.fn() }; vi.doMock('sonner', () => ({ toast }))
  const api = {
    listInterviewPrep: vi.fn().mockResolvedValue([session()]),
    generateInterviewPrep: vi.fn().mockResolvedValue({ prep_id: 'generated', job_id: 'job' }),
    deleteInterviewPrep: vi.fn().mockResolvedValue(undefined),
  }
  configure?.(api); vi.doMock('@/lib/api-client', () => ({ apiClient: api }))
  const Component = (await import('@/components/InterviewPrepPanel')).default
  const Boundary = (await import('@/components/AccountContentBoundary')).default
  const renderBoundary = () => {
    hooks = boundaryHooks; index = 0
    accountScope = Boundary({ children: null }).props.value as AccountContentScope
    return accountScope
  }
  renderBoundary()
  const scopeRef = { current: { ownerId: 'owner-a', authToken: 'token-a', resumeId: 'resume', generation: 0, ready: true, authReady: true, recoveryAvailable: true, recoveryIdentity: accountScope!.recoveryIdentity } as InterviewPrepScope }
  const initialSourceLease = { ready: true }
  let sourceLease = initialSourceLease
  let sourceReady = () => initialSourceLease.ready
  const renewSourceLease = (ready: boolean) => {
    sourceLease.ready = false
    sourceLease = { ready }
    const lease = sourceLease
    sourceReady = () => lease.ready
  }
  const unmount = (state: Hooks) => { state.mounted = false; state.slots.forEach(slot => slot.cleanup?.()); state.effects = [] }
  const expandForm = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(expandForm)
    if (!value || typeof value !== 'object' || !('props' in value)) return value
    const node = value as Element
    if (typeof node.type === 'function' && node.type.name === 'GenerateForm') return expandForm((node.type as (props: unknown) => unknown)(node.props))
    return { ...node, props: { ...node.props, children: expandForm(node.props.children) } }
  }
  const render = () => {
    const tree = Component({ resumeId: scopeRef.current.resumeId, ownerScopeRef: scopeRef, sourceReady }) as Element | null
    if (!tree) { if (inner) unmount(inner.hooks); inner = undefined; return tree }
    if (!inner || inner.key !== tree.key) { if (inner) unmount(inner.hooks); inner = { key: tree.key, hooks: createHooks() } }
    hooks = inner.hooks; index = 0
    return expandForm((tree.type as (props: Record<string, unknown>) => unknown)(tree.props))
  }
  const flush = async () => {
    { const effects = boundaryHooks.effects; boundaryHooks.effects = []; effects.forEach(effect => effect()) }
    if (inner?.hooks.mounted) { const effects = inner.hooks.effects; inner.hooks.effects = []; effects.forEach(effect => effect()) }
    for (let i = 0; i < 12; i++) await Promise.resolve()
  }
  const changeScope = (ownerId: string | null, resumeId = scopeRef.current.resumeId) => {
    auth = { data: ownerId ? { user: { id: ownerId }, session: { token: `token-${ownerId}` } } : null, isPending: false, isRefetching: false, error: null }
    pathname = `/workspace/${resumeId}/edit`; renderBoundary(); renewSourceLease(Boolean(ownerId))
    scopeRef.current = { ownerId, authToken: auth.data?.session.token ?? null, resumeId, generation: scopeRef.current.generation + 1, ready: Boolean(ownerId), authReady: Boolean(ownerId), recoveryAvailable: Boolean(ownerId), recoveryIdentity: accountScope!.recoveryIdentity }
  }
  render(); await flush()
  const replayEffects = () => {
    const slots = inner!.hooks.slots
    slots.forEach(slot => slot.cleanup?.())
    slots.forEach(slot => { if (slot.effect) slot.cleanup = slot.effect() || undefined })
  }
  return { api, toast, render, flush, stream, jobStreams, scopeRef, changeScope, replayEffects, key: () => inner?.key,
    allow: (features: string[], pending = false) => { grants = new Set(features); loading = pending },
    ready: (ready: boolean) => {
      auth = { ...auth, isRefetching: !ready }; renderBoundary(); renewSourceLease(ready)
      scopeRef.current.ready = ready; scopeRef.current.authReady = ready
    },
    sourceReady: (ready: boolean) => { renewSourceLease(ready); scopeRef.current.ready = ready },
    outerSnapshot: (next: Partial<typeof auth>) => { auth = { ...auth, ...next }; return renderBoundary() },
    outerPath: (next: string) => { pathname = next; return renderBoundary() },
    withoutBoundary: () => { accountScope = null },
    initialSession,
  }
}

afterEach(() => {
  for (const name of ['react', '@/contexts/EntitlementsContext', '@/hooks/useJobStream', '@/components/InterviewSimulation', '@/lib/api-client', 'sonner', '@/lib/auth-client', 'next/navigation']) vi.doUnmock(name)
  vi.resetModules()
})

it('reads saved preparation with E02 off/E03 on and retains read/delete recovery with both off', async () => {
  const h = await harness()
  h.allow(['e03'])
  expect(button(h.render(), 'New')).toBeUndefined()
  const simulation = elements(h.render()).find(node => node.type === 'simulation')!
  expect(simulation.props.questions).toEqual(session().questions)
  expect((simulation.props.canActForOwner as () => boolean)()).toBe(true)
  h.allow([])
  const tree = h.render()
  expect(label(tree)).toContain('owner-a')
  expect(button(tree, 'New')).toBeUndefined()
  await click(button(tree, 'Delete')!)
  expect(h.api.deleteInterviewPrep).toHaveBeenCalledExactlyOnceWith('prep', expect.objectContaining({ authToken: 'token-a', isCurrent: expect.any(Function) }))
  expect(button(h.render(), 'Generate Screening Practice')).toBeUndefined()
})

it('distinguishes refresh loading from explicit denial, preserves generation drafts, and fences retained generation', async () => {
  const h = await harness(api => api.listInterviewPrep.mockResolvedValue([]))
  const field = elements(h.render()).find(node => node.type === 'textarea')!
  ;(field.props.onChange as (event: unknown) => void)({ target: { value: 'A valid unsaved job description' } })
  const generate = button(h.render(), 'Generate Screening Practice')!
  h.allow([], true)
  expect(label(h.render())).toContain('Checking interview-prep availability')
  expect(button(h.render(), 'Generate Screening Practice')).toBeUndefined()
  await click(generate)
  h.allow([])
  expect(label(h.render())).toContain('New interview-prep generation is unavailable')
  expect(elements(h.render()).find(node => node.type === 'textarea')?.props.value).toBe('A valid unsaved job description')
  await click(generate)
  expect(h.api.generateInterviewPrep).not.toHaveBeenCalled()
  h.allow(['e02'])
  await click(button(h.render(), 'Generate Screening Practice')!)
  expect(h.api.generateInterviewPrep).toHaveBeenCalledExactlyOnceWith({ resume_id: 'resume', job_description: 'A valid unsaved job description', company_name: undefined, role_title: undefined }, expect.objectContaining({ authToken: 'token-a', isCurrent: expect.any(Function) }))
})

it('same-owner auth refresh retains valid work while retained mutations wait for confirmed authentication', async () => {
  const h = await harness(api => api.listInterviewPrep.mockResolvedValue([]))
  const field = elements(h.render()).find(node => node.type === 'textarea')!
  ;(field.props.onChange as (event: unknown) => void)({ target: { value: 'Preserved same-owner draft' } })
  const generate = button(h.render(), 'Generate Screening Practice')!
  const key = h.key()
  h.ready(false); h.render(); await h.flush()
  await click(generate)
  expect(h.api.generateInterviewPrep).not.toHaveBeenCalled()
  expect(h.key()).toBe(key)
  expect(elements(h.render()).find(node => node.type === 'textarea')?.props.value).toBe('Preserved same-owner draft')
  h.ready(true); h.render(); await h.flush()
  expect(h.api.listInterviewPrep).toHaveBeenCalledOnce()
  expect(elements(h.render()).find(node => node.type === 'textarea')?.props.value).toBe('Preserved same-owner draft')
  await click(button(h.render(), 'Generate Screening Practice')!)
  expect(h.api.generateInterviewPrep).toHaveBeenCalledOnce()
})

for (const operation of ['load', 'generate', 'delete'] as const) {
  it.each(['A→B', 'A→B→A', 'logout→A', 'document change'])(`fences old ${operation} callbacks and admitted responses after %s`, async transition => {
    let resolve!: (value: unknown) => void
    const h = await harness(api => {
      const target = operation === 'load' ? api.listInterviewPrep : operation === 'generate' ? api.generateInterviewPrep : api.deleteInterviewPrep
      target.mockImplementationOnce(() => new Promise(done => { resolve = done }))
    })
    let callback: Element | undefined
    let pending: unknown
    if (operation === 'generate') { await click(button(h.render(), 'New')!); callback = button(h.render(), 'Generate Screening Practice')!; pending = click(callback) }
    if (operation === 'delete') { callback = button(h.render(), 'Delete')!; pending = click(callback) }
    h.api.listInterviewPrep.mockResolvedValue([session('new-owner', 'Current private session')])
    if (transition === 'logout→A') { h.changeScope(null); expect(h.render()).toBeNull(); h.changeScope('owner-a') }
    else if (transition === 'document change') h.changeScope('owner-a', 'new-resume')
    else { h.changeScope('owner-b'); h.render(); await h.flush(); if (transition === 'A→B→A') h.changeScope('owner-a') }
    h.api.listInterviewPrep.mockResolvedValue([session(h.scopeRef.current.ownerId!, 'Current private session')])
    h.render(); await h.flush()
    if (callback) await click(callback)
    resolve(operation === 'load' ? [session('owner-a', 'Old private session')] : operation === 'generate' ? { prep_id: 'old-generated', job_id: 'old-job' } : undefined)
    await pending; await h.flush()
    expect(label(h.render())).not.toContain('Old private session')
    expect(label(h.render())).toContain('Current private session')
    expect(h.toast.success).not.toHaveBeenCalled()
    expect(h.toast.error).not.toHaveBeenCalled()
    if (operation !== 'load') expect(operation === 'generate' ? h.api.generateInterviewPrep : h.api.deleteInterviewPrep).toHaveBeenCalledOnce()
    const simulation = elements(h.render()).find(node => node.type === 'simulation')!
    expect(simulation.props.questions).toEqual(session(h.scopeRef.current.ownerId!, 'Current private session').questions)
  })
}

it('retains a same-owner generation admitted before revocation and recovers its saved output without another generation', async () => {
  let resolve!: (value: { prep_id: string; job_id: string }) => void
  const h = await harness(api => {
    api.listInterviewPrep.mockResolvedValue([])
    api.generateInterviewPrep.mockImplementation(() => new Promise(done => { resolve = done }))
  })
  const generate = button(h.render(), 'Generate Screening Practice')!
  const pending = click(generate)
  await click(generate)
  h.allow([]); h.render()
  resolve({ prep_id: 'admitted', job_id: 'admitted-job' }); await pending
  expect(h.api.generateInterviewPrep).toHaveBeenCalledOnce()
  h.api.listInterviewPrep.mockResolvedValue([{ ...session(), id: 'admitted' }])
  h.stream.status = 'completed'; h.render(); await h.flush()
  expect(elements(h.render()).find(node => node.type === 'simulation')?.props.questions).toEqual(session().questions)
  expect(button(h.render(), 'New')).toBeUndefined()
})

it('preserves editor capability/ACL guards and uses an owned interview recovery shell without changing global permission policy', () => {
  const editor = readFileSync(new URL('../app/workspace/[resumeId]/edit/page.tsx', import.meta.url), 'utf8')
  const recovery = readFileSync(new URL('../hooks/useInterviewPrepRecovery.ts', import.meta.url), 'utf8')
  expect(recovery).toContain("can('e02') || can('e03')")
  expect(recovery).toContain('scopeRef.current !== scope')
  expect(editor).toContain('sourceReady={isSourceReady}')
  expect(editor).toContain('preserveRecovery: latexGeneratorRecovery.mounted || interviewRecovery.mounted')
  expect(editor).toContain('Resume refresh failed:')
  expect(editor).not.toContain('<CapabilityGate feature="e02"><InterviewPrepPanel')
  expect(editor).toContain("can('c01') && collabCanEdit && !currentCheckpointRecoveryPreview")
  const routes = readFileSync(new URL('../../../backend/app/api/interview_routes.py', import.meta.url), 'utf8')
  expect(routes).toContain('InterviewPrep.user_id == user_id')
  expect(routes).toContain('Resume.user_id == user_id')
})

it('reloads after StrictMode effect replay instead of discarding the sole initial read and leaving a spinner', async () => {
  let resolve!: (value: unknown) => void
  const h = await harness(api => api.listInterviewPrep.mockImplementationOnce(() => new Promise(done => { resolve = done })))
  h.replayEffects(); await h.flush()
  resolve([session('owner-a', 'Discarded strict replay request')]); await h.flush()
  expect(h.api.listInterviewPrep).toHaveBeenCalledTimes(2)
  expect(label(h.render())).toContain('owner-a')
  expect(label(h.render())).not.toContain('Discarded strict replay request')
})

it('fences retained new/delete/selector callbacks synchronously before old subtree effect cleanup', async () => {
  const h = await harness()
  const original = h.render()
  const remove = button(original, 'Delete')!
  const newSet = button(original, 'New')!
  const selector = elements(original).find(node => node.type === 'select')!
  h.changeScope('owner-b')
  await click(remove)
  await click(newSet)
  ;(selector.props.onChange as (event: unknown) => void)({ target: { value: 'old-private-prep' } })
  expect(h.api.deleteInterviewPrep).not.toHaveBeenCalled()
  expect(h.api.generateInterviewPrep).not.toHaveBeenCalled()
  h.render(); await h.flush()
  expect(elements(h.render()).find(node => node.type === 'select')?.props.value).toBe('prep')
})

it('shows and retries a failed recovery read without authorizing generation or discarding saved sessions', async () => {
  const h = await harness(api => api.listInterviewPrep.mockRejectedValueOnce(new Error('Recovery read unavailable')))
  h.allow([])
  expect(label(h.render())).toContain('Recovery read unavailable')
  expect(button(h.render(), 'Generate Screening Practice')).toBeUndefined()
  await click(button(h.render(), 'Retry')!)
  expect(elements(h.render()).find(node => node.type === 'simulation')?.props.questions).toEqual(session().questions)
  expect(h.api.generateInterviewPrep).not.toHaveBeenCalled()
})

const chooseSession = (tree: unknown, id: string) => {
  const selector = elements(tree).find(node => node.type === 'select')!
  ;(selector.props.onChange as (event: unknown) => void)({ target: { value: id } })
}
const sessionIds = (tree: unknown) => elements(tree).filter(node => node.type === 'option').map(node => node.props.value)

it.each([false, true])('two deferred deletions in one turn do not resurrect either prep or corrupt selection (selected deleted=%s)', async selectedDeleted => {
  const releases = new Map<string, () => void>()
  const rows = ['first', 'second', 'third'].map(id => ({ ...session(), id, role_title: id }))
  const h = await harness(api => {
    api.listInterviewPrep.mockResolvedValue(rows)
    api.deleteInterviewPrep.mockImplementation((id: string) => new Promise<void>(resolve => { releases.set(id, resolve) }))
  })
  const firstDelete = button(h.render(), 'Delete')!
  chooseSession(h.render(), 'second')
  const secondDelete = button(h.render(), 'Delete')!
  chooseSession(h.render(), selectedDeleted ? 'first' : 'third')
  h.render()
  const first = click(firstDelete); const second = click(secondDelete)
  releases.get('first')!(); releases.get('second')!()
  await Promise.all([first, second])
  expect(sessionIds(h.render())).toEqual(['third'])
  expect(elements(h.render()).find(node => node.type === 'select')?.props.value).toBe('third')
  expect(h.api.deleteInterviewPrep).toHaveBeenCalledTimes(2)
})

it('a stale list admitted before deletion cannot resurrect the deleted prep or erase concurrently generated placeholders', async () => {
  let releaseList!: (rows: unknown) => void
  const original = session()
  const h = await harness(api => {
    api.listInterviewPrep.mockResolvedValueOnce([original]).mockImplementationOnce(() => new Promise(resolve => { releaseList = resolve }))
  })
  await click(button(h.render(), 'New')!)
  await click(button(h.render(), 'Generate Screening Practice')!)
  h.stream.status = 'completed'; h.render(); await h.flush()
  expect(h.api.listInterviewPrep).toHaveBeenCalledTimes(2)
  chooseSession(h.render(), 'prep')
  await click(button(h.render(), 'Delete')!)
  expect(sessionIds(h.render())).toEqual(['generated'])
  releaseList([original]); await h.flush()
  expect(sessionIds(h.render())).toEqual(['generated'])
  expect(elements(h.render()).find(node => node.type === 'select')?.props.value).toBe('generated')
})

it('a late pre-generation list cannot erase a newly admitted generation placeholder', async () => {
  let releaseList!: (rows: unknown) => void
  const original = session()
  const h = await harness(api => {
    api.listInterviewPrep.mockResolvedValueOnce([original]).mockImplementationOnce(() => new Promise(resolve => { releaseList = resolve }))
    api.generateInterviewPrep.mockResolvedValueOnce({ prep_id: 'first-generated', job_id: 'first-job' })
      .mockResolvedValueOnce({ prep_id: 'second-generated', job_id: 'second-job' })
  })
  await click(button(h.render(), 'New')!)
  await click(button(h.render(), 'Generate Screening Practice')!)
  h.stream.status = 'completed'; h.render(); await h.flush()
  expect(h.api.listInterviewPrep).toHaveBeenCalledTimes(2)
  await click(button(h.render(), 'New')!)
  await click(button(h.render(), 'Generate Screening Practice')!)
  releaseList([original]); await h.flush()
  expect(sessionIds(h.render())).toEqual(['second-generated', 'first-generated', 'prep'])
  expect(elements(h.render()).find(node => node.type === 'select')?.props.value).toBe('second-generated')
})

it.each(['stale first', 'fresh first'])('replaces a displaced completion read and recovers generated questions after delete (%s)', async ordering => {
  let releaseOld!: (rows: unknown) => void
  let releaseFresh!: (rows: unknown) => void
  const original = session()
  const h = await harness(api => {
    api.listInterviewPrep.mockResolvedValueOnce([original])
      .mockImplementationOnce(() => new Promise(resolve => { releaseOld = resolve }))
      .mockImplementationOnce(() => new Promise(resolve => { releaseFresh = resolve }))
  })
  await click(button(h.render(), 'New')!)
  await click(button(h.render(), 'Generate Screening Practice')!)
  h.stream.status = 'completed'; h.render(); await h.flush()
  expect(h.api.listInterviewPrep).toHaveBeenCalledTimes(2)
  chooseSession(h.render(), 'prep')
  h.allow([])
  await click(button(h.render(), 'Delete')!)
  expect(h.api.listInterviewPrep).toHaveBeenCalledTimes(3)
  const generated = { ...session(), id: 'generated', role_title: 'Recovered completed prep', questions: [{ question: 'Fresh completed question', category: 'behavioral' }] }
  if (ordering === 'stale first') {
    releaseOld([original]); await h.flush()
    expect(sessionIds(h.render())).toEqual(['generated'])
    releaseFresh([generated]); await h.flush()
  } else {
    releaseFresh([generated]); await h.flush()
    releaseOld([original]); await h.flush()
  }
  expect(sessionIds(h.render())).toEqual(['generated'])
  expect(elements(h.render()).find(node => node.type === 'select')?.props.value).toBe('generated')
  expect(elements(h.render()).find(node => node.type === 'simulation')?.props.questions).toEqual(generated.questions)
  expect(button(h.render(), 'New')).toBeUndefined()
  expect(h.api.generateInterviewPrep).toHaveBeenCalledOnce()
})

it('defers displaced completion recovery during same-owner auth refresh and resumes the read when ready', async () => {
  let releaseOld!: (rows: unknown) => void
  let releaseDelete!: () => void
  const original = session()
  const generated = { ...session(), id: 'generated', role_title: 'Recovered completed prep' }
  const h = await harness(api => {
    api.listInterviewPrep.mockResolvedValueOnce([original])
      .mockImplementationOnce(() => new Promise(resolve => { releaseOld = resolve }))
      .mockResolvedValueOnce([generated])
    api.deleteInterviewPrep.mockImplementationOnce(() => new Promise<void>(resolve => { releaseDelete = resolve }))
  })
  await click(button(h.render(), 'New')!)
  await click(button(h.render(), 'Generate Screening Practice')!)
  h.stream.status = 'completed'; h.render(); await h.flush()
  chooseSession(h.render(), 'prep')
  const deleting = click(button(h.render(), 'Delete')!)
  h.ready(false); h.render(); await h.flush()
  releaseDelete(); await deleting
  releaseOld([original]); await h.flush()
  expect(h.api.listInterviewPrep).toHaveBeenCalledTimes(2)
  expect(sessionIds(h.render())).toEqual(['generated'])
  h.ready(true); h.render(); await h.flush()
  expect(h.api.listInterviewPrep).toHaveBeenCalledTimes(3)
  expect(elements(h.render()).find(node => node.type === 'simulation')?.props.questions).toEqual(generated.questions)
})

it('keeps authenticated read/delete and admitted generation recovery available while latest source readiness denies new E02/E03 work', async () => {
  let releaseGeneration!: (value: unknown) => void
  const h = await harness(api => api.generateInterviewPrep.mockImplementationOnce(() => new Promise(resolve => { releaseGeneration = resolve })))
  await click(button(h.render(), 'New')!)
  const generate = button(h.render(), 'Generate Screening Practice')!
  const admitted = click(generate)
  h.sourceReady(false); h.render()
  await click(generate)
  expect(h.api.generateInterviewPrep).toHaveBeenCalledOnce()
  releaseGeneration({ prep_id: 'generated', job_id: 'owned-job' }); await admitted
  h.api.listInterviewPrep.mockResolvedValue([{ ...session(), id: 'generated' }])
  h.stream.status = 'completed'; h.render(); await h.flush()
  expect(h.api.listInterviewPrep).toHaveBeenCalledTimes(2)
  expect(elements(h.render()).find(node => node.type === 'simulation')?.props.questions).toEqual(session().questions)
  expect((elements(h.render()).find(node => node.type === 'simulation')!.props.canActForOwner as () => boolean)()).toBe(false)
  expect(button(h.render(), 'New')).toBeUndefined()
  await click(button(h.render(), 'Delete')!)
  expect(h.api.deleteInterviewPrep).toHaveBeenCalledExactlyOnceWith('generated', expect.objectContaining({ authToken: 'token-a', isCurrent: expect.any(Function) }))
  expect(button(h.render(), 'Generate Screening Practice')).toBeUndefined()
})

it.each(['idle', 'queued', 'processing'])('keeps the admitted A job watched instead of admitting B while A is %s', async status => {
  const h = await harness(api => api.generateInterviewPrep
    .mockResolvedValueOnce({ prep_id: 'a', job_id: 'job-a' })
    .mockResolvedValueOnce({ prep_id: 'b', job_id: 'job-b' }))
  const newSet = button(h.render(), 'New')!
  await click(newSet)
  const generate = button(h.render(), 'Generate Screening Practice')!
  await click(generate)
  // Retained callbacks cannot race the render after A's POST acknowledgment.
  await click(generate)
  await click(newSet)
  expect(h.api.generateInterviewPrep).toHaveBeenCalledOnce()
  h.jobStreams.set('job-a', { status, message: '', percent: 10 })
  h.render(); await h.flush()
  expect(button(h.render(), 'New')).toBeUndefined()
  expect(elements(h.render()).find(node => node.type === 'select')?.props.value).toBe('a')
  // Existing preparation stays readable and deletable while A runs.
  chooseSession(h.render(), 'prep')
  expect(elements(h.render()).find(node => node.type === 'simulation')?.props.questions).toEqual(session().questions)
  await click(button(h.render(), 'Delete')!)
  expect(h.api.deleteInterviewPrep).toHaveBeenCalledExactlyOnceWith('prep', expect.objectContaining({ authToken: 'token-a', isCurrent: expect.any(Function) }))
  expect(sessionIds(h.render())).toEqual(['a'])
  await click(generate)
  expect(h.api.generateInterviewPrep).toHaveBeenCalledOnce()
  const completedA = { ...session(), id: 'a', role_title: 'Completed A' }
  h.api.listInterviewPrep.mockResolvedValue([completedA])
  h.jobStreams.set('job-a', { status: 'completed', message: '', percent: 100 })
  h.render(); await h.flush()
  expect(elements(h.render()).find(node => node.type === 'simulation')?.props.questions).toEqual(completedA.questions)
  await click(button(h.render(), 'New')!)
  await click(button(h.render(), 'Generate Screening Practice')!)
  expect(h.api.generateInterviewPrep).toHaveBeenCalledTimes(2)
  expect(sessionIds(h.render())).toEqual(['b', 'a'])
})

it.each(['completed', 'failed', 'cancelled'])('restores new generation after an admitted job is %s, once authentication is confirmed', async status => {
  const h = await harness(api => api.generateInterviewPrep
    .mockResolvedValueOnce({ prep_id: 'a', job_id: 'job-a' })
    .mockResolvedValueOnce({ prep_id: 'b', job_id: 'job-b' }))
  await click(button(h.render(), 'New')!)
  await click(button(h.render(), 'Generate Screening Practice')!)
  h.jobStreams.set('job-a', { status, message: '', percent: 100 })
  h.ready(false); h.render(); await h.flush()
  expect(button(h.render(), 'New')).toBeUndefined()
  h.ready(true); h.render(); await h.flush()
  expect(button(h.render(), 'New')).toBeDefined()
  await click(button(h.render(), 'New')!)
  await click(button(h.render(), 'Generate Screening Practice')!)
  expect(h.api.generateInterviewPrep).toHaveBeenCalledTimes(2)
})

it.each(['refetch', 'pending', 'error', 'snapshot'] as const)('never revives retained prep callbacks after an outer %s round trip skipped by the editor', async change => {
  const h = await harness()
  const initial = h.render()
  const remove = button(initial, 'Delete')!
  const newSet = button(initial, 'New')!
  await click(newSet)
  const generate = button(h.render(), 'Generate Screening Practice')!
  const scope = h.scopeRef.current
  h.outerSnapshot(change === 'refetch' ? { isRefetching: true } : change === 'pending' ? { isPending: true }
    : change === 'error' ? { error: { status: 503 } } : { data: { ...h.initialSession } })
  h.outerSnapshot({ data: h.initialSession, isRefetching: false, isPending: false, error: null })
  expect(h.scopeRef.current).toBe(scope)
  expect(scope.ready).toBe(true) // The skipped editor snapshot has stale ready flags.
  await click(generate); await click(remove); await click(newSet)
  expect(h.api.generateInterviewPrep).not.toHaveBeenCalled()
  expect(h.api.deleteInterviewPrep).not.toHaveBeenCalled()
  // New render leases can use the same saved preparation and local draft.
  await click(button(h.render(), 'Generate Screening Practice')!)
  expect(h.api.generateInterviewPrep).toHaveBeenCalledOnce()
})

it('pins a retained generation callback to its exact source-ready lease', async () => {
  const h = await harness()
  await click(button(h.render(), 'New')!)
  const oldGenerate = button(h.render(), 'Generate Screening Practice')!
  h.sourceReady(false); h.sourceReady(true)
  const currentGenerate = button(h.render(), 'Generate Screening Practice')!
  await click(oldGenerate)
  expect(h.api.generateInterviewPrep).not.toHaveBeenCalled()
  await click(currentGenerate)
  expect(h.api.generateInterviewPrep).toHaveBeenCalledOnce()
})

it.each(['owner', 'route', '401'] as const)('fences old prep mutations during an actual outer %s ABA before the editor rerenders', async change => {
  let resolve!: (value: unknown) => void
  const h = await harness(api => api.generateInterviewPrep.mockImplementationOnce(() => new Promise(done => { resolve = done })))
  const initial = h.render()
  const remove = button(initial, 'Delete')!
  const newSet = button(initial, 'New')!
  await click(newSet)
  const generate = button(h.render(), 'Generate Screening Practice')!
  const pending = click(generate)
  if (change === 'route') {
    h.outerPath('/workspace/other/edit'); h.outerPath('/workspace/resume/edit')
  } else {
    h.outerSnapshot(change === '401' ? { error: { status: 401 } }
      : { data: { user: { id: 'owner-b' }, session: { token: 'token-b' } } })
    h.outerSnapshot({ data: h.initialSession, error: null })
  }
  await click(generate); await click(remove); await click(newSet)
  resolve({ prep_id: 'old-private-prep', job_id: 'old-private-job' }); await pending
  expect(h.api.generateInterviewPrep).toHaveBeenCalledOnce()
  expect(h.api.deleteInterviewPrep).not.toHaveBeenCalled()
  expect(h.toast.success).not.toHaveBeenCalled()
  expect(h.render()).toBeNull()
})

it('keeps an admitted generation through actual same-owner refetch while deferring recovery HTTP until a fresh lease', async () => {
  let resolve!: (value: unknown) => void
  const h = await harness(api => api.generateInterviewPrep.mockImplementationOnce(() => new Promise(done => { resolve = done })))
  await click(button(h.render(), 'New')!)
  const pending = click(button(h.render(), 'Generate Screening Practice')!)
  h.outerSnapshot({ isRefetching: true })
  resolve({ prep_id: 'admitted', job_id: 'admitted-job' }); await pending
  h.api.listInterviewPrep.mockResolvedValue([{ ...session(), id: 'admitted' }])
  h.stream.status = 'completed'; h.render(); await h.flush()
  expect(sessionIds(h.render())).toContain('admitted')
  expect(h.api.listInterviewPrep).toHaveBeenCalledOnce()
  h.outerSnapshot({ isRefetching: false }); h.render(); await h.flush()
  expect(h.api.listInterviewPrep).toHaveBeenCalledTimes(2)
  expect(elements(h.render()).find(node => node.type === 'simulation')?.props.questions).toEqual(session().questions)
})

it('fails closed without the outer account boundary even when editor flags say ready', async () => {
  const h = await harness()
  h.withoutBoundary()
  expect(h.render()).toBeNull()
})

it.each(['outer refetch', 'source replacement', 'capability revocation', 'token replacement', 'owner ABA'] as const)('rejects deferred generation dispatch after %s using the captured token and current guard', async change => {
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  const dispatch = vi.fn()
  let captured!: AccountPreferenceRequestContext
  const h = await harness(api => api.generateInterviewPrep.mockImplementationOnce(async (_body, context: AccountPreferenceRequestContext) => {
    captured = context
    await gate
    if (!context.isCurrent()) throw new Error('Account request context changed before dispatch')
    dispatch()
    return { prep_id: 'generated', job_id: 'job' }
  }))
  await click(button(h.render(), 'New')!)
  const field = elements(h.render()).find(node => node.type === 'textarea')!
  ;(field.props.onChange as (event: unknown) => void)({ target: { value: 'My unsent interview draft' } })
  const pending = click(button(h.render(), 'Generate Screening Practice')!)
  expect(captured.authToken).toBe('token-a')
  expect(captured.isCurrent()).toBe(true)
  if (change === 'outer refetch') {
    h.outerSnapshot({ isRefetching: true }); h.outerSnapshot({ isRefetching: false })
  } else if (change === 'source replacement') {
    h.sourceReady(false); h.sourceReady(true); h.render()
  } else if (change === 'capability revocation') {
    h.allow(['e03']); h.render()
  } else if (change === 'token replacement') {
    h.scopeRef.current.authToken = 'replacement-token'
  } else {
    h.outerSnapshot({ data: { user: { id: 'owner-b' }, session: { token: 'token-b' } } })
    h.outerSnapshot({ data: h.initialSession })
  }
  expect(captured.authToken).toBe('token-a')
  expect(captured.isCurrent()).toBe(false)
  release(); await pending
  expect(dispatch).not.toHaveBeenCalled()
  if (change !== 'owner ABA') expect(elements(h.render()).find(node => node.type === 'textarea')?.props.value).toBe('My unsent interview draft')
})

it.each(['load', 'delete'] as const)('fences deferred recovery %s dispatch on outer auth ABA even when the editor flags never changed', async operation => {
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  let captured!: AccountPreferenceRequestContext
  const dispatch = vi.fn()
  const h = await harness(api => {
    const target = operation === 'load' ? api.listInterviewPrep : api.deleteInterviewPrep
    target.mockImplementationOnce(async (_id: string, context: AccountPreferenceRequestContext) => {
      captured = context; await gate
      if (!context.isCurrent()) throw new Error('Account request context changed before dispatch')
      dispatch(); return operation === 'load' ? [session()] : undefined
    })
  })
  const pending = operation === 'delete' ? click(button(h.render(), 'Delete')!) : undefined
  expect(captured.authToken).toBe('token-a'); expect(captured.isCurrent()).toBe(true)
  h.outerSnapshot({ isRefetching: true }); h.outerSnapshot({ isRefetching: false })
  expect(h.scopeRef.current.authReady).toBe(true)
  expect(captured.isCurrent()).toBe(false)
  release(); await pending; await h.flush()
  expect(dispatch).not.toHaveBeenCalled()
})

it('keeps recovery dispatch independent of feature revocation and source availability', async () => {
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  let captured!: AccountPreferenceRequestContext
  const dispatch = vi.fn()
  const h = await harness(api => api.deleteInterviewPrep.mockImplementationOnce(async (_id: string, context: AccountPreferenceRequestContext) => {
    captured = context; await gate
    if (!context.isCurrent()) throw new Error('Account request context changed before dispatch')
    dispatch()
  }))
  const pending = click(button(h.render(), 'Delete')!)
  h.sourceReady(false); h.allow([]); h.render()
  expect(captured.authToken).toBe('token-a'); expect(captured.isCurrent()).toBe(true)
  release(); await pending
  expect(dispatch).toHaveBeenCalledOnce()
  expect(h.toast.success).toHaveBeenCalledWith('Deleted')
})

it.each(['auth first', 'rejection first'] as const)('automatically retries a completion read retired before dispatch (%s)', async order => {
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  let captured!: AccountPreferenceRequestContext
  const completed = { ...session(), id: 'generated', role_title: 'Recovered completion' }
  const h = await harness(api => api.listInterviewPrep.mockResolvedValueOnce([session()])
    .mockImplementationOnce(async (_resumeId, context: AccountPreferenceRequestContext) => {
      captured = context; await gate
      if (!context.isCurrent()) throw new Error('Account request context changed before dispatch')
      return [completed]
    }).mockResolvedValueOnce([completed]))
  await click(button(h.render(), 'New')!)
  await click(button(h.render(), 'Generate Screening Practice')!)
  h.stream.status = 'completed'; h.render(); await h.flush()
  expect(h.api.listInterviewPrep).toHaveBeenCalledTimes(2)
  expect(captured.isCurrent()).toBe(true)
  h.outerSnapshot({ isRefetching: true }); h.render(); await h.flush()
  expect(captured.isCurrent()).toBe(false)
  if (order === 'auth first') {
    h.outerSnapshot({ isRefetching: false }); h.render(); await h.flush()
    release(); await h.flush()
  } else {
    release(); await h.flush()
    h.render(); await h.flush()
    expect(h.api.listInterviewPrep).toHaveBeenCalledTimes(2)
    h.outerSnapshot({ isRefetching: false })
  }
  h.render(); await h.flush()
  expect(h.api.listInterviewPrep).toHaveBeenCalledTimes(3)
  expect(elements(h.render()).find(node => node.type === 'simulation')?.props.questions).toEqual(completed.questions)
  expect(label(h.render())).not.toContain('Account request context changed')
})

it.each(['auth first', 'rejection first'] as const)('retries an initial read canceled before dispatch after confirmed auth (%s)', async order => {
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  const h = await harness(api => api.listInterviewPrep.mockImplementationOnce(async (_resumeId, context: AccountPreferenceRequestContext) => {
    await gate
    if (!context.isCurrent()) throw new Error('Account request context changed before dispatch')
    return [session()]
  }))
  h.outerSnapshot({ isRefetching: true }); h.render(); await h.flush()
  if (order === 'auth first') {
    h.outerSnapshot({ isRefetching: false }); h.render(); await h.flush()
    release(); await h.flush()
  } else {
    release(); await h.flush(); h.render(); await h.flush()
    expect(h.api.listInterviewPrep).toHaveBeenCalledOnce()
    h.outerSnapshot({ isRefetching: false })
  }
  h.render(); await h.flush()
  expect(h.api.listInterviewPrep).toHaveBeenCalledTimes(2)
  expect(elements(h.render()).find(node => node.type === 'simulation')?.props.questions).toEqual(session().questions)
  expect(label(h.render())).not.toContain('Account request context changed')
})

it('does not loop completion recovery on a network or server failure in the current lease', async () => {
  const h = await harness(api => api.listInterviewPrep.mockResolvedValueOnce([session()])
    .mockRejectedValueOnce(new Error('Recovery service temporarily unavailable')))
  await click(button(h.render(), 'New')!)
  await click(button(h.render(), 'Generate Screening Practice')!)
  h.stream.status = 'completed'
  for (let i = 0; i < 4; i++) { h.render(); await h.flush() }
  expect(h.api.listInterviewPrep).toHaveBeenCalledTimes(2)
  expect(label(h.render())).toContain('Recovery service temporarily unavailable')
  const retry = button(h.render(), 'Retry')!
  expect(retry).toBeDefined()
  await click(retry)
  expect(h.api.listInterviewPrep).toHaveBeenCalledTimes(3)
})
