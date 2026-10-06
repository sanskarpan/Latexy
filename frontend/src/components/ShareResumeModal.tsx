'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Check, Copy, EyeOff, Link, Loader2, BarChart2, RefreshCw, Trash2, X } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type ShareLinkResponse, type ResumeAnalytics } from '@/lib/api-client'

interface ShareResumeModalProps {
  ownerId: string | null
  resumeId: string
  resumeTitle: string
  /** Existing share token from the resume response (null if not yet shared) */
  initialShareToken?: string | null
  initialShareUrl?: string | null
  initialAnonymous?: boolean
  initialReviewComments?: boolean
  onClose: () => void
  onShareTokenChange?: (token: string | null, url: string | null, anonymous: boolean, reviewComments?: boolean) => void
}

type Tab = 'share' | 'analytics'

// ── Tiny SVG sparkline ──────────────────────────────────────────────────────

function Sparkline({ data }: { data: { date: string; count: number }[] }) {
  const W = 220
  const H = 36
  if (data.length === 0) {
    return <div className="h-9 flex items-center justify-center text-[10px] text-fg-3">No data yet</div>
  }
  const max = Math.max(...data.map((d) => d.count), 1)
  const pts = data.map((d, i) => {
    const x = (i / Math.max(data.length - 1, 1)) * W
    const y = H - (d.count / max) * (H - 4) - 2
    return `${x},${y}`
  })
  const polyline = pts.join(' ')
  // fill area
  const fill = `${pts[0].split(',')[0]},${H} ${polyline} ${pts[pts.length - 1].split(',')[0]},${H}`
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-9" preserveAspectRatio="none">
      <polygon points={fill} fill="var(--accent)" fillOpacity={0.12} />
      <polyline points={polyline} fill="none" stroke="var(--accent)" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}

// ── Country flag emoji ───────────────────────────────────────────────────────

function countryFlag(code: string | null) {
  if (!code || code.length !== 2) return '🌐'
  return String.fromCodePoint(
    ...code.toUpperCase().split('').map((c) => 0x1f1e6 + c.charCodeAt(0) - 65)
  )
}

// ── Referrer display ─────────────────────────────────────────────────────────

function displayReferrer(raw: string | null) {
  if (!raw) return 'Direct'
  try {
    const url = new URL(raw.startsWith('http') ? raw : `https://${raw}`)
    return url.hostname.replace(/^www\./, '')
  } catch {
    return raw.slice(0, 40)
  }
}

// ── Analytics panel ──────────────────────────────────────────────────────────

