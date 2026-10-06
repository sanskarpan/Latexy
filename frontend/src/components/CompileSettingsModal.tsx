'use client'

import { useEffect, useRef, useState } from 'react'
import { X, RotateCcw, Save, Loader2, Settings2 } from 'lucide-react'
import { toast } from 'sonner'
import {
  apiClient,
  type CompileSettings,
  type LatexCompiler,
  type LatexmkFlag,
  ALLOWED_LATEXMK_FLAGS,
} from '@/lib/api-client'

// ── Constants ────────────────────────────────────────────────────────────────

const COMPILER_OPTIONS: { id: LatexCompiler; label: string; desc: string }[] = [
  { id: 'pdflatex', label: 'pdfLaTeX', desc: 'Fastest, widest compatibility' },
  { id: 'xelatex', label: 'XeLaTeX', desc: 'Unicode + custom fonts' },
  { id: 'lualatex', label: 'LuaLaTeX', desc: 'Modern engine with Lua scripting' },
]

const FLAG_LABELS: Record<LatexmkFlag, string> = {
  '--synctex=1': 'SyncTeX (editor source sync)',
  '--file-line-error': 'File-line error format',
  '--interaction=nonstopmode': 'Non-stop mode (default)',
  '--halt-on-error': 'Halt on first error (default)',
}

const DEFAULT_SETTINGS: Required<CompileSettings> = {
  compiler: 'pdflatex',
  texlive_version: null,
  main_file: 'resume.tex',
  latexmk_flags: [],
  extra_packages: [],
  halt_on_error: true,
  draft_mode: false,
}

// ── Props ────────────────────────────────────────────────────────────────────

interface CompileSettingsModalProps {
  open: boolean
  resumeId: string
  initial: CompileSettings
  onClose: () => void
  onSaved: (settings: CompileSettings) => void
}

// ── Component ────────────────────────────────────────────────────────────────

