'use client'

import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

/**
 * A small themed, accessible confirmation dialog — a drop-in replacement for
 * `window.confirm` that matches the app's visual language. Controlled via
 * `open`; resolves through `onConfirm` / `onCancel`.
 */
export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  destructive = false,
  onConfirm,
  onCancel,
}: {
  open: boolean
  title: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  destructive?: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  const confirmRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    confirmRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onCancel])

  if (!open || typeof document === 'undefined') return null

  return createPortal(
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/50 p-4"
      onMouseDown={onCancel}
    >
      <div
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-message"
        className="w-full max-w-sm rounded-[var(--radius-lg)] border border-line bg-surface p-5 shadow-xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2 id="confirm-dialog-title" className="text-sm font-semibold text-fg">{title}</h2>
        <p id="confirm-dialog-message" className="mt-2 text-sm leading-relaxed text-fg-2">{message}</p>
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-[var(--radius-md)] border border-line-2 px-3 py-1.5 text-xs font-medium text-fg-2 transition hover:bg-surface-2"
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            onClick={onConfirm}
            className={`rounded-[var(--radius-md)] px-3 py-1.5 text-xs font-semibold text-accent-fg transition hover:brightness-110 ${destructive ? 'bg-err' : 'bg-accent'}`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
