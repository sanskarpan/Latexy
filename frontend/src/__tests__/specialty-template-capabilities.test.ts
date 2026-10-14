import { readFileSync } from 'node:fs'
import { afterEach, expect, it, vi } from 'vitest'

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

async function harness(authenticated = true, initiallySpecialty = true, configure?: (api: Record<string, ReturnType<typeof vi.fn>>) => void) {
  vi.resetModules()
  let index = 0
  let grants = new Set(['b04', 'b01', 'c01', ...(initiallySpecialty ? ['b05'] : [])])
  const slots: Array<{ value?: unknown; deps?: unknown[]; cleanup?: () => void }> = []
  let effects: Array<() => void> = []
  const sameDeps = (a?: unknown[], b?: unknown[]) => Boolean(a && b && a.length === b.length && a.every((item, i) => Object.is(item, b[i])))
  const memo = (callback: () => unknown, deps: unknown[]) => {
    const slot = index++
    if (!slots[slot] || !sameDeps(slots[slot].deps, deps)) slots[slot] = { value: callback(), deps }
    return slots[slot].value
  }
  vi.doMock('react', async importOriginal => ({
    ...await importOriginal<typeof import('react')>(),
    useRef: (initial: unknown) => { const slot = index++; slots[slot] ??= { value: { current: initial } }; return slots[slot].value },
    useState: (initial: unknown) => {
      const slot = index++; slots[slot] ??= { value: typeof initial === 'function' ? (initial as () => unknown)() : initial }
      return [slots[slot].value, (next: unknown) => { slots[slot].value = typeof next === 'function' ? (next as (previous: unknown) => unknown)(slots[slot].value) : next }]
    },
    useCallback: (callback: unknown, deps: unknown[]) => memo(() => callback, deps),
    useMemo: memo,
    useEffect: (effect: () => void | (() => void), deps?: unknown[]) => {
      const slot = index++; const previous = slots[slot]
      if (!previous || !sameDeps(previous.deps, deps)) {
        const next = { deps, cleanup: previous?.cleanup }; slots[slot] = next
        effects.push(() => { next.cleanup?.(); next.cleanup = effect() || undefined })
      }
    },
  }))
  vi.doMock('@/contexts/EntitlementsContext', () => ({ useEntitlements: () => {
    const snapshot = grants; return { can: (key: string) => snapshot.has(key) }
  } }))
  let auth: { data: { user: { id: string }; session?: { token: string } } | null; isPending: boolean; isRefetching: boolean; error: unknown } = {
    data: authenticated ? { user: { id: 'owner' }, session: { token: 'owner-token' } } : null, isPending: false, isRefetching: false, error: null,
  }
  vi.doMock('@/lib/auth-client', () => ({ useSession: () => auth }))
  let recoveryIdentity = {}; let admissionIdentity = {}
  const makeScope = () => {
    const recovery = recoveryIdentity; const admission = admissionIdentity
    return { recoveryIdentity: recovery, isCurrent: () => recovery === recoveryIdentity,
      isAdmissionCurrent: () => recovery === recoveryIdentity && admission === admissionIdentity,
      canAdmit: () => recovery === recoveryIdentity && admission === admissionIdentity }
  }
  let accountScope: ReturnType<typeof makeScope> | null = makeScope()
  vi.doMock('@/contexts/AccountContentScope', () => ({ useAccountContentScope: () => accountScope }))
  const router = { push: vi.fn(), replace: vi.fn() }
  vi.doMock('next/navigation', () => ({ useRouter: () => router }))
  const toast = Object.assign(vi.fn(), { success: vi.fn(), error: vi.fn() })
  vi.doMock('sonner', () => ({ toast }))
  vi.doMock('@/components/TemplateCard', () => ({ default: 'template-card' }))
  vi.doMock('@/components/TemplatePreviewModal', () => ({ default: 'template-preview' }))
  vi.stubGlobal('window', { addEventListener: vi.fn(), removeEventListener: vi.fn(), location: { search: '' }, prompt: vi.fn(() => 'en') })
  const templates = ['professional', 'academic', 'regional', 'presentation'].map(category => ({
    id: category, category, name: `${category} template`, category_label: category, description: '', tags: [],
  }))
  const permittedRows = () => templates.filter(template => grants.has('b05') || template.category === 'professional')
  const api = { getTemplates: vi.fn().mockImplementation(async () => permittedRows()), getTemplateCategories: vi.fn().mockImplementation(async () => permittedRows().map(template => ({ category: template.category, label: template.category, count: 1 }))), useTemplate: vi.fn().mockResolvedValue({ resume_id: 'created' }) }
  configure?.(api)
  vi.doMock('@/lib/api-client', () => ({ apiClient: api }))
  const Component = (await import('@/app/templates/page')).default
  const render = () => { index = 0; return Component() }
  const flush = async () => { const queued = effects; effects = []; queued.forEach(effect => effect()); for (let i = 0; i < 8; i++) await Promise.resolve() }
  render(); await flush()
  const cards = (tree: unknown) => elements(tree).filter(node => node.type === 'template-card')
  const card = (tree: unknown, id: string) => cards(tree).find(node => (node.props.template as { id: string }).id === id)!
  const preview = (tree: unknown) => elements(tree).find(node => node.type === 'template-preview')!
  return { api, router, toast, render, flush, card, cards, preview,
    session: (patch: Partial<typeof auth>) => { auth = { ...auth, ...patch } },
    removeOuterScope: () => { accountScope = null },
    advanceOuterScope: (newRecovery = false) => { if (newRecovery) recoveryIdentity = {}; admissionIdentity = {}; accountScope = makeScope() },
    allow: (keys: string[]) => { grants = new Set(keys) } }
}

