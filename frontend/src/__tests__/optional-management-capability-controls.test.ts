import { afterEach, describe, expect, it, vi } from 'vitest'

type Element = { type: unknown; props: Record<string, unknown> }
type Effect = { deps?: unknown[]; cleanup?: () => void }
const MOCKS = [
  'react', 'react/jsx-runtime', 'react/jsx-dev-runtime', 'lucide-react', 'next/link', 'next/navigation', '@/contexts/EntitlementsContext',
  '@/contexts/FeatureFlagsContext', '@/hooks/useRequireAuth', '@/lib/auth-client',
  '@/lib/api-client', '@/lib/download', 'sonner', '@/components/billing/PricingCard',
  '@/components/billing/SubscriptionManager', '@/components/JobQueue',
  '@/components/analytics/MetricCharts', '@/components/CommentsPanel',
]
function elements(value: unknown): Element[] {
  if (Array.isArray(value)) return value.flatMap(elements)
  if (!value || typeof value !== 'object' || !('props' in value)) return []
  const node = value as Element
  return [node, ...elements(node.props.children)]
}
function content(value: unknown): string {
  if (typeof value === 'string') return value
  if (Array.isArray(value)) return value.map(content).join(' ')
  return value && typeof value === 'object' && 'props' in value ? content((value as Element).props.children) : ''
}
function control(tree: unknown, label: string): Element {
  const node = elements(tree).find((item) => item.type === 'button' && (content(item).includes(label) || item.props.title === label))
  expect(node, label).toBeDefined()
  return node!
}
function input(tree: unknown, placeholder: string): Element {
  const node = elements(tree).find((item) => item.props.placeholder === placeholder)
  expect(node, placeholder).toBeDefined()
  return node!
}
function click(node: Element) { return (node.props.onClick as () => unknown)() }
function type(node: Element, value: string) { (node.props.onChange as (event: unknown) => void)({ target: { value } }) }
async function settle() { for (let i = 0; i < 8; i += 1) await Promise.resolve() }

