'use client'

import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { toast } from 'sonner'
import { apiClient, type AdminUser360 } from '@/lib/api-client'
import { formatDateTime, formatMoney, formatNumber, shortId, summarize } from './admin-format'

const PLAN_OPTIONS = ['free', 'basic', 'basic_annual', 'pro', 'pro_annual', 'byok', 'byok_annual', 'student', 'team']
const STATUS_OPTIONS = ['active', 'inactive', 'trialing', 'past_due', 'cancelled', 'comped']
const QUOTA_OPTIONS = [
  { value: '', label: 'All dimensions' },
  { value: 'compilations', label: 'Compilations' },
  { value: 'optimizations', label: 'Optimizations' },
  { value: 'ai_assists', label: 'AI assists' },
] as const

function Section({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
      <h3 className="text-sm font-semibold text-fg">{title}</h3>
      {description && <p className="mt-1 text-xs leading-relaxed text-fg-3">{description}</p>}
      <div className="mt-3">{children}</div>
    </section>
  )
}

function Pill({ label, ok }: { label: string; ok: boolean }) {
  return (
    <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${ok ? 'border-ok/30 bg-ok/10 text-ok' : 'border-line bg-surface-2 text-fg-3'}`}>
      {label}
    </span>
  )
}

function text(value: unknown): string {
  return typeof value === 'string' && value ? value : '—'
}

function isActive(value: unknown): boolean {
  return value !== false
}

export default function AdminUserDetail({
  userId,
  onClose,
  canAdmin = true,
}: {
  userId: string
  onClose: () => void
  canAdmin?: boolean
}) {
  const [data, setData] = useState<AdminUser360 | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [plan, setPlan] = useState('pro')
  const [status, setStatus] = useState('active')
  const [dimension, setDimension] = useState<'' | 'compilations' | 'optimizations' | 'ai_assists'>('')
  const [revealed, setRevealed] = useState<{ email: string | null; name: string | null } | null>(null)
  const [busy, setBusy] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const next = await apiClient.getAdminUser360(userId)
      setData(next)
      if (next.user.subscription_plan && PLAN_OPTIONS.includes(next.user.subscription_plan)) {
        setPlan(next.user.subscription_plan)
      }
      if (next.user.subscription_status && STATUS_OPTIONS.includes(next.user.subscription_status)) {
        setStatus(next.user.subscription_status)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load User 360')
    } finally {
      setLoading(false)
    }
  }, [userId])

  useEffect(() => {
    void load()
  }, [load])

  const run = async (
    action: string,
    call: () => Promise<unknown>,
    successMessage: string,
  ) => {
    setBusy(action)
    try {
      await call()
      toast.success(successMessage)
      await load()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Action failed')
    } finally {
      setBusy(null)
    }
  }

  const requireReason = (): string | null => {
    if (!reason.trim()) {
      toast.error('Enter a reason for this audited action')
      return null
    }
    return reason.trim()
  }

  const revealPii = async () => {
    const cleaned = requireReason()
    if (!cleaned) return
    setBusy('reveal')
    try {
      const next = await apiClient.revealAdminUserPii(userId, cleaned)
      setRevealed(next)
      toast.success('PII revealed and recorded in the audit log')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'PII reveal failed')
    } finally {
      setBusy(null)
    }
  }

  const changePlan = async () => {
    const cleaned = requireReason()
    if (!cleaned) return
    await run(
      'plan',
      () => apiClient.changeAdminUserPlan(userId, { plan, status, reason: cleaned }),
      'Plan updated and audited',
    )
  }

  const resetTrial = async () => {
    const cleaned = requireReason()
    if (!cleaned) return
    await run('trial', () => apiClient.resetAdminUserTrial(userId, cleaned), 'Trial reset and audited')
  }

  const resetQuota = async () => {
    const cleaned = requireReason()
    if (!cleaned) return
    await run(
      'quota',
      () => apiClient.resetAdminUserQuota(userId, { reason: cleaned, dimension: dimension || undefined }),
      'Quota counters reset and audited',
    )
  }

  const revokeSessions = async () => {
    const cleaned = requireReason()
    if (!cleaned) return
    await run('sessions', () => apiClient.revokeAdminUserSessions(userId, cleaned), 'Sessions revoked')
  }

  const revokePasskeys = async () => {
    const cleaned = requireReason()
    if (!cleaned) return
    await run('passkeys', () => apiClient.revokeAdminUserPasskeys(userId, cleaned), 'Passkeys revoked')
  }

  const revokeKeys = async () => {
    const cleaned = requireReason()
    if (!cleaned) return
    await run(
      'keys',
      () => apiClient.revokeAdminUserApiKeys(userId, { reason: cleaned, scope: 'all' }),
      'API keys deactivated',
    )
  }

  if (loading && !data) {
    return (
      <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-6" role="status">
        <p className="text-sm text-fg-3">Loading User 360…</p>
      </div>
    )
  }
  if (error && !data) {
    return (
      <div className="rounded-[var(--radius-lg)] border border-err/20 bg-err/[0.06] p-5" role="alert">
        <p className="text-sm font-semibold text-err">User 360 could not be loaded</p>
        <p className="mt-1 text-xs text-err/80">{error}</p>
        <button type="button" onClick={() => void load()} className="mt-3 rounded border border-line px-3 py-1.5 text-xs">Retry</button>
      </div>
    )
  }
  if (!data) return null

  const user = data.user
  const email = revealed?.email ?? user.email
  const name = revealed?.name ?? user.name
  const activeSubscriptions = data.billing.subscriptions.filter((row) => ['active', 'cancel_scheduled'].includes(text(row.status)))
  const failedCompiles = Math.max(0, data.production.compilations - data.production.successful_compilations)

  return (
    <section className="overflow-hidden rounded-[var(--radius-lg)] border-2 border-accent/30 bg-surface">
      <header className="border-b border-line bg-accent-soft/30 px-5 py-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-base font-semibold text-fg">{name || 'Unnamed user'}</h3>
              <Pill label={user.role} ok={user.role === 'admin'} />
              <Pill label={user.email_verified ? 'verified' : 'unverified'} ok={user.email_verified} />
              {user.two_factor_enabled && <Pill label="2FA" ok />}
              {user.pii_masked && !revealed && <Pill label="PII masked" ok={false} />}
            </div>
            <p className="mt-1 break-all font-mono text-xs text-fg-2">{email || 'No email'}</p>
            <p className="mt-1 text-[11px] text-fg-3">
              {user.subscription_plan || 'free'} · {user.subscription_status || 'inactive'} · joined {formatDateTime(user.created_at)}
            </p>
          </div>
          <button type="button" onClick={onClose} className="rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2">
            Close
          </button>
        </div>
        {error && <p className="mt-2 text-xs text-err">{error}</p>}
      </header>

      <div className="space-y-4 p-5">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-md border border-line bg-surface-2/60 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wider text-fg-3">Resumes</p>
            <p className="mt-0.5 text-xl font-semibold text-fg">{formatNumber(data.production.resumes)}</p>
          </div>
          <div className="rounded-md border border-line bg-surface-2/60 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wider text-fg-3">Compiles</p>
            <p className="mt-0.5 text-xl font-semibold text-fg">{formatNumber(data.production.compilations)}</p>
            <p className="text-[10px] text-err">{formatNumber(failedCompiles)} failed</p>
          </div>
          <div className="rounded-md border border-line bg-surface-2/60 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wider text-fg-3">AI optimizations</p>
            <p className="mt-0.5 text-xl font-semibold text-fg">{formatNumber(data.production.optimizations)}</p>
          </div>
          <div className="rounded-md border border-line bg-surface-2/60 px-3 py-2">
            <p className="text-[10px] uppercase tracking-wider text-fg-3">Active subscriptions</p>
            <p className="mt-0.5 text-xl font-semibold text-fg">{formatNumber(activeSubscriptions.length)}</p>
          </div>
        </div>

        {canAdmin ? <Section
          title="Audited support controls"
          description="Every action requires a reason and is written to the immutable audit log. PII reveal is limited to admins."
        >
          <label className="block text-[11px] font-medium text-fg-2">
            Reason for this session of actions
            <input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              maxLength={1000}
              placeholder="e.g. Ticket #1234 — customer reports failed checkout"
              className="mt-1 w-full rounded-md border border-line bg-bg px-3 py-2 text-xs text-fg"
            />
          </label>
          <div className="mt-3 grid gap-3 lg:grid-cols-3">
            <div className="rounded-md border border-line bg-surface-2/40 p-3">
              <p className="text-xs font-semibold text-fg">Identity</p>
              <button type="button" onClick={() => void revealPii()} disabled={busy === 'reveal' || Boolean(revealed)} className="mt-2 w-full rounded border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40">
                {revealed ? 'PII revealed' : 'Reveal email and name'}
              </button>
            </div>
            <div className="rounded-md border border-line bg-surface-2/40 p-3">
              <p className="text-xs font-semibold text-fg">Plan override</p>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <select aria-label="Plan SKU" value={plan} onChange={(event) => setPlan(event.target.value)} className="rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg">
                  {PLAN_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
                <select aria-label="Subscription status" value={status} onChange={(event) => setStatus(event.target.value)} className="rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg">
                  {STATUS_OPTIONS.map((item) => <option key={item} value={item}>{item}</option>)}
                </select>
              </div>
              <button type="button" onClick={() => void changePlan()} disabled={busy === 'plan'} className="mt-2 w-full rounded border border-line px-3 py-1.5 text-xs font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40">
                Apply plan override
              </button>
            </div>
            <div className="rounded-md border border-line bg-surface-2/40 p-3">
              <p className="text-xs font-semibold text-fg">Quota and trial</p>
              <select aria-label="Quota dimension" value={dimension} onChange={(event) => setDimension(event.target.value as typeof dimension)} className="mt-2 w-full rounded border border-line bg-bg px-2 py-1.5 text-xs text-fg">
                {QUOTA_OPTIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}
              </select>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <button type="button" onClick={() => void resetQuota()} disabled={busy === 'quota'} className="rounded border border-line px-2 py-1.5 text-[10px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40">Reset quota</button>
                <button type="button" onClick={() => void resetTrial()} disabled={busy === 'trial'} className="rounded border border-line px-2 py-1.5 text-[10px] font-medium text-fg-2 hover:bg-surface-2 disabled:opacity-40">Reset trial</button>
              </div>
            </div>
            <div className="rounded-md border border-line bg-surface-2/40 p-3 lg:col-span-3">
              <p className="text-xs font-semibold text-fg">Security revocation</p>
              <p className="mt-1 text-[11px] text-fg-3">
                {formatNumber(data.security.session_count)} sessions · {formatNumber(data.security.passkey_count)} passkeys ·{' '}
                {formatNumber(data.security.byok_keys.filter((row) => isActive(row.is_active)).length)} active BYOK keys ·{' '}
                {formatNumber(data.security.developer_keys.filter((row) => isActive(row.is_active)).length)} active developer keys
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                <button type="button" onClick={() => void revokeSessions()} disabled={busy === 'sessions'} className="rounded border border-err/30 px-3 py-1.5 text-xs font-medium text-err hover:bg-err/5 disabled:opacity-40">Revoke sessions</button>
                <button type="button" onClick={() => void revokePasskeys()} disabled={busy === 'passkeys'} className="rounded border border-err/30 px-3 py-1.5 text-xs font-medium text-err hover:bg-err/5 disabled:opacity-40">Revoke passkeys</button>
                <button type="button" onClick={() => void revokeKeys()} disabled={busy === 'keys'} className="rounded border border-err/30 px-3 py-1.5 text-xs font-medium text-err hover:bg-err/5 disabled:opacity-40">Deactivate API keys</button>
              </div>
            </div>
          </div>
        </Section> : (
          <div className="rounded-[var(--radius-lg)] border border-line bg-surface-2/50 px-4 py-3 text-xs text-fg-3">
            Support access is read-only. PII stays masked and support actions require an admin.
          </div>
        )}

        <div className="grid gap-4 xl:grid-cols-2">
          <Section title="Activation and usage" description="Milestones and first-party actions. No document content is included.">
            <div className="flex flex-wrap gap-2">
              <Pill label="resume" ok={data.activation.has_resume} />
              <Pill label="compile" ok={data.activation.has_compile} />
              <Pill label="export" ok={data.activation.has_export} />
              <Pill label="AI optimize" ok={data.activation.has_optimization} />
              <Pill label="paid" ok={data.activation.has_paid} />
            </div>
            <p className="mt-2 text-xs text-fg-3">
              {formatNumber(data.usage.events_30d)} events in 30 days · last activity {formatDateTime(data.activation.last_activity_at)}
            </p>
            <div className="mt-3 max-h-48 overflow-auto">
              <table className="w-full border-collapse text-xs">
                <thead><tr className="text-left text-[10px] uppercase tracking-wider text-fg-3"><th className="py-1">Action</th><th className="py-1 text-right">Count</th><th className="py-1 text-right">Last</th></tr></thead>
                <tbody>
                  {data.usage.actions.map((row) => (
                    <tr key={row.action} className="border-t border-line">
                      <td className="py-1.5 font-mono text-[11px] text-fg-2">{row.action}</td>
                      <td className="py-1.5 text-right text-fg">{formatNumber(row.count)}</td>
                      <td className="py-1.5 text-right text-fg-3">{formatDateTime(row.last_at)}</td>
                    </tr>
                  ))}
                  {data.usage.actions.length === 0 && <tr><td colSpan={3} className="py-3 text-center text-fg-3">No usage events.</td></tr>}
                </tbody>
              </table>
            </div>
          </Section>

          <Section title="Integrations" description="Presence only. Credentials and external account identifiers are never returned.">
            <div className="grid grid-cols-2 gap-2 text-xs">
              {Object.entries(data.integrations).map(([key, connected]) => (
                <div key={key} className="flex items-center justify-between rounded border border-line bg-surface-2/40 px-3 py-2">
                  <span className="capitalize text-fg-2">{key}</span>
                  <Pill label={connected ? 'connected' : 'off'} ok={connected} />
                </div>
              ))}
            </div>
          </Section>
        </div>

        <Section title="Billing history" description="Amounts are stored in the provider's smallest currency unit. No card or bank details are present.">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[620px] border-collapse text-xs">
              <thead><tr className="text-left text-[10px] uppercase tracking-wider text-fg-3"><th className="py-1">Payment</th><th className="py-1">Status</th><th className="py-1 text-right">Amount</th><th className="py-1">Created</th></tr></thead>
              <tbody>
                {data.billing.payments.map((row) => (
                  <tr key={row.id} className="border-t border-line">
                    <td className="py-1.5 font-mono text-[10px] text-fg-3">{shortId(row.provider_payment_id, 18)}</td>
                    <td className="py-1.5 text-fg-2">{row.status}</td>
                    <td className="py-1.5 text-right text-fg">{formatMoney(row.amount / 100, row.currency)}</td>
                    <td className="py-1.5 text-fg-3">{formatDateTime(row.created_at)}</td>
                  </tr>
                ))}
                {data.billing.payments.length === 0 && <tr><td colSpan={4} className="py-3 text-center text-fg-3">No payments.</td></tr>}
              </tbody>
            </table>
          </div>
          {data.billing.refund_requests.length > 0 && (
            <div className="mt-3 space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-fg-3">Refund requests</p>
              {data.billing.refund_requests.map((row) => (
                <p key={row.id} className="text-[11px] text-fg-3">
                  {row.status} · {row.amount == null ? 'full' : formatMoney(row.amount / 100)} · {formatDateTime(row.requested_at)}
                </p>
              ))}
            </div>
          )}
        </Section>

        <div className="grid gap-4 xl:grid-cols-2">
          <Section title="Recent resumes" description="Titles and timestamps only; document bodies are not loaded.">
            <ul className="space-y-1 text-xs">
              {data.production.recent_resumes.map((row) => (
                <li key={row.id} className="flex items-center justify-between gap-3 border-b border-line py-1.5 last:border-0">
                  <span className="truncate text-fg-2">{row.title}</span>
                  <span className="shrink-0 text-[10px] text-fg-3">{formatDateTime(row.updated_at)}</span>
                </li>
              ))}
              {data.production.recent_resumes.length === 0 && <li className="text-fg-3">No resumes.</li>}
            </ul>
          </Section>
          <Section title="Recent security sessions" description="IP addresses are intentionally omitted from this composed view.">
            <ul className="space-y-1 text-xs">
              {data.security.sessions.map((row) => (
                <li key={row.id} className="border-b border-line py-1.5 last:border-0">
                  <p className="text-fg-2">{summarize(row.user_agent, 80)}</p>
                  <p className="text-[10px] text-fg-3">created {formatDateTime(row.created_at)} · expires {formatDateTime(row.expires_at)}</p>
                </li>
              ))}
              {data.security.sessions.length === 0 && <li className="text-fg-3">No active sessions.</li>}
            </ul>
          </Section>
        </div>

        {data.recent_admin_actions.length > 0 && (
          <Section title="Recent admin actions" description="Audit records targeting this user. Reasons are included because this view is admin-only.">
            <ul className="space-y-1 text-xs">
              {data.recent_admin_actions.map((row) => (
                <li key={row.id} className="border-b border-line py-1.5 last:border-0">
                  <p className="font-mono text-[11px] text-fg-2">{row.action}</p>
                  <p className="text-[10px] text-fg-3">
                    {formatDateTime(row.created_at)} · {row.actor_email || shortId(row.actor_user_id, 12)}
                    {row.reason ? ` · ${summarize(row.reason, 100)}` : ''}
                  </p>
                </li>
              ))}
            </ul>
          </Section>
        )}
      </div>
    </section>
  )
}
