import { afterEach, expect, it, vi } from 'vitest'
import type { AccountPreferenceRequestContext } from '@/lib/api-client'
import type { AccountContentScope } from '@/contexts/AccountContentScope'

type Element = { type: unknown; props: Record<string, unknown> }
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
function findButton(tree: unknown, text: string) {
  return elements(tree).find(node => node.type === 'button' && label(node).replace(/\s+/g, ' ').includes(text))
}
function click(node: Element) { return (node.props.onClick as () => unknown)() }

async function harness() {
  vi.resetModules()
  let index = 0
  let grants = new Set(['e02', 'e03'])
  const slots: unknown[] = []
  const boundarySlots: unknown[] = []
  let activeSlots = slots
  let accountScope: AccountContentScope | null = null
  const initialSession = { user: { id: 'owner-a' }, session: { token: 'token-a' } }
  let auth = { data: initialSession as typeof initialSession | null, isPending: false, isRefetching: false, error: null as unknown }
  let pathname = '/workspace/resume/edit'
  vi.doMock('@/lib/auth-client', () => ({ useSession: () => auth }))
  vi.doMock('next/navigation', () => ({ usePathname: () => pathname }))
  vi.doMock('react', async importOriginal => ({
    ...await importOriginal<typeof import('react')>(),
    useContext: () => accountScope,
    useEffect: () => { index++ },
    useRef: (initial: unknown) => {
      const slot = index++
      activeSlots[slot] ??= { current: initial }
      return activeSlots[slot]
    },
    useState: (initial: unknown) => {
      const slot = index++; const state = activeSlots
      if (!(slot in state)) state[slot] = typeof initial === 'function' ? (initial as () => unknown)() : initial
      return [state[slot], (next: unknown) => {
        state[slot] = typeof next === 'function' ? (next as (previous: unknown) => unknown)(state[slot]) : next
      }]
    },
  }))
  vi.doMock('@/contexts/EntitlementsContext', () => ({
    useEntitlements: () => {
      const snapshot = grants
      return { can: (feature: string) => snapshot.has(feature) }
    },
  }))
  const api = { evaluateInterviewSimulation: vi.fn().mockResolvedValue({ feedback: [], overall_feedback: 'Admitted feedback' }) }
  vi.doMock('@/lib/api-client', () => ({ apiClient: api }))
  const Component = (await import('@/components/InterviewSimulation')).default
  const Boundary = (await import('@/components/AccountContentBoundary')).default
  const renderBoundary = () => {
    activeSlots = boundarySlots; index = 0
    accountScope = Boundary({ children: null }).props.value as AccountContentScope
    return accountScope
  }
  renderBoundary()
  let ownerReady = true
  let currentScope = {}
  const admittedScope = currentScope
  const props: Parameters<typeof Component>[0] = { authToken: 'token-a', isCurrentSession: () => currentScope === admittedScope, canActForOwner: () => ownerReady && currentScope === admittedScope, prepId: 'prep', questions: [{ question: 'Tell me about a project', category: 'behavioral', what_interviewer_assesses: 'Project experience', star_hint: null }] }
  const render = () => { activeSlots = slots; index = 0; return Component(props) }
  let sourceLease = { ready: true }
  const renewSource = (ready: boolean) => {
    sourceLease.ready = false; sourceLease = { ready }
    const lease = sourceLease
    props.canActForOwner = () => lease.ready && ownerReady && currentScope === admittedScope
  }
  renewSource(true)
  const answer = (tree: unknown) => {
    const field = elements(tree).find(node => node.type === 'textarea')!
    ;(field.props.onChange as (event: unknown) => void)({ target: { value: 'An answer longer than twenty characters' } })
  }
  return { api, render, answer, ready: (value: boolean) => { ownerReady = value; auth = { ...auth, isRefetching: !value }; renderBoundary() },
    invalidate: () => { currentScope = {} }, allow: (features: string[]) => { grants = new Set(features) },
    outerSnapshot: (next: Partial<typeof auth>) => { auth = { ...auth, ...next }; return renderBoundary() },
    outerPath: (next: string) => { pathname = next; return renderBoundary() },
    withoutBoundary: () => { accountScope = null },
    prep: (id: string) => { props.prepId = id },
    renewSource, initialSession,
  }
}

afterEach(() => {
  for (const name of ['react', '@/contexts/EntitlementsContext', '@/lib/api-client', '@/lib/auth-client', 'next/navigation']) vi.doUnmock(name)
  vi.resetModules()
})

it('hides E03 new sessions independently of the E02 prep grant and restores them when allowed', async () => {
  const h = await harness()
  h.allow(['e02'])
  expect(findButton(h.render(), 'Start Coach')).toBeUndefined()
  h.allow(['e03'])
  expect(findButton(h.render(), 'Start Coach')).toBeDefined()
})

it('rejects a retained start callback after E03 revocation without changing the draft', async () => {
  const h = await harness()
  const start = findButton(h.render(), 'Start Coach')!
  h.allow(['e02'])
  h.render()
  click(start)
  expect(elements(h.render()).some(node => node.type === 'textarea')).toBe(false)
  expect(h.api.evaluateInterviewSimulation).not.toHaveBeenCalled()
})