async function harness(kind: 'workspaces' | 'workspace' | 'recruiter' | 'billing' | 'dashboard' | 'referral', initiallyAllowed = true, query = '') {
  vi.resetModules()
  let allowed = initiallyAllowed
  let entitlementFeatures = { i02: initiallyAllowed }
  let stateIndex = 0
  let refIndex = 0
  let effectIndex = 0
  const states: unknown[] = []
  const refs: Array<{ current: unknown }> = []
  const effects: Effect[] = []
  let pending: Array<() => void> = []
  let session = { user: { id: 'owner', email: 'owner@example.test', name: 'Owner' }, session: { token: 'session-token' } }
  const workspace = { id: 'workspace', owner_id: 'owner', name: 'Saved team', plan_id: 'team', member_count: 2, max_members: 5, resume_count: 1, members: [{ user_id: 'owner', role: 'owner' }, { user_id: 'member', role: 'editor', email: 'member@example.test' }] }
  const resume = { id: 'resume', owner_id: 'owner', title: 'Saved resume', shared_at: '2026-01-01' }
  const plans = Object.fromEntries(['free', 'pro', 'student', 'team', 'custom_student', 'custom_team'].map((id) => [id, { id, name: id, capabilities: { i02: initiallyAllowed }, purchasable: true, price: id === 'free' ? 0 : 100, interval: 'month', ...(id.startsWith('custom_') ? { plan_family: id.slice(7) } : {}), features: { compilations: 10, optimizations: 10, historyRetention: 30, prioritySupport: false, apiAccess: false } }]))
  const api = {
    listWorkspaces: vi.fn().mockResolvedValue([workspace]), createWorkspace: vi.fn(), deleteWorkspace: vi.fn().mockResolvedValue(undefined),
    getWorkspace: vi.fn().mockResolvedValue(workspace), listWorkspaceResumes: vi.fn().mockResolvedValue([resume]), listAllResumes: vi.fn().mockResolvedValue([{ id: 'unshared', title: 'Unshared resume' }]),
    updateWorkspace: vi.fn(), inviteWorkspaceMember: vi.fn(), updateWorkspaceMemberRole: vi.fn().mockResolvedValue({ role: 'viewer' }), addResumeToWorkspace: vi.fn(),
    removeWorkspaceMember: vi.fn().mockResolvedValue(undefined), removeResumeFromWorkspace: vi.fn().mockResolvedValue(undefined), downloadWorkspaceResume: vi.fn().mockResolvedValue(new Blob(['saved pdf'])),
    listRecruiterNotes: vi.fn().mockResolvedValue([{ id: 'note', author_id: 'owner', content: 'Saved note', created_at: '2026-01-01' }]), createRecruiterNote: vi.fn(), updateRecruiterNote: vi.fn(), deleteRecruiterNote: vi.fn().mockResolvedValue(undefined),
    getSubscriptionPlans: vi.fn().mockResolvedValue({ success: true, data: { plans, billing: { available: true } } }),
    verifyStudentSubscription: vi.fn().mockResolvedValue({ success: true }), previewTeamSeat: vi.fn().mockResolvedValue({ success: true }), joinTeamSeat: vi.fn(), inviteTeamSeat: vi.fn(), createSubscription: vi.fn().mockResolvedValue({ success: true, data: { shortUrl: 'https://payments.example.test/pay' } }),
    getTeamSeats: vi.fn().mockResolvedValue({ success: true, data: [{ id: 'seat', member_email: 'member@example.test', status: 'active', invited_at: '2026-01-01' }] }), removeTeamSeat: vi.fn().mockResolvedValue({ success: true }),
    getCurrentSubscription: vi.fn().mockResolvedValue({ success: true, data: { planId: 'team' } }), cancelSubscription: vi.fn().mockResolvedValue({ success: true }),
    getMyAnalytics: vi.fn().mockResolvedValue({ daily_activity: {}, feature_usage: {}, success_rate: 100 }), getMyAnalyticsTimeseries: vi.fn().mockResolvedValue({}), getResumeStats: vi.fn().mockResolvedValue({ total_resumes: 1 }), getCoverLetterStats: vi.fn().mockResolvedValue({ total: 1 }),
    listJobs: vi.fn().mockResolvedValue({ jobs: [{ job_id: 'job', status: 'completed', stage: 'compile', last_updated: 1, percent: 100 }] }), getJobResult: vi.fn().mockResolvedValue({ ats_score: 90 }),
  }
  const tab = { close: vi.fn(), opener: {}, location: { href: '' } }
  const browser = { confirm: vi.fn(() => true), open: vi.fn(() => tab), location: { origin: 'https://example.test', pathname: '/billing', assign: vi.fn() }, setTimeout: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn() }
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ available: true, share_code: 'saved-code', message: 'Referrals', referral_summary: { total: 1, qualified: 1 }, reward_summary: { issued: 1, pending: 0 } }) })
  const copy = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal('window', browser); vi.stubGlobal('confirm', browser.confirm); vi.stubGlobal('navigator', { clipboard: { writeText: copy } }); vi.stubGlobal('fetch', fetch)
  vi.doMock('react', () => ({
    Suspense: 'Suspense',
    useState: (initial: unknown) => {
      const slot = stateIndex++
      if (!(slot in states)) states[slot] = typeof initial === 'function' ? (initial as () => unknown)() : initial
      return [states[slot], (next: unknown) => { states[slot] = typeof next === 'function' ? (next as (old: unknown) => unknown)(states[slot]) : next }]
    },
    useRef: (initial: unknown) => { const slot = refIndex++; refs[slot] ??= { current: initial }; return refs[slot] },
    useCallback: (fn: unknown) => fn,
    useMemo: (factory: () => unknown) => factory(),
    useEffect: (effect: () => void | (() => void), deps?: unknown[]) => {
      const slot = effectIndex++
      const old = effects[slot]
      if (old && deps && old.deps && deps.length === old.deps.length && deps.every((value, i) => Object.is(value, old.deps![i]))) return
      effects[slot] = { deps, cleanup: old?.cleanup }
      pending.push(() => { effects[slot].cleanup?.(); effects[slot].cleanup = effect() || undefined })
    },
  }))
  const jsx = (type: unknown, props: Record<string, unknown>) => ({ type, props })
  vi.doMock('react/jsx-runtime', () => ({ jsx, jsxs: jsx, Fragment: 'Fragment' }))
  vi.doMock('react/jsx-dev-runtime', () => ({ jsxDEV: jsx, Fragment: 'Fragment' }))
  vi.doMock('lucide-react', () => Object.fromEntries(['Users', 'Plus', 'Loader2', 'Building2', 'Trash2', 'ArrowLeft', 'FileText', 'Download', 'UserMinus', 'ChevronDown', 'Check', 'X', 'ExternalLink', 'StickyNote', 'Pencil', 'ChevronRight'].map((name) => [name, name])))
  vi.doMock('next/link', () => ({ default: 'Link' }))
  const router = { push: vi.fn(), replace: vi.fn() }
  const params = new URLSearchParams(query)
  vi.doMock('next/navigation', () => ({ useParams: () => ({ workspaceId: 'workspace' }), useRouter: () => router, useSearchParams: () => params }))
  vi.doMock('@/contexts/EntitlementsContext', () => ({ useEntitlements: () => ({ can: () => allowed, features: entitlementFeatures, loaded: true, loading: false }) }))
  vi.doMock('@/contexts/FeatureFlagsContext', () => ({ useFeatureFlags: () => ({ billing: true }) }))
  vi.doMock('@/hooks/useRequireAuth', () => ({ useRequireAuth: () => ({ session, isPending: false, error: null }) }))
  vi.doMock('@/lib/auth-client', () => ({ useSession: () => ({ data: session, isPending: false, error: null }) }))
  vi.doMock('@/lib/api-client', () => ({ apiClient: api }))
  vi.doMock('@/lib/download', () => ({ downloadBlob: vi.fn() }))
  vi.doMock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }))
  vi.doMock('@/components/billing/PricingCard', () => ({ default: 'PricingCard' }))
  vi.doMock('@/components/billing/SubscriptionManager', () => ({ default: 'SubscriptionManager' }))
  vi.doMock('@/components/JobQueue', () => ({ JobQueue: 'JobQueue' }))
  vi.doMock('@/components/analytics/MetricCharts', () => ({ ActivityAreaChart: 'ActivityAreaChart', FeatureUsageBars: 'FeatureUsageBars', StatusDonutChart: 'StatusDonutChart' }))
  vi.doMock('@/components/CommentsPanel', () => ({ default: 'CommentsPanel' }))
  const Component = kind === 'workspaces' ? (await import('@/app/workspaces/page')).default
    : kind === 'workspace' ? (await import('@/app/workspaces/[workspaceId]/page')).default
      : kind === 'recruiter' ? (await import('@/app/workspaces/[workspaceId]/recruiter/page')).default
        : kind === 'billing' ? (await import('@/app/billing/page')).default
          : kind === 'dashboard' ? (await import('@/app/dashboard/page')).default
            : (await import('@/components/ReferralPanel')).default
  return {
    api, browser, tab, fetch, copy,
    allow: (value: boolean) => { allowed = value },
    allowTarget: (value: boolean) => {
      Object.values(plans).forEach((plan) => { plan.capabilities.i02 = value })
      entitlementFeatures = { ...entitlementFeatures }
    },
    setUser: (id: string) => { session = { user: { id, email: `${id}@example.test`, name: id }, session: { token: `session-${id}` } } },
    render: () => {
      stateIndex = 0; refIndex = 0; effectIndex = 0
      const tree = Component() as unknown as Element
      if (kind !== 'billing') return tree
      const child = tree.props.children as Element
      return (child.type as () => Element)()
    },
    flush: async () => { const scheduled = pending; pending = []; scheduled.forEach((effect) => effect()); await settle() },
  }
}

