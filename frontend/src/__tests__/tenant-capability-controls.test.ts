import { readFileSync } from 'node:fs'
import ts from 'typescript'
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
function findButton(tree: unknown, text: string) {
  return elements(tree).find(node => node.type === 'button' && label(node).replace(/\s+/g, ' ').trim() === text)
}
function click(node: Element) { return (node.props.onClick as () => unknown)() }
const expectedContext = expect.objectContaining({ authToken: 'owner-token', isCurrent: expect.any(Function) })
const tenant = { id: 'tenant', name: 'Owned tenant', owner_id: 'owner', primary_color: '#19375d', logo_url: null, custom_domain: 'old.example.com', max_members: 50, plan_id: 'agency', slug: 'owned', domain_verified: false }

type HookState = { slots: Array<{ value?: unknown; deps?: unknown[]; cleanup?: () => void }>; effects: Array<() => void>; mounted: boolean }
type TenantAuth = { session: { user: { id: string }; session?: { token: string } } | null; isPending: boolean; isRefetching?: boolean; error: unknown }
async function harness(configure?: (api: Record<string, ReturnType<typeof vi.fn>>) => void, initialAuth?: TenantAuth) {
  vi.resetModules()
  let index = 0
  let grants = new Set(['f10', 'f11'])
  const createHooks = (): HookState => ({ slots: [], effects: [], mounted: true })
  const outer = createHooks()
  let hooks = outer
  let inner: { key: unknown; hooks: HookState } | undefined
  const sameDeps = (a?: unknown[], b?: unknown[]) => Boolean(a && b && a.length === b.length && a.every((item, i) => Object.is(item, b[i])))
  vi.doMock('react', async importOriginal => ({
    ...await importOriginal<typeof import('react')>(),
    useRef: (initial: unknown) => {
      const slot = index++; hooks.slots[slot] ??= { value: { current: initial } }; return hooks.slots[slot].value
    },
    useState: (initial: unknown) => {
      const ownerHooks = hooks
      const slot = index++; ownerHooks.slots[slot] ??= { value: typeof initial === 'function' ? (initial as () => unknown)() : initial }
      return [ownerHooks.slots[slot].value, (next: unknown) => {
        if (ownerHooks.mounted) ownerHooks.slots[slot].value = typeof next === 'function' ? (next as (previous: unknown) => unknown)(ownerHooks.slots[slot].value) : next
      }]
    },
    useCallback: (callback: unknown, deps: unknown[]) => {
      const slot = index++
      if (!hooks.slots[slot] || !sameDeps(hooks.slots[slot].deps, deps)) hooks.slots[slot] = { value: callback, deps }
      return hooks.slots[slot].value
    },
    useEffect: (effect: () => void | (() => void), deps?: unknown[]) => {
      const slot = index++; const ownerHooks = hooks; const previous = ownerHooks.slots[slot]
      if (!previous || !sameDeps(previous.deps, deps)) {
        const next = { deps, cleanup: previous?.cleanup }; ownerHooks.slots[slot] = next
        ownerHooks.effects.push(() => { next.cleanup?.(); next.cleanup = effect() || undefined })
      }
    },
  }))
  vi.doMock('@/contexts/EntitlementsContext', () => ({ useEntitlements: () => {
    const snapshot = grants; return { can: (key: string) => snapshot.has(key) }
  } }))
  let auth: TenantAuth = initialAuth ?? { session: { user: { id: 'owner' }, session: { token: 'owner-token' } }, isPending: false, error: null }
  vi.doMock('@/hooks/useRequireAuth', () => ({ useRequireAuth: () => auth }))
  let recoveryIdentity = {}; let admissionIdentity = {}
  const makeScope = () => {
    const recovery = recoveryIdentity; const admission = admissionIdentity
    return { recoveryIdentity: recovery, isCurrent: () => recovery === recoveryIdentity,
      isAdmissionCurrent: () => recovery === recoveryIdentity && admission === admissionIdentity,
      canAdmit: () => recovery === recoveryIdentity && admission === admissionIdentity }
  }
  let accountScope: ReturnType<typeof makeScope> | null = makeScope()
  vi.doMock('@/contexts/AccountContentScope', () => ({ useAccountContentScope: () => accountScope }))
  vi.doMock('next/link', () => ({ default: 'a' }))
  const toast = { success: vi.fn(), error: vi.fn(), info: vi.fn() }
  vi.doMock('sonner', () => ({ toast }))
  const applyTenantTheme = vi.fn()
  vi.doMock('@/lib/tenant-theme', () => ({ applyTenantTheme }))
  const api = {
    listMyTenants: vi.fn().mockResolvedValue([tenant]), getMe: vi.fn().mockResolvedValue({ role: 'admin', plan: 'team' }),
    listTenantMembers: vi.fn().mockResolvedValue([{ user_id: 'member', email: 'member@example.com', name: 'Existing member', role: 'member' }]),
    getTenantStats: vi.fn().mockResolvedValue({ member_count: 1 }), listTenantCohorts: vi.fn().mockResolvedValue([]),
    updateTenant: vi.fn().mockImplementation(async (_id, patch) => ({ ...tenant, ...patch })),
    verifyTenantDomain: vi.fn().mockResolvedValue({ verified: false }), inviteTenantMember: vi.fn().mockResolvedValue({ email: 'new@example.com' }),
    createTenant: vi.fn().mockResolvedValue(tenant), createTenantCohort: vi.fn().mockResolvedValue({ id: 'cohort', name: 'New cohort' }),
    removeTenantMember: vi.fn().mockResolvedValue(undefined),
  }
  configure?.(api)
  vi.doMock('@/lib/api-client', () => ({ apiClient: api }))
  const Component = (await import('@/app/admin/tenant/page')).default
  const unmount = (state: HookState) => { state.mounted = false; state.slots.forEach(slot => slot.cleanup?.()); state.effects = [] }
  const render = () => {
    hooks = outer; index = 0
    const tree = Component() as (Element & { key?: unknown }) | null
    if (!tree || typeof tree.type !== 'function') { if (inner) unmount(inner.hooks); inner = undefined; return tree }
    // Model the keyed private subtree with distinct hook/setter incarnations.
    if (!inner || inner.key !== tree.key) { if (inner) unmount(inner.hooks); inner = { key: tree.key, hooks: createHooks() } }
    hooks = inner.hooks; index = 0
    return (tree.type as (props: Record<string, unknown>) => unknown)(tree.props)
  }
  const flush = async () => {
    for (const state of [outer, inner?.hooks]) {
      if (!state?.mounted) continue
      const queued = state.effects; state.effects = []; queued.forEach(effect => effect())
    }
    for (let i = 0; i < 12; i++) await Promise.resolve()
  }
  render(); await flush()
  return { api, toast, applyTenantTheme, render, flush,
    switchOwner: (id: string | null) => { auth = { session: id ? { user: { id }, session: { token: `${id}-token` } } : null, isPending: false, error: null } },
    readiness: (isPending: boolean, error: unknown = null) => { auth = { ...auth, isPending, error } },
    refetch: (isRefetching: boolean) => { auth = { ...auth, isRefetching } },
    removeOuterScope: () => { accountScope = null },
    advanceOuterScope: (newRecovery = false) => {
      if (newRecovery) recoveryIdentity = {}
      admissionIdentity = {}; accountScope = makeScope()
    },
    key: () => inner?.key, allow: (keys: string[]) => { grants = new Set(keys) } }
}

