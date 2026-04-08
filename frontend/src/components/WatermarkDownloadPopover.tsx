'use client'

import { useRef, useState } from 'react'
import { Loader2, Stamp } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api-client'

interface WatermarkDownloadPopoverProps {
  getLatex: () => string
  filename?: string
  userPlan?: string
  deviceFingerprint?: string
}

const PRESETS = ['DRAFT', 'CONFIDENTIAL', 'FOR REVIEW ONLY'] as const
const WATERMARK_RE = /^[A-Za-z0-9 \-\.]+$/
const MAX_LEN = 30

export default function WatermarkDownloadPopover({
  getLatex,
  filename = 'resume',
  userPlan = 'free',
  deviceFingerprint,
}: WatermarkDownloadPopoverProps) {
  const [open, setOpen] = useState(false)
  const [custom, setCustom] = useState('')
  const [loading, setLoading] = useState(false)
  const popoverRef = useRef<HTMLDivElement>(null)

  const triggerDownload = async (watermarkText: string) => {
    const latex = getLatex()
    if (!latex.trim()) {
      toast.error('Editor is empty — compile first')
      return
    }
    setLoading(true)
    try {
      const { job_id } = await apiClient.compileWatermarked({
        latex_content: latex,
        watermark: watermarkText,
        user_plan: userPlan,
        device_fingerprint: deviceFingerprint,
      })
      toast.info('Compiling watermarked PDF…')
      const { success } = await apiClient.pollJobUntilComplete(job_id)
      if (!success) {
        toast.error('Watermarked compile failed')
        return
      }
      const blob = await apiClient.downloadPdf(job_id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${filename.replace(/\s+/g, '_')}_${watermarkText.replace(/\s+/g, '_')}.pdf`
      a.click()
      URL.revokeObjectURL(url)
      toast.success('Watermarked PDF downloaded')
      setOpen(false)
      setCustom('')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Download failed')
    } finally {
      setLoading(false)
    }
  }

  const handleCustomDownload = () => {
    const text = custom.trim()
    if (!text) { toast.error('Enter watermark text'); return }
    if (!WATERMARK_RE.test(text)) {
      toast.error('Only letters, digits, spaces, hyphens, and dots allowed')
      return
    }
    if (text.length > MAX_LEN) {
      toast.error(`Max ${MAX_LEN} characters`)
      return
    }
    triggerDownload(text)
  }

  return (
    <div className="relative" ref={popoverRef}>
      <button
        onClick={() => setOpen((o) => !o)}
        disabled={loading}
        title="Download with Watermark"
        className="flex items-center gap-1 px-2 py-1 text-[10px] text-zinc-600 transition hover:text-zinc-300 disabled:opacity-50"
      >
        {loading ? <Loader2 size={11} className="animate-spin" /> : <Stamp size={11} />}
        Watermark
      </button>

      {open && !loading && (
        <>
          {/* Backdrop */}
          <div
            className="fixed inset-0 z-40"
            onClick={() => setOpen(false)}
          />
          {/* Popover */}
          <div className="absolute right-0 z-50 mt-1 w-56 rounded-xl border border-white/[0.08] bg-[#0d0d0d] p-3 shadow-2xl">
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-zinc-500">
              Watermark text
            </p>

            {/* Presets */}
            <div className="mb-2 flex flex-col gap-1">
              {PRESETS.map((preset) => (
                <button
                  key={preset}
                  onClick={() => triggerDownload(preset)}
                  className="rounded-md px-2.5 py-1.5 text-left text-[11px] font-medium text-zinc-300 transition hover:bg-white/[0.06]"
                >
                  {preset}
                </button>
              ))}
            </div>

            {/* Divider */}
            <div className="my-2 border-t border-white/[0.06]" />

            {/* Custom input */}
            <div className="flex gap-1.5">
              <input
                type="text"
                value={custom}
                maxLength={MAX_LEN}
                onChange={(e) => setCustom(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') handleCustomDownload() }}
                placeholder="Custom…"
                className="min-w-0 flex-1 rounded-md border border-white/[0.08] bg-white/[0.03] px-2 py-1 text-[11px] text-zinc-200 placeholder-zinc-600 outline-none focus:border-white/[0.15]"
              />
              <button
                onClick={handleCustomDownload}
                disabled={!custom.trim()}
                className="rounded-md bg-white/[0.06] px-2 py-1 text-[10px] font-semibold text-zinc-300 transition hover:bg-white/[0.10] disabled:opacity-40"
              >
                ↓
              </button>
            </div>
            <p className="mt-1.5 text-[9px] text-zinc-600">
              Letters, digits, spaces, hyphens, dots · max {MAX_LEN} chars
            </p>
          </div>
        </>
      )}
    </div>
  )
}