export default function CompileSettingsModal({
  open,
  resumeId,
  initial,
  onClose,
  onSaved,
}: CompileSettingsModalProps) {
  const [compiler, setCompiler] = useState<LatexCompiler>(initial.compiler ?? 'pdflatex')
  const [mainFile, setMainFile] = useState(initial.main_file ?? 'resume.tex')
  const [packagesInput, setPackagesInput] = useState((initial.extra_packages ?? []).join(', '))
  const [flags, setFlags] = useState<Set<LatexmkFlag>>(new Set(initial.latexmk_flags ?? []))
  const [haltOnError, setHaltOnError] = useState(initial.halt_on_error !== false)
  const [draftMode, setDraftMode] = useState(initial.draft_mode === true)
  const [saving, setSaving] = useState(false)
  const backdropRef = useRef<HTMLDivElement>(null)

  // Re-sync when initial changes (e.g. first load)
  useEffect(() => {
    setCompiler(initial.compiler ?? 'pdflatex')
    setMainFile(initial.main_file ?? 'resume.tex')
    setPackagesInput((initial.extra_packages ?? []).join(', '))
    setFlags(new Set(initial.latexmk_flags ?? []))
    setHaltOnError(initial.halt_on_error !== false)
    setDraftMode(initial.draft_mode === true)
  }, [initial])

  // Close on Escape
  useEffect(() => {
    if (!open) return
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  if (!open) return null

  // ── Helpers ────────────────────────────────────────────────────────────────

  function parsePackages(raw: string): string[] {
    return raw
      .split(/[,\s]+/)
      .map((p) => p.trim())
      .filter((p) => /^[a-zA-Z0-9-]+$/.test(p) && p.length <= 50)
  }

  function toggleFlag(flag: LatexmkFlag) {
    setFlags((prev) => {
      const next = new Set(prev)
      if (next.has(flag)) next.delete(flag)
      else next.add(flag)
      return next
    })
  }

  function handleReset() {
    setCompiler(DEFAULT_SETTINGS.compiler)
    setMainFile(DEFAULT_SETTINGS.main_file)
    setPackagesInput('')
    setFlags(new Set())
    setHaltOnError(true)
    setDraftMode(false)
  }

  async function handleSave() {
    // Validate main_file
    if (mainFile && !/^[a-zA-Z0-9_-]+\.tex$/.test(mainFile)) {
      toast.error('Main file must match: letters/numbers/underscores/hyphens + .tex')
      return
    }

    const body: CompileSettings = {
      compiler,
      main_file: mainFile || 'resume.tex',
      latexmk_flags: [...flags] as LatexmkFlag[],
      extra_packages: parsePackages(packagesInput),
      halt_on_error: haltOnError,
      draft_mode: draftMode,
    }

    setSaving(true)
    try {
      await apiClient.updateResumeSettings(resumeId, body)
      onSaved(body)
      toast.success('Compile settings saved')
      onClose()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to save settings')
    } finally {
      setSaving(false)
    }
  }

  // ── Render ─────────────────────────────────────────────────────────────────

  return (
    <div
      ref={backdropRef}
      role="dialog"
      aria-modal="true"
      aria-labelledby="compile-settings-title"
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] backdrop-blur-sm"
      onClick={(e) => { if (e.target === backdropRef.current) onClose() }}
    >
      <div className="relative flex max-h-[calc(100vh-2rem)] w-full max-w-md flex-col rounded-[var(--radius-lg)] border border-line bg-bg shadow-[var(--shadow-2)]">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-line px-5 py-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-[var(--radius-md)] bg-accent-soft">
              <Settings2 size={14} className="text-accent-strong" />
            </div>
            <h2 id="compile-settings-title" className="text-sm font-semibold text-fg">Compile Settings</h2>
          </div>
          <button
            onClick={onClose}
            aria-label="Close compile settings"
            className="flex h-7 w-7 items-center justify-center rounded-[var(--radius-md)] text-fg-3 transition hover:bg-surface-2 hover:text-fg"
          >
            <X size={14} />
          </button>
        </div>

        {/* Body */}
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-5 py-5">
          {/* Compiler */}
          <div className="space-y-2">
            <label className="text-[11px] font-medium uppercase tracking-wider text-fg-3">
              Compiler Engine
            </label>
            <div className="grid grid-cols-3 gap-1.5">
              {COMPILER_OPTIONS.map((opt) => (
                <button
                  key={opt.id}
                  onClick={() => setCompiler(opt.id)}
                  className={`flex flex-col items-start gap-0.5 rounded-[var(--radius-md)] border px-3 py-2.5 text-left transition ${
                    compiler === opt.id
                      ? 'border-accent bg-accent-soft text-accent-strong'
                      : 'border-line text-fg-2 hover:border-line-2 hover:text-fg'
                  }`}
                >
                  <span className="text-[12px] font-semibold">{opt.label}</span>
                  <span className="text-[10px] text-fg-3 leading-tight">{opt.desc}</span>
                </button>
              ))}
            </div>
          </div>

          {/* TeX Live runtime */}
          <div className="space-y-2">
            <p className="text-[11px] font-medium uppercase tracking-wider text-fg-3">
              TeX Live Runtime
            </p>
            <p className="rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-[11px] text-fg-3">
              Managed by Latexy and updated with the compiler deployment. Per-resume version pinning is not supported.
            </p>
          </div>

          {/* Main .tex file */}
          <div className="space-y-2">
            <label className="text-[11px] font-medium uppercase tracking-wider text-fg-3">
              Main .tex File
            </label>
            <input
              type="text"
              value={mainFile}
              onChange={(e) => setMainFile(e.target.value)}
              placeholder="resume.tex"
              className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 font-mono text-[12px] text-fg outline-none focus:border-accent focus:ring-1 focus:ring-accent"
            />
            <p className="text-[10px] text-fg-3">
              Only alphanumeric, underscores, hyphens + .tex extension allowed
            </p>
          </div>

          {/* Extra packages */}
          <div className="space-y-2">
            <label className="text-[11px] font-medium uppercase tracking-wider text-fg-3">
              Extra Packages
            </label>
            <input
              type="text"
              value={packagesInput}
              onChange={(e) => setPackagesInput(e.target.value)}
              placeholder="xcolor, multicol, fontawesome5"
              className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 font-mono text-[12px] text-fg outline-none focus:border-accent focus:ring-1 focus:ring-accent"
            />
            <p className="text-[10px] text-fg-3">
              Comma-separated. Injected via \usepackage if not already in source.
            </p>
            <p className="text-[10px] text-warn">
              Packages requiring shell escape are unsupported because arbitrary command execution is prohibited.
            </p>
          </div>

          {/* Custom flags */}
          <div className="space-y-2">
            <label className="flex cursor-pointer items-start gap-2.5 rounded-[var(--radius-md)] border border-line px-3 py-2.5 hover:border-line-2">
              <input
                type="checkbox"
                checked={draftMode}
                onChange={(event) => setDraftMode(event.target.checked)}
                className="mt-0.5 h-3 w-3 rounded accent-accent"
              />
              <span>
                <span className="block text-[11px] font-medium text-fg-2">Draft mode</span>
                <span className="mt-0.5 block text-[10px] leading-snug text-fg-3">
                  Skip image rendering for faster previews. Image boxes remain in the document layout.
                </span>
              </span>
            </label>
          </div>

          <div className="space-y-2">
            <label className="flex cursor-pointer items-start gap-2.5 rounded-[var(--radius-md)] border border-line px-3 py-2.5 hover:border-line-2">
              <input
                type="checkbox"
                checked={haltOnError}
                onChange={(event) => setHaltOnError(event.target.checked)}
                className="mt-0.5 h-3 w-3 rounded accent-accent"
              />
              <span>
                <span className="block text-[11px] font-medium text-fg-2">Stop on first error</span>
                <span className="mt-0.5 block text-[10px] leading-snug text-fg-3">
                  Disable to let TeX continue and collect more errors in one compile. A document with errors still fails.
                </span>
              </span>
            </label>
          </div>

          {/* Custom flags */}
          <div className="space-y-2">
            <label className="text-[11px] font-medium uppercase tracking-wider text-fg-3">
              Compiler Flags
            </label>
            <div className="space-y-1.5">
              {ALLOWED_LATEXMK_FLAGS.filter((flag) => flag !== '--halt-on-error').map((flag) => {
                const isHardcoded = flag === '--interaction=nonstopmode' || flag === '--synctex=1'
                return (
                  <label
                    key={flag}
                    className={`flex items-center gap-2.5 rounded-[var(--radius-md)] border px-3 py-2 ${
                      isHardcoded
                        ? 'cursor-not-allowed border-line opacity-50'
                        : 'cursor-pointer border-line hover:border-line-2'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={isHardcoded || flags.has(flag)}
                      disabled={isHardcoded}
                      onChange={() => !isHardcoded && toggleFlag(flag)}
                      className="h-3 w-3 rounded accent-accent"
                    />
                    <div className="flex flex-1 items-center justify-between gap-2">
                      <code className="text-[11px] text-fg-2">{flag}</code>
                      <span className="text-[10px] text-fg-3">{FLAG_LABELS[flag]}</span>
                    </div>
                    {isHardcoded && (
                      <span className="text-[9px] text-fg-3 ml-1">(always on)</span>
                    )}
                  </label>
                )
              })}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex shrink-0 items-center justify-between border-t border-line px-5 py-4">
          <button
            onClick={handleReset}
            className="flex items-center gap-1.5 rounded-[var(--radius-md)] px-3 py-1.5 text-[11px] font-medium text-fg-3 transition hover:bg-surface-2 hover:text-fg-2"
          >
            <RotateCcw size={11} />
            Reset to Defaults
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-1.5 rounded-[var(--radius-md)] bg-accent px-4 py-1.5 text-[11px] font-semibold text-accent-fg ring-1 ring-accent transition hover:brightness-110 disabled:opacity-40"
          >
            {saving ? <Loader2 size={11} className="animate-spin" /> : <Save size={11} />}
            {saving ? 'Saving…' : 'Save Settings'}
          </button>
        </div>
      </div>
    </div>
  )
}