it('hides submission and rejects its retained callback after live E03 revocation', async () => {
  const h = await harness()
  click(findButton(h.render(), 'Start Coach')!)
  h.answer(h.render())
  const submit = findButton(h.render(), 'Finish session')!
  h.allow(['e02'])
  const denied = h.render()
  expect(findButton(denied, 'Finish session')).toBeUndefined()
  expect(elements(denied).find(node => node.type === 'textarea')?.props.value).toContain('An answer')
  await click(submit)
  expect(h.api.evaluateInterviewSimulation).not.toHaveBeenCalled()
  h.allow(['e03'])
  await click(findButton(h.render(), 'Finish session')!)
  expect(h.api.evaluateInterviewSimulation).toHaveBeenCalledExactlyOnceWith('prep', {
    mode: 'coach', answers: [{ question_index: 0, answer: 'An answer longer than twenty characters' }],
  }, expect.objectContaining({ authToken: 'token-a', isCurrent: expect.any(Function) }))
})

it('retains already-admitted feedback after revocation while blocking a new session', async () => {
  const h = await harness()
  let resolve!: (value: { feedback: unknown[]; overall_feedback: string }) => void
  h.api.evaluateInterviewSimulation.mockImplementation(() => new Promise(done => { resolve = done }))
  click(findButton(h.render(), 'Mock mode')!)
  click(findButton(h.render(), 'Start Mock')!)
  h.answer(h.render())
  click(findButton(h.render(), 'Finish session')!)
  h.allow(['e02'])
  h.render()
  resolve({ feedback: [], overall_feedback: 'Admitted feedback' })
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()
  expect(h.api.evaluateInterviewSimulation).toHaveBeenCalledOnce()
  expect(label(h.render())).toContain('Admitted feedback')
  expect(findButton(h.render(), 'Start another session')).toBeUndefined()
  h.allow(['e03'])
  const restart = findButton(h.render(), 'Start another session')!
  h.allow(['e02'])
  h.render()
  click(restart)
  expect(label(h.render())).toContain('Admitted feedback')
})

it('preserves the answer during same-owner auth refresh while retained evaluation stays fenced', async () => {
  const h = await harness()
  click(findButton(h.render(), 'Start Coach')!)
  h.answer(h.render())
  const submit = findButton(h.render(), 'Finish session')!
  h.ready(false)
  expect(findButton(h.render(), 'Finish session')).toBeUndefined()
  await click(submit)
  expect(h.api.evaluateInterviewSimulation).not.toHaveBeenCalled()
  expect(elements(h.render()).find(node => node.type === 'textarea')?.props.value).toContain('An answer')
  h.ready(true)
  await click(findButton(h.render(), 'Finish session')!)
  expect(h.api.evaluateInterviewSimulation).toHaveBeenCalledOnce()
})

it.each(['owner switch', 'A→B→A', 'logout', 'document switch', 'prep switch'])('fences an admitted evaluation and all retained actions after %s', async () => {
  const h = await harness()
  let resolve!: (value: { feedback: unknown[]; overall_feedback: string }) => void
  h.api.evaluateInterviewSimulation.mockImplementation(() => new Promise(done => { resolve = done }))
  click(findButton(h.render(), 'Mock mode')!)
  const start = findButton(h.render(), 'Start Mock')!
  click(start)
  h.answer(h.render())
  const submit = findButton(h.render(), 'Finish session')!
  const pending = click(submit)
  h.invalidate()
  resolve({ feedback: [], overall_feedback: 'Old private feedback' })
  await pending
  await click(start)
  await click(submit)
  expect(label(h.render())).not.toContain('Old private feedback')
  expect(h.api.evaluateInterviewSimulation).toHaveBeenCalledOnce()
})

it('retains an admitted same-owner feedback response while latest source readiness blocks new evaluation', async () => {
  const h = await harness()
  let resolve!: (value: { feedback: unknown[]; overall_feedback: string }) => void
  h.api.evaluateInterviewSimulation.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  click(findButton(h.render(), 'Mock mode')!)
  click(findButton(h.render(), 'Start Mock')!)
  h.answer(h.render())
  const pending = click(findButton(h.render(), 'Finish session')!)
  h.ready(false); h.render()
  resolve({ feedback: [], overall_feedback: 'Owned admitted feedback survives failed source refresh' })
  await pending
  for (let i = 0; i < 4; i++) await Promise.resolve()
  expect(label(h.render())).toContain('Owned admitted feedback survives failed source refresh')
  expect(findButton(h.render(), 'Start another session')).toBeUndefined()
  expect(h.api.evaluateInterviewSimulation).toHaveBeenCalledOnce()
})