afterEach(() => { MOCKS.forEach((name) => vi.doUnmock(name)); vi.unstubAllGlobals(); vi.resetModules() })

describe('optional workspace management controls', () => {
  it('hides create even when its form is open and denies a stale handler, preserving saved workspaces', async () => {
    const h = await harness('workspaces')
    h.render(); await h.flush()
    click(control(h.render(), 'New Workspace'))
    type(input(h.render(), 'e.g. Engineering Team'), 'New team')
    const create = control(h.render(), 'Create')
    h.allow(false)
    const denied = h.render()
    expect(content(denied)).toContain('Saved team')
    expect(content(denied)).not.toContain('New Workspace')
    expect(elements(denied).some((node) => node.props.placeholder === 'e.g. Engineering Team')).toBe(false)
    await click(create)
    expect(h.api.createWorkspace).not.toHaveBeenCalled()
    await (control(denied, 'Delete workspace').props.onClick as (event: unknown) => unknown)({ preventDefault: vi.fn() })
    expect(h.api.deleteWorkspace).toHaveBeenCalledWith('workspace')
  })

  it('blocks invite and submit after revocation, keeps download and removal, and skips optional picker fetch when OFF', async () => {
    const h = await harness('workspace')
    h.render(); await h.flush()
    type(input(h.render(), 'colleague@company.com'), 'new@example.test')
    let tree = h.render()
    const invite = elements(tree).find((node) => node.type === 'button' && (node.props.onClick as { name?: string })?.name === 'handleInvite')!
    click(control(tree, 'Submit mine'))
    const submit = control(h.render(), 'Unshared resume')
    h.allow(false); tree = h.render()
    expect(content(tree)).toContain('Saved resume')
    expect(content(tree)).not.toContain('Submit mine')
    expect(elements(tree).some((node) => node.props.placeholder === 'colleague@company.com')).toBe(false)
    await click(invite); await click(submit)
    expect(h.api.inviteWorkspaceMember).not.toHaveBeenCalled()
    expect(h.api.addResumeToWorkspace).not.toHaveBeenCalled()
    await click(control(tree, 'viewer'))
    expect(h.api.updateWorkspaceMemberRole).toHaveBeenCalledWith('workspace', 'member', 'viewer')
    await click(control(tree, 'Download PDF')); await click(control(tree, 'Remove from workspace'))
    expect(h.api.downloadWorkspaceResume).toHaveBeenCalledWith('workspace', 'resume')
    expect(h.api.removeResumeFromWorkspace).toHaveBeenCalledWith('workspace', 'resume')
    const off = await harness('workspace', false)
    off.render(); await off.flush()
    expect(off.api.listAllResumes).not.toHaveBeenCalled()
    expect(off.api.getWorkspace).toHaveBeenCalledOnce()
  })

  it('does not treat a workspace viewer as a recruiter editor when the feature is enabled', async () => {
    const h = await harness('recruiter', true, 'resume_id=resume')
    h.api.getWorkspace.mockResolvedValue({ id: 'workspace', owner_id: 'another-owner', name: 'Saved team', members: [{ user_id: 'owner', role: 'viewer' }] })
    h.render(); await h.flush()
    const tree = h.render()
    expect(h.api.listRecruiterNotes).not.toHaveBeenCalled()
    expect(content(tree)).not.toContain('Add Note')
    expect(content(tree)).not.toContain('Saved note')
    expect(elements(tree).find((node) => node.type === 'CommentsPanel')?.props.canComment).toBe(false)
  })

  it('keeps saved internal notes readable/removable while hiding add and already-open edit forms', async () => {
    const h = await harness('recruiter', true, 'resume_id=resume')
    h.render(); await h.flush()
    type(input(h.render(), 'Add a recruiter note…'), 'New note')
    const add = control(h.render(), 'Add Note')
    click(control(h.render(), 'Edit note'))
    const save = control(h.render(), 'Save')
    h.allow(false)
    const denied = h.render()
    expect(content(denied)).toContain('Saved note')
    expect(content(denied)).not.toContain('Add Note')
    expect(elements(denied).some((node) => node.type === 'textarea')).toBe(false)
    await click(add); await click(save)
    expect(h.api.createRecruiterNote).not.toHaveBeenCalled()
    expect(h.api.updateRecruiterNote).not.toHaveBeenCalled()
    await click(control(denied, 'Delete note'))
    expect(h.api.deleteRecruiterNote).toHaveBeenCalledWith('workspace', 'resume', 'note')
  })
})