afterEach(() => {
  for (const name of ['react', '@/contexts/AccountContentScope', '@/contexts/EntitlementsContext', '@/lib/auth-client', '@/lib/api-client', 'next/navigation', 'sonner', '@/components/TemplateCard', '@/components/TemplatePreviewModal']) vi.doUnmock(name)
  vi.unstubAllGlobals(); vi.resetModules()
})

it.each([true, false])('hides cached specialty cards/categories on B05 revocation while preserving regular browse (authenticated=%s)', async authenticated => {
  const h = await harness(authenticated)
  expect(h.cards(h.render())).toHaveLength(4)
  h.allow(['b04', 'b01', 'c01'])
  const tree = h.render()
  expect(h.cards(tree).map(node => (node.props.template as { id: string }).id)).toEqual(['professional'])
  const buttons = elements(tree).filter(node => node.type === 'button').map(label)
  expect(buttons.some(text => text.includes('academic'))).toBe(false)
  expect(buttons.some(text => text.includes('regional'))).toBe(false)
  expect(buttons.some(text => text.includes('presentation'))).toBe(false)
  expect(buttons.some(text => text.replace(/\s+/g, ' ').includes('All ( 1 )'))).toBe(true)
  h.allow(['b04', 'b05', 'b01', 'c01'])
  expect(h.cards(h.render())).toHaveLength(4)
})

it.each(['academic', 'regional', 'presentation'])('denies a retained %s preview/use callback and masks its open preview after revocation', async id => {
  const h = await harness()
  const oldCard = h.card(h.render(), id)
  const open = oldCard.props.onPreview as (id: string) => void
  const use = oldCard.props.onSelect as (id: string) => Promise<boolean>
  open(id)
  expect(h.preview(h.render()).props.templateId).toBe(id)
  h.allow(['b04', 'b01', 'c01'])
  expect(h.preview(h.render()).props.templateId).toBeNull()
  open(id)
  expect(h.preview(h.render()).props.templateId).toBeNull()
  expect(await use(id)).toBe(false)
  expect(h.api.useTemplate).not.toHaveBeenCalled()
  const regular = h.card(h.render(), 'professional')
  ;(regular.props.onPreview as (id: string) => void)('professional')
  expect(h.preview(h.render()).props.templateId).toBe('professional')
  expect(await (regular.props.onSelect as (id: string) => Promise<boolean>)('professional')).toBe(true)
  expect(h.api.useTemplate).toHaveBeenCalledExactlyOnceWith('professional', undefined, undefined, expect.objectContaining({ authToken: 'owner-token', isCurrent: expect.any(Function) }))
})

it('keeps an unrelated search and specialty selection preference while exposing permitted cards during revocation', async () => {
  const h = await harness()
  const search = elements(h.render()).find(node => node.type === 'input' && node.props.id === 'template-search')!
  ;(search.props.onChange as (event: unknown) => void)({ target: { value: 'template' } })
  const category = elements(h.render()).find(node => node.type === 'button' && label(node).includes('academic'))!
  ;(category.props.onClick as () => void)()
  expect(h.cards(h.render()).map(node => (node.props.template as { id: string }).id)).toEqual(['academic'])
  h.allow(['b04', 'b01', 'c01'])
  expect(h.cards(h.render()).map(node => (node.props.template as { id: string }).id)).toEqual(['professional'])
  expect(elements(h.render()).find(node => node.type === 'input' && node.props.id === 'template-search')?.props.value).toBe('template')
  h.allow(['b04', 'b05', 'b01', 'c01'])
  expect(h.cards(h.render()).map(node => (node.props.template as { id: string }).id)).toEqual(['academic'])
})

