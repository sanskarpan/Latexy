import { afterEach, describe, expect, it, vi } from 'vitest'

type ModalProps = { open: boolean; ownerId: string | null; onClose: () => void }
type HookSlot = { value?: unknown; deps?: unknown[]; cleanup?: () => void }
type Deferred<T> = { promise: Promise<T>; resolve: (value: T) => void; reject: (reason: unknown) => void }

function deferred<T>(): Deferred<T> {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((accept, fail) => { resolve = accept; reject = fail })
  return { promise, resolve, reject }
}

function textContent(node: unknown): string {
  if (node == null || typeof node === 'boolean') return ''
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(textContent).join('')
  if (typeof node === 'object' && 'props' in node) {
    const element = node as { type?: unknown; props?: Record<string, unknown> }
    if (typeof element.type === 'function') {
      return textContent((element.type as (props: Record<string, unknown>) => unknown)(element.props ?? {}))
    }
    return textContent(element.props?.children)
  }
  return ''
}

function findInput(node: unknown): { props: Record<string, unknown> } | null {
  if (Array.isArray(node)) {
    for (const child of node) {
      const match = findInput(child)
      if (match) return match
    }
    return null
  }
  if (node == null || typeof node !== 'object' || !('type' in node)) return null
  const element = node as { type: unknown; props: Record<string, unknown> }
  if (element.type === 'input') return element
  return findInput(element.props.children)
}

async function mountModal(initialOwnerId: string) {
  vi.resetModules()
  const slots: HookSlot[] = []
  let hookIndex = 0
  let scheduledEffects: Array<{ index: number; effect: () => void | (() => void) }> = []
  let mounted = true
  const searchResumes = vi.fn<(...args: unknown[]) => Promise<unknown>>()

  vi.doMock('react', () => ({
    useRef: (initial: unknown) => {
      const index = hookIndex++
      slots[index] ??= { value: { current: initial } }
      return slots[index].value
    },
    useState: (initial: unknown) => {
      const index = hookIndex++
      slots[index] ??= { value: typeof initial === 'function' ? (initial as () => unknown)() : initial }
      return [slots[index].value, (next: unknown) => {
        const previous = slots[index].value
        slots[index].value = typeof next === 'function' ? (next as (value: unknown) => unknown)(previous) : next
      }]
    },
    useCallback: (callback: unknown) => callback,
    useEffect: (effect: () => void | (() => void), deps?: unknown[]) => {
      const index = hookIndex++
      const previous = slots[index]
      const changed = !previous || !deps || !previous.deps || deps.length !== previous.deps.length || deps.some((value, at) => !Object.is(value, previous.deps?.[at]))
      if (changed) {
        if (previous?.cleanup) scheduledEffects.push({ index, effect: () => { previous.cleanup?.(); return effect() } })
        else scheduledEffects.push({ index, effect })
        slots[index] = { ...previous, deps }
      }
    },
  }))
  vi.doMock('react/jsx-runtime', () => ({
    Fragment: 'Fragment',
    jsx: (type: unknown, props: Record<string, unknown>) => ({ type, props }),
    jsxs: (type: unknown, props: Record<string, unknown>) => ({ type, props }),
  }))
  vi.doMock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))
  vi.doMock('lucide-react', () => ({ Search: 'Search', X: 'X', FileText: 'FileText', Clock: 'Clock' }))
  vi.doMock('@/lib/api-client', () => ({ apiClient: { searchResumes } }))

  const { default: ProjectSearchModal } = await import('@/components/ProjectSearchModal')
  let props: ModalProps = { open: true, ownerId: initialOwnerId, onClose: vi.fn() }
  const render = (nextProps: ModalProps = props) => {
    if (!mounted) throw new Error('Cannot render an unmounted modal')
    props = nextProps
    hookIndex = 0
    scheduledEffects = []
    const tree = ProjectSearchModal(nextProps as never)
    const effects = scheduledEffects
    scheduledEffects = []
    for (const scheduled of effects) {
      const cleanup = scheduled.effect()
      slots[scheduled.index].cleanup = typeof cleanup === 'function' ? cleanup : undefined
    }
    return tree
  }
  const enterQuery = (query: string) => {
    const input = findInput(render())
    if (!input) throw new Error('Search input was not rendered')
    const onChange = input.props.onChange as ((event: { target: { value: string } }) => void) | undefined
    if (!onChange) throw new Error('Search input has no change handler')
    onChange({ target: { value: query } })
    vi.advanceTimersByTime(300)
  }
  const unmount = () => {
    if (!mounted) return
    mounted = false
    for (const slot of slots) slot.cleanup?.()
  }

  return { render, enterQuery, unmount, searchResumes }
}

const privateResult = (resumeId: string, title: string, content: string) => ({
  resume_id: resumeId,
  resume_title: title,
  updated_at: '2026-10-16T12:00:00Z',
  matches: [{
    line_number: 7,
    line_content: content,
    context_before: [],
    context_after: [],
    highlight_start: 0,
    highlight_end: content.length,
  }],
})

