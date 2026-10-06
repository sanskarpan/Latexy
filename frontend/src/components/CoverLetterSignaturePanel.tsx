'use client'

import { useEffect, useRef, useState } from 'react'
import { Eraser, PenLine, Type, Upload } from 'lucide-react'
import { toast } from 'sonner'
import {
  applyCoverLetterSignature,
  hasCoverLetterSignature,
  removeCoverLetterSignature,
} from '@/lib/cover-letter-signature'

type Mode = 'typed' | 'draw' | 'upload'

interface Props {
  latex: string
  disabled?: boolean
  /** False means the owner changed or persistence was rejected; do not toast success. */
  onApply: (latex: string) => Promise<boolean>
}

const MAX_UPLOAD_BYTES = 2_000_000

export default function CoverLetterSignaturePanel({ latex, disabled = false, onApply }: Props) {
  const [mode, setMode] = useState<Mode>('typed')
  const [name, setName] = useState('')
  const [uploadedImage, setUploadedImage] = useState<string | null>(null)
  const [hasDrawing, setHasDrawing] = useState(false)
  const [isApplying, setIsApplying] = useState(false)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const drawingRef = useRef(false)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const context = canvas.getContext('2d')
    if (!context) return
    context.lineCap = 'round'
    context.lineJoin = 'round'
    context.lineWidth = 3
    context.strokeStyle = '#111827'
  }, [mode])

  const point = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = event.currentTarget
    const bounds = canvas.getBoundingClientRect()
    return {
      x: (event.clientX - bounds.left) * (canvas.width / bounds.width),
      y: (event.clientY - bounds.top) * (canvas.height / bounds.height),
    }
  }

  const beginDrawing = (event: React.PointerEvent<HTMLCanvasElement>) => {
    drawingRef.current = true
    event.currentTarget.setPointerCapture(event.pointerId)
    const context = event.currentTarget.getContext('2d')
    const { x, y } = point(event)
    context?.beginPath()
    context?.moveTo(x, y)
  }

  const draw = (event: React.PointerEvent<HTMLCanvasElement>) => {
    if (!drawingRef.current) return
    const context = event.currentTarget.getContext('2d')
    const { x, y } = point(event)
    context?.lineTo(x, y)
    context?.stroke()
    setHasDrawing(true)
  }

  const clearDrawing = () => {
    const canvas = canvasRef.current
    canvas?.getContext('2d')?.clearRect(0, 0, canvas.width, canvas.height)
    setHasDrawing(false)
  }

  const normalizeUpload = async (file: File) => {
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
      throw new Error('Use a PNG, JPEG, or WebP image.')
    }
    if (file.size > MAX_UPLOAD_BYTES) throw new Error('Signature images must be 2 MB or smaller.')
    const bitmap = await createImageBitmap(file)
    if (bitmap.width * bitmap.height > 4_000_000) {
      bitmap.close()
      throw new Error('Signature image dimensions are too large.')
    }
    const scale = Math.min(1, 1200 / bitmap.width, 400 / bitmap.height)
    const canvas = document.createElement('canvas')
    canvas.width = Math.max(2, Math.round(bitmap.width * scale))
    canvas.height = Math.max(2, Math.round(bitmap.height * scale))
    canvas.getContext('2d')?.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
    bitmap.close()
    const dataUrl = canvas.toDataURL('image/png')
    if (dataUrl.length > 700_000) throw new Error('The normalized signature image is too large.')
    setUploadedImage(dataUrl)
  }

  const apply = async () => {
    try {
      let next: string
      if (mode === 'typed') {
        next = applyCoverLetterSignature(latex, { mode: 'typed', name })
      } else {
        if (mode === 'draw' && !hasDrawing) throw new Error('Draw your signature first.')
        const dataUrl = mode === 'draw' ? canvasRef.current?.toDataURL('image/png') : uploadedImage
        if (!dataUrl) throw new Error(mode === 'draw' ? 'Draw your signature first.' : 'Choose a signature image first.')
        next = applyCoverLetterSignature(latex, { mode: 'image', name, dataUrl })
      }
      setIsApplying(true)
      if (await onApply(next)) toast.success('Signature saved and added to the cover letter')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not add signature')
    } finally {
      setIsApplying(false)
    }
  }

  const remove = async () => {
    setIsApplying(true)
    try {
      if (await onApply(removeCoverLetterSignature(latex))) toast.success('Signature removed from the cover letter')
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not remove signature')
    } finally {
      setIsApplying(false)
    }
  }

  return (
    <section className="rounded-[var(--radius-lg)] border border-line bg-surface p-5">
      <h2 className="text-xs font-semibold uppercase tracking-[0.14em] text-fg-2">Signature</h2>
      <p className="mt-1 text-[11px] text-fg-3">Type, draw, or upload a signature. Review local conventions before using one.</p>
      <div role="tablist" aria-label="Signature method" className="mt-3 grid grid-cols-3 gap-1 rounded-[var(--radius-md)] bg-bg p-1">
        {([
          ['typed', Type, 'Type'], ['draw', PenLine, 'Draw'], ['upload', Upload, 'Upload'],
        ] as const).map(([value, Icon, label]) => (
          <button key={value} type="button" role="tab" aria-selected={mode === value} onClick={() => setMode(value)} disabled={disabled}
            className={`flex items-center justify-center gap-1 rounded px-2 py-1.5 text-[11px] ${mode === value ? 'bg-surface-2 text-fg' : 'text-fg-3'}`}>
            <Icon size={12} />{label}
          </button>
        ))}
      </div>
      <label className="mt-3 block text-[11px] text-fg-2" htmlFor="signature-name">Printed name {mode === 'typed' ? '' : '(optional)'}</label>
      <input id="signature-name" value={name} onChange={(event) => setName(event.target.value)} disabled={disabled}
        className="mt-1 w-full rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent" />
      {mode === 'draw' && (
        <div className="mt-3">
          <canvas ref={canvasRef} width={640} height={180} aria-label="Draw signature" onPointerDown={beginDrawing} onPointerMove={draw}
            onPointerUp={() => { drawingRef.current = false }} onPointerCancel={() => { drawingRef.current = false }}
            className="h-24 w-full touch-none rounded-[var(--radius-md)] border border-line bg-white" />
          <button type="button" onClick={clearDrawing} className="mt-1 flex items-center gap-1 text-[11px] text-fg-3 hover:text-fg"><Eraser size={11} />Clear drawing</button>
        </div>
      )}
      {mode === 'upload' && (
        <div className="mt-3">
          <label htmlFor="signature-upload" className="block cursor-pointer rounded-[var(--radius-md)] border border-dashed border-line-2 px-3 py-3 text-center text-xs text-fg-2 hover:bg-surface-2">Choose PNG, JPEG, or WebP</label>
          <input id="signature-upload" type="file" accept="image/png,image/jpeg,image/webp" className="sr-only" disabled={disabled}
            onChange={(event) => { const file = event.target.files?.[0]; if (file) void normalizeUpload(file).catch((error: Error) => toast.error(error.message)) }} />
          {uploadedImage && <p className="mt-1 text-[11px] text-ok">Image ready</p>}
        </div>
      )}
      <div className="mt-4 flex gap-2">
        <button type="button" onClick={() => void apply()} disabled={disabled || isApplying}
          className="flex-1 rounded-[var(--radius-md)] bg-accent px-3 py-2 text-xs font-semibold text-accent-fg disabled:opacity-50">
          {isApplying ? 'Saving…' : 'Add signature'}
        </button>
        {hasCoverLetterSignature(latex) && (
          <button type="button" onClick={() => void remove()} disabled={disabled || isApplying}
            className="rounded-[var(--radius-md)] border border-line px-3 py-2 text-xs text-fg-2">Remove</button>
        )}
      </div>
    </section>
  )
}