afterEach(() => {
  for (const name of ['react', '@/contexts/AccountContentScope', '@/contexts/EntitlementsContext', '@/hooks/useRequireAuth', '@/lib/api-client', 'next/link', 'sonner', '@/lib/tenant-theme']) vi.doUnmock(name)
  vi.resetModules()
})

it('hides denied tenant setup controls even for a team admin and retains existing member removal', async () => {
  const h = await harness()
  h.allow([])
  const tree = h.render()
  for (const name of ['+ New Tenant', 'Save Branding', 'Create cohort', 'Invite', 'Verify DNS']) expect(findButton(tree, name), name).toBeUndefined()
  expect(label(tree)).toContain('Owned tenant')
  await click(findButton(tree, 'Remove')!)
  expect(h.api.removeTenantMember).toHaveBeenCalledExactlyOnceWith('tenant', 'member', expectedContext)
})

it('independently gates F10 setup and F11 domain verification', async () => {
  const h = await harness()
  h.allow(['f10'])
  expect(findButton(h.render(), 'Save Branding')).toBeDefined()
  expect(findButton(h.render(), 'Create cohort')).toBeDefined()
  expect(findButton(h.render(), 'Verify DNS')).toBeUndefined()
  h.allow(['f11'])
  expect(findButton(h.render(), 'Save Branding')).toBeUndefined()
  expect(findButton(h.render(), 'Verify DNS')).toBeDefined()
})