afterEach(() => {
  vi.useRealTimers()
  for (const name of ['react', 'react/jsx-runtime', 'next/navigation', 'lucide-react', '@/lib/api-client']) vi.doUnmock(name)
  vi.resetModules()
})

describe('workspace search owner isolation', () => {
  it('hides old results immediately and ignores a late successful response after an account switch', async () => {
    vi.useFakeTimers()
    const h = await mountModal('account-a')
    const pending = deferred<{ results: ReturnType<typeof privateResult>[] }>()
    h.searchResumes.mockReturnValueOnce(pending.promise)
    h.render()
    h.enterQuery('shared phrase')
    expect(h.searchResumes).toHaveBeenCalledWith('shared phrase')

    const switched = h.render({ open: true, ownerId: 'account-b', onClose: vi.fn() })
    expect(findInput(switched)?.props.value).toBe('')
    expect(textContent(switched)).not.toContain('Account A Private Resume')

    pending.resolve({ results: [privateResult('resume-a', 'Account A Private Resume', 'A secret phrase')] })
    await pending.promise
    const afterLateResponse = h.render()
    expect(textContent(afterLateResponse)).not.toContain('Account A Private Resume')
    expect(textContent(afterLateResponse)).not.toContain('A secret phrase')
  })

  it('ignores an old account’s late search error after switching accounts', async () => {
    vi.useFakeTimers()
    const h = await mountModal('account-a')
    const pending = deferred<never>()
    h.searchResumes.mockReturnValueOnce(pending.promise)
    h.render()
    h.enterQuery('shared phrase')

    h.render({ open: true, ownerId: 'account-b', onClose: vi.fn() })
    pending.reject(new Error('Account A search failed privately'))
    await pending.promise.catch(() => undefined)

    const afterLateError = h.render()
    expect(textContent(afterLateError)).not.toContain('Account A search failed privately')
    expect(textContent(afterLateError)).not.toContain('Account A Private Resume')
  })

  it('runs the same query against the new account after removing the previous account’s result', async () => {
    vi.useFakeTimers()
    const h = await mountModal('account-a')
    const accountASearch = deferred<{ results: ReturnType<typeof privateResult>[] }>()
    const accountBSearch = deferred<{ results: ReturnType<typeof privateResult>[] }>()
    h.searchResumes.mockReturnValueOnce(accountASearch.promise).mockReturnValueOnce(accountBSearch.promise)
    h.render()
    h.enterQuery('same query')
    accountASearch.resolve({ results: [privateResult('resume-a', 'Account A Private Resume', 'A secret phrase')] })
    await accountASearch.promise
    expect(textContent(h.render())).toContain('Account A Private Resume')

    const switched = h.render({ open: true, ownerId: 'account-b', onClose: vi.fn() })
    expect(findInput(switched)?.props.value).toBe('')
    expect(textContent(switched)).not.toContain('Account A Private Resume')

    h.enterQuery('same query')
    expect(h.searchResumes).toHaveBeenLastCalledWith('same query')
    accountBSearch.resolve({ results: [privateResult('resume-b', 'Account B Resume', 'B visible phrase')] })
    await accountBSearch.promise

    const afterSwitch = h.render()
    expect(textContent(afterSwitch)).toContain('Account B Resume')
    expect(textContent(afterSwitch)).toContain('B visible phrase')
    expect(textContent(afterSwitch)).not.toContain('Account A Private Resume')
    expect(textContent(afterSwitch)).not.toContain('A secret phrase')
  })

  it('allows a fresh identical query after logout and relogin without restoring the previous account’s result', async () => {
    vi.useFakeTimers()
    const accountA = await mountModal('account-a')
    const oldSearch = deferred<{ results: ReturnType<typeof privateResult>[] }>()
    accountA.searchResumes.mockReturnValueOnce(oldSearch.promise)
    accountA.render()
    accountA.enterQuery('same query')
    accountA.unmount()

    oldSearch.resolve({ results: [privateResult('resume-a', 'Account A Private Resume', 'A secret phrase')] })
    await oldSearch.promise

    const accountB = await mountModal('account-b')
    const newSearch = deferred<{ results: ReturnType<typeof privateResult>[] }>()
    accountB.searchResumes.mockReturnValueOnce(newSearch.promise)
    accountB.render()
    accountB.enterQuery('same query')
    expect(accountB.searchResumes).toHaveBeenCalledWith('same query')
    newSearch.resolve({ results: [privateResult('resume-b', 'Account B Resume', 'B visible phrase')] })
    await newSearch.promise

    const afterRelogin = accountB.render()
    expect(textContent(afterRelogin)).toContain('Account B Resume')
    expect(textContent(afterRelogin)).toContain('B visible phrase')
    expect(textContent(afterRelogin)).not.toContain('Account A Private Resume')
    expect(textContent(afterRelogin)).not.toContain('A secret phrase')
  })
})