it('matches the server specialty categories exactly', async () => {
  const h = await harness()
  h.allow(['b04'])
  expect(h.cards(h.render())).toHaveLength(1)
  const server = readFileSync(new URL('../../../backend/app/api/template_routes.py', import.meta.url), 'utf8')
  expect(server).toContain('{"academic", "regional", "presentation"}')
})

it('keeps the owned outcome of an already-admitted template use after specialty revocation', async () => {
  const h = await harness()
  let resolve!: (result: { resume_id: string }) => void
  h.api.useTemplate.mockImplementation(() => new Promise(done => { resolve = done }))
  const use = h.card(h.render(), 'academic').props.onSelect as (id: string) => Promise<boolean>
  const pending = use('academic')
  expect(h.api.useTemplate).toHaveBeenCalledOnce()
  h.allow(['b04', 'b01', 'c01'])
  h.render()
  resolve({ resume_id: 'created' })
  expect(await pending).toBe(true)
  expect(h.router.push).toHaveBeenCalledExactlyOnceWith('/workspace/created/edit')
})

it.each(['pending', 'refetching', 'error'] as const)('blocks retained template creation during %s and never revives its old admission', async state => {
  const h = await harness()
  const oldUse = h.card(h.render(), 'academic').props.onSelect as (id: string) => Promise<boolean>
  h.session({ isPending: state === 'pending', isRefetching: state === 'refetching', error: state === 'error' ? new Error('offline') : null })
  expect(h.card(h.render(), 'academic').props.allowUse).toBe(false)
  expect(await oldUse('academic')).toBe(false)
  expect(h.api.useTemplate).not.toHaveBeenCalled()
  h.session({ isPending: false, isRefetching: false, error: null }); h.render()
  expect(await oldUse('academic')).toBe(false)
  const freshUse = h.card(h.render(), 'academic').props.onSelect as (id: string) => Promise<boolean>
  expect(await freshUse('academic')).toBe(true)
  expect(h.api.useTemplate).toHaveBeenCalledOnce()
})

it('does not let a stale authenticated callback create work after a completed 401 with stale session data', async () => {
  const h = await harness()
  const oldUse = h.card(h.render(), 'academic').props.onSelect as (id: string) => Promise<boolean>
  h.session({ error: { status: 401 } }); h.render()
  expect(await oldUse('academic')).toBe(false)
  expect(h.api.useTemplate).not.toHaveBeenCalled()
  expect(h.router.push).not.toHaveBeenCalled()
})

it('respects the outer admission lease even when the child skips the uncertainty render', async () => {
  const h = await harness()
  const oldUse = h.card(h.render(), 'academic').props.onSelect as (id: string) => Promise<boolean>
  h.advanceOuterScope()
  expect(await oldUse('academic')).toBe(false)
  h.render()
  expect(await oldUse('academic')).toBe(false)
  expect(h.api.useTemplate).not.toHaveBeenCalled()
  const freshUse = h.card(h.render(), 'academic').props.onSelect as (id: string) => Promise<boolean>
  expect(await freshUse('academic')).toBe(true)
})

it.each(['owner switch', 'owner ABA', 'outer recovery ABA'] as const)('drops an admitted template response after %s', async transition => {
  const h = await harness()
  let resolve!: (result: { resume_id: string }) => void
  h.api.useTemplate.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  const oldUse = h.card(h.render(), 'academic').props.onSelect as (id: string) => Promise<boolean>
  const pending = oldUse('academic')
  if (transition === 'outer recovery ABA') h.advanceOuterScope(true)
  else h.session({ data: { user: { id: 'other-owner' } } })
  h.render(); await h.flush()
  if (transition === 'owner ABA') { h.session({ data: { user: { id: 'owner' } } }); h.render(); await h.flush() }
  resolve({ resume_id: 'old-owner-document' })
  expect(await pending).toBe(false)
  expect(h.router.push).not.toHaveBeenCalled()
  expect(h.toast.success).not.toHaveBeenCalled()
  expect(await oldUse('academic')).toBe(false)
  expect(h.api.useTemplate).toHaveBeenCalledOnce()
})

