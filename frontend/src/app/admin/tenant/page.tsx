'use client'

/**
 * Tenant Admin Dashboard — Feature 85E.
 *
 * Lets agency/career-center owners manage their white-label tenant:
 *  - Branding (name, logo URL, primary color)
 *  - Member management (invite by email, list, remove)
 *  - Custom domain + DNS TXT verification
 *  - Aggregate stats (members, resumes, compilations)
 */

import { useEffect, useState, useCallback, useRef } from 'react'
import Link from 'next/link'
import { toast } from 'sonner'
import {
  apiClient,
  type CohortSubmission,
  type DomainVerifyResponse,
  type MemberResponse,
  type TenantCohort,
  type TenantResponse,
  type TenantStats,
} from '@/lib/api-client'
import { applyTenantTheme } from '@/lib/tenant-theme'
import { useRequireAuth } from '@/hooks/useRequireAuth'
import SessionLoadError from '@/components/SessionLoadError'

// ── Minimal icon components ───────────────────────────────────────────────────

function Spinner() {
  return (
    <div className="h-5 w-5 animate-spin rounded-full border-2 border-line-2 border-t-accent" />
  )
}

function Badge({ label, color = 'zinc' }: { label: string; color?: string }) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider
        ${color === 'orange' ? 'bg-accent-soft text-accent-strong' : 'bg-surface-2 text-fg-2'}`}
    >
      {label}
    </span>
  )
}

function safeHttpUrl(value: string): string | null {
  try {
    const url = new URL(value)
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : null
  } catch {
    return null
  }
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function TenantAdminPage() {
  const { session, isPending: sessionLoading, error: sessionError } = useRequireAuth()
  const [tenants, setTenants] = useState<TenantResponse[] | null>(null)
  const [selected, setSelected] = useState<TenantResponse | null>(null)
  const [members, setMembers] = useState<MemberResponse[]>([])
  const [stats, setStats] = useState<TenantStats | null>(null)
  const [cohorts, setCohorts] = useState<TenantCohort[]>([])
  const [cohortSubmissions, setCohortSubmissions] = useState<Record<string, CohortSubmission[]>>({})
  const [newCohortName, setNewCohortName] = useState('')
  const [creatingCohort, setCreatingCohort] = useState(false)
  const [inviteCohortId, setInviteCohortId] = useState('')
  const [dnsInfo, setDnsInfo] = useState<DomainVerifyResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [tenantListError, setTenantListError] = useState<string | null>(null)
  const [membersLoading, setMembersLoading] = useState(false)
  const [membersError, setMembersError] = useState<string | null>(null)
  const [statsLoading, setStatsLoading] = useState(false)
  const [statsError, setStatsError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState<'admin' | 'member'>('member')
  const [inviting, setInviting] = useState(false)
  const [canProvisionTenant, setCanProvisionTenant] = useState(false)

  // Branding form state
  const [name, setName] = useState('')
  const [logoUrl, setLogoUrl] = useState('')
  const [primaryColor, setPrimaryColor] = useState('#19375d')
  const [customDomain, setCustomDomain] = useState('')

  // Create-tenant form
  const [showCreate, setShowCreate] = useState(false)
  const [newName, setNewName] = useState('')
  const [newSlug, setNewSlug] = useState('')
  const [creating, setCreating] = useState(false)
  const safeLogoUrl = safeHttpUrl(logoUrl)
  const detailRequestRef = useRef(0)
  const selectedTenantIdRef = useRef<string | null>(null)

  const loadTenants = useCallback(async () => {
    setLoading(true)
    setTenantListError(null)
    try {
      const data = await apiClient.listMyTenants()
      setTenants(data)
      if (data.length > 0 && !selectedTenantIdRef.current) {
        void selectTenant(data[0])
      }
    } catch (error) {
      setTenantListError(error instanceof Error ? error.message : 'Failed to load tenants')
    } finally {
      setLoading(false)
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (sessionLoading) return
    if (!session?.user) {
      setLoading(false)
      return
    }
    loadTenants()
    apiClient.getMe().then(
      (account) => setCanProvisionTenant(account.role === 'admin' || account.plan === 'team'),
      () => setCanProvisionTenant(false),
    )
  }, [loadTenants, session, sessionLoading])

  const selectTenant = useCallback(async (tenant: TenantResponse) => {
    const requestId = ++detailRequestRef.current
    selectedTenantIdRef.current = tenant.id
    setSelected(tenant)
    setName(tenant.name)
    setLogoUrl(tenant.logo_url ?? '')
    setPrimaryColor(tenant.primary_color ?? '#19375d')
    setCustomDomain(tenant.custom_domain ?? '')
    setDnsInfo(null)
    setMembers([])
    setStats(null)
    setCohorts([])
    setCohortSubmissions({})
    setMembersLoading(true)
    setStatsLoading(true)
    setMembersError(null)
    setStatsError(null)

    const [membersResult, statsResult, cohortsResult] = await Promise.allSettled([
      apiClient.listTenantMembers(tenant.id),
      apiClient.getTenantStats(tenant.id),
      apiClient.listTenantCohorts(tenant.id),
    ])
    if (requestId !== detailRequestRef.current) return

    if (membersResult.status === 'fulfilled') {
      setMembers(membersResult.value)
    } else {
      setMembersError(membersResult.reason instanceof Error ? membersResult.reason.message : 'Failed to load tenant members')
    }
    if (statsResult.status === 'fulfilled') {
      setStats(statsResult.value)
    } else {
      setStatsError(statsResult.reason instanceof Error ? statsResult.reason.message : 'Failed to load tenant stats')
    }
    if (cohortsResult.status === 'fulfilled') setCohorts(cohortsResult.value)
    setMembersLoading(false)
    setStatsLoading(false)
  }, [])

  useEffect(() => () => { detailRequestRef.current += 1 }, [])

  const saveBranding = async () => {
    if (!selected) return
    setSaving(true)
    try {
      const updated = await apiClient.updateTenant(selected.id, {
        name: name || undefined,
        logo_url: logoUrl || null,
        primary_color: primaryColor || null,
        custom_domain: customDomain || null,
      })
      setSelected(updated)
      setTenants((prev) => prev?.map((t) => (t.id === updated.id ? updated : t)) ?? null)
      applyTenantTheme({
        ...updated,
        logo_url: updated.logo_url ?? null,
        primary_color: updated.primary_color ?? null,
        custom_domain: updated.custom_domain ?? null,
      })
      toast.success('Branding saved')
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      toast.error(msg || 'Failed to save branding')
    } finally {
      setSaving(false)
    }
  }

  const invite = async () => {
    if (!selected || !inviteEmail.trim()) return
    setInviting(true)
    try {
      const member = await apiClient.inviteTenantMember(
        selected.id,
        inviteEmail.trim(),
        inviteRole,
        inviteCohortId || undefined,
      )
      setInviteEmail('')
      toast.success(`Invitation sent to ${member.email}`)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      toast.error(msg || 'Failed to invite member')
    } finally {
      setInviting(false)
    }
  }

  const createCohort = async () => {
    if (!selected || !newCohortName.trim()) return
    setCreatingCohort(true)
    try {
      const cohort = await apiClient.createTenantCohort(selected.id, newCohortName.trim())
      setCohorts((current) => [...current, cohort])
      setNewCohortName('')
      toast.success(`Cohort “${cohort.name}” created`)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Cohort creation failed')
    } finally {
      setCreatingCohort(false)
    }
  }

  const loadCohortSubmissions = async (cohortId: string) => {
    if (!selected) return
    try {
      const submissions = await apiClient.listCohortSubmissions(selected.id, cohortId)
      setCohortSubmissions((current) => ({ ...current, [cohortId]: submissions }))
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Cohort submissions failed to load')
    }
  }

  const removeMember = async (userId: string) => {
    if (!selected) return
    try {
      await apiClient.removeTenantMember(selected.id, userId)
      setMembers((prev) => prev.filter((m) => m.user_id !== userId))
      toast.success('Member removed')
    } catch {
      toast.error('Failed to remove member')
    }
  }

  const verifyDomain = async () => {
    if (!selected) return
    try {
      const info = await apiClient.verifyTenantDomain(selected.id)
      setDnsInfo(info)
      if (info.verified) {
        setSelected((current) => current ? { ...current, domain_verified: true } : current)
        setTenants((current) => current?.map((tenant) => (
          tenant.id === selected.id ? { ...tenant, domain_verified: true } : tenant
        )) ?? null)
        toast.success('Domain ownership verified')
      } else {
        toast.info('DNS record is not visible yet. Add the record and retry.')
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      toast.error(msg || 'Failed to fetch DNS instructions')
    }
  }

  const createTenant = async () => {
    if (!newName.trim() || !newSlug.trim()) return
    setCreating(true)
    try {
      const tenant = await apiClient.createTenant({ name: newName, slug: newSlug })
      setTenants((prev) => [...(prev ?? []), tenant])
      setShowCreate(false)
      setNewName('')
      setNewSlug('')
      await selectTenant(tenant)
      toast.success(`Tenant "${tenant.name}" created`)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err)
      toast.error(msg || 'Failed to create tenant')
    } finally {
      setCreating(false)
    }
  }

  if (sessionLoading || (session && loading)) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center">
        <Spinner />
      </div>
    )
  }
  if (sessionError && !session) return <SessionLoadError area="Tenant management" />
  if (!session?.user) return null

  return (
    <div className="mx-auto max-w-5xl px-4 py-12 space-y-10">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <p className="text-[10px] uppercase tracking-[0.25em] text-fg-3">Admin</p>
          <h1 className="mt-1 text-xl font-semibold text-fg">Tenant Management</h1>
        </div>
        {canProvisionTenant && (
          <button
            onClick={() => setShowCreate(true)}
            className="rounded-[var(--radius-md)] bg-accent-soft px-4 py-2 text-sm font-medium text-accent-strong transition hover:brightness-110"
          >
            + New Tenant
          </button>
        )}
      </div>

      {/* Create tenant modal */}
      {showCreate && canProvisionTenant && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)]">
          <div className="w-full max-w-sm rounded-[var(--radius-lg)] border border-line bg-bg p-6 shadow-[var(--shadow-2)]">
            <h2 className="mb-5 text-base font-semibold text-fg">Create New Tenant</h2>
            <div className="space-y-3">
              <input
                type="text"
                placeholder="Tenant name (e.g. Acme Recruiting)"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                className="w-full rounded-[var(--radius-md)] border border-line bg-surface px-3 py-2 text-sm text-fg placeholder-fg-3 focus:outline-none focus:ring-1 focus:ring-accent"
              />
              <input
                type="text"
                placeholder="Slug (e.g. acme-recruiting)"
                value={newSlug}
                onChange={(e) => setNewSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-'))}
                className="w-full rounded-[var(--radius-md)] border border-line bg-surface px-3 py-2 text-sm text-fg placeholder-fg-3 focus:outline-none focus:ring-1 focus:ring-accent"
              />
              <p className="text-[11px] text-fg-3">
                Access URL: <span className="text-fg-2">{newSlug || 'your-slug'}.latexy.io</span>
              </p>
            </div>
            <div className="mt-5 flex gap-3">
              <button
                onClick={() => setShowCreate(false)}
                className="flex-1 rounded-[var(--radius-md)] border border-line py-2 text-sm text-fg-2 transition hover:text-fg"
              >
                Cancel
              </button>
              <button
                onClick={createTenant}
                disabled={creating || !newName.trim() || !newSlug.trim()}
                className="flex-1 rounded-[var(--radius-md)] bg-accent-soft py-2 text-sm font-medium text-accent-strong transition hover:brightness-110 disabled:opacity-40"
              >
                {creating ? 'Creating…' : 'Create'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Tenant selector */}
      {tenants && tenants.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {tenants.map((t) => (
            <button
              key={t.id}
              onClick={() => selectTenant(t)}
              className={`rounded-full border px-4 py-1.5 text-sm transition ${
                selected?.id === t.id
                  ? 'border-accent bg-accent-soft text-accent-strong'
                  : 'border-line bg-surface text-fg-2 hover:text-fg'
              }`}
            >
              {t.name}
            </button>
          ))}
        </div>
      )}

      {tenantListError && (
        <div role="alert" className="rounded-[var(--radius-lg)] border border-err/30 bg-err/5 px-6 py-5 text-center">
          <p className="text-sm font-semibold text-err">Tenant list could not be loaded</p>
          <p className="mt-1 text-xs text-fg-2">{tenantListError}</p>
          <button type="button" onClick={() => void loadTenants()} className="mt-3 rounded border border-line px-3 py-1.5 text-xs text-fg-2 hover:bg-surface-2">Retry</button>
        </div>
      )}

      {!selected && !tenantListError && (
        <div className="rounded-[var(--radius-lg)] border border-line bg-surface px-6 py-12 text-center text-fg-3">
          No tenants yet. Create one to get started.
        </div>
      )}

      {selected && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          {/* Left column — stats */}
          <div className="space-y-4 lg:col-span-1">
            {/* Stats cards */}
            <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
              <p className="mb-4 text-[10px] uppercase tracking-[0.25em] text-fg-3">Stats</p>
              {statsLoading ? (
                <div className="flex justify-center py-4"><Spinner /></div>
              ) : statsError ? (
                <div role="alert" className="space-y-2 py-3 text-center">
                  <p className="text-xs text-err">{statsError}</p>
                  <button type="button" onClick={() => void selectTenant(selected)} className="text-xs text-err underline">Retry tenant data</button>
                </div>
              ) : stats ? (
                <div className="space-y-3">
                  {[{ label: 'Members', value: stats.member_count }].map(({ label, value }) => (
                    <div key={label} className="flex items-center justify-between">
                      <span className="text-sm text-fg-3">{label}</span>
                      <span className="text-sm font-semibold text-fg">{value}</span>
                    </div>
                  ))}
                </div>
              ) : null}
            </div>

            {/* Tenant meta */}
            <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-5 space-y-2">
              <p className="text-[10px] uppercase tracking-[0.25em] text-fg-3">Info</p>
              <div className="text-sm text-fg-2">
                <span className="text-fg-3">Slug: </span>{selected.slug}
              </div>
              <div className="text-sm text-fg-2">
                <span className="text-fg-3">Plan: </span>
                <Badge label={selected.plan_id} color="orange" />
              </div>
              <div className="text-sm text-fg-2">
                <span className="text-fg-3">Max members: </span>{selected.max_members}
              </div>
            </div>
          </div>

          {/* Right column — branding + members + domain */}
          <div className="space-y-6 lg:col-span-2">
            {/* Branding */}
            <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
              <p className="mb-4 text-[10px] uppercase tracking-[0.25em] text-fg-3">Branding</p>
              <div className="space-y-3">
                <div>
                  <label className="mb-1 block text-xs text-fg-3">Tenant name</label>
                  <input
                    type="text"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg placeholder-fg-3 focus:outline-none focus:ring-1 focus:ring-accent"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs text-fg-3">Logo URL</label>
                  <input
                    type="url"
                    value={logoUrl}
                    onChange={(e) => setLogoUrl(e.target.value)}
                    placeholder="https://example.com/logo.png"
                    className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg placeholder-fg-3 focus:outline-none focus:ring-1 focus:ring-accent"
                  />
                  {safeLogoUrl && (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={safeLogoUrl} alt="Logo preview" className="mt-2 h-10 rounded object-contain" />
                  )}
                </div>
                <div>
                  <label className="mb-1 block text-xs text-fg-3">Primary color</label>
                  <div className="flex items-center gap-3">
                    <input
                      type="color"
                      value={primaryColor}
                      onChange={(e) => setPrimaryColor(e.target.value)}
                      className="h-9 w-14 cursor-pointer rounded border border-line bg-transparent"
                    />
                    <span className="font-mono text-sm text-fg-2">{primaryColor}</span>
                    <span
                      className="h-6 w-6 rounded-full border border-line"
                      style={{ background: primaryColor }}
                    />
                  </div>
                </div>
                <button
                  onClick={saveBranding}
                  disabled={saving}
                  className="w-full rounded-[var(--radius-md)] bg-accent-soft py-2 text-sm font-medium text-accent-strong transition hover:brightness-110 disabled:opacity-40"
                >
                  {saving ? 'Saving…' : 'Save Branding'}
                </button>
              </div>
            </section>

            {/* Custom domain */}
            <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
              <p className="mb-4 text-[10px] uppercase tracking-[0.25em] text-fg-3">Custom Domain</p>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={customDomain}
                  onChange={(e) => setCustomDomain(e.target.value)}
                  placeholder="resumes.acme.com"
                  className="flex-1 rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg placeholder-fg-3 focus:outline-none focus:ring-1 focus:ring-accent"
                />
                <button
                  onClick={verifyDomain}
                  disabled={!selected.custom_domain || customDomain !== selected.custom_domain}
                  className="rounded-[var(--radius-md)] border border-line px-4 py-2 text-sm text-fg-2 transition hover:text-fg disabled:opacity-30"
                >
                  {selected.domain_verified ? 'Recheck DNS' : 'Verify DNS'}
                </button>
              </div>

              {dnsInfo && (
                <div className="mt-4 rounded-[var(--radius-md)] border border-line bg-bg p-4 space-y-2 text-xs text-fg-2">
                  <p className="font-medium text-fg">
                    {dnsInfo.verified ? 'Domain verified' : 'Add this DNS TXT record:'}
                  </p>
                  <div>
                    <span className="text-fg-3">Name: </span>
                    <code className="text-accent-strong">{dnsInfo.txt_record_name}</code>
                  </div>
                  <div>
                    <span className="text-fg-3">Value: </span>
                    <code className="text-accent-strong">{dnsInfo.txt_record_value}</code>
                  </div>
                  <p className="text-fg-3 leading-relaxed">{dnsInfo.instructions}</p>
                  <p className="text-fg-3 leading-relaxed">
                    DNS verification proves ownership only. Your deployment operator must also attach this
                    hostname to the frontend deployment and add it to the explicit authentication origins.
                  </p>
                </div>
              )}
              {customDomain !== (selected.custom_domain ?? '') && (
                <p className="mt-2 text-xs text-fg-3">Save branding before verifying a changed domain.</p>
              )}
            </section>

            {/* Career-centre cohorts */}
            <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
              <p className="mb-4 text-[10px] uppercase tracking-[0.25em] text-fg-3">Student Cohorts</p>
              <div className="mb-4 flex gap-2">
                <input
                  value={newCohortName}
                  onChange={(event) => setNewCohortName(event.target.value)}
                  onKeyDown={(event) => event.key === 'Enter' && void createCohort()}
                  placeholder="e.g. Class of 2027"
                  className="flex-1 rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg placeholder-fg-3 focus:outline-none focus:ring-1 focus:ring-accent"
                />
                <button
                  type="button"
                  onClick={() => void createCohort()}
                  disabled={creatingCohort || !newCohortName.trim()}
                  className="rounded-[var(--radius-md)] bg-accent-soft px-4 py-2 text-sm font-medium text-accent-strong disabled:opacity-40"
                >
                  {creatingCohort ? 'Creating…' : 'Create cohort'}
                </button>
              </div>
              {cohorts.length === 0 ? (
                <p className="text-sm text-fg-3">No cohorts yet.</p>
              ) : (
                <div className="space-y-3">
                  {cohorts.map((cohort) => (
                    <div key={cohort.id} className="rounded-[var(--radius-md)] border border-line bg-surface-2 p-4">
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <div>
                          <p className="text-sm font-medium text-fg">{cohort.name}</p>
                          <p className="text-xs text-fg-3">{cohort.member_count} students/admins · {cohort.resume_count} submissions</p>
                        </div>
                        <div className="flex gap-3 text-xs">
                          <button type="button" onClick={() => void loadCohortSubmissions(cohort.id)} className="text-accent-strong underline">Refresh milestones</button>
                          <Link href={`/workspaces/${cohort.id}/recruiter`} className="text-accent-strong underline">Review & comment</Link>
                        </div>
                      </div>
                      {cohortSubmissions[cohort.id] && (
                        <div className="mt-3 overflow-x-auto">
                          <table className="w-full text-left text-xs">
                            <thead className="text-fg-3"><tr><th className="py-1">Student</th><th>Started</th><th>Candidate opened</th><th>Candidate downloaded</th></tr></thead>
                            <tbody className="text-fg-2">
                              {cohortSubmissions[cohort.id].map((submission) => (
                                <tr key={submission.resume_id} className="border-t border-line">
                                  <td className="py-2 pr-3"><span className="block text-fg">{submission.student_name || submission.student_email}</span><span className="text-fg-3">{submission.title}</span></td>
                                  <td>{new Date(submission.started_at).toLocaleDateString()}</td>
                                  <td>{submission.opened_at && submission.opened_actor === 'candidate' && submission.opened_source === 'candidate_self' ? new Date(submission.opened_at).toLocaleDateString() : '—'}</td>
                                  <td>{submission.downloaded_at && submission.downloaded_actor === 'candidate' && submission.downloaded_source === 'candidate_self' ? new Date(submission.downloaded_at).toLocaleDateString() : '—'}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </section>

            {/* Member management */}
            <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
              <p className="mb-4 text-[10px] uppercase tracking-[0.25em] text-fg-3">
                Members ({members.length} / {selected.max_members})
              </p>

              {/* Invite */}
              <div className="mb-4 flex gap-2">
                <input
                  type="email"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  placeholder="colleague@example.com"
                  onKeyDown={(e) => e.key === 'Enter' && invite()}
                  className="flex-1 rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg placeholder-fg-3 focus:outline-none focus:ring-1 focus:ring-accent"
                />
                <select
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value as 'admin' | 'member')}
                  className="rounded-[var(--radius-md)] border border-line bg-surface-2 px-2 py-2 text-sm text-fg-2 focus:outline-none"
                >
                  <option value="member">Member</option>
                  {session.user.id === selected.owner_id && <option value="admin">Admin</option>}
                </select>
                {cohorts.length > 0 && (
                  <select
                    value={inviteCohortId}
                    onChange={(event) => setInviteCohortId(event.target.value)}
                    aria-label="Cohort for invited member"
                    className="rounded-[var(--radius-md)] border border-line bg-surface-2 px-2 py-2 text-sm text-fg-2 focus:outline-none"
                  >
                    <option value="">No cohort</option>
                    {cohorts.map((cohort) => <option key={cohort.id} value={cohort.id}>{cohort.name}</option>)}
                  </select>
                )}
                <button
                  onClick={invite}
                  disabled={inviting || !inviteEmail.trim()}
                  className="rounded-[var(--radius-md)] bg-accent-soft px-4 py-2 text-sm font-medium text-accent-strong transition hover:brightness-110 disabled:opacity-40"
                >
                  {inviting ? 'Inviting…' : 'Invite'}
                </button>
              </div>

              {/* Member list */}
              <div className="space-y-2">
                {membersLoading && <div className="flex justify-center py-4"><Spinner /></div>}
                {!membersLoading && membersError && (
                  <div role="alert" className="space-y-2 py-3 text-center">
                    <p className="text-xs text-err">{membersError}</p>
                    <button type="button" onClick={() => void selectTenant(selected)} className="text-xs text-err underline">Retry tenant data</button>
                  </div>
                )}
                {!membersLoading && !membersError && members.length === 0 && (
                  <p className="text-sm text-fg-3">No members yet.</p>
                )}
                {!membersLoading && members.map((m) => (
                  <div
                    key={m.user_id}
                    className="flex items-center justify-between rounded-[var(--radius-md)] border border-line bg-surface-2 px-4 py-3"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm text-fg">{m.name || m.email}</p>
                      {m.name && (
                        <p className="truncate text-xs text-fg-3">{m.email}</p>
                      )}
                    </div>
                    <div className="flex items-center gap-3">
                      <Badge label={m.role} color={m.role === 'admin' ? 'orange' : 'zinc'} />
                      <button
                        onClick={() => removeMember(m.user_id)}
                        className="text-xs text-fg-3 transition hover:text-err"
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          </div>
        </div>
      )}
    </div>
  )
}
