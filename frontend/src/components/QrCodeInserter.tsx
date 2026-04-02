'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { QrCode, X } from 'lucide-react'
import QRCode from 'qrcode'
import { addPackageToPreamble } from '@/lib/latex-preamble'

type QrSize = 'small' | 'medium' | 'large'

const SIZE_LABELS: Record<QrSize, string> = {
  small: 'Small (1 cm)',
  medium: 'Medium (1.5 cm)',
  large: 'Large (2 cm)',
}

const SIZE_CM: Record<QrSize, string> = {
  small: '1cm',
  medium: '1.5cm',
  large: '2cm',
}

interface QrCodeInserterProps {
  isOpen: boolean
  onClose: () => void
  /** Called with the LaTeX snippet to insert at the cursor position */
  onInsert: (latex: string) => void
  /** Full current editor content — needed to check/add \usepackage{qrcode} */
  getLatex: () => string
  /** Called with the updated full latex if the preamble was modified */
  onLatexChange: (newLatex: string) => void
}

function isValidUrl(url: string): boolean {
  try {
    const u = new URL(url)
    return u.protocol === 'https:' || u.protocol === 'http:'
  } catch {
    return false
  }
}

export default function QrCodeInserter({
  isOpen,
  onClose,
  onInsert,
  getLatex,
  onLatexChange,
}: QrCodeInserterProps) {
  const [url, setUrl] = useState('')
  const [size, setSize] = useState<QrSize>('medium')
  const canvasRef = useRef<HTMLCanvasElement>(null)

  // Render QR preview whenever URL changes
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    if (!url || !isValidUrl(url)) {
      const ctx = canvas.getContext('2d')
      if (ctx) {
        ctx.clearRect(0, 0, canvas.width, canvas.height)
      }
      return
    }
    QRCode.toCanvas(canvas, url, {
      width: 120,
      margin: 1,
      color: { dark: '#ffffff', light: '#00000000' },
    }).catch(() => {/* ignore render errors */})
  }, [url])

  // Reset state when opening
  useEffect(() => {
    if (isOpen) {
      setUrl('')
      setSize('medium')
    }
  }, [isOpen])

  // Close on Escape
  useEffect(() => {
    if (!isOpen) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [isOpen, onClose])

  const handleInsert = useCallback(() => {
    if (!isValidUrl(url)) return

    // Insert at cursor FIRST (preserves cursor position before any setValue resets it)
    const heightParam = SIZE_CM[size]
    onInsert(`\\qrcode[height=${heightParam}]{\\detokenize{${url}}}`)

    // THEN update the preamble (setValue resets cursor, but insert already happened)
    const currentLatex = getLatex()
    const withPackage = addPackageToPreamble(currentLatex, 'qrcode')
    if (withPackage !== currentLatex) {
      onLatexChange(withPackage)
    }

    onClose()
  }, [url, size, getLatex, onLatexChange, onInsert, onClose])

  if (!isOpen) return null

  const valid = isValidUrl(url)

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-sm rounded-xl border border-white/[0.08] bg-[#0d0d0d] shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/[0.06] px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-lg bg-orange-500/15">
              <QrCode size={13} className="text-orange-300" />
            </div>
            <h2 className="text-sm font-semibold text-zinc-100">Insert QR Code</h2>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1.5 text-zinc-600 transition hover:bg-white/[0.06] hover:text-zinc-300"
          >
            <X size={14} />
          </button>
        </div>

        <div className="space-y-4 p-4">
          {/* URL input */}
          <div>
            <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500">
              URL
            </label>
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://linkedin.com/in/yourname"
              autoFocus
              className={`w-full rounded-lg border bg-white/[0.03] px-3 py-2 text-sm text-zinc-100 outline-none placeholder:text-zinc-700 transition ${
                url && !valid
                  ? 'border-rose-400/40 focus:border-rose-400/60'
                  : 'border-white/[0.06] focus:border-orange-400/30'
              }`}
            />
            {url && !valid && (
              <p className="mt-1 text-[10px] text-rose-400">Enter a valid https:// URL</p>
            )}
          </div>

          {/* Size selector */}
          <div>
            <label className="mb-1.5 block text-[11px] font-semibold uppercase tracking-[0.12em] text-zinc-500">
              Size
            </label>
            <div className="flex gap-2">
              {(Object.keys(SIZE_LABELS) as QrSize[]).map((s) => (
                <button
                  key={s}
                  onClick={() => setSize(s)}
                  className={`flex-1 rounded-lg border py-1.5 text-[11px] font-medium transition ${
                    size === s
                      ? 'border-orange-400/30 bg-orange-500/10 text-orange-200'
                      : 'border-white/[0.06] text-zinc-500 hover:border-white/[0.10] hover:text-zinc-300'
                  }`}
                >
                  {s.charAt(0).toUpperCase() + s.slice(1)}
                </button>
              ))}
            </div>
            <p className="mt-1 text-[10px] text-zinc-700">{SIZE_LABELS[size]}</p>
          </div>

          {/* Preview */}
          <div className="flex items-center justify-center rounded-lg border border-white/[0.06] bg-black/30 p-4 min-h-[140px]">
            {valid ? (
              <canvas ref={canvasRef} width={120} height={120} />
            ) : (
              <div className="flex flex-col items-center gap-2 text-center">
                <canvas ref={canvasRef} width={120} height={120} className="hidden" />
                <QrCode size={32} className="text-zinc-800" />
                <p className="text-[11px] text-zinc-700">Enter a URL to preview</p>
              </div>
            )}
          </div>

          {/* LaTeX preview */}
          {valid && (
            <div className="rounded-lg border border-white/[0.06] bg-black/20 px-3 py-2">
              <p className="font-mono text-[11px] text-zinc-500">
                {`\\qrcode[height=${SIZE_CM[size]}]{\\detokenize{${url.length > 35 ? url.slice(0, 35) + '…' : url}}}`}
              </p>
            </div>
          )}

          {/* Actions */}
          <div className="flex gap-2 pt-1">
            <button
              onClick={onClose}
              className="flex-1 rounded-lg border border-white/[0.06] py-2 text-xs font-semibold text-zinc-500 transition hover:text-zinc-300"
            >
              Cancel
            </button>
            <button
              onClick={handleInsert}
              disabled={!valid}
              className="flex-1 rounded-lg bg-orange-500/20 py-2 text-xs font-semibold text-orange-200 ring-1 ring-orange-400/20 transition hover:bg-orange-500/30 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Insert
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
