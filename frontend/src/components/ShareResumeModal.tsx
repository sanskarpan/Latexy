'use client'

import { useEffect, useState } from 'react'
import { Check, Copy, EyeOff, Link, Loader2, BarChart2, Trash2, X } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type ShareLinkResponse, type ResumeAnalytics } from '@/lib/api-client'

interface ShareResumeModalProps {
  resumeId: string
  resumeTitle: string
  /** Existing share token from the resume response (null if not yet shared) */
  initialShareToken?: string | null
  initialShareUrl?: string | null
  onClose: () => void
  onShareTokenChange?: (token: string | null, url: string | null) => void
}

type Tab = 'share' | 'analytics'

// ── Tiny SVG sparkline ──────────────────────────────────────────────────────

function Sparkline({ data }: { data: { date: string; count: number }[] }) {
  const W = 220
  const H = 36
  if (data.length === 0) {
    return <div className="h-9 flex items-center justify-center text-[10px] text-zinc-600">No data yet</div>
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
      <polygon points={fill} fill="rgba(56,189,248,0.12)" />
      <polyline points={polyline} fill="none" stroke="rgb(56,189,248)" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
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

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    apiClient
      .getResumeAnalytics(resumeId)
      .then((data) => { if (!cancelled) { setAnalytics(data); setLoading(false) } })
      .catch((err) => { if (!cancelled) { setError(err.message || 'Failed to load analytics'); setLoading(false) } })
    return () => { cancelled = true }
  }, [resumeId])

  if (loading) {
    return (
      <div className="flex h-48 items-center justify-center">
        <Loader2 size={16} className="animate-spin text-zinc-600" />
      </div>
    )
  }
  if (error) {
    return <p className="py-4 text-center text-[11px] text-rose-400">{error}</p>
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
          <div key={label} className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-2 py-2 text-center">
            <p className="text-base font-semibold text-sky-300">{value}</p>
            <p className="text-[9px] uppercase tracking-wider text-zinc-600">{label}</p>
          </div>
        ))}
      </div>

      {/* Sparkline */}
      <div>
        <p className="mb-1 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Last 30 days</p>
        <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2">
          <Sparkline data={analytics.views_by_day} />
        </div>
      </div>

      {/* Countries */}
      {analytics.views_by_country.length > 0 && (
        <div>
          <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Top countries</p>
          <div className="space-y-1">
            {analytics.views_by_country.slice(0, 5).map((c, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="text-sm leading-none">{countryFlag(c.country_code)}</span>
                <span className="flex-1 text-[11px] text-zinc-400">{c.country_code ?? 'Unknown'}</span>
                <span className="text-[11px] font-semibold text-zinc-300">{c.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Referrers */}
      {analytics.views_by_referrer.length > 0 && (
        <div>
          <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">Top referrers</p>
          <div className="space-y-1">
            {analytics.views_by_referrer.slice(0, 5).map((r, i) => (
              <div key={i} className="flex items-center gap-2">
                <span className="flex-1 truncate text-[11px] text-zinc-400">{displayReferrer(r.referrer)}</span>
                <span className="text-[11px] font-semibold text-zinc-300">{r.count}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {analytics.total_views === 0 && (
        <p className="text-center text-[11px] text-zinc-600">No views recorded yet. Share your link to start tracking.</p>
      )}

      {lastViewed && (
        <p className="text-[10px] text-zinc-600">Last viewed {lastViewed}</p>
      )}
    </div>
  )
}

// ── Main modal ───────────────────────────────────────────────────────────────

export default function ShareResumeModal({
  resumeId,
  resumeTitle,
  initialShareToken,
  initialShareUrl,
  onClose,
  onShareTokenChange,
}: ShareResumeModalProps) {
  const [shareData, setShareData] = useState<ShareLinkResponse | null>(
    initialShareToken && initialShareUrl
      ? { share_token: initialShareToken, share_url: initialShareUrl, created_at: '', anonymous: false }
      : null
  )
  const [isGenerating, setIsGenerating] = useState(false)
  const [isRevoking, setIsRevoking] = useState(false)
  const [copied, setCopied] = useState(false)
  const [showRevokeConfirm, setShowRevokeConfirm] = useState(false)
  const [anonymous, setAnonymous] = useState(false)
  const [tab, setTab] = useState<Tab>('share')

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  const handleGenerate = async () => {
    setIsGenerating(true)
    try {
      const data = await apiClient.createShareLink(resumeId, anonymous)
      setShareData(data)
      onShareTokenChange?.(data.share_token, data.share_url)
      toast.success(data.anonymous ? 'Anonymous share link created' : 'Share link created')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to create share link')
    } finally {
      setIsGenerating(false)
    }
  }

  const handleCopy = async () => {
    if (!shareData?.share_url) return
    try {
      await navigator.clipboard.writeText(shareData.share_url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      toast.error('Failed to copy link')
    }
  }

  const handleRevoke = async () => {
    setIsRevoking(true)
    try {
      await apiClient.revokeShareLink(resumeId)
      setShareData(null)
      setShowRevokeConfirm(false)
      setTab('share')
      onShareTokenChange?.(null, null)
      toast.success('Share link revoked')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to revoke link')
    } finally {
      setIsRevoking(false)
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-md rounded-xl border border-white/[0.08] bg-[#111] shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/[0.06] px-5 py-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-sky-500/15 ring-1 ring-sky-400/20">
              <Link size={13} className="text-sky-300" />
            </div>
            <div>
              <h2 className="text-sm font-semibold text-white">Share Resume</h2>
              <p className="text-[11px] text-zinc-500">{resumeTitle}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-zinc-600 transition hover:bg-white/[0.05] hover:text-zinc-300"
          >
            <X size={14} />
          </button>
        </div>

        {/* Tab bar — only when link exists */}
        {shareData && (
          <div className="flex border-b border-white/[0.06] px-5">
            {tabs.map(({ id, label, icon }) => (
              <button
                key={id}
                onClick={() => setTab(id)}
                className={`flex items-center gap-1.5 border-b-2 px-3 py-2.5 text-[11px] font-medium transition ${
                  tab === id
                    ? 'border-sky-400 text-sky-300'
                    : 'border-transparent text-zinc-500 hover:text-zinc-300'
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
              <p className="text-sm text-zinc-400">
                Generate a public link so anyone can view the compiled PDF — no login needed.
              </p>
              <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3">
                <p className="text-[11px] text-zinc-500">
                  Viewers can read the PDF but cannot edit or access your LaTeX source.
                </p>
              </div>

              {/* Anonymous mode toggle */}
              <div className="flex items-center justify-between rounded-lg border border-white/[0.06] bg-white/[0.02] px-3 py-2.5">
                <div className="flex items-center gap-2">
                  <EyeOff size={13} className="text-zinc-500" />
                  <div>
                    <p className="text-[12px] font-medium text-zinc-300">Anonymous Mode</p>
                    <p className="text-[10px] text-zinc-600">Hides name, email, phone &amp; social profiles</p>
                  </div>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={anonymous}
                  onClick={() => setAnonymous(a => !a)}
                  className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
                    anonymous ? 'bg-amber-500' : 'bg-zinc-700'
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
                onClick={handleGenerate}
                disabled={isGenerating}
                className="flex w-full items-center justify-center gap-2 rounded-lg border border-sky-400/25 bg-sky-500/15 py-2.5 text-sm font-semibold text-sky-200 transition hover:bg-sky-500/25 disabled:opacity-50"
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
                <div className="flex items-center gap-1.5 rounded-md border border-amber-400/20 bg-amber-500/10 px-3 py-1.5">
                  <EyeOff size={11} className="text-amber-400" />
                  <p className="text-[11px] text-amber-300">Anonymous mode — PII redacted in shared view</p>
                </div>
              )}
              {/* URL display */}
              <div>
                <p className="mb-2 text-xs font-medium text-zinc-400">Shareable link</p>
                <div className="flex items-center gap-2 rounded-lg border border-white/[0.08] bg-black/40 px-3 py-2">
                  <span className="flex-1 truncate text-xs font-mono text-sky-300">
                    {shareData.share_url}
                  </span>
                  <button
                    onClick={handleCopy}
                    className="shrink-0 rounded-md p-1 text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-200"
                    title="Copy link"
                  >
                    {copied ? (
                      <Check size={13} className="text-emerald-400" />
                    ) : (
                      <Copy size={13} />
                    )}
                  </button>
                </div>
                {createdAt && (
                  <p className="mt-1.5 text-[11px] text-zinc-600">Link created {createdAt}</p>
                )}
              </div>

              {/* Copy button (full-width) */}
              <button
                onClick={handleCopy}
                className="flex w-full items-center justify-center gap-2 rounded-lg border border-white/[0.08] bg-white/[0.04] py-2 text-xs font-semibold text-zinc-300 transition hover:bg-white/[0.08]"
              >
                {copied ? (
                  <><Check size={12} className="text-emerald-400" /> Copied!</>
                ) : (
                  <><Copy size={12} /> Copy link</>
                )}
              </button>

              {/* Info */}
              <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3">
                <p className="text-[11px] text-zinc-500">
                  Anyone with this link can view the PDF. They cannot edit the resume.
                </p>
              </div>

              {/* Revoke section */}
              <div className="border-t border-white/[0.06] pt-4">
                {!showRevokeConfirm ? (
                  <button
                    onClick={() => setShowRevokeConfirm(true)}
                    className="flex items-center gap-1.5 text-[11px] text-zinc-600 transition hover:text-rose-400"
                  >
                    <Trash2 size={11} />
                    Revoke link
                  </button>
                ) : (
                  <div className="space-y-2">
                    <p className="text-[11px] text-zinc-400">
                      Revoking this link will immediately break all shared URLs. Are you sure?
                    </p>
                    <div className="flex gap-2">
                      <button
                        onClick={() => setShowRevokeConfirm(false)}
                        className="flex-1 rounded-md border border-white/[0.08] py-1.5 text-[11px] text-zinc-500 transition hover:text-zinc-300"
                      >
                        Cancel
                      </button>
                      <button
                        onClick={handleRevoke}
                        disabled={isRevoking}
                        className="flex flex-1 items-center justify-center gap-1.5 rounded-md border border-rose-400/20 bg-rose-500/10 py-1.5 text-[11px] font-semibold text-rose-300 transition hover:bg-rose-500/20 disabled:opacity-50"
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