it('preserves an already-admitted template outcome through same-owner uncertainty and grant revocation', async () => {
  const h = await harness()
  let resolve!: (result: { resume_id: string }) => void
  h.api.useTemplate.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  const use = h.card(h.render(), 'academic').props.onSelect as (id: string) => Promise<boolean>
  const pending = use('academic')
  h.session({ isRefetching: true }); h.allow([]); h.render()
  resolve({ resume_id: 'admitted-document' })
  expect(await pending).toBe(true)
  expect(h.router.push).toHaveBeenCalledExactlyOnceWith('/workspace/admitted-document/edit')
})

it('serializes duplicate template clicks before a React render', async () => {
  const h = await harness()
  let resolve!: (result: { resume_id: string }) => void
  h.api.useTemplate.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  const use = h.card(h.render(), 'academic').props.onSelect as (id: string) => Promise<boolean>
  const pending = use('academic')
  expect(await use('academic')).toBe(false)
  expect(h.api.useTemplate).toHaveBeenCalledOnce()
  resolve({ resume_id: 'created' }); await pending
})

it('requires the outer account scope for authenticated creation while keeping anonymous browse available', async () => {
  const h = await harness()
  h.removeOuterScope()
  expect(h.card(h.render(), 'academic').props.allowUse).toBe(false)
  expect(h.cards(h.render())).toHaveLength(4)
  expect(h.api.useTemplate).not.toHaveBeenCalled()
})

it('refetches a server-filtered cold catalog when B05 becomes allowed without resetting the search', async () => {
  const h = await harness(true, false)
  expect(h.cards(h.render())).toHaveLength(1)
  const search = elements(h.render()).find(node => node.type === 'input' && node.props.id === 'template-search')!
  ;(search.props.onChange as (event: unknown) => void)({ target: { value: 'template' } })
  h.allow(['b04', 'b05', 'b01', 'c01']); h.render(); await h.flush()
  expect(h.cards(h.render())).toHaveLength(4)
  expect(h.api.getTemplates).toHaveBeenCalledTimes(2)
  expect(h.api.getTemplateCategories).toHaveBeenCalledTimes(2)
  expect(elements(h.render()).find(node => node.props.id === 'template-search')?.props.value).toBe('template')
})

it('rejects a pre-revocation catalog response and does not mistake it for current full-catalog coverage', async () => {
  let resolve!: (rows: unknown[]) => void
  const h = await harness(true, true, api => api.getTemplates.mockImplementationOnce(() => new Promise(done => { resolve = done })))
  h.allow(['b04', 'b01', 'c01']); h.render(); await h.flush()
  expect(h.cards(h.render())).toHaveLength(1)
  resolve([{ id: 'stale', name: 'Stale catalog', category: 'academic', category_label: 'academic', tags: [] }]); await h.flush()
  expect(h.cards(h.render()).map(node => (node.props.template as { id: string }).id)).toEqual(['professional'])
  h.allow(['b04', 'b05', 'b01', 'c01']); h.render(); await h.flush()
  expect(h.cards(h.render())).toHaveLength(4)
  expect(h.api.getTemplates).toHaveBeenCalledTimes(3)
})

it.each(['b01', 'b04', 'b05', 'c01', 'refetch', 'outer lease'] as const)('rechecks %s at template HTTP dispatch rather than only when the callback starts', async change => {
  const h = await harness()
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  const dispatch = vi.fn()
  h.api.useTemplate.mockImplementationOnce(async (_id, _title, _locale, context) => {
    expect(context.authToken).toBe('owner-token')
    await gate
    if (!context.isCurrent()) throw new Error('Account request context changed before dispatch')
    dispatch()
    return { resume_id: 'created' }
  })
  const pending = (h.card(h.render(), 'academic').props.onSelect as (id: string) => Promise<boolean>)('academic')
  if (change === 'outer lease') h.advanceOuterScope()
  else if (change === 'refetch') { h.session({ isRefetching: true }); h.render() }
  else { h.allow(['b01', 'b04', 'b05', 'c01'].filter(key => key !== change)); h.render() }
  release()
  expect(await pending).toBe(false)
  expect(dispatch).not.toHaveBeenCalled()
  expect(h.router.push).not.toHaveBeenCalled()
})