it.each(['refetch', 'pending', 'error', 'snapshot'] as const)('retires simulation start and submit leases after an actual outer %s round trip skipped by the child', async change => {
  const h = await harness()
  const start = findButton(h.render(), 'Start Coach')!
  const roundTrip = () => {
    h.outerSnapshot(change === 'refetch' ? { isRefetching: true } : change === 'pending' ? { isPending: true }
      : change === 'error' ? { error: { status: 503 } } : { data: { ...h.initialSession } })
    h.outerSnapshot({ data: h.initialSession, isRefetching: false, isPending: false, error: null })
  }
  roundTrip()
  click(start)
  expect(elements(h.render()).some(node => node.type === 'textarea')).toBe(false)
  click(findButton(h.render(), 'Start Coach')!)
  h.answer(h.render())
  const submit = findButton(h.render(), 'Finish session')!
  roundTrip()
  const fresh = h.render()
  await click(submit)
  expect(h.api.evaluateInterviewSimulation).not.toHaveBeenCalled()
  expect(elements(h.render()).find(node => node.type === 'textarea')?.props.value).toContain('An answer')
  await click(findButton(fresh, 'Finish session')!)
  expect(h.api.evaluateInterviewSimulation).toHaveBeenCalledOnce()
})

it('cannot upgrade a retained evaluation callback to the newest source-ready prop lease', async () => {
  const h = await harness()
  click(findButton(h.render(), 'Start Coach')!)
  h.answer(h.render())
  const submit = findButton(h.render(), 'Finish session')!
  h.renewSource(false); h.render(); h.renewSource(true)
  const fresh = h.render()
  await click(submit)
  expect(h.api.evaluateInterviewSimulation).not.toHaveBeenCalled()
  expect(elements(fresh).find(node => node.type === 'textarea')?.props.value).toContain('An answer')
  await click(findButton(fresh, 'Finish session')!)
  expect(h.api.evaluateInterviewSimulation).toHaveBeenCalledOnce()
})

it.each(['owner', 'route', '401'] as const)('discards admitted feedback after an actual outer %s ABA skipped by the simulation', async change => {
  const h = await harness()
  let resolve!: (value: { feedback: unknown[]; overall_feedback: string }) => void
  h.api.evaluateInterviewSimulation.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  click(findButton(h.render(), 'Mock mode')!)
  click(findButton(h.render(), 'Start Mock')!)
  h.answer(h.render())
  const submit = findButton(h.render(), 'Finish session')!
  const pending = click(submit)
  if (change === 'route') {
    h.outerPath('/workspace/other/edit'); h.outerPath('/workspace/resume/edit')
  } else {
    h.outerSnapshot(change === '401' ? { error: { status: 401 } }
      : { data: { user: { id: 'owner-b' }, session: { token: 'token-b' } } })
    h.outerSnapshot({ data: h.initialSession, error: null })
  }
  resolve({ feedback: [], overall_feedback: 'Old private feedback' }); await pending
  for (let i = 0; i < 4; i++) await Promise.resolve()
  await click(submit)
  expect(h.api.evaluateInterviewSimulation).toHaveBeenCalledOnce()
  expect(label(h.render())).not.toContain('Old private feedback')
})

it('retires a prep incarnation after a retained component sees prep A to B to A', async () => {
  const h = await harness()
  const oldStart = findButton(h.render(), 'Start Coach')!
  h.prep('other'); h.render(); h.prep('prep'); h.render()
  click(oldStart)
  expect(elements(h.render()).some(node => node.type === 'textarea')).toBe(false)
})

it('admits no simulation outside the account boundary even with permissive owner props', async () => {
  const h = await harness()
  h.withoutBoundary()
  expect(findButton(h.render(), 'Start Coach')).toBeUndefined()
})

it.each(['outer refetch', 'source replacement', 'capability revocation', 'owner ABA'] as const)('rejects deferred simulation dispatch after %s without losing the local answer', async change => {
  const h = await harness()
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  let captured!: AccountPreferenceRequestContext
  const dispatch = vi.fn()
  h.api.evaluateInterviewSimulation.mockImplementationOnce(async (_prepId, _body, context: AccountPreferenceRequestContext) => {
    captured = context; await gate
    if (!context.isCurrent()) throw new Error('Account request context changed before dispatch')
    dispatch(); return { feedback: [], overall_feedback: 'Should not dispatch' }
  })
  click(findButton(h.render(), 'Start Coach')!)
  h.answer(h.render())
  click(findButton(h.render(), 'Finish session')!)
  expect(captured.authToken).toBe('token-a'); expect(captured.isCurrent()).toBe(true)
  if (change === 'outer refetch') {
    h.outerSnapshot({ isRefetching: true }); h.outerSnapshot({ isRefetching: false })
  } else if (change === 'source replacement') {
    h.renewSource(false); h.renewSource(true); h.render()
  } else if (change === 'capability revocation') {
    h.allow(['e02']); h.render()
  } else {
    h.outerSnapshot({ data: { user: { id: 'owner-b' }, session: { token: 'token-b' } } })
    h.outerSnapshot({ data: h.initialSession })
  }
  expect(captured.authToken).toBe('token-a'); expect(captured.isCurrent()).toBe(false)
  release()
  for (let i = 0; i < 8; i++) await Promise.resolve()
  expect(dispatch).not.toHaveBeenCalled()
  expect(label(h.render())).not.toContain('Should not dispatch')
  expect(elements(h.render()).find(node => node.type === 'textarea')?.props.value).toContain('An answer')
})
