'use client'

import { useEffect, useState } from 'react'
import { Check, Copy, Link, Loader2, Trash2, X } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type ShareLinkResponse } from '@/lib/api-client'

interface ShareResumeModalProps {
  resumeId: string
  resumeTitle: string
  /** Existing share token from the resume response (null if not yet shared) */
  initialShareToken?: string | null
  initialShareUrl?: string | null
  onClose: () => void
  onShareTokenChange?: (token: string | null, url: string | null) => void
}

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
      ? { share_token: initialShareToken, share_url: initialShareUrl, created_at: '' }
      : null
  )
  const [isGenerating, setIsGenerating] = useState(false)
  const [isRevoking, setIsRevoking] = useState(false)
  const [copied, setCopied] = useState(false)
  const [showRevokeConfirm, setShowRevokeConfirm] = useState(false)

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
      const data = await apiClient.createShareLink(resumeId)
      setShareData(data)
      onShareTokenChange?.(data.share_token, data.share_url)
      toast.success('Share link created')
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

        {/* Body */}
        <div className="px-5 py-5">
          {!shareData ? (
            // No link yet
            <div className="space-y-4">
              <p className="text-sm text-zinc-400">
                Generate a public link so anyone can view the compiled PDF — no login needed.
              </p>
              <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3">
                <p className="text-[11px] text-zinc-500">
                  Viewers can read the PDF but cannot edit or access your LaTeX source.
                </p>
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
          ) : (
            // Link exists
            <div className="space-y-4">
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
          )}
        </div>
      </div>
    </div>
  )
}