it('rejects retained branding and DNS callbacks after revocation before API work', async () => {
  const h = await harness()
  const tree = h.render()
  const branding = findButton(tree, 'Save Branding')!
  const dns = findButton(tree, 'Verify DNS')!
  h.allow([]); h.render()
  await click(branding); await click(dns)
  expect(h.api.updateTenant).not.toHaveBeenCalled()
  expect(h.api.verifyTenantDomain).not.toHaveBeenCalled()
})

const source = ts.createSourceFile('tenant.tsx', readFileSync(new URL('../app/admin/tenant/page.tsx', import.meta.url), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
function action(name: string, context: Record<string, unknown>) {
  let expression: ts.Expression | undefined
  const visit = (node: ts.Node) => {
    if (ts.isVariableDeclaration(node) && node.name.getText(source) === name && node.initializer) expression = node.initializer
    ts.forEachChild(node, visit)
  }
  visit(source); expect(expression, name).toBeDefined()
  const javascript = ts.transpileModule(`const run = ${expression!.getText(source)}`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
  const scope = { canActForOwner: () => true, isCurrentOwner: () => true, isCurrentSelection: () => true, requestContext: (isCurrent: () => boolean) => ({ authToken: 'owner-token', isCurrent }), ...context }
  return new Function(...Object.keys(scope), `${javascript}; return run`)(...Object.values(scope)) as () => Promise<void>
}

it.each(['createTenant', 'invite', 'createCohort'])('%s rejects retained F10 callbacks before state/network changes', async name => {
  const canRef = { current: () => false }
  const run = action(name, { canRef, selected: tenant, canProvisionTenant: true, newName: 'New tenant', newSlug: 'new-tenant', inviteEmail: 'new@example.com', newCohortName: 'New cohort' })
  // Any setter or API access after a missed gate throws, preventing a false pass.
  await run()
})

it('saves a domain without retransmitting branding and can remove it when setup is denied', async () => {
  const updateTenant = vi.fn().mockResolvedValue({ ...tenant, custom_domain: 'new.example.com' })
  const scope = { tenantPatchPendingRef: { current: false }, detailRequestRef: { current: 1 }, selectedTenantIdRef: { current: 'tenant' }, selected: tenant, canRef: { current: (key: string) => key === 'f11' }, customDomain: 'new.example.com', setSavingDomain: vi.fn(), setSelected: vi.fn(), setTenants: vi.fn(), setDnsInfo: vi.fn(), setCustomDomain: vi.fn(), applyTenantTheme: vi.fn(), apiClient: { updateTenant }, toast: { success: vi.fn(), error: vi.fn() } }
  await action('saveDomain', scope)()
  expect(updateTenant).toHaveBeenCalledExactlyOnceWith('tenant', { custom_domain: 'new.example.com' }, expectedContext)
  updateTenant.mockClear()
  await action('saveDomain', { ...scope, customDomain: '', canRef: { current: () => false } })()
  expect(updateTenant).toHaveBeenCalledExactlyOnceWith('tenant', { custom_domain: null }, expectedContext)
  updateTenant.mockClear()
  await action('saveDomain', { ...scope, canRef: { current: () => false } })()
  expect(updateTenant).not.toHaveBeenCalled()
})

it('retains explicit existing-domain removal while F10 and F11 are both denied', async () => {
  const h = await harness()
  h.allow([])
  const remove = findButton(h.render(), 'Remove Domain')
  expect(remove).toBeDefined()
  click(remove!)
  expect(h.api.updateTenant).toHaveBeenCalledExactlyOnceWith('tenant', { custom_domain: null }, expectedContext)
})

it('does not add a domain grant requirement to branding-only requests', async () => {
  const h = await harness()
  h.allow(['f10'])
  await click(findButton(h.render(), 'Save Branding')!)
  expect(h.api.updateTenant).toHaveBeenCalledExactlyOnceWith('tenant', {
    name: 'Owned tenant', logo_url: null, primary_color: '#19375d',
  }, expectedContext)
})

it('does not apply a domain response after the selected tenant changes', async () => {
  let resolve!: (value: typeof tenant) => void
  const updateTenant = vi.fn(() => new Promise(done => { resolve = done }))
  const detailRequestRef = { current: 1 }
  const selectedTenantIdRef = { current: 'tenant' }
  const setSelected = vi.fn()
  const setTenants = vi.fn()
  const setDnsInfo = vi.fn()
  const scope = { tenantPatchPendingRef: { current: false }, detailRequestRef, selectedTenantIdRef, selected: tenant, canRef: { current: () => true }, customDomain: 'new.example.com', setSavingDomain: vi.fn(), setSelected, setTenants, setDnsInfo, applyTenantTheme: vi.fn(), apiClient: { updateTenant }, toast: { success: vi.fn(), error: vi.fn() } }
  const pending = action('saveDomain', scope)()
  detailRequestRef.current = 2
  selectedTenantIdRef.current = 'other-tenant'
  resolve({ ...tenant, custom_domain: 'new.example.com' })
  await pending
  expect(setSelected).not.toHaveBeenCalled()
  expect(setTenants).toHaveBeenCalledOnce()
  const refreshList = setTenants.mock.calls[0][0] as (previous: typeof tenant[]) => typeof tenant[]
  expect(refreshList([tenant])[0].custom_domain).toBe('new.example.com')
  expect(setDnsInfo).not.toHaveBeenCalled()
})

it.each([['saveBranding', 'saveDomain'], ['saveDomain', 'saveBranding']] as const)(
  'serializes %s and retained %s so reversed patch responses cannot regress domain state', async (first, second) => {
    let resolve!: (value: typeof tenant) => void
    const updateTenant = vi.fn(() => new Promise(done => { resolve = done }))
    const setSelected = vi.fn()
    const scope = {
      tenantPatchPendingRef: { current: false }, detailRequestRef: { current: 1 }, selectedTenantIdRef: { current: 'tenant' },
      selected: tenant, canRef: { current: () => true }, name: 'New branding', logoUrl: '', primaryColor: '#19375d', customDomain: 'new.example.com',
      setSaving: vi.fn(), setSavingDomain: vi.fn(), setSelected, setTenants: vi.fn(), setDnsInfo: vi.fn(), setCustomDomain: vi.fn(),
      applyTenantTheme: vi.fn(), apiClient: { updateTenant }, toast: { success: vi.fn(), error: vi.fn() },
    }
    const pending = action(first, scope)()
    const blocked = action(second, scope)()
    expect(updateTenant).toHaveBeenCalledTimes(1)
    resolve({ ...tenant, custom_domain: first === 'saveDomain' ? 'new.example.com' : tenant.custom_domain })
    await pending; await blocked
    expect(scope.tenantPatchPendingRef.current).toBe(false)
    updateTenant.mockResolvedValueOnce({ ...tenant, custom_domain: 'new.example.com' })
    await action('saveDomain', scope)()
    expect(updateTenant).toHaveBeenCalledTimes(2)
    expect(setSelected).toHaveBeenLastCalledWith({ ...tenant, custom_domain: 'new.example.com' })
  },
)

it('applies the canonical domain returned by the server to the editable input', async () => {
  const updateTenant = vi.fn().mockResolvedValue({ ...tenant, custom_domain: 'new.example.com' })
  const setCustomDomain = vi.fn()
  const scope = { tenantPatchPendingRef: { current: false }, detailRequestRef: { current: 1 }, selectedTenantIdRef: { current: 'tenant' }, selected: tenant, canRef: { current: () => true }, customDomain: ' NEW.EXAMPLE.COM. ', setSavingDomain: vi.fn(), setSelected: vi.fn(), setTenants: vi.fn(), setDnsInfo: vi.fn(), setCustomDomain, applyTenantTheme: vi.fn(), apiClient: { updateTenant }, toast: { success: vi.fn(), error: vi.fn() } }
  await action('saveDomain', scope)()
  expect(setCustomDomain).toHaveBeenCalledExactlyOnceWith('new.example.com')
})

it('resets private tenant data synchronously on A-to-B and blocks retained new/recovery callbacks', async () => {
  const h = await harness()
  const oldTree = h.render()
  expect(label(oldTree)).toContain('Existing member')
  const oldCallbacks = ['Save Branding', 'Verify DNS', 'Remove Domain', 'Remove'].map(name => findButton(oldTree, name)!)
  h.api.listMyTenants.mockResolvedValue([])
  h.api.getMe.mockResolvedValue({ role: 'user', plan: 'free' })
  h.switchOwner('other-owner')
  const changedFrame = h.render()
  expect(label(changedFrame)).not.toContain('Existing member')
  expect(elements(changedFrame).some(node => node.props.value === 'old.example.com')).toBe(false)
  for (const button of oldCallbacks) await click(button)
  expect(h.api.updateTenant).not.toHaveBeenCalled()
  expect(h.api.verifyTenantDomain).not.toHaveBeenCalled()
  expect(h.api.removeTenantMember).not.toHaveBeenCalled()
  await h.flush()
  expect(h.api.listMyTenants).toHaveBeenCalledTimes(2)
  expect(label(h.render())).not.toContain('Existing member')
})

it.each([false, true])('does not display a delayed A tenant list after an owner change (round-trip=%s)', async roundTrip => {
  let resolve!: (value: typeof tenant[]) => void
  const h = await harness(api => api.listMyTenants.mockImplementationOnce(() => new Promise(done => { resolve = done })))
  const originalKey = h.key()
  h.api.listMyTenants.mockResolvedValue([])
  h.switchOwner('other-owner'); h.render(); await h.flush()
  if (roundTrip) { h.switchOwner('owner'); h.render(); await h.flush(); expect(h.key()).not.toBe(originalKey) }
  resolve([tenant]); await h.flush()
  expect(label(h.render())).not.toContain('Owned tenant')
  expect(h.api.listTenantMembers).not.toHaveBeenCalled()
})

it('drops delayed A member details and provisioning status without entering B private state', async () => {
  let resolveMembers!: (value: Array<{ user_id: string; email: string; name: string; role: string }>) => void
  let resolveAccount!: (value: { role: string; plan: string }) => void
  const h = await harness(api => {
    api.listTenantMembers.mockImplementationOnce(() => new Promise(done => { resolveMembers = done }))
    api.getMe.mockImplementationOnce(() => new Promise(done => { resolveAccount = done }))
  })
  h.api.listMyTenants.mockResolvedValue([]); h.api.getMe.mockResolvedValue({ role: 'user', plan: 'free' })
  h.switchOwner('other-owner'); h.render(); await h.flush()
  resolveMembers([{ user_id: 'member', email: 'private-a@example.com', name: 'Private A member', role: 'member' }])
  resolveAccount({ role: 'admin', plan: 'team' }); await h.flush()
  const tree = h.render()
  expect(label(tree)).not.toContain('Private A member')
  expect(findButton(tree, '+ New Tenant')).toBeUndefined()
})

it.each([false, true])('keeps admitted A mutation outcomes off B/new-A views and themes (round-trip=%s)', async roundTrip => {
  const h = await harness()
  let resolve!: (value: typeof tenant) => void
  h.api.updateTenant.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  const originalKey = h.key()
  const retained = findButton(h.render(), 'Save Branding')!
  const pending = click(retained)
  expect(h.api.updateTenant).toHaveBeenCalledOnce()
  h.api.listMyTenants.mockResolvedValue([])
  h.switchOwner('other-owner'); h.render(); await h.flush()
  if (roundTrip) { h.switchOwner('owner'); h.render(); await h.flush(); expect(h.key()).not.toBe(originalKey) }
  resolve({ ...tenant, name: 'Admitted old A result' }); await pending
  expect(label(h.render())).not.toContain('Admitted old A result')
  expect(h.applyTenantTheme).not.toHaveBeenCalled()
  expect(h.toast.success).not.toHaveBeenCalled()
  await click(retained)
  expect(h.api.updateTenant).toHaveBeenCalledOnce()
})

it('preserves same-owner draft state during transient session loading while retained actions fail closed', async () => {
  const h = await harness()
  const tree = h.render()
  const domain = elements(tree).find(node => node.type === 'input' && node.props.value === 'old.example.com')!
  ;(domain.props.onChange as (event: unknown) => void)({ target: { value: 'unsaved.example.com' } })
  const readyTree = h.render()
  const retained = findButton(readyTree, 'Save Domain')!
  const key = h.key()
  h.readiness(true); h.render(); await click(retained)
  expect(h.key()).toBe(key)
  expect(h.api.updateTenant).not.toHaveBeenCalled()
  h.readiness(false, new Error('offline')); h.render(); await click(retained)
  expect(h.api.updateTenant).not.toHaveBeenCalled()
  h.readiness(false); const restored = h.render(); await h.flush()
  expect(h.key()).toBe(key)
  expect(elements(restored).some(node => node.props.value === 'unsaved.example.com')).toBe(true)
  await click(findButton(h.render(), 'Save Domain')!)
  expect(h.api.updateTenant).toHaveBeenCalledExactlyOnceWith('tenant', { custom_domain: 'unsaved.example.com' }, expectedContext)
})

it.each(['saveBranding', 'saveDomain', 'removeDomain', 'invite', 'createCohort', 'loadCohortSubmissions', 'removeMember', 'verifyDomain', 'createTenant'])('%s rejects a callback from a prior owner before any state/network access', async name => {
  // Missing setters/API/selection deliberately throw if the incarnation gate is missed.
  await action(name, { canActForOwner: () => false })()
})

it('keeps the shared mutation lock through selection changes and serializes DNS with patches', async () => {
  let resolve!: (value: { verified: boolean }) => void
  const verifyTenantDomain = vi.fn(() => new Promise(done => { resolve = done }))
  const updateTenant = vi.fn()
  const setSelected = vi.fn(); const setTenants = vi.fn(); const setDnsInfo = vi.fn()
  const scope = {
    tenantPatchPendingRef: { current: false }, detailRequestRef: { current: 1 }, selectedTenantIdRef: { current: 'tenant' },
    selected: tenant, canRef: { current: () => true }, customDomain: 'new.example.com', setVerifyingDomain: vi.fn(), setSavingDomain: vi.fn(),
    setSelected, setTenants, setDnsInfo, apiClient: { verifyTenantDomain, updateTenant }, toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
  }
  const pending = action('verifyDomain', scope)()
  scope.detailRequestRef.current += 1; scope.selectedTenantIdRef.current = 'other-tenant'
  await action('saveDomain', { ...scope, selected: { ...tenant, id: 'other-tenant' } })()
  expect(updateTenant).not.toHaveBeenCalled()
  expect(scope.tenantPatchPendingRef.current).toBe(true)
  resolve({ verified: true }); await pending
  expect(scope.tenantPatchPendingRef.current).toBe(false)
  expect(setSelected).not.toHaveBeenCalled(); expect(setDnsInfo).not.toHaveBeenCalled()
  const refreshList = setTenants.mock.calls[0][0] as (previous: typeof tenant[]) => typeof tenant[]
  expect(refreshList([tenant])[0].domain_verified).toBe(true)
})


it('renders the actual accessible initial session error without loading any private tenant data', async () => {
  const h = await harness(undefined, { session: null, isPending: false, error: new Error('offline') })
  const tree = h.render()
  expect(label(tree).replace(/\s+/g, ' ')).toContain('Tenant management could not verify your session')
  expect(elements(tree).some(node => node.props.role === 'alert')).toBe(true)
  expect(findButton(tree, 'Retry')).toBeDefined()
  expect(h.api.listMyTenants).not.toHaveBeenCalled()
  expect(h.api.getMe).not.toHaveBeenCalled()
})

it('renders no private subtree on an authoritative initial signed-out response', async () => {
  const h = await harness(undefined, { session: null, isPending: false, error: null })
  expect(h.render()).toBeNull()
  expect(h.api.listMyTenants).not.toHaveBeenCalled()
})

it('discards private state and old recovery callbacks after confirmed signout, including same-owner return', async () => {
  const h = await harness()
  const original = h.render(); const key = h.key()
  const remove = findButton(original, 'Remove Domain')!
  expect(label(original)).toContain('Existing member')
  h.switchOwner(null)
  expect(h.render()).toBeNull()
  await click(remove)
  expect(h.api.updateTenant).not.toHaveBeenCalled()
  h.api.listMyTenants.mockResolvedValue([])
  h.switchOwner('owner'); h.render(); await h.flush()
  expect(h.key()).not.toBe(key)
  expect(label(h.render())).not.toContain('Existing member')
  expect(domainField(h.render())).toBeUndefined()
  await click(remove)
  expect(h.api.updateTenant).not.toHaveBeenCalled()
})

function domainField(tree: unknown) {
  return elements(tree).find(node => node.type === 'input' && node.props.placeholder === 'resumes.acme.com')
}

it('retires callbacks through isRefetching-only uncertainty without losing the same-owner domain draft', async () => {
  const h = await harness()
  const domain = domainField(h.render())!
  ;(domain.props.onChange as (event: unknown) => void)({ target: { value: 'pending.example.com' } })
  const before = h.render(); const key = h.key()
  const retained = ['Save Domain', 'Remove Domain', 'Remove'].map(name => findButton(before, name)!)
  h.refetch(true)
  const pending = h.render()
  expect(h.key()).toBe(key)
  expect(domainField(pending)?.props.value).toBe('pending.example.com')
  expect(findButton(pending, 'Save Domain')).toBeUndefined()
  for (const button of retained) await click(button)
  expect(h.api.updateTenant).not.toHaveBeenCalled()
  expect(h.api.removeTenantMember).not.toHaveBeenCalled()
  h.refetch(false); h.render(); await h.flush()
  for (const button of retained) await click(button)
  expect(h.api.updateTenant).not.toHaveBeenCalled()
  expect(h.api.removeTenantMember).not.toHaveBeenCalled()
  expect(domainField(h.render())?.props.value).toBe('pending.example.com')
  await click(findButton(h.render(), 'Save Domain')!)
  expect(h.api.updateTenant).toHaveBeenCalledExactlyOnceWith('tenant', { custom_domain: 'pending.example.com' }, expectedContext)
})

it('treats a completed 401 as signout even when the session hook still exposes the old owner', async () => {
  const h = await harness()
  const old = findButton(h.render(), 'Remove Domain')!
  h.readiness(false, { status: 401 })
  expect(h.render()).toBeNull()
  await click(old)
  expect(h.api.updateTenant).not.toHaveBeenCalled()
  h.api.listMyTenants.mockResolvedValue([])
  h.readiness(false); h.render(); await h.flush()
  expect(label(h.render())).not.toContain('Existing member')
  await click(old)
  expect(h.api.updateTenant).not.toHaveBeenCalled()
})

it('honors a retired outer admission lease before this child renders and does not revive it', async () => {
  const h = await harness()
  const old = findButton(h.render(), 'Remove Domain')!
  h.advanceOuterScope()
  await click(old)
  expect(h.api.updateTenant).not.toHaveBeenCalled()
  h.render(); await h.flush()
  await click(old)
  expect(h.api.updateTenant).not.toHaveBeenCalled()
  await click(findButton(h.render(), 'Remove Domain')!)
  expect(h.api.updateTenant).toHaveBeenCalledOnce()
})

it('resets private tenant state for a new outer recovery identity even if the owner string repeats', async () => {
  const h = await harness()
  const old = findButton(h.render(), 'Remove Domain')!; const key = h.key()
  h.api.listMyTenants.mockResolvedValue([])
  h.advanceOuterScope(true)
  h.render(); await h.flush()
  expect(h.key()).not.toBe(key)
  expect(label(h.render())).not.toContain('Existing member')
  await click(old)
  expect(h.api.updateTenant).not.toHaveBeenCalled()
})

it('fails closed when the authenticated tenant page loses its outer account scope', async () => {
  const h = await harness()
  h.api.listMyTenants.mockClear(); h.api.getMe.mockClear()
  h.removeOuterScope(); h.render(); await h.flush()
  expect(h.api.listMyTenants).not.toHaveBeenCalled()
  expect(h.api.getMe).not.toHaveBeenCalled()
})

it.each(['invite', 'createCohort'])('%s cannot clear or insert into a different selected tenant after completion', async name => {
  let resolve!: (value: unknown) => void
  const api = { [name === 'invite' ? 'inviteTenantMember' : 'createTenantCohort']: vi.fn(() => new Promise(done => { resolve = done })) }
  let selected = true
  const setInviteEmail = vi.fn(); const setCohorts = vi.fn(); const setNewCohortName = vi.fn()
  const scope = { selected: tenant, canRef: { current: () => true }, isCurrentSelection: () => selected,
    inviteEmail: 'a@example.com', inviteRole: 'member', inviteCohortId: '', newCohortName: 'A cohort',
    setInviting: vi.fn(), setCreatingCohort: vi.fn(), setInviteEmail, setCohorts, setNewCohortName,
    apiClient: api, toast: { success: vi.fn(), error: vi.fn() } }
  const pending = action(name, scope)()
  selected = false
  resolve({ id: 'cohort-a', name: 'A cohort', email: 'a@example.com' }); await pending
  expect(setInviteEmail).not.toHaveBeenCalled()
  expect(setCohorts).not.toHaveBeenCalled()
  expect(setNewCohortName).not.toHaveBeenCalled()
  expect(scope.toast.success).not.toHaveBeenCalled()
})

it.each(['saveBranding', 'saveDomain', 'removeDomain', 'invite', 'createCohort', 'loadCohortSubmissions', 'removeMember', 'verifyDomain'])('%s rejects a retained callback from an earlier tenant selection before network work', async name => {
  await action(name, { isCurrentSelection: () => false })()
})

it('keeps an already-admitted same-owner patch outcome through an authentication refresh', async () => {
  const h = await harness()
  let resolve!: (value: typeof tenant) => void
  h.api.updateTenant.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  const pending = click(findButton(h.render(), 'Save Branding')!)
  h.refetch(true); h.render()
  resolve({ ...tenant, name: 'Admitted branding' }); await pending
  expect(h.applyTenantTheme).toHaveBeenCalledOnce()
  h.refetch(false); h.render(); await h.flush()
  expect(h.toast.success).toHaveBeenCalledWith('Branding saved')
})

it('pins real retained domain callbacks to their rendered tenant selection, including selection ABA', async () => {
  const second = { ...tenant, id: 'second', name: 'Second tenant' }
  const h = await harness(api => api.listMyTenants.mockResolvedValue([tenant, second]))
  const retained = findButton(h.render(), 'Remove Domain')!
  await click(findButton(h.render(), 'Second tenant')!); h.render()
  await click(retained)
  expect(h.api.updateTenant).not.toHaveBeenCalled()
  await click(findButton(h.render(), 'Owned tenant')!); h.render()
  await click(retained)
  expect(h.api.updateTenant).not.toHaveBeenCalled()
  await click(findButton(h.render(), 'Remove Domain')!)
  expect(h.api.updateTenant).toHaveBeenCalledExactlyOnceWith('tenant', { custom_domain: null }, expectedContext)
})

it('keeps a delayed first-tenant cohort out of the second tenant and preserves its newer draft', async () => {
  const second = { ...tenant, id: 'second', name: 'Second tenant' }
  const h = await harness(api => api.listMyTenants.mockResolvedValue([tenant, second]))
  let resolve!: (value: unknown) => void
  h.api.createTenantCohort.mockImplementationOnce(() => new Promise(done => { resolve = done }))
  const field = () => elements(h.render()).find(node => node.props.placeholder === 'e.g. Class of 2027')!
  ;(field().props.onChange as (event: unknown) => void)({ target: { value: 'First-tenant cohort' } })
  click(findButton(h.render(), 'Create cohort')!)
  expect(h.api.createTenantCohort).toHaveBeenCalledExactlyOnceWith('tenant', 'First-tenant cohort', expectedContext)
  await click(findButton(h.render(), 'Second tenant')!)
  ;(field().props.onChange as (event: unknown) => void)({ target: { value: 'Second-tenant draft' } })
  resolve({ id: 'first-cohort', name: 'First-tenant cohort' }); await h.flush()
  expect(label(h.render())).not.toContain('First-tenant cohort')
  expect(field().props.value).toBe('Second-tenant draft')
  expect(h.toast.success).not.toHaveBeenCalled()
})

it.each(['f11', 'refetch', 'outer lease', 'selection'] as const)('rechecks %s before a queued domain patch dispatches with the captured session token', async change => {
  const second = { ...tenant, id: 'second', name: 'Second tenant' }
  const h = await harness(api => api.listMyTenants.mockResolvedValue([tenant, second]))
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  const dispatch = vi.fn()
  h.api.updateTenant.mockImplementationOnce(async (_id, patch, context) => {
    expect(context.authToken).toBe('owner-token')
    await gate
    if (!context.isCurrent()) throw new Error('Account request context changed before dispatch')
    dispatch()
    return { ...tenant, ...patch }
  })
  const field = domainField(h.render())!
  ;(field.props.onChange as (event: unknown) => void)({ target: { value: 'queued.example.com' } })
  click(findButton(h.render(), 'Save Domain')!)
  if (change === 'outer lease') h.advanceOuterScope()
  else if (change === 'refetch') { h.refetch(true); h.render() }
  else if (change === 'f11') { h.allow(['f10']); h.render() }
  else { await click(findButton(h.render(), 'Second tenant')!); h.render() }
  release(); await h.flush()
  expect(dispatch).not.toHaveBeenCalled()
  expect(h.applyTenantTheme).not.toHaveBeenCalled()
})
