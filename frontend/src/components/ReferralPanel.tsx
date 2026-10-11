'use client'

import { useEffect, useRef, useState } from 'react'

import { useEntitlements } from '@/contexts/EntitlementsContext'
import { useSession } from '@/lib/auth-client'

type ReferralStatus = {
  available: boolean
  scope: string
  message: string
  share_code: string | null
  your_attribution: { status: string; captured_at: string | null } | null
  referral_summary: { total: number; captured: number; qualified: number; reversed: number }
  reward_summary: { issued: number; pending: number; reversed: number; issued_extension_days: number }
  policy_configured: boolean
}

export default function ReferralPanel() {
  const { can } = useEntitlements()
  const { data: session } = useSession()
  const userId = session?.user?.id ?? null
  const enabled = Boolean(userId) && can('i03')
  const userIdRef = useRef(userId)
  userIdRef.current = userId
  const enabledRef = useRef(enabled)
  enabledRef.current = enabled
  const [snapshot, setSnapshot] = useState<{ userId: string; status: ReferralStatus } | null>(null)
  const status = snapshot && snapshot.userId === userId ? snapshot.status : null
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!enabled || !userId) return
    let active = true
    setSnapshot(null)
    setError(null)
    fetch('/api/referral', { credentials: 'include', cache: 'no-store' })
      .then(async (response) => {
        if (!response.ok) throw new Error('Referral status unavailable')
        return response.json() as Promise<ReferralStatus>
      })
      .then((data) => { if (active) setSnapshot({ userId, status: data }) })
      .catch(() => { if (active) setError('Referral status is unavailable right now.') })
    return () => { active = false }
  }, [enabled, userId])

  const shareUrl = status?.share_code && typeof window !== 'undefined'
    ? `${window.location.origin}/signup?ref=${encodeURIComponent(status.share_code)}`
    : null

  const copy = async () => {
    if (!enabledRef.current || userIdRef.current !== userId || !shareUrl) return
    try {
      await navigator.clipboard.writeText(shareUrl)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1800)
    } catch {
      setError('Copy failed. You can select the link manually.')
    }
  }

  if (!enabled) return null

  return (
    <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-6 space-y-4" aria-labelledby="referral-heading">
      <div>
        <h2 id="referral-heading" className="text-base font-semibold text-fg">User referrals</h2>
        <p className="mt-1 text-[11px] leading-relaxed text-fg-3">
          This is a personal referral link for people you know, not an affiliate or cash-commission programme.
        </p>
      </div>
      {error ? <p className="rounded-[var(--radius-md)] bg-warn/10 px-3 py-2 text-[11px] text-warn">{error}</p> : !status ? <p className="text-[11px] text-fg-3">Checking referral availability…</p> : !status.available ? <p className="text-[11px] text-fg-3">{status.message}</p> : (
        <>
          <p className="text-[11px] text-fg-2">{status.message}</p>
          {shareUrl && <div className="flex gap-2">
            <input readOnly value={shareUrl} aria-label="Your referral link" className="min-w-0 flex-1 rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-[11px] text-fg-2" />
            <button type="button" onClick={copy} className="rounded-[var(--radius-md)] bg-accent px-3 py-2 text-[11px] font-semibold text-accent-fg">{copied ? 'Copied' : 'Copy'}</button>
          </div>}
          <p className="text-[11px] text-fg-3" aria-live="polite">
            {status.referral_summary.total > 0
              ? `${status.referral_summary.total} invited ${status.referral_summary.total === 1 ? 'person has' : 'people have'} claimed your link; ${status.referral_summary.qualified} qualified.`
              : 'No invited user has claimed this link yet.'}
            {status.reward_summary.issued > 0 ? ` ${status.reward_summary.issued} ${status.reward_summary.issued === 1 ? 'reward' : 'rewards'} issued.` : ''}
            {status.reward_summary.pending > 0 ? ` ${status.reward_summary.pending} pending until you have an eligible paid term.` : ''}
          </p>
        </>
      )}
    </section>
  )
}
