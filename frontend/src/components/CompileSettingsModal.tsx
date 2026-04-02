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

const TEXLIVE_VERSIONS = [
  { value: '', label: 'Latest (default)' },
  { value: '2024', label: 'TeX Live 2024' },
  { value: '2023', label: 'TeX Live 2023' },
  { value: '2022', label: 'TeX Live 2022' },
]

const FLAG_LABELS: Record<LatexmkFlag, string> = {
  '--shell-escape': 'Shell escape (for minted, svg, etc.)',
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
  const [texliveVersion, setTexliveVersion] = useState<string>(initial.texlive_version ?? '')
  const [mainFile, setMainFile] = useState(initial.main_file ?? 'resume.tex')
  const [packagesInput, setPackagesInput] = useState((initial.extra_packages ?? []).join(', '))
  const [flags, setFlags] = useState<Set<LatexmkFlag>>(new Set(initial.latexmk_flags ?? []))
  const [saving, setSaving] = useState(false)
  const backdropRef = useRef<HTMLDivElement>(null)

  // Re-sync when initial changes (e.g. first load)
  useEffect(() => {
    setCompiler(initial.compiler ?? 'pdflatex')
    setTexliveVersion(initial.texlive_version ?? '')
    setMainFile(initial.main_file ?? 'resume.tex')
    setPackagesInput((initial.extra_packages ?? []).join(', '))
    setFlags(new Set(initial.latexmk_flags ?? []))
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
    setTexliveVersion('')
    setMainFile(DEFAULT_SETTINGS.main_file)
    setPackagesInput('')
    setFlags(new Set())
  }

  async function handleSave() {
    // Validate main_file
    if (mainFile && !/^[a-zA-Z0-9_-]+\.tex$/.test(mainFile)) {
      toast.error('Main file must match: letters/numbers/underscores/hyphens + .tex')
      return
    }

    const body: CompileSettings = {
      compiler,
      texlive_version: texliveVersion || null,
      main_file: mainFile || 'resume.tex',
      latexmk_flags: [...flags] as LatexmkFlag[],
      extra_packages: parsePackages(packagesInput),
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => { if (e.target === backdropRef.current) onClose() }}
    >
      <div className="relative w-full max-w-md rounded-2xl border border-white/[0.08] bg-[#0d0d0d] shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/[0.06] px-5 py-4">
          <div className="flex items-center gap-2.5">
            <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-violet-500/15">
              <Settings2 size={14} className="text-violet-300" />
            </div>
            <h2 className="text-sm font-semibold text-zinc-100">Compile Settings</h2>
          </div>
          <button
            onClick={onClose}
            className="flex h-7 w-7 items-center justify-center rounded-lg text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-200"
          >
            <X size={14} />
          </button>
        </div>

        {/* Body */}
        <div className="space-y-5 px-5 py-5">
          {/* Compiler */}
          <div className="space-y-2">
            <label className="text-[11px] font-medium uppercase tracking-wider text-zinc-500">
              Compiler Engine
            </label>
            <div className="grid grid-cols-3 gap-1.5">
              {COMPILER_OPTIONS.map((opt) => (
                <button
                  key={opt.id}
                  onClick={() => setCompiler(opt.id)}
                  className={`flex flex-col items-start gap-0.5 rounded-lg border px-3 py-2.5 text-left transition ${
                    compiler === opt.id
                      ? 'border-violet-500/40 bg-violet-500/10 text-violet-200'
                      : 'border-white/[0.07] text-zinc-400 hover:border-white/[0.12] hover:text-zinc-200'
                  }`}
                >
                  <span className="text-[12px] font-semibold">{opt.label}</span>
                  <span className="text-[10px] text-zinc-600 leading-tight">{opt.desc}</span>
                </button>
              ))}
            </div>
          </div>

          {/* TeX Live Version */}
          <div className="space-y-2">
            <label className="text-[11px] font-medium uppercase tracking-wider text-zinc-500">
              TeX Live Version
            </label>
            <select
              value={texliveVersion}
              onChange={(e) => setTexliveVersion(e.target.value)}
              className="w-full rounded-lg border border-white/[0.08] bg-[#141414] px-3 py-2 text-[12px] text-zinc-200 outline-none focus:border-violet-500/40 focus:ring-1 focus:ring-violet-500/20"
            >
              {TEXLIVE_VERSIONS.map((v) => (
                <option key={v.value} value={v.value}>
                  {v.label}
                </option>
              ))}
            </select>
          </div>

          {/* Main .tex file */}
          <div className="space-y-2">
            <label className="text-[11px] font-medium uppercase tracking-wider text-zinc-500">
              Main .tex File
            </label>
            <input
              type="text"
              value={mainFile}
              onChange={(e) => setMainFile(e.target.value)}
              placeholder="resume.tex"
              className="w-full rounded-lg border border-white/[0.08] bg-[#141414] px-3 py-2 font-mono text-[12px] text-zinc-200 outline-none focus:border-violet-500/40 focus:ring-1 focus:ring-violet-500/20"
            />
            <p className="text-[10px] text-zinc-600">
              Only alphanumeric, underscores, hyphens + .tex extension allowed
            </p>
          </div>

          {/* Extra packages */}
          <div className="space-y-2">
            <label className="text-[11px] font-medium uppercase tracking-wider text-zinc-500">
              Extra Packages
            </label>
            <input
              type="text"
              value={packagesInput}
              onChange={(e) => setPackagesInput(e.target.value)}
              placeholder="xcolor, multicol, fontawesome5"
              className="w-full rounded-lg border border-white/[0.08] bg-[#141414] px-3 py-2 font-mono text-[12px] text-zinc-200 outline-none focus:border-violet-500/40 focus:ring-1 focus:ring-violet-500/20"
            />
            <p className="text-[10px] text-zinc-600">
              Comma-separated. Injected via \usepackage if not already in source.
            </p>
          </div>

          {/* Custom flags */}
          <div className="space-y-2">
            <label className="text-[11px] font-medium uppercase tracking-wider text-zinc-500">
              Compiler Flags
            </label>
            <div className="space-y-1.5">
              {ALLOWED_LATEXMK_FLAGS.map((flag) => {
                const isHardcoded = flag === '--interaction=nonstopmode' || flag === '--halt-on-error' || flag === '--synctex=1'
                return (
                  <label
                    key={flag}
                    className={`flex items-center gap-2.5 rounded-lg border px-3 py-2 ${
                      isHardcoded
                        ? 'cursor-not-allowed border-white/[0.04] opacity-50'
                        : 'cursor-pointer border-white/[0.07] hover:border-white/[0.12]'
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={isHardcoded || flags.has(flag)}
                      disabled={isHardcoded}
                      onChange={() => !isHardcoded && toggleFlag(flag)}
                      className="h-3 w-3 rounded accent-violet-500"
                    />
                    <div className="flex flex-1 items-center justify-between gap-2">
                      <code className="text-[11px] text-zinc-300">{flag}</code>
                      <span className="text-[10px] text-zinc-600">{FLAG_LABELS[flag]}</span>
                    </div>
                    {isHardcoded && (
                      <span className="text-[9px] text-zinc-600 ml-1">(always on)</span>
                    )}
                  </label>
                )
              })}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-white/[0.06] px-5 py-4">
          <button
            onClick={handleReset}
            className="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-[11px] font-medium text-zinc-500 transition hover:bg-white/[0.04] hover:text-zinc-300"
          >
            <RotateCcw size={11} />
            Reset to Defaults
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="flex items-center gap-1.5 rounded-lg bg-violet-600/80 px-4 py-1.5 text-[11px] font-semibold text-white ring-1 ring-violet-500/30 transition hover:bg-violet-600 disabled:opacity-40"
          >
            {saving ? <Loader2 size={11} className="animate-spin" /> : <Save size={11} />}
            {saving ? 'Saving…' : 'Save Settings'}
          </button>
        </div>
      </div>
    </div>
  )
}