describe('optional commercial and referral controls', () => {
  it('does not verify or preview tokens while OFF, hides standard/custom team/student offers, and preserves seat removal', async () => {
    const h = await harness('billing', false, 'student_verify=student-token&team_invite=invite-token')
    h.render(); await h.flush()
    let tree = h.render()
    expect(h.api.verifyStudentSubscription).not.toHaveBeenCalled()
    expect(h.api.previewTeamSeat).not.toHaveBeenCalled()
    expect(elements(tree).filter((node) => node.type === 'PricingCard').map((node) => (node.props.plan as { id: string }).id)).toEqual(['free', 'pro'])
    const manager = elements(tree).find((node) => node.type === 'SubscriptionManager')!
    ;(manager.props.onLoaded as (value: unknown) => void)({ planId: 'team' })
    h.render(); await h.flush(); tree = h.render()
    expect(content(tree)).not.toContain('Invite teammate')
    expect(h.api.getTeamSeats).toHaveBeenCalled()
    await click(control(tree, 'Remove'))
    expect(h.api.removeTeamSeat).toHaveBeenCalledWith('seat')
  })

  it('uses target SKU grants for upgrades even when the current Free plan disables i02', async () => {
    const h = await harness('billing', false, 'student_verify=student-token')
    h.allowTarget(true)
    h.render(); await h.flush(); h.render(); await h.flush()
    const tree = h.render()
    expect(h.api.verifyStudentSubscription).toHaveBeenCalledOnce()
    expect(elements(tree).filter((node) => node.type === 'PricingCard').map((node) => (node.props.plan as { id: string }).id)).toContain('team')
    const select = elements(tree).find((node) => node.type === 'PricingCard')!.props.onSelectPlan as (id: string) => Promise<void>
    await select('team')
    expect(h.api.createSubscription).toHaveBeenCalledWith('team', 'owner@example.test', 'Owner', { billingPeriod: 'monthly', couponCode: undefined })
    expect(h.api.previewTeamSeat).not.toHaveBeenCalled()
  })

  it('denies target commercial offers even when the current plan grants i02', async () => {
    const h = await harness('billing', true, 'student_verify=student-token')
    h.allowTarget(false)
    h.render(); await h.flush(); h.render(); await h.flush()
    const tree = h.render()
    expect(h.api.verifyStudentSubscription).not.toHaveBeenCalled()
    expect(elements(tree).filter((node) => node.type === 'PricingCard').map((node) => (node.props.plan as { id: string }).id)).toEqual(['free', 'pro'])
    const select = elements(tree).find((node) => node.type === 'PricingCard')!.props.onSelectPlan as (id: string) => Promise<void>
    await select('student'); await select('team')
    expect(h.api.createSubscription).not.toHaveBeenCalled()
    expect(h.browser.open).not.toHaveBeenCalled()
  })

  it('blocks stale student/team handlers and closes a team checkout if revoked across coupon await', async () => {
    const h = await harness('billing')
    h.render(); await h.flush()
    let tree = h.render()
    const select = elements(tree).find((node) => node.type === 'PricingCard')!.props.onSelectPlan as (id: string) => Promise<void>
    await select('student')
    type(input(h.render(), 'you@university.edu'), 'student@university.edu')
    const verify = control(h.render(), 'Send Verification')
    const checkout = select('team')
    h.allowTarget(false); tree = h.render()
    expect(content(tree)).not.toContain('Verify student plan')
    await click(verify); await checkout; await select('custom_team')
    expect(h.api.createSubscription).not.toHaveBeenCalled()
    expect(h.tab.close).toHaveBeenCalledOnce()
  })

  it('blocks already-open team acceptance and invite handlers immediately after revocation', async () => {
    const h = await harness('billing', true, 'team_invite=invite-token')
    h.render(); await h.flush()
    let tree = h.render()
    const accept = control(tree, 'Accept team invitation')
    const manager = elements(tree).find((node) => node.type === 'SubscriptionManager')!
    ;(manager.props.onLoaded as (value: unknown) => void)({ planId: 'team' })
    h.render(); await h.flush()
    type(input(h.render(), 'teammate@company.com'), 'new@example.test')
    const invite = control(h.render(), 'Invite teammate')
    h.allow(false); tree = h.render()
    expect(content(tree)).not.toContain('Accept team invitation')
    expect(content(tree)).not.toContain('Invite teammate')
    await click(accept); await click(invite)
    expect(h.api.joinTeamSeat).not.toHaveBeenCalled()
    expect(h.api.inviteTeamSeat).not.toHaveBeenCalled()
    expect(h.browser.open).not.toHaveBeenCalled()
  })

  it('ignores a student verification response after revocation', async () => {
    const h = await harness('billing', true, 'student_verify=student-token')
    let finish!: (value: unknown) => void
    h.api.verifyStudentSubscription.mockImplementation(() => new Promise((resolve) => { finish = resolve }))
    h.render(); await h.flush(); h.render(); await h.flush()
    expect(h.api.verifyStudentSubscription).toHaveBeenCalledOnce()
    h.allowTarget(false); h.render()
    finish({ success: true, data: { shortUrl: 'https://payments.example.test/checkout' } }); await settle()
    expect(h.browser.location.assign).not.toHaveBeenCalled()
  })

  it('never exposes a previous account referral link or copies it through an old callback', async () => {
    const h = await harness('referral')
    h.render(); await h.flush()
    const copy = control(h.render(), 'Copy')
    h.setUser('other-owner')
    const tree = h.render()
    expect(elements(tree).some((node) => node.props['aria-label'] === 'Your referral link')).toBe(false)
    await click(copy)
    expect(h.copy).not.toHaveBeenCalled()
  })

  it('hides referral UI, skips its fetch, and refuses old copy handlers after revocation', async () => {
    const off = await harness('referral', false)
    expect(off.render()).toBeNull(); await off.flush()
    expect(off.fetch).not.toHaveBeenCalled()
    const h = await harness('referral')
    h.render(); await h.flush()
    const copy = control(h.render(), 'Copy')
    h.allow(false)
    expect(h.render()).toBeNull()
    await click(copy)
    expect(h.copy).not.toHaveBeenCalled()
  })
})

