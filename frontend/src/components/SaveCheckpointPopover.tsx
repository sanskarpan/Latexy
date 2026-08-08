'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { Bookmark } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient } from '@/lib/api-client'

interface SaveCheckpointPopoverProps {
  resumeId: string
  onSaved?: () => void
}

export default function SaveCheckpointPopover({
  resumeId,
  onSaved,
}: SaveCheckpointPopoverProps) {
  const [open, setOpen] = useState(false)
  const [label, setLabel] = useState('')
  const [saving, setSaving] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (open) {
      setLabel('')
      const timer = setTimeout(() => inputRef.current?.focus(), 50)
      return () => clearTimeout(timer)
    }
  }, [open])

  // Close on Escape
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open])

  // Close on click outside
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const handleSave = useCallback(async () => {
    const trimmed = label.trim()
    if (!trimmed) return
    setSaving(true)
    try {
      await apiClient.createCheckpoint(resumeId, trimmed)
      toast.success('Checkpoint saved')
      setOpen(false)
      onSaved?.()
    } catch {
      toast.error('Failed to save checkpoint')
    } finally {
      setSaving(false)
    }
  }, [resumeId, label, onSaved])

  return (
    <div className="relative" ref={containerRef}>
      <button
        onClick={() => setOpen(!open)}
        className="flex items-center gap-1.5 rounded-[var(--radius-md)] border border-line px-3 py-1.5 text-xs text-fg-2 transition hover:border-line-2 hover:text-fg"
        title="Save checkpoint"
      >
        <Bookmark size={13} />
        <span className="hidden sm:inline">Save Checkpoint</span>
      </button>

      {open && (
        <div className="absolute right-0 top-full z-50 mt-1.5 w-64 rounded-[var(--radius-lg)] border border-line bg-surface p-3 shadow-[var(--shadow-2)]">
          <p className="mb-2 text-[11px] font-medium text-fg-2">
            Name this checkpoint
          </p>
          <input
            ref={inputRef}
            type="text"
            value={label}
            onChange={(e) => setLabel(e.target.value.slice(0, 100))}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleSave()
            }}
            placeholder="e.g. Before rewrite"
            className="mb-2 w-full rounded-[var(--radius-md)] border border-line bg-bg px-2.5 py-1.5 text-xs text-fg outline-none transition placeholder:text-fg-3 focus:border-accent"
          />
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-fg-3">
              {label.length}/100
            </span>
            <div className="flex gap-1.5">
              <button
                onClick={() => setOpen(false)}
                className="rounded-[var(--radius-md)] px-2.5 py-1 text-[11px] text-fg-3 transition hover:text-fg-2"
              >
                Cancel
              </button>
              <button
                onClick={handleSave}
                disabled={!label.trim() || saving}
                className="rounded-[var(--radius-md)] bg-accent-soft px-2.5 py-1 text-[11px] font-medium text-accent-strong border border-accent transition hover:brightness-110 disabled:opacity-40"
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