function AnalyticsPanel({ resumeId }: { resumeId: string }) {
  const [analytics, setAnalytics] = useState<ResumeAnalytics | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const requestIdRef = useRef(0)

  const loadAnalytics = useCallback(async () => {
    const requestId = ++requestIdRef.current
    setLoading(true)
    setError(null)
    try {
      const data = await apiClient.getResumeAnalytics(resumeId)
      if (requestId === requestIdRef.current) setAnalytics(data)
    } catch (requestError) {
      if (requestId === requestIdRef.current) {
        setError(requestError instanceof Error ? requestError.message : 'Failed to load analytics')
      }
    } finally {
      if (requestId === requestIdRef.current) setLoading(false)
    }
  }, [resumeId])

  useEffect(() => {
    void loadAnalytics()
    return () => { requestIdRef.current += 1 }
  }, [loadAnalytics])

  if (loading) {
    return (
      <div className="flex h-48 items-center justify-center">
        <Loader2 size={16} className="animate-spin text-fg-3" />
      </div>
    )
  }
  if (error) {
    return (
      <div role="alert" className="flex flex-col items-center gap-2 py-4 text-center">
        <p className="text-[11px] text-err">{error}</p>
        <button type="button" onClick={() => void loadAnalytics()} className="rounded border border-line px-2 py-1 text-[10px] text-fg-2 hover:bg-surface-2">Retry</button>
      </div>
    )
  }
  if (!analytics) return null

  const lastViewed = analytics.last_viewed_at
    ? new Date(analytics.last_viewed_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
    : null

  return (
    <div className="space-y-4">
      {/* KPI row */}
      <div className="grid grid-cols-3 gap-2">
        {[
          { label: 'Total', value: analytics.total_views },
          { label: 'Last 7d', value: analytics.views_last_7_days },
          { label: 'Last 30d', value: analytics.views_last_30_days },
        ].map(({ label, value }) => (
          <div key={label} className="rounded-[var(--radius-md)] border border-line bg-surface-2 px-2 py-2 text-center">
            <p className="text-base font-semibold text-accent-strong">{value}</p>
            <p className="text-[9px] uppercase tracking-wider text-fg-3">{label}</p>
          </div>
        ))}
      </div>

      {/* Sparkline */}
      <div>
        <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-fg-3">Last 30 days</p>
        <div className="rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2">
          <Sparkline data={analytics.views_by_day} />
        </div>
      </div>

      {/* Countries */}
      {analytics.views_by_country.length > 0 && (
        <div>
          <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-fg-3">Top countries</p>
          <div className="space-y-1">
            {analytics.views_by_country.slice(0, 5).map((c, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="text-sm leading-none">{countryFlag(c.country_code)}</span>
                <span className="flex-1 text-[11px] text-fg-2">{c.country_code ?? 'Unknown'}</span>
                <span className="text-[11px] font-semibold text-fg-2">{c.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Referrers */}
      {analytics.views_by_referrer.length > 0 && (
        <div>
          <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-fg-3">Top referrers</p>
          <div className="space-y-1">
            {analytics.views_by_referrer.slice(0, 5).map((r, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="flex-1 truncate text-[11px] text-fg-2">{displayReferrer(r.referrer)}</span>
                <span className="text-[11px] font-semibold text-fg-2">{r.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {analytics.total_views === 0 && (
        <p className="text-center text-[11px] text-fg-3">No views recorded yet. Share your link to start tracking.</p>
      )}

      {lastViewed && (
        <p className="text-[10px] text-fg-3">Last viewed {lastViewed}</p>
      )}
    </div>
  )
}

// ── Main modal ───────────────────────────────────────────────────────────────

export default function ShareResumeModal({
  ownerId,
  resumeId,
  resumeTitle,
  initialShareToken,
  initialShareUrl,
  initialAnonymous = false,
  initialReviewComments,
  onClose,
  onShareTokenChange,
}: ShareResumeModalProps) {
  // Callers key the modal by owner/document. The immutable identity also
  // invalidates work during a transition render; mounted state rejects late
  // responses from a closed or replaced modal before callbacks/toasts run.
  const mountedRef = useRef(false)
  const identityRef = useRef({ ownerId, resumeId })
  if (identityRef.current.ownerId !== ownerId || identityRef.current.resumeId !== resumeId) {
    identityRef.current = { ownerId, resumeId }
  }
  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])
  const captureOwnership = () => {
    const identity = identityRef.current
    return () => mountedRef.current && identityRef.current === identity
  }
  const [shareData, setShareData] = useState<ShareLinkResponse | null>(
    initialShareToken && initialShareUrl
      ? {
          share_token: initialShareToken,
          share_url: initialShareUrl,
          created_at: '',
          anonymous: initialAnonymous,
          review_comments: initialReviewComments ?? false,
        }
      : null
  )
  const [isGenerating, setIsGenerating] = useState(false)
  const [isRevoking, setIsRevoking] = useState(false)
  const [copied, setCopied] = useState(false)
  const [showRevokeConfirm, setShowRevokeConfirm] = useState(false)
  const [anonymous, setAnonymous] = useState(initialAnonymous)
  // null means an existing link was loaded without the capability in the
  // resume payload. Keep it unknown until the owner explicitly changes it so
  // updating anonymous privacy cannot silently disable review comments.
  const [reviewComments, setReviewComments] = useState<boolean | null>(
    initialShareToken ? (initialReviewComments ?? null) : false,
  )
  const reviewCommentsTouched = useRef(false)
  const [tab, setTab] = useState<Tab>('share')

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  const handleGenerate = async (regenerateAnonymous = false, reviewCommentsOverride?: boolean) => {
    const isActive = captureOwnership()
    setIsGenerating(true)
    try {
      const requestedReviewComments = reviewCommentsOverride
        ?? (reviewCommentsTouched.current || initialReviewComments !== undefined
          ? reviewComments ?? undefined
          : undefined)
      const data = await apiClient.createShareLink(
        resumeId,
        anonymous,
        regenerateAnonymous,
        requestedReviewComments,
      )
      if (!isActive()) return
      const enabledReviewComments = data.review_comments ?? false
      setShareData({ ...data, review_comments: enabledReviewComments })
      setReviewComments(enabledReviewComments)
      onShareTokenChange?.(data.share_token, data.share_url, data.anonymous, enabledReviewComments)
      toast.success(data.anonymous ? 'Anonymous share link created' : 'Share link created')
    } catch (err) {
      if (isActive()) toast.error(err instanceof Error ? err.message : 'Failed to create share link')
    } finally {
      if (isActive()) setIsGenerating(false)
    }
  }

  const toggleReviewComments = () => {
    reviewCommentsTouched.current = true
    setReviewComments((value) => value !== true)
  }

  const handleCopy = async () => {
    if (!shareData?.share_url) return
    const isActive = captureOwnership()
    try {
      await navigator.clipboard.writeText(shareData.share_url)
      if (!isActive()) return
      setCopied(true)
      setTimeout(() => { if (isActive()) setCopied(false) }, 2000)
    } catch {
      if (isActive()) toast.error('Failed to copy link')
    }
  }

  const handleRevoke = async () => {
    const isActive = captureOwnership()
    setIsRevoking(true)
    try {
      await apiClient.revokeShareLink(resumeId)
      if (!isActive()) return
      setShareData(null)
      setShowRevokeConfirm(false)
      setTab('share')
      onShareTokenChange?.(null, null, false, false)
      toast.success('Share link revoked')
    } catch (err) {
      if (isActive()) toast.error(err instanceof Error ? err.message : 'Failed to revoke link')
    } finally {
      if (isActive()) setIsRevoking(false)
    }
  }

  const createdAt = shareData?.created_at
    ? new Date(shareData.created_at).toLocaleDateString('en-US', {
        month: 'long',
        day: 'numeric',
        year: 'numeric',
      })
    : null

  const tabs: { id: Tab; label: string; icon: React.ReactNode }[] = [
    { id: 'share', label: 'Share', icon: <Link size={11} /> },
    { id: 'analytics', label: 'Analytics', icon: <BarChart2 size={11} /> },
  ]

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] p-4 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-md rounded-[var(--radius-lg)] border border-line bg-surface shadow-[var(--shadow-2)]">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-[var(--radius-md)] bg-accent-soft ring-1 ring-accent">
              <Link size={13} className="text-accent-strong" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-fg">Share Resume</h2>
              <p className="text-[11px] text-fg-3">{resumeTitle}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-[var(--radius-md)] p-1 text-fg-3 transition hover:bg-surface-2 hover:text-fg-2"
          >
            <X size={14} />
          </button>
        </div>

        {/* Tab bar — only when link exists */}
        {shareData && (
          <div className="flex border-b border-line px-5">
            {tabs.map(({ id, label, icon }) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                className={`flex items-center gap-1.5 border-b-2 px-3 py-2.5 text-[11px] font-medium transition ${
                  tab === id
                    ? 'border-accent text-accent-strong'
                    : 'border-transparent text-fg-3 hover:text-fg-2'
                }`}
              >
                {icon}
                {label}
              </button>
            ))}
          </div>
        )}

        {/* Body */}
        <div className="px-5 py-5">
          {!shareData ? (
            // No link yet — always show the generate UI
            <div className="space-y-4">
              <p className="text-sm text-fg-2">
                Generate a public link so anyone can view the compiled PDF — no login needed.
              </p>
              <div className="rounded-[var(--radius-md)] border border-line bg-surface-2 p-3">
                <p className="text-[11px] text-fg-3">
                  Viewers can read the PDF but cannot edit or access your LaTeX source.
                </p>
              </div>

              <div className="flex items-center justify-between rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2.5">
                <div className="flex items-center gap-2">
                  <Link size={13} className="text-fg-3" />
                  <div>
                    <p className="text-[12px] font-medium text-fg-2">Allow review comments</p>
                    <p className="text-[10px] text-fg-3">Let viewers leave pseudonymous sticky feedback</p>
                  </div>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-label="Allow review comments"
                  aria-checked={reviewComments === true}
                  onClick={toggleReviewComments}
                  className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${reviewComments ? 'bg-accent' : 'bg-surface-2'}`}
                >
                  <span className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${reviewComments ? 'translate-x-4' : 'translate-x-0'}`} />
                </button>
              </div>

              {/* Anonymous mode toggle */}
              <div className="flex items-center justify-between rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2.5">
                <div className="flex items-center gap-2">
                  <EyeOff size={13} className="text-fg-3" />
                  <div>
                    <p className="text-[12px] font-medium text-fg-2">Anonymous Mode</p>
                    <p className="text-[10px] text-fg-3">Hides name, email, phone &amp; social profiles</p>
                  </div>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-label="Share anonymously"
                  aria-checked={anonymous}
                  onClick={() => setAnonymous(a => !a)}
                  className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
                    anonymous ? 'bg-warn' : 'bg-surface-2'
                  }`}
                >
                  <span
                    className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${
                      anonymous ? 'translate-x-4' : 'translate-x-0'
                    }`}
                  />
                </button>
              </div>

              <button
                onClick={() => void handleGenerate(false)}
                disabled={isGenerating}
                className="flex w-full items-center justify-center gap-2 rounded-[var(--radius-md)] border border-accent bg-accent-soft py-2.5 text-sm font-semibold text-accent-strong transition hover:brightness-110 disabled:opacity-50"
              >
                {isGenerating ? (
                  <><Loader2 size={13} className="animate-spin" /> Generating…</>
                ) : (
                  <><Link size={13} /> Generate shareable link</>
                )}
              </button>
            </div>
          ) : tab === 'share' ? (
            // Share tab
            <div className="space-y-4">
              {shareData.anonymous && (
                <div className="flex items-center gap-1.5 rounded-[var(--radius-md)] border border-warn bg-surface-2 px-3 py-1.5">
                  <EyeOff size={11} className="text-warn" />
                  <p className="text-[11px] text-warn">Anonymous mode — PII redacted in shared view</p>
                </div>
              )}
              <div className="rounded-[var(--radius-md)] border border-line bg-surface-2 p-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-[12px] font-medium text-fg-2">Anonymous Mode</p>
                    <p className="text-[10px] text-fg-3">Hides detected identity and contact details</p>
                  </div>
                  <button
                    type="button"
                    role="switch"
                    aria-label="Share anonymously"
                    aria-checked={anonymous}
                    onClick={() => setAnonymous(value => !value)}
                    disabled={isGenerating}
                    className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors disabled:opacity-50 ${
                      anonymous ? 'bg-warn' : 'bg-surface'
                    }`}
                  >
                    <span className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${
                      anonymous ? 'translate-x-4' : 'translate-x-0'
                    }`} />
                  </button>
                </div>
                {shareData.anonymous && !anonymous && (
                  <p className="mt-2 text-[10px] text-err">
                    Turning this off exposes the original PDF at the existing link.
                  </p>
                )}
                {anonymous !== shareData.anonymous && (
                  <button
                    type="button"
                    onClick={() => void handleGenerate(false)}
                    disabled={isGenerating}
                    className="mt-3 flex w-full items-center justify-center gap-2 rounded-[var(--radius-md)] border border-accent bg-accent-soft py-2 text-xs font-semibold text-accent-strong disabled:opacity-50"
                  >
                    {isGenerating ? <Loader2 size={12} className="animate-spin" /> : <EyeOff size={12} />}
                    Update link privacy
                  </button>
                )}
                {shareData.anonymous && anonymous === shareData.anonymous && (
                  <button
                    type="button"
                    onClick={() => void handleGenerate(true)}
                    disabled={isGenerating}
                    className="mt-3 flex w-full items-center justify-center gap-2 rounded-[var(--radius-md)] border border-line-2 py-2 text-xs font-semibold text-fg-2 disabled:opacity-50"
                  >
                    {isGenerating ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                    Regenerate redacted PDF
                  </button>
                )}
              </div>
              <div className="rounded-[var(--radius-md)] border border-line bg-surface-2 p-3">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-[12px] font-medium text-fg-2">Allow review comments</p>
                    <p className="text-[10px] text-fg-3">Viewers can leave pseudonymous feedback on this link</p>
                  </div>
                  <button
                    type="button"
                    role="switch"
                    aria-label="Allow review comments"
                    aria-checked={reviewComments === true}
                    onClick={toggleReviewComments}
                    disabled={isGenerating}
                    className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors disabled:opacity-50 ${reviewComments ? 'bg-accent' : 'bg-surface'}`}
                  >
                    <span className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow transition-transform ${reviewComments ? 'translate-x-4' : 'translate-x-0'}`} />
                  </button>
                </div>
                {reviewComments !== null && reviewComments !== shareData.review_comments && (
                  <button
                    type="button"
                    onClick={() => void handleGenerate(false, reviewComments)}
                    disabled={isGenerating}
                    className="mt-3 flex w-full items-center justify-center gap-2 rounded-[var(--radius-md)] border border-accent bg-accent-soft py-2 text-xs font-semibold text-accent-strong disabled:opacity-50"
                  >
                    {isGenerating ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />}
                    Update review access
                  </button>
                )}
              </div>
              {/* URL display */}
              <div>
                <p className="mb-2 text-xs font-medium text-fg-2">Shareable link</p>
                <div className="flex items-center gap-2 rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2">
                  <span className="flex-1 truncate text-xs font-mono text-accent-strong">
                    {shareData.share_url}
                  </span>
                  <button
                    onClick={handleCopy}
                    className="shrink-0 rounded-[var(--radius-md)] p-1 text-fg-3 transition hover:bg-surface-2 hover:text-fg"
                    title="Copy link"
                  >
                    {copied ? (
                      <Check size={13} className="text-ok" />
                    ) : (
                      <Copy size={13} />
                    )}
                  </button>
                </div>
                {createdAt && (
                  <p className="mt-1.5 text-[11px] text-fg-3">Link created {createdAt}</p>
                )}
              </div>

              {/* Copy button (full-width) */}
              <button
                onClick={handleCopy}
                className="flex w-full items-center justify-center gap-2 rounded-[var(--radius-md)] border border-line-2 bg-surface-2 py-2 text-xs font-semibold text-fg-2 transition hover:bg-surface-2"
              >
                {copied ? (
                  <><Check size={12} className="text-ok" /> Copied!</>
                ) : (
                  <><Copy size={12} /> Copy link</>
                )}
              </button>

              {/* Info */}
              <div className="rounded-[var(--radius-md)] border border-line bg-surface-2 p-3">
                <p className="text-[11px] text-fg-3">
                  Anyone with this link can view the PDF. They cannot edit the resume.
                </p>
              </div>

              {/* Revoke section */}
              <div className="border-t border-line pt-4">
                {!showRevokeConfirm ? (
                  <button
                    onClick={() => setShowRevokeConfirm(true)}
                    className="flex items-center gap-1.5 text-[11px] text-fg-3 transition hover:text-err"
                  >
                    <Trash2 size={11} />
                    Revoke link
                  </button>
                ) : (
                  <div className="space-y-2">
                    <p className="text-[11px] text-fg-2">
                      Revoking this link will immediately break all shared URLs. Are you sure?
                    </p>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setShowRevokeConfirm(false)}
                        className="flex-1 rounded-[var(--radius-md)] border border-line-2 py-1.5 text-[11px] text-fg-3 transition hover:text-fg-2"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={handleRevoke}
                        disabled={isRevoking}
                        className="flex flex-1 items-center justify-center gap-1.5 rounded-[var(--radius-md)] border border-err bg-surface-2 py-1.5 text-[11px] font-semibold text-err transition hover:brightness-110 disabled:opacity-50"
                      >
                        {isRevoking ? (
                          <><Loader2 size={10} className="animate-spin" /> Revoking…</>
                        ) : (
                          'Revoke permanently'
                        )}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            </div>
          ) : (
            // Analytics tab
            <AnalyticsPanel resumeId={resumeId} />
          )}
        </div>
      </div>
    </div>
  )
}