describe('analytics preserves saved-run recovery', () => {
  it('never requests optional analytics when OFF while loading jobs and their results', async () => {
    const h = await harness('dashboard', false)
    h.render(); await h.flush()
    let tree = h.render()
    expect(h.api.listJobs).toHaveBeenCalledOnce()
    for (const method of ['getMyAnalytics', 'getMyAnalyticsTimeseries', 'getResumeStats', 'getCoverLetterStats'] as const) expect(h.api[method]).not.toHaveBeenCalled()
    expect(content(tree)).not.toContain('Activity Trend')
    expect(content(tree)).not.toContain('Feature Usage Mix')
    expect(content(tree)).toContain('Recent Runs')
    expect(elements(tree).some((node) => node.type === 'JobQueue')).toBe(true)
    click(control(tree, 'completed'))
    h.render(); await h.flush(); tree = h.render()
    expect(h.api.getJobResult).toHaveBeenCalledWith('job')
    expect(elements(tree).some((node) => node.props.result && (node.props.result as { ats_score: number }).ats_score === 90)).toBe(true)
  })

  it('does not let an analytics error hide completed job recovery', async () => {
    const h = await harness('dashboard')
    h.api.getMyAnalytics.mockRejectedValue(new Error('Analytics unavailable'))
    h.render(); await h.flush()
    const tree = h.render()
    expect(content(tree)).toContain('Analytics unavailable')
    expect(content(tree)).toContain('completed')
  })
})
