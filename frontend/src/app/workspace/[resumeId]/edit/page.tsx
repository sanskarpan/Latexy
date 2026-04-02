'use client'

import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import Link from 'next/link'
import { useParams, useRouter, useSearchParams } from 'next/navigation'
import { toast } from 'sonner'
import {
  Sparkles,
  Play,
  Save,
  ChevronRight,
  Download,
  FileText,
  Terminal,
  Loader2,
  CheckCircle2,
  AlertCircle,
  Eye,
  List,
  ChevronDown,
  ChevronRight as ChevronRightIcon,
  History,
  AlertTriangle,
  Upload,
  X,
  Mail,
  Share2,
  BookOpen,
  MessageSquare,
  Palette,
  Brain,
  GitFork,
  Zap,
  ShieldCheck,
  Package,
  Braces,
  Github,
  Settings2,
  QrCode,
  Calendar,
} from 'lucide-react'
import { apiClient, type CheckpointEntry, type CompileSettings, type DiffWithParentResponse, type ExplainErrorResponse, type GitHubResumeStatus, type LatexCompiler, type ProofreadIssue, type ResumeResponse } from '@/lib/api-client'
import WritingAssistantWidget from '@/components/WritingAssistantWidget'
import ShareResumeModal from '@/components/ShareResumeModal'
import { useJobStream, type JobStreamState } from '@/hooks/useJobStream'
import LaTeXEditor, { type LaTeXEditorRef } from '@/components/LaTeXEditor'
import LogViewer from '@/components/LogViewer'
import PDFPreview from '@/components/PDFPreview'
import LoadingSpinner from '@/components/LoadingSpinner'
import DeepAnalysisPanel from '@/components/ats/DeepAnalysisPanel'
import InterviewPrepPanel from '@/components/InterviewPrepPanel'
import ExportDropdown from '@/components/ExportDropdown'
import MultiFormatUpload from '@/components/MultiFormatUpload'
import VersionHistoryPanel from '@/components/VersionHistoryPanel'
import SaveCheckpointPopover from '@/components/SaveCheckpointPopover'
import DiffViewerModal from '@/components/DiffViewerModal'
import CompareModal from '@/components/CompareModal'
import ErrorExplainerPanel from '@/components/ErrorExplainerPanel'
import ReferencesPanel from '@/components/ReferencesPanel'
import DesignPanel from '@/components/DesignPanel'
import BulletGeneratorWidget from '@/components/BulletGeneratorWidget'
import SummaryGeneratorWidget from '@/components/SummaryGeneratorWidget'
import ProofreadPanel from '@/components/ProofreadPanel'
import PackageManagerPanel from '@/components/PackageManagerPanel'
import LinterPanel from '@/components/LinterPanel'
import SymbolPalette from '@/components/SymbolPalette'
import QrCodeInserter from '@/components/QrCodeInserter'
import DateStandardizerPanel from '@/components/DateStandardizerPanel'
import CompilerSelector from '@/components/CompilerSelector'
import CompileSettingsModal from '@/components/CompileSettingsModal'
import { useAutoCompile } from '@/hooks/useAutoCompile'
import { useQuickATSScore } from '@/hooks/useQuickATSScore'
import { useLatexLinter } from '@/hooks/useLatexLinter'
import { useSpellCheck, addWordToDict } from '@/hooks/useSpellCheck'
import { useFeatureFlags } from '@/contexts/FeatureFlagsContext'
import KeyboardShortcutsPanel from '@/components/KeyboardShortcutsPanel'
import { usePushNotifications } from '@/hooks/usePushNotifications'


type RightTab = 'preview' | 'ai' | 'logs' | 'history' | 'references' | 'interview' | 'design' | 'proofread' | 'packages' | 'linter' | 'symbols'
type OptLevel = 'conservative' | 'balanced' | 'aggressive'
type AIModel = 'gpt-4o-mini' | 'gpt-4o'

// ─── Outline ────────────────────────────────────────────────────────────────

interface OutlineItem {
  level: number
  label: string
  line: number
}

function buildOutline(latex: string): OutlineItem[] {
  const items: OutlineItem[] = []
  const sectionRe = /^[^%]*\\(part|chapter|section|subsection|subsubsection)\*?\{([^}]*)\}/
  const lines = latex.split('\n')
  const levelMap: Record<string, number> = {
    part: 0, chapter: 1, section: 2, subsection: 3, subsubsection: 4,
  }
  for (let i = 0; i < lines.length; i++) {
    const m = lines[i].match(sectionRe)
    if (m) {
      items.push({ level: levelMap[m[1]] ?? 2, label: m[2].trim(), line: i + 1 })
    }
  }
  return items
}

function OutlinePanel({
  latex,
  onJump,
}: {
  latex: string
  onJump: (line: number) => void
}) {
  const items = useMemo(() => buildOutline(latex), [latex])

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-8 px-4">
        <List size={18} className="text-zinc-800" />
        <p className="text-[11px] text-zinc-700 text-center">
          No sections found.<br />Add \section{} to your document.
        </p>
      </div>
    )
  }

  return (
    <div className="overflow-y-auto py-1">
      {items.map((item, idx) => (
        <button
          key={idx}
          onClick={() => onJump(item.line)}
          className="flex w-full items-baseline gap-1 px-2 py-1 text-left text-[11px] text-zinc-500 transition hover:bg-white/[0.04] hover:text-zinc-200"
          style={{ paddingLeft: `${8 + item.level * 10}px` }}
          title={`Line ${item.line}`}
        >
          <span className="shrink-0 text-zinc-800" style={{ fontSize: 9 }}>
            {'─'.repeat(item.level > 0 ? 1 : 0)}
          </span>
          <span className="truncate">{item.label}</span>
        </button>
      ))}
    </div>
  )
}

// ─── AI Stage Pipeline ───────────────────────────────────────────────────────

const STAGES = [
  { key: 'llm_optimization', label: 'Rewrite' },
  { key: 'latex_compilation', label: 'Compile' },
  { key: 'ats_scoring', label: 'Score' },
]

function AIStagePipeline({ stage, percent, message }: { stage: string; percent: number; message: string }) {
  const current = STAGES.findIndex((s) => s.key === stage)
  return (
    <div className="w-full space-y-4">
      <div className="relative flex items-start justify-between">
        <div className="absolute left-4 right-4 top-3.5 h-px bg-white/[0.06]" />
        {STAGES.map((s, i) => {
          const done = i < current
          const active = i === current
          return (
            <div key={s.key} className="relative z-10 flex flex-col items-center gap-2">
              <div
                className={`flex h-7 w-7 items-center justify-center rounded-full border text-[10px] font-bold transition-all duration-300 ${
                  done
                    ? 'border-emerald-400/40 bg-emerald-500/15 text-emerald-400'
                    : active
                    ? 'border-violet-400/50 bg-violet-500/20 text-violet-300'
                    : 'border-white/[0.08] bg-black/40 text-zinc-700'
                }`}
              >
                {done ? <CheckCircle2 size={13} /> : <span>{i + 1}</span>}
              </div>
              <span
                className={`text-[10px] font-medium ${
                  done ? 'text-emerald-400' : active ? 'text-violet-300' : 'text-zinc-700'
                }`}
              >
                {s.label}
              </span>
            </div>
          )
        })}
      </div>
      <div>
        <div className="mb-1.5 flex justify-between text-[10px]">
          <span className="text-zinc-500 truncate">{message || 'Processing…'}</span>
          <span className="shrink-0 pl-2 tabular-nums text-zinc-600">{percent}%</span>
        </div>
        <div className="h-[3px] w-full overflow-hidden rounded-full bg-white/[0.05]">
          <div
            className="h-full rounded-full bg-gradient-to-r from-violet-500 to-orange-400 transition-all duration-500"
            style={{ width: `${percent}%` }}
          />
        </div>
      </div>
    </div>
  )
}

// ─── Shared sub-components ───────────────────────────────────────────────────

function LevelSelector({
  value,
  onChange,
  compact = false,
}: {
  value: OptLevel
  onChange: (v: OptLevel) => void
  compact?: boolean
}) {
  const descriptions: Record<OptLevel, string> = {
    conservative: 'Fix issues and add missing keywords only.',
    balanced: 'Moderate rewrites, preserves your voice.',
    aggressive: 'Full restructure for maximum ATS score.',
  }
  return (
    <div>
      <label className="mb-2 block text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-600">
        Optimization Level
      </label>
      <div className="grid grid-cols-3 gap-1 rounded-xl border border-white/[0.06] bg-black/30 p-1">
        {(['conservative', 'balanced', 'aggressive'] as OptLevel[]).map((level) => (
          <button
            key={level}
            onClick={() => onChange(level)}
            className={`rounded-lg py-2 text-[11px] font-medium capitalize transition ${
              value === level
                ? 'bg-violet-500/25 text-violet-200 ring-1 ring-violet-400/30'
                : 'text-zinc-600 hover:text-zinc-300'
            }`}
          >
            {level}
          </button>
        ))}
      </div>
      {!compact && (
        <p className="mt-1.5 text-[10px] text-zinc-700">{descriptions[value]}</p>
      )}
    </div>
  )
}

function ModelSelector({
  value,
  onChange,
  compact = false,
}: {
  value: AIModel
  onChange: (v: AIModel) => void
  compact?: boolean
}) {
  const models: { id: AIModel; label: string; desc: string }[] = [
    { id: 'gpt-4o-mini', label: 'Fast', desc: 'Quick & cost-efficient.' },
    { id: 'gpt-4o', label: 'Best', desc: 'Higher quality rewrites.' },
  ]
  return (
    <div>
      <label className="mb-2 block text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-600">
        Model
      </label>
      <div className="grid grid-cols-2 gap-1 rounded-xl border border-white/[0.06] bg-black/30 p-1">
        {models.map((m) => (
          <button
            key={m.id}
            onClick={() => onChange(m.id)}
            className={`rounded-lg py-2 text-[11px] font-medium transition ${
              value === m.id
                ? 'bg-violet-500/25 text-violet-200 ring-1 ring-violet-400/30'
                : 'text-zinc-600 hover:text-zinc-300'
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>
      {!compact && (
        <p className="mt-1.5 text-[10px] text-zinc-700">
          {models.find((m) => m.id === value)?.desc}
        </p>
      )}
    </div>
  )
}

function JDInput({
  value,
  onChange,
  compact = false,
}: {
  value: string
  onChange: (v: string) => void
  compact?: boolean
}) {
  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <label className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-600">
          Job Description
        </label>
        <span className="text-[10px] text-zinc-700">optional</span>
      </div>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={
          compact
            ? 'Paste job description…'
            : 'Paste a job description to tailor optimization to a specific role. Leave blank for general improvements.'
        }
        rows={compact ? 3 : 5}
        className="w-full resize-none rounded-xl border border-white/[0.06] bg-black/40 p-3 text-[12px] text-zinc-200 outline-none transition placeholder:text-zinc-700 focus:border-violet-400/30"
      />
    </div>
  )
}

// ─── Section Selector ────────────────────────────────────────────────────────

function SectionSelector({
  outline,
  selected,
  onChange,
}: {
  outline: OutlineItem[]
  selected: string[]
  onChange: (v: string[]) => void
}) {
  const allLabels = outline.map((o) => o.label)
  const allSelected = selected.length === 0 || selected.length === allLabels.length

  const toggle = (label: string) => {
    const isChecked = selected.length === 0 || selected.includes(label)
    if (isChecked) {
      if (selected.length === 0) {
        // All were selected — now select all except this one
        onChange(allLabels.filter((l) => l !== label))
      } else {
        const next = selected.filter((s) => s !== label)
        onChange(next.length === allLabels.length ? [] : next)
      }
    } else {
      const next = [...selected, label]
      onChange(next.length === allLabels.length ? [] : next)
    }
  }

  if (outline.length === 0) return null

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <label className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-600">
          Sections
        </label>
        <button
          onClick={() => onChange([])}
          className="text-[10px] text-zinc-700 transition hover:text-zinc-400"
        >
          {allSelected ? 'all' : `${selected.length} selected`}
        </button>
      </div>
      <div className="max-h-32 overflow-y-auto rounded-xl border border-white/[0.06] bg-black/30 p-2 space-y-0.5">
        {outline.map((item) => {
          const checked = selected.length === 0 || selected.includes(item.label)
          return (
            <label
              key={item.label}
              className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1 text-[11px] transition hover:bg-white/[0.04]"
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => toggle(item.label)}
                className="h-3 w-3 accent-violet-400"
              />
              <span
                className="truncate text-zinc-400"
                style={{ paddingLeft: `${item.level * 8}px` }}
              >
                {item.label}
              </span>
            </label>
          )
        })}
      </div>
    </div>
  )
}

// ─── AI Panel ────────────────────────────────────────────────────────────────

interface AIPanelProps {
  aiStream: JobStreamState
  isRunning: boolean
  isSubmitting: boolean
  jobDescription: string
  setJobDescription: (v: string) => void
  optLevel: OptLevel
  setOptLevel: (v: OptLevel) => void
  onRun: () => void
  onApplyAnyway: () => void
  outline: OutlineItem[]
  targetSections: string[]
  setTargetSections: (v: string[]) => void
  customInstructions: string
  setCustomInstructions: (v: string) => void
  onOpenDeepAnalysis: () => void
  model: AIModel
  setModel: (v: AIModel) => void
}

function AIPanel({
  aiStream,
  isRunning,
  isSubmitting,
  jobDescription,
  setJobDescription,
  optLevel,
  setOptLevel,
  onRun,
  onApplyAnyway,
  outline,
  targetSections,
  setTargetSections,
  customInstructions,
  setCustomInstructions,
  onOpenDeepAnalysis,
  model,
  setModel,
}: AIPanelProps) {
  const isDone = !isRunning && aiStream.status === 'completed'
  const isFailed = !isRunning && aiStream.status === 'failed'
  const isIdle = !isRunning && aiStream.status !== 'completed' && aiStream.status !== 'failed'
  const [showCustom, setShowCustom] = useState(false)
  const flags = useFeatureFlags()

  return (
    <div className="flex h-full flex-col overflow-y-auto scrollbar-subtle">
      {isRunning && (
        <div className="flex flex-1 flex-col items-center justify-center gap-8 p-6">
          <div className="w-full">
            <div className="mb-5 flex items-center gap-2">
              <div className="flex h-5 w-5 items-center justify-center rounded-full bg-violet-500/20">
                <Sparkles size={11} className="animate-pulse text-violet-300" />
              </div>
              <span className="text-xs font-semibold text-zinc-300">AI is working…</span>
            </div>
            <AIStagePipeline
              stage={aiStream.stage}
              percent={aiStream.percent}
              message={aiStream.message}
            />
          </div>
          {aiStream.streamingLatex && (
            <div className="flex items-center gap-2 rounded-lg border border-violet-400/20 bg-violet-500/5 px-3 py-2 text-[11px] text-violet-300">
              <Sparkles size={11} />
              <span>Streaming to editor in real-time…</span>
            </div>
          )}
        </div>
      )}

      {isDone && (
        <div className="space-y-4 p-4">
          <div className="flex items-center gap-3 rounded-xl border border-emerald-400/20 bg-emerald-500/[0.07] p-3">
            <CheckCircle2 size={16} className="shrink-0 text-emerald-400" />
            <div className="min-w-0">
              <p className="text-sm font-semibold text-emerald-300">Optimization complete</p>
              <p className="truncate text-[10px] text-zinc-500">
                {aiStream.changesMade?.length ?? 0} changes ·{' '}
                {aiStream.tokensUsed ? `${aiStream.tokensUsed.toLocaleString()} tokens` : 'PDF ready'}
              </p>
            </div>
          </div>

          {aiStream.atsScore != null && (
            <div className="flex items-center gap-4 rounded-xl border border-white/[0.06] bg-black/40 p-4">
              <div className="relative shrink-0">
                <svg className="h-[68px] w-[68px] -rotate-90" viewBox="0 0 36 36">
                  <circle cx="18" cy="18" r="15.9" fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth="3" />
                  <circle
                    cx="18" cy="18" r="15.9" fill="none"
                    stroke={aiStream.atsScore >= 80 ? '#34d399' : aiStream.atsScore >= 60 ? '#f59e0b' : '#f87171'}
                    strokeWidth="3"
                    strokeDasharray={`${aiStream.atsScore} ${100 - aiStream.atsScore}`}
                    strokeLinecap="round"
                  />
                </svg>
                <span
                  className={`absolute inset-0 flex items-center justify-center text-base font-bold ${
                    aiStream.atsScore >= 80 ? 'text-emerald-400' : aiStream.atsScore >= 60 ? 'text-amber-400' : 'text-rose-400'
                  }`}
                >
                  {Math.round(aiStream.atsScore)}
                </span>
              </div>
              <div>
                <p className="text-sm font-semibold text-zinc-200">ATS Score</p>
                <p className="mt-0.5 text-[11px] leading-relaxed text-zinc-500">
                  {aiStream.atsScore >= 80
                    ? 'Excellent — highly compatible'
                    : aiStream.atsScore >= 60
                    ? 'Good — minor improvements possible'
                    : 'Needs improvement'}
                </p>
                {aiStream.atsDetails?.recommendations?.[0] && (
                  <p className="mt-1 text-[10px] italic text-zinc-600">
                    {aiStream.atsDetails.recommendations[0]}
                  </p>
                )}
              </div>
            </div>
          )}

          <button
            onClick={onRun}
            disabled={isSubmitting}
            className="flex w-full items-center justify-center gap-1.5 rounded-xl bg-violet-500/20 py-2.5 text-xs font-semibold text-violet-200 ring-1 ring-violet-400/20 transition hover:bg-violet-500/30"
          >
            <Sparkles size={12} /> Run again
          </button>

          <button
            onClick={onOpenDeepAnalysis}
            className="flex w-full items-center justify-center gap-2 rounded-xl border border-violet-400/20 bg-violet-500/10 py-2.5 text-xs font-semibold text-violet-200 transition hover:bg-violet-500/20"
          >
            <Brain size={12} /> Deep AI Analysis
          </button>

          <div className="border-t border-white/[0.05]" />
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-600">
            Settings for next run
          </p>
          <LevelSelector value={optLevel} onChange={setOptLevel} compact />
          <ModelSelector value={model} onChange={setModel} compact />
          <JDInput value={jobDescription} onChange={setJobDescription} compact />
        </div>
      )}

      {isFailed && (
        <div className="space-y-4 p-4">
          <div className="flex items-start gap-3 rounded-xl border border-rose-400/20 bg-rose-500/[0.07] p-3">
            <AlertCircle size={15} className="mt-0.5 shrink-0 text-rose-400" />
            <div>
              <p className="text-sm font-semibold text-rose-300">Optimization failed</p>
              <p className="mt-0.5 text-[11px] text-zinc-500">{aiStream.error || 'An error occurred'}</p>
            </div>
          </div>

          {/* Timeout upgrade CTA */}
          {aiStream.errorCode === 'compile_timeout' && (
            <div className="flex items-center justify-between rounded-xl border border-orange-500/20 bg-orange-500/10 px-3 py-2.5">
              <span className="text-[11px] text-orange-300">
                ⏱ {aiStream.timeoutError?.plan ?? 'free'} plan limit reached (
                {aiStream.timeoutError?.plan === 'free' ? '30s'
                  : aiStream.timeoutError?.plan === 'basic' ? '120s'
                  : '240s'})
              </span>
              {flags.upgrade_ctas && (
                <a
                  href="/billing"
                  className="ml-3 shrink-0 text-[11px] font-medium text-orange-200 underline hover:text-orange-100"
                >
                  Upgrade →
                </a>
              )}
            </div>
          )}

          {/* Fix 3: Apply anyway when LLM succeeded but compile failed */}
          {aiStream.streamingLatex && (
            <div className="rounded-xl border border-amber-400/20 bg-amber-500/[0.07] p-3">
              <div className="flex items-center gap-2 mb-2">
                <AlertTriangle size={13} className="text-amber-400" />
                <p className="text-[11px] font-semibold text-amber-300">AI rewrite is available</p>
              </div>
              <p className="text-[10px] text-zinc-500 mb-3">
                The LaTeX rewrite completed but failed to compile. You can apply it to the editor and fix the errors manually.
              </p>
              <button
                onClick={onApplyAnyway}
                className="w-full rounded-lg border border-amber-400/30 bg-amber-500/10 py-2 text-[11px] font-semibold text-amber-200 transition hover:bg-amber-500/20"
              >
                Apply optimized LaTeX anyway
              </button>
            </div>
          )}

          <button
            onClick={onRun}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-violet-500/20 py-2.5 text-sm font-semibold text-violet-200 ring-1 ring-violet-400/20 transition hover:bg-violet-500/30"
          >
            <Sparkles size={13} /> Try again
          </button>
        </div>
      )}

      {isIdle && (
        <div className="space-y-5 p-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500/20 to-orange-500/10 ring-1 ring-violet-400/20">
              <Sparkles size={16} className="text-violet-300" />
            </div>
            <div>
              <p className="text-sm font-semibold text-zinc-100">AI Optimization</p>
              <p className="text-[10px] text-zinc-600">GPT-4o · Optimize + Compile + Score</p>
            </div>
          </div>

          <p className="text-[12px] leading-relaxed text-zinc-500">
            Rewrites your resume with improved language and ATS keywords, then compiles to PDF and
            scores for recruiter visibility.
          </p>

          <ModelSelector value={model} onChange={setModel} />
          <LevelSelector value={optLevel} onChange={setOptLevel} />
          <JDInput value={jobDescription} onChange={setJobDescription} />

          {/* Feature 3: Section-specific optimization */}
          {outline.length > 0 && (
            <SectionSelector
              outline={outline}
              selected={targetSections}
              onChange={setTargetSections}
            />
          )}

          {/* Feature 3: Custom instructions */}
          <div>
            <button
              onClick={() => setShowCustom((v) => !v)}
              className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-600 transition hover:text-zinc-400"
            >
              <ChevronDown
                size={11}
                className={`transition-transform ${showCustom ? 'rotate-180' : ''}`}
              />
              Custom Instructions
            </button>
            {showCustom && (
              <textarea
                value={customInstructions}
                onChange={(e) => setCustomInstructions(e.target.value)}
                placeholder="e.g. keep it to 1 page, emphasize Python experience, avoid passive voice"
                rows={3}
                className="mt-2 w-full resize-none rounded-xl border border-white/[0.06] bg-black/40 p-3 text-[12px] text-zinc-200 outline-none transition placeholder:text-zinc-700 focus:border-violet-400/30"
              />
            )}
          </div>

          <button
            onClick={onRun}
            disabled={isSubmitting}
            className="flex w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-r from-violet-600/80 to-violet-500/60 py-3 text-sm font-semibold text-white shadow-lg shadow-violet-900/20 ring-1 ring-violet-400/20 transition hover:from-violet-600 hover:to-violet-500/80 disabled:opacity-50"
          >
            {isSubmitting ? (
              <><Loader2 size={14} className="animate-spin" /> Starting…</>
            ) : (
              <><Sparkles size={14} /> {jobDescription.trim() ? 'Optimize for this Role' : 'Optimize Resume'}</>
            )}
          </button>
        </div>
      )}
    </div>
  )
}

// ─── History Panel (now uses VersionHistoryPanel component) ────────────────

// ─── Main page ───────────────────────────────────────────────────────────────

export default function ResumeEditPage() {
  const params = useParams()
  const router = useRouter()
  const resumeId = params.resumeId as string
  const flags = useFeatureFlags()

  // Core state
  const [title, setTitle] = useState('')
  const [latexContent, setLatexContent] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [isSaving, setIsSaving] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [compileJobId, setCompileJobId] = useState<string | null>(null)
  const [lastStartedJobKind, setLastStartedJobKind] = useState<'compile' | 'ai'>('compile')
  const userInitiatedJobRef = useRef(false)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [showImportModal, setShowImportModal] = useState(false)
  const [qrInserterOpen, setQrInserterOpen] = useState(false)
  const [dateStandardizerOpen, setDateStandardizerOpen] = useState(false)

  // Layout
  const [rightTab, setRightTab] = useState<RightTab>('preview')
  const [rightWidth, setRightWidth] = useState<number | null>(null)
  const [showOutline, setShowOutline] = useState(false)
  const [isDraggingResize, setIsDraggingResize] = useState(false)
  const isResizingRef = useRef(false)
  const resizeStartX = useRef(0)
  const resizeStartWidth = useRef(0)

  // AI
  const [aiJobId, setAiJobId] = useState<string | null>(null)
  const [jobDescription, setJobDescription] = useState('')
  const [optLevel, setOptLevel] = useState<OptLevel>('balanced')
  const [model, setModel] = useState<AIModel>('gpt-4o-mini')
  const [isAiSubmitting, setIsAiSubmitting] = useState(false)
  // Feature 2: Multi-level undo stack (replaces single baselineLatex)
  const [undoStack, setUndoStack] = useState<Array<{ label: string; latex: string }>>([])
  // Feature 3: Section-specific optimization
  const [targetSections, setTargetSections] = useState<string[]>([])
  const [customInstructions, setCustomInstructions] = useState('')

  // Version history / diff
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0)
  const [diffCheckpointA, setDiffCheckpointA] = useState<CheckpointEntry | null>(null)
  const [diffCheckpointB, setDiffCheckpointB] = useState<CheckpointEntry | null>(null)
  const [showDiffModal, setShowDiffModal] = useState(false)
  const [compareData, setCompareData] = useState<{ original: string; optimized: string } | null>(null)

  // Auto-compile
  const { enabled: autoCompile, toggle: toggleAutoCompile } = useAutoCompile()

  // SyncTeX
  const [syncFromLine, setSyncFromLine] = useState<number | null>(null)
  const [cursorLine, setCursorLine] = useState<number | null>(null)

  // Bullet generator widget
  const [bulletWidgetOpen, setBulletWidgetOpen] = useState(false)
  const [bulletWidgetTop, setBulletWidgetTop] = useState(0)
  const [bulletWidgetLine, setBulletWidgetLine] = useState<number | null>(null)

  // Summary generator widget
  const [summaryWidgetOpen, setSummaryWidgetOpen] = useState(false)
  const [summaryWidgetTop, setSummaryWidgetTop] = useState(0)
  const [cursorInSummarySection, setCursorInSummarySection] = useState(false)

  // Proofreader
  const [proofreadIssues, setProofreadIssues] = useState<ProofreadIssue[]>([])

  // Linter
  const [linterEnabled, setLinterEnabled] = useState(true)
  const { issues: lintIssues, autoFixAll: runLintAutoFixAll } = useLatexLinter(latexContent, linterEnabled)

  // Spell check (Feature 35)
  const [spellCheckEnabled, setSpellCheckEnabled] = useState(() => {
    if (typeof window === 'undefined') return false
    return localStorage.getItem('latexy_spell_check') === 'true'
  })
  const { issues: spellCheckIssues, loading: spellCheckLoading } = useSpellCheck(
    latexContent,
    spellCheckEnabled,
  )

  // Deep analysis (Layer 2)
  const [deepPanelOpen, setDeepPanelOpen] = useState(false)
  const [deepAnalysisJobId, setDeepAnalysisJobId] = useState<string | null>(null)
  const [deepAnalysisUsesRemaining, setDeepAnalysisUsesRemaining] = useState<number | null>(null)
  const [isDeepRunning, setIsDeepRunning] = useState(false)
  const [deepAnalysisError, setDeepAnalysisError] = useState<string | null>(null)

  // Variant awareness
  const [parentResumeId, setParentResumeId] = useState<string | null>(null)
  const [parentTitle, setParentTitle] = useState<string | null>(null)
  const [parentDiffData, setParentDiffData] = useState<DiffWithParentResponse | null>(null)
  const [showParentDiff, setShowParentDiff] = useState(false)
  const [forkPopoverOpen, setForkPopoverOpen] = useState(false)
  const [forkTitleInput, setForkTitleInput] = useState('')
  const [isForkingResume, setIsForkingResume] = useState(false)

  // Error explainer
  const [explainerOpen, setExplainerOpen] = useState(false)
  const [explainerLoading, setExplainerLoading] = useState(false)
  const [explainerData, setExplainerData] = useState<ExplainErrorResponse | null>(null)
  const [explainerLine, setExplainerLine] = useState<number | null>(null)

  // Writing assistant
  const [writingOpen, setWritingOpen] = useState(false)
  const [writingSelected, setWritingSelected] = useState('')
  const [writingContext, setWritingContext] = useState('')
  const [writingRange, setWritingRange] = useState<{ startLine: number; startColumn: number; endLine: number; endColumn: number } | null>(null)
  const [writingTop, setWritingTop] = useState(0)

  // Compiler preference (stored in resume metadata)
  const [compiler, setCompiler] = useState<LatexCompiler>('pdflatex')
  // Compile settings modal (Feature 38)
  const [compileSettingsOpen, setCompileSettingsOpen] = useState(false)
  const [compileSettings, setCompileSettings] = useState<CompileSettings>({ compiler: 'pdflatex' })

  // Share link
  const [shareModalOpen, setShareModalOpen] = useState(false)
  const [shareToken, setShareToken] = useState<string | null>(null)
  const [shareUrl, setShareUrl] = useState<string | null>(null)

  // Keyboard shortcuts panel (Feature 61)
  const [shortcutsOpen, setShortcutsOpen] = useState(false)

  // Push notifications (Feature 65)
  const { requestPermission, notify } = usePushNotifications()

  // GitHub sync (Feature 37)
  const [ghConnected, setGhConnected] = useState(false)
  const [ghSyncEnabled, setGhSyncEnabled] = useState(false)
  const [ghPushing, setGhPushing] = useState(false)
  const [ghTogglingSync, setGhTogglingSync] = useState(false)

  const searchParams = useSearchParams()
  const activePdfJobId = useRef<string | null>(null)
  const editorRef = useRef<LaTeXEditorRef>(null)
  const pdfUrlRef = useRef<string | null>(null)

  // Navigate to line from ?line= search param (set by ProjectSearchModal)
  useEffect(() => {
    const lineParam = searchParams.get('line')
    if (!lineParam) return
    const lineNumber = parseInt(lineParam, 10)
    if (isNaN(lineNumber) || lineNumber < 1) return
    // Wait for editor to mount, then reveal the line
    const attempt = () => {
      if (editorRef.current) {
        editorRef.current.highlightLine(lineNumber)
        // Clear param from URL without navigation
        const url = new URL(window.location.href)
        url.searchParams.delete('line')
        window.history.replaceState(null, '', url.toString())
      } else {
        setTimeout(attempt, 100)
      }
    }
    attempt()
  }, [searchParams])

  // Check GitHub user connection
  useEffect(() => {
    apiClient.getGitHubStatus().then(s => setGhConnected(s.connected)).catch(() => {})
  }, [])

  const { score: quickATSScore, loading: quickATSLoading, refetch: refetchATS } = useQuickATSScore(latexContent)

  const { state: compileStream } = useJobStream(compileJobId)
  const { state: aiStream } = useJobStream(aiJobId)
  const { state: deepStream } = useJobStream(deepAnalysisJobId)

  // Load resume and auto-compile on load
  useEffect(() => {
    const fetchResume = async () => {
      try {
        const data = await apiClient.getResume(resumeId)
        setTitle(data.title)
        setLatexContent(data.latex_content)
        editorRef.current?.setValue(data.latex_content)
        // Load compiler preference from resume metadata
        const savedCompiler = data.metadata?.compiler as LatexCompiler | undefined
        if (savedCompiler && ['pdflatex', 'xelatex', 'lualatex'].includes(savedCompiler)) {
          setCompiler(savedCompiler)
        }
        // Load all compile settings for the modal (Feature 38)
        const meta = data.metadata as Record<string, unknown> | null | undefined
        setCompileSettings({
          compiler: savedCompiler ?? 'pdflatex',
          texlive_version: (meta?.texlive_version as string | null | undefined) ?? null,
          main_file: (meta?.main_file as string | undefined) ?? 'resume.tex',
          latexmk_flags: ((meta?.latexmk_flags as string[] | undefined) ?? []) as CompileSettings['latexmk_flags'],
          extra_packages: (meta?.extra_packages as string[] | undefined) ?? [],
        })
        // Load share token state
        setShareToken(data.share_token ?? null)
        setShareUrl(data.share_url ?? null)

        // GitHub sync state
        setGhSyncEnabled(data.github_sync_enabled ?? false)

        setParentResumeId(data.parent_resume_id ?? null)
        // Fetch parent title if this is a variant
        if (data.parent_resume_id) {
          apiClient.getResume(data.parent_resume_id).then(p => setParentTitle(p.title)).catch(() => {
            setParentResumeId(null) // parent was deleted
          })
        }

        // Auto-compile on load so user sees PDF immediately
        if (data.latex_content && data.latex_content.length >= 100) {
          try {
            const initCompiler = (data.metadata?.compiler as LatexCompiler | undefined) ?? 'pdflatex'
            const r = await apiClient.compileLatex({ latex_content: data.latex_content, resume_id: resumeId, compiler: initCompiler })
            if (r.success && r.job_id) { setCompileJobId(r.job_id); setLastStartedJobKind('compile') }
          } catch {
            // Silent — user can compile manually
          }
        }
      } catch {
        toast.error('Failed to load resume')
        router.push('/workspace')
      } finally {
        setIsLoading(false)
      }
    }
    fetchResume()
  }, [resumeId, router])

  // Stream AI tokens to Monaco in real-time (direct model mutation, no setState per token)
  useEffect(() => {
    if (!aiStream.streamingLatex || !editorRef.current) return
    editorRef.current.setValue(aiStream.streamingLatex)
  }, [aiStream.streamingLatex])

  // When AI completes, commit streamed content to React state + record optimization + track
  useEffect(() => {
    if (aiStream.status === 'completed') {
      const finalLatex = editorRef.current?.getValue() || ''
      setLatexContent(finalLatex)
      // Feature 1: save optimization record
      if (finalLatex && aiJobId) {
        const baselineLatex = undoStack[undoStack.length - 1]?.latex || ''
        apiClient.recordOptimization(resumeId, {
          original_latex: baselineLatex,
          optimized_latex: finalLatex,
          changes_made: aiStream.changesMade,
          ats_score: aiStream.atsScore ?? undefined,
          tokens_used: aiStream.tokensUsed ?? undefined,
          job_description: jobDescription.trim() || undefined,
        }).catch(() => {}) // non-critical
        // Track optimization for analytics
        apiClient.trackOptimization(aiJobId, 'openai', model, aiStream.tokensUsed ?? undefined)
        apiClient.trackFeatureUsage('ai_optimization')
      }
    }
  }, [aiStream.status]) // eslint-disable-line react-hooks/exhaustive-deps

  // Track compilation completion for analytics
  useEffect(() => {
    if (compileStream.status === 'completed' && compileJobId) {
      apiClient.trackCompilation(compileJobId, 'completed')
      apiClient.trackFeatureUsage('compile')
      refetchATS()
    } else if (compileStream.status === 'failed' && compileJobId) {
      apiClient.trackCompilation(compileJobId, 'failed')
    }
  }, [compileStream.status, compileJobId, refetchATS])

  // Load PDF after either job completes
  useEffect(() => {
    const pdfJobId = compileStream.pdfJobId ?? aiStream.pdfJobId
    const anyCompleted =
      (compileStream.status === 'completed' && compileStream.pdfJobId) ||
      (aiStream.status === 'completed' && aiStream.pdfJobId)

    if (anyCompleted && pdfJobId) {
      activePdfJobId.current = pdfJobId
      apiClient.downloadPdf(pdfJobId).then((blob) => {
        const nextUrl = URL.createObjectURL(blob)
        if (pdfUrlRef.current) URL.revokeObjectURL(pdfUrlRef.current)
        pdfUrlRef.current = nextUrl
        setPdfUrl(nextUrl)
        setRightTab('preview')
      }).catch(() => toast.error('Failed to load PDF preview'))
      return
    }

    const anyRunning =
      compileStream.status === 'queued' || compileStream.status === 'processing' ||
      aiStream.status === 'queued' || aiStream.status === 'processing'

    if (anyRunning && pdfUrlRef.current) {
      URL.revokeObjectURL(pdfUrlRef.current)
      pdfUrlRef.current = null
      setPdfUrl(null)
      activePdfJobId.current = null
    }
  }, [
    compileStream.status, compileStream.pdfJobId,
    aiStream.status, aiStream.pdfJobId,
  ])

  // Cleanup blob URL on unmount
  useEffect(() => {
    return () => { if (pdfUrlRef.current) URL.revokeObjectURL(pdfUrlRef.current) }
  }, [])

  // Push notification on compile/AI job complete (Feature 65) — only for user-initiated jobs
  useEffect(() => {
    if (userInitiatedJobRef.current && compileStream.status === 'completed') {
      notify('Compilation complete', 'Your resume PDF is ready')
      userInitiatedJobRef.current = false
    }
  }, [compileStream.status, notify])

  useEffect(() => {
    if (userInitiatedJobRef.current && aiStream.status === 'completed') {
      notify('Optimization complete', 'Your AI-optimized resume is ready to review')
      userInitiatedJobRef.current = false
    }
  }, [aiStream.status, notify])

  // Request notification permission after first user-initiated compile attempt
  useEffect(() => {
    if (userInitiatedJobRef.current && (compileStream.status === 'processing' || aiStream.status === 'processing')) {
      requestPermission()
    }
  }, [compileStream.status, aiStream.status, requestPermission])

  // Cmd+? keyboard shortcut for shortcuts panel (Feature 61)
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.code === 'Slash') {
        e.preventDefault()
        setShortcutsOpen(true)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  // ── Resize handle ──────────────────────────────────────────────────────
  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!isResizingRef.current) return
      const delta = resizeStartX.current - e.clientX
      const next = Math.max(280, Math.min(window.innerWidth - 300, resizeStartWidth.current + delta))
      setRightWidth(next)
    }
    const onMouseUp = () => {
      if (!isResizingRef.current) return
      isResizingRef.current = false
      setIsDraggingResize(false)
      document.body.style.userSelect = ''
      document.body.style.cursor = ''
    }
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
    return () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
    }
  }, [])

  const rightPanelRef = useRef<HTMLElement>(null)

  const startResize = useCallback((e: React.MouseEvent) => {
    const w = rightPanelRef.current
      ? rightPanelRef.current.getBoundingClientRect().width
      : (rightWidth ?? 560)
    isResizingRef.current = true
    setIsDraggingResize(true)
    resizeStartX.current = e.clientX
    resizeStartWidth.current = w
    document.body.style.userSelect = 'none'
    document.body.style.cursor = 'col-resize'
    e.preventDefault()
  }, [rightWidth])

  // ── Undo stack helpers (Feature 2) ──────────────────────────────────────
  const pushUndo = useCallback((label: string) => {
    const current = editorRef.current?.getValue() || latexContent
    setUndoStack((prev) => [...prev.slice(-9), { label, latex: current }])
  }, [latexContent])

  // ── Handlers ────────────────────────────────────────────────────────────
  // ── GitHub sync handlers ──────────────────────────────────────────
  const handleToggleGitHubSync = async () => {
    setGhTogglingSync(true)
    try {
      if (ghSyncEnabled) {
        await apiClient.disableGitHubSync(resumeId)
        setGhSyncEnabled(false)
        toast.success('GitHub sync disabled')
      } else {
        await apiClient.enableGitHubSync(resumeId)
        setGhSyncEnabled(true)
        toast.success('GitHub sync enabled')
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Failed to toggle sync')
    } finally {
      setGhTogglingSync(false)
    }
  }

  const handlePushToGitHub = async () => {
    setGhPushing(true)
    try {
      // Save first to ensure latest content is pushed
      const content = editorRef.current?.getValue() || latexContent
      await apiClient.updateResume(resumeId, { title, latex_content: content })
      const result = await apiClient.pushToGitHub(resumeId)
      toast.success(result.message)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'GitHub push failed')
    } finally {
      setGhPushing(false)
    }
  }

  const handlePullFromGitHub = async () => {
    if (!window.confirm('Replace local content with the latest version from GitHub? Unsaved changes will be overwritten.')) return
    setGhPushing(true)
    try {
      const result = await apiClient.pullFromGitHub(resumeId)
      editorRef.current?.setValue(result.latex_content)
      setLatexContent(result.latex_content)
      toast.success('Pulled latest content from GitHub')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'GitHub pull failed')
    } finally {
      setGhPushing(false)
    }
  }

  const handleSave = async () => {
    const content = editorRef.current?.getValue() || latexContent
    setIsSaving(true)
    try {
      await apiClient.updateResume(resumeId, { title, latex_content: content })
      setLatexContent(content)
      toast.success('Saved')
    } catch {
      toast.error('Failed to save')
    } finally {
      setIsSaving(false)
    }
  }

  const runCompile = async () => {
    const content = editorRef.current?.getValue() || latexContent
    if (!content.trim()) { toast.error('Nothing to compile'); return }
    setIsSubmitting(true)
    try {
      const r = await apiClient.compileLatex({ latex_content: content, resume_id: resumeId, compiler })
      if (!r.success || !r.job_id) throw new Error(r.message)
      userInitiatedJobRef.current = true
      setCompileJobId(r.job_id)
      setLastStartedJobKind('compile')
      setRightTab('logs')
      toast.success('Compilation started')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Compile failed')
    } finally {
      setIsSubmitting(false)
    }
  }

  const runAiOptimize = async () => {
    const content = editorRef.current?.getValue() || latexContent
    setIsAiSubmitting(true)
    try {
      const r = await apiClient.optimizeAndCompile({
        latex_content: content,
        job_description: jobDescription.trim() || undefined,
        optimization_level: optLevel,
                // Feature 3: pass section and instruction filters
        target_sections: targetSections.length > 0 ? targetSections : undefined,
        custom_instructions: customInstructions.trim() || undefined,
        model,
        resume_id: resumeId,
        compiler,
      })
      if (!r.success || !r.job_id) throw new Error(r.message)
      userInitiatedJobRef.current = true
      pushUndo('Before AI optimization')
      setAiJobId(r.job_id)
      setLastStartedJobKind('ai')
      toast.success('AI optimization started')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'AI optimization failed')
    } finally {
      setIsAiSubmitting(false)
    }
  }

  // Fix 3: Apply optimized LaTeX even when compilation failed
  const handleApplyAnyway = useCallback(() => {
    if (!aiStream.streamingLatex) return
    pushUndo('Before apply (failed compile)')
    editorRef.current?.setValue(aiStream.streamingLatex)
    setLatexContent(aiStream.streamingLatex)
    toast.success('Applied optimized LaTeX — fix the compile errors manually')
  }, [aiStream.streamingLatex, pushUndo])

  // Version history: restore from checkpoint
  const handleHistoryRestore = useCallback((latex: string) => {
    pushUndo('Before restore')
    editorRef.current?.setValue(latex)
    setLatexContent(latex)
  }, [pushUndo])

  // Version history: compare two checkpoints
  const handleCompare = useCallback((a: CheckpointEntry, b: CheckpointEntry) => {
    setDiffCheckpointA(a)
    setDiffCheckpointB(b)
    setShowDiffModal(true)
  }, [])

  // Version history: restore from diff viewer
  const handleDiffRestore = useCallback((latex: string) => {
    pushUndo('Before diff restore')
    editorRef.current?.setValue(latex)
    setLatexContent(latex)
    setShowDiffModal(false)
    toast.success('Version restored from diff')
  }, [pushUndo])

  // Checkpoint saved callback
  const handleCheckpointSaved = useCallback(() => {
    setHistoryRefreshKey((k) => k + 1)
  }, [])

  // Close diff modal
  const handleCloseDiff = useCallback(() => {
    setShowDiffModal(false)
  }, [])


  const handleDownload = async () => {
    const id = compileStream.pdfJobId ?? aiStream.pdfJobId ?? compileJobId ?? aiJobId
    if (!id) return
    try {
      const blob = await apiClient.downloadPdf(id)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${title.replace(/\s+/g, '_') || 'resume'}.pdf`
      a.click()
      URL.revokeObjectURL(url)
    } catch { toast.error('Download failed') }
  }

  const handleOpenDeepAnalysis = useCallback(async () => {
    setDeepPanelOpen(true)
    if (deepAnalysisJobId) return // already have a job running/done
    const content = editorRef.current?.getValue() || latexContent
    if (!content.trim()) { toast.error('Add LaTeX content first'); return }
    setIsDeepRunning(true)
    setDeepAnalysisError(null)
    try {
      const response = await apiClient.deepAnalyzeResume({
        latex_content: content,
        job_description: jobDescription.trim() || undefined,
      })
      if (response.success && response.job_id) {
        setDeepAnalysisJobId(response.job_id)
        setDeepAnalysisUsesRemaining(response.uses_remaining ?? null)
      } else {
        throw new Error(response.message || 'Deep analysis failed')
      }
    } catch (error) {
      const msg = error instanceof Error ? error.message : 'Deep analysis failed'
      setDeepAnalysisError(msg)
      toast.error(msg)
    } finally {
      setIsDeepRunning(false)
    }
  }, [deepAnalysisJobId, latexContent, jobDescription])

  const handleSyncToSource = useCallback((line: number) => {
    editorRef.current?.highlightLine(line)
  }, [])

  const handleCursorChange = useCallback((line: number) => {
    setCursorLine(line)
  }, [])

  const handleCursorLineChange = useCallback((lineContent: string, lineNumber: number) => {
    // \b prevents matching \itemsep, \itemize, etc.
    const isItemLine = /^\s*\\item\b/.test(lineContent)
    setBulletWidgetLine(isItemLine ? lineNumber : null)
    // Don't close the widget if it's already open (user is interacting with it)
    if (!isItemLine && !bulletWidgetOpen) setBulletWidgetLine(null)
  }, [bulletWidgetOpen])

  const handleOpenBulletWidget = useCallback(() => {
    const pos = editorRef.current?.getCaretPosition()
    setBulletWidgetTop(pos?.top ?? 0)
    setBulletWidgetOpen(true)
  }, [])

  const handleBulletInsert = useCallback((bullet: string) => {
    if (bulletWidgetLine === null) return
    // Preserve existing indentation by reading the current line from the model
    const allContent = editorRef.current?.getValue() ?? ''
    const lineText = allContent.split('\n')[bulletWidgetLine - 1] ?? ''
    const indent = lineText.match(/^(\s*)/)?.[1] ?? ''
    editorRef.current?.applyFix(bulletWidgetLine, `${indent}\\item ${bullet}`)
    setBulletWidgetOpen(false)
  }, [bulletWidgetLine])

  const handleCursorInSummarySection = useCallback((inSummary: boolean) => {
    setCursorInSummarySection(inSummary)
    if (!inSummary && summaryWidgetOpen) setSummaryWidgetOpen(false)
  }, [summaryWidgetOpen])

  const handleOpenSummaryWidget = useCallback(() => {
    const pos = editorRef.current?.getCaretPosition()
    setSummaryWidgetTop(pos?.top ?? 0)
    setSummaryWidgetOpen(true)
  }, [])

  const handleSummaryInsert = useCallback((text: string) => {
    editorRef.current?.insertAtCursor(text)
    setSummaryWidgetOpen(false)
  }, [])

  const handleOutlineJump = useCallback((line: number) => {
    editorRef.current?.highlightLine(line)
  }, [])

  // Error explainer handlers
  const handleExplainError = useCallback(async (error: { line: number; message: string; surroundingLatex: string }) => {
    setExplainerLine(error.line)
    setExplainerOpen(true)
    setExplainerLoading(true)
    setExplainerData(null)
    try {
      const result = await apiClient.explainLatexError({
        error_message: error.message,
        surrounding_latex: error.surroundingLatex,
        error_line: error.line,
      })
      setExplainerData(result)
    } catch {
      setExplainerData({
        success: false,
        explanation: 'Failed to analyze error.',
        suggested_fix: 'Check the error message and surrounding code manually.',
        corrected_code: null,
        source: 'error',
        cached: false,
        processing_time: 0,
      })
    } finally {
      setExplainerLoading(false)
    }
  }, [])

  const handleApplyExplainerFix = useCallback(() => {
    if (!explainerData?.corrected_code || explainerLine == null) return
    editorRef.current?.applyFix(explainerLine, explainerData.corrected_code)
    setExplainerOpen(false)
    toast.success('Fix applied')
  }, [explainerData, explainerLine])

  // Writing assistant handlers
  const handleWritingAssistantAction = useCallback((info: {
    selectedText: string
    context: string
    startLine: number
    startColumn: number
    endLine: number
    endColumn: number
  }) => {
    setWritingSelected(info.selectedText)
    setWritingContext(info.context)
    setWritingRange({ startLine: info.startLine, startColumn: info.startColumn, endLine: info.endLine, endColumn: info.endColumn })
    const pos = editorRef.current?.getCaretPosition()
    setWritingTop(pos?.top ?? 100)
    setWritingOpen(true)
  }, [])

  const handleWritingAccept = useCallback((rewrittenText: string) => {
    if (!writingRange) return
    editorRef.current?.applyRewrite(writingRange.startLine, writingRange.startColumn, writingRange.endLine, writingRange.endColumn, rewrittenText)
    setWritingOpen(false)
    toast.success('Text rewritten')
  }, [writingRange])

  // Variant handlers
  const handleCompareWithParent = useCallback(async () => {
    try {
      const data = await apiClient.getResumeDiffWithParent(resumeId)
      setParentDiffData(data)
      setShowParentDiff(true)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to load diff')
    }
  }, [resumeId])

  const handleParentDiffRestore = useCallback((latex: string) => {
    pushUndo('Before restore from parent diff')
    editorRef.current?.setValue(latex)
    setLatexContent(latex)
    setShowParentDiff(false)
    toast.success('Version restored')
  }, [pushUndo])

  // ── Design panel — preamble change (Feature 20) ──────────────────────────
  const handleDesignPreambleChange = useCallback((newLatex: string) => {
    editorRef.current?.setValue(newLatex)
    setLatexContent(newLatex)
  }, [])

  const handleCreateVariant = useCallback(async () => {
    if (isForkingResume) return
    setIsForkingResume(true)
    try {
      const newResume = await apiClient.forkResume(resumeId, forkTitleInput || undefined)
      setForkPopoverOpen(false)
      setForkTitleInput('')
      router.push(`/workspace/${newResume.id}/edit`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to create variant')
    } finally {
      setIsForkingResume(false)
    }
  }, [resumeId, forkTitleInput, isForkingResume, router])

  const isCompiling = compileStream.status === 'queued' || compileStream.status === 'processing'
  const isAiRunning = aiStream.status === 'queued' || aiStream.status === 'processing'
  const isAnyRunning = isCompiling || isAiRunning

  // Auto-compile handler (compile-only, not optimize)
  const handleAutoCompile = useCallback(async (content: string) => {
    if (isSubmitting) return
    setIsSubmitting(true)
    try {
      const r = await apiClient.compileLatex({ latex_content: content, resume_id: resumeId, compiler })
      if (!r.success || !r.job_id) throw new Error(r.message)
      setCompileJobId(r.job_id)
      setLastStartedJobKind('compile')
    } catch {
      // Silent fail for auto-compile — don't spam toasts
    } finally {
      setIsSubmitting(false)
    }
  }, [isSubmitting, resumeId, compiler])

  // Design panel — trigger compile after preamble change (Feature 20)
  const handleDesignTriggerCompile = useCallback(() => {
    if (isAnyRunning) return
    const content = editorRef.current?.getValue()
    if (content?.trim()) handleAutoCompile(content)
  }, [isAnyRunning, handleAutoCompile])

  const pageCount = lastStartedJobKind === 'ai'
    ? aiStream.pageCount
    : compileStream.pageCount
  const extractedPdfText = lastStartedJobKind === 'ai'
    ? aiStream.extractedPdfText
    : compileStream.extractedPdfText

  const TRIM_INSTRUCTION = "Condense this resume to fit on exactly ONE page. Prioritize recent and most impactful content. Remove less critical details, condense bullet points, reduce descriptions. Do NOT remove any job titles, companies, degrees, or institution names."

  const handleTrimToOnePage = useCallback(async () => {
    const content = editorRef.current?.getValue() || latexContent
    setIsAiSubmitting(true)
    try {
      const r = await apiClient.optimizeAndCompile({
        latex_content: content,
        optimization_level: 'aggressive',
        custom_instructions: TRIM_INSTRUCTION,
        resume_id: resumeId,
      })
      if (!r.success || !r.job_id) throw new Error(r.message)
      userInitiatedJobRef.current = true
      pushUndo('Before AI trim (1 page)')
      setAiJobId(r.job_id)
      setLastStartedJobKind('ai')
      toast.success('AI trim started — condensing to 1 page…')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Trim failed')
    } finally {
      setIsAiSubmitting(false)
    }
  }, [latexContent, resumeId, pushUndo, TRIM_INSTRUCTION])

  const logLines = isCompiling || compileStream.logLines.length > 0
    ? compileStream.logLines
    : aiStream.logLines

  const statusText = isAiRunning
    ? `AI: ${aiStream.message || aiStream.stage || 'processing…'}`
    : isCompiling
    ? `Compiling… ${compileStream.percent}%`
    : compileStream.status === 'completed'
    ? 'Compiled successfully'
    : aiStream.status === 'completed'
    ? `AI complete · ATS ${aiStream.atsScore != null ? Math.round(aiStream.atsScore) : '—'}`
    : aiStream.status === 'failed'
    ? `AI failed: ${aiStream.error || 'error'}`
    : 'LaTeX editor ready'

  const currentLatex = editorRef.current?.getValue() || latexContent
  const outline = buildOutline(currentLatex)

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-[#0d0d0d]">
        <LoadingSpinner />
      </div>
    )
  }

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-[#0d0d0d]">

      {/* ── TOP HEADER ── */}
      <header className="flex h-11 shrink-0 items-center justify-between border-b border-white/[0.07] bg-[#111] px-4">
        <div className="flex min-w-0 items-center gap-1.5 text-xs">
          <Link href="/workspace" className="shrink-0 text-zinc-600 transition hover:text-zinc-300">
            Workspace
          </Link>
          <ChevronRight size={12} className="shrink-0 text-zinc-800" />
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            className="min-w-0 max-w-[280px] bg-transparent text-sm font-medium text-zinc-300 outline-none transition placeholder:text-zinc-700 hover:text-white focus:text-white"
            placeholder="Untitled"
          />
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <button
            onClick={() => setShowImportModal(true)}
            className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[11px] font-medium text-zinc-500 transition hover:bg-white/[0.05] hover:text-zinc-200"
          >
            <Upload size={12} />
            Import
          </button>

          <ExportDropdown resumeId={resumeId} variant="toolbar" />

          <button
            onClick={() => setQrInserterOpen(true)}
            title="Insert QR code"
            className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[11px] font-medium text-zinc-500 transition hover:bg-white/[0.05] hover:text-zinc-200"
          >
            <QrCode size={12} />
            QR
          </button>

          <button
            onClick={() => setDateStandardizerOpen(true)}
            title="Standardize date formats"
            className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[11px] font-medium text-zinc-500 transition hover:bg-white/[0.05] hover:text-zinc-200"
          >
            <Calendar size={12} />
            Dates
          </button>

          <Link
            href={`/workspace/${resumeId}/cover-letter`}
            className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[11px] font-medium text-violet-300/80 transition hover:bg-violet-500/10 hover:text-violet-200"
          >
            <Mail size={12} />
            Cover Letter
          </Link>

          {/* Create Variant button */}
          <div className="relative">
            <button
              onClick={() => { setForkPopoverOpen(v => !v); setForkTitleInput(`${title} — Variant`) }}
              className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[11px] font-medium text-zinc-500 transition hover:bg-white/[0.05] hover:text-zinc-200"
            >
              <GitFork size={12} />
              Variant
            </button>
            {forkPopoverOpen && (
              <div className="absolute right-0 top-full z-50 mt-1 w-64 rounded-lg border border-white/10 bg-zinc-950 p-3 shadow-xl">
                <input
                  type="text"
                  value={forkTitleInput}
                  onChange={e => setForkTitleInput(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') handleCreateVariant(); if (e.key === 'Escape') setForkPopoverOpen(false) }}
                  placeholder="Variant title"
                  autoFocus
                  className="w-full rounded-md border border-white/10 bg-black/40 px-2 py-1.5 text-xs text-zinc-100 outline-none focus:border-orange-300/40 mb-2"
                />
                <div className="flex gap-2 justify-end">
                  <button onClick={() => setForkPopoverOpen(false)} className="px-2 py-1 text-[10px] text-zinc-500 hover:text-zinc-300">Cancel</button>
                  <button onClick={handleCreateVariant} disabled={isForkingResume} className="rounded-md bg-orange-500/20 px-3 py-1 text-[10px] font-semibold text-orange-200 ring-1 ring-orange-400/20 hover:bg-orange-500/30 disabled:opacity-50">
                    {isForkingResume ? 'Creating...' : 'Create'}
                  </button>
                </div>
              </div>
            )}
          </div>

          <button
            onClick={handleSave}
            disabled={isSaving}
            className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[11px] font-medium text-zinc-500 transition hover:bg-white/[0.05] hover:text-zinc-200 disabled:opacity-40"
          >
            <Save size={12} />
            {isSaving ? 'Saving…' : 'Save'}
          </button>

          <SaveCheckpointPopover resumeId={resumeId} onSaved={handleCheckpointSaved} />

          <button
            onClick={() => setShareModalOpen(true)}
            title="Share resume"
            className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[11px] font-medium transition ${
              shareToken
                ? 'text-sky-300/90 hover:bg-sky-500/10 hover:text-sky-200'
                : 'text-zinc-500 hover:bg-white/[0.05] hover:text-zinc-200'
            }`}
          >
            <Share2 size={12} />
            Share
          </button>

          {/* GitHub sync (Feature 37) — only show if user has connected GitHub */}
          {ghConnected && (
            <>
              <button
                onClick={handleToggleGitHubSync}
                disabled={ghTogglingSync}
                title={ghSyncEnabled ? 'Disable GitHub sync' : 'Enable GitHub sync'}
                className={`flex items-center gap-1 rounded-md px-2 py-1.5 text-[11px] font-medium transition ${
                  ghSyncEnabled
                    ? 'bg-zinc-800 text-zinc-200 ring-1 ring-white/[0.1]'
                    : 'text-zinc-600 hover:text-zinc-300'
                }`}
              >
                {ghTogglingSync ? <Loader2 size={11} className="animate-spin" /> : <Github size={11} />}
                Sync
              </button>
              {ghSyncEnabled && (
                <>
                  <button
                    onClick={handlePushToGitHub}
                    disabled={ghPushing}
                    title="Push to GitHub"
                    className="flex items-center gap-1 rounded-md px-2 py-1.5 text-[11px] font-medium text-zinc-500 transition hover:bg-white/[0.05] hover:text-zinc-200 disabled:opacity-40"
                  >
                    {ghPushing ? <Loader2 size={11} className="animate-spin" /> : <Upload size={11} />}
                    Push
                  </button>
                  <button
                    onClick={handlePullFromGitHub}
                    disabled={ghPushing}
                    title="Pull from GitHub"
                    className="flex items-center gap-1 rounded-md px-2 py-1.5 text-[11px] font-medium text-zinc-500 transition hover:bg-white/[0.05] hover:text-zinc-200 disabled:opacity-40"
                  >
                    <Download size={11} />
                    Pull
                  </button>
                </>
              )}
            </>
          )}

          <div className="mx-1 h-3.5 w-px bg-white/[0.08]" />

          <CompilerSelector
            resumeId={resumeId}
            current={compiler}
            onChange={(c) => {
              setCompiler(c)
              setCompileSettings((prev) => ({ ...prev, compiler: c }))
            }}
            disabled={isAnyRunning}
          />

          <button
            onClick={() => setCompileSettingsOpen(true)}
            title="Compile settings"
            className="flex items-center gap-1 rounded-md px-2 py-1.5 text-[11px] font-medium text-zinc-500 transition hover:bg-white/[0.04] hover:text-zinc-300"
          >
            <Settings2 size={11} />
          </button>

          <div className="mx-1 h-3.5 w-px bg-white/[0.08]" />

          <button
            onClick={toggleAutoCompile}
            title="Auto-compile on change (2s debounce)"
            className={`flex items-center gap-1 rounded-md px-2 py-1.5 text-[11px] font-medium transition ${
              autoCompile
                ? 'bg-orange-500/20 text-orange-300 ring-1 ring-orange-500/30'
                : 'text-zinc-600 hover:text-zinc-300'
            }`}
          >
            <Zap size={11} />
            Auto
          </button>

          <button
            onClick={runCompile}
            disabled={isSubmitting || isAnyRunning}
            className="flex items-center gap-1.5 rounded-md border border-white/[0.08] bg-white/[0.05] px-3 py-1.5 text-[11px] font-semibold text-zinc-200 transition hover:bg-white/[0.09] disabled:opacity-40"
          >
            {isCompiling
              ? <Loader2 size={11} className="animate-spin" />
              : <Play size={11} className="fill-current" />}
            {isCompiling ? 'Compiling…' : 'Compile'}
          </button>

          <button
            onClick={() => setRightTab('ai')}
            className={`flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[11px] font-semibold transition ${
              isAiRunning
                ? 'border-violet-400/30 bg-violet-500/15 text-violet-200'
                : 'border-violet-400/20 bg-gradient-to-r from-violet-500/15 to-orange-500/10 text-violet-200 hover:from-violet-500/25 hover:to-orange-500/15'
            }`}
          >
            {isAiRunning
              ? <Loader2 size={11} className="animate-spin" />
              : <Sparkles size={11} />}
            {isAiRunning ? `AI ${aiStream.percent}%` : 'AI Optimize'}
          </button>
        </div>
      </header>

      {/* Variant banner */}
      {parentResumeId && parentTitle && (
        <div className="flex h-7 shrink-0 items-center justify-between border-b border-orange-500/10 bg-orange-500/5 px-4">
          <span className="text-xs text-zinc-400">
            Variant of: <span className="font-medium text-zinc-300">{parentTitle}</span>
          </span>
          <button
            onClick={handleCompareWithParent}
            className="text-xs font-semibold text-orange-300 transition hover:text-orange-200"
          >
            Compare with Parent
          </button>
        </div>
      )}

      {/* Resize drag overlay */}
      {isDraggingResize && (
        <div className="fixed inset-0 z-50" style={{ cursor: 'col-resize' }} />
      )}

      {/* ── MAIN BODY ── */}
      <main className="flex min-h-0 flex-1 overflow-hidden">

        {/* ── Left: Outline sidebar (collapsible) ── */}
        <aside
          className={`flex shrink-0 flex-col border-r border-white/[0.05] bg-[#0a0a0a] transition-all duration-200 ${
            showOutline ? 'w-48' : 'w-8'
          }`}
        >
          <button
            onClick={() => setShowOutline((v) => !v)}
            className={`flex h-8 w-full shrink-0 items-center border-b border-white/[0.05] px-1.5 text-zinc-600 transition hover:text-zinc-300 ${
              showOutline ? 'justify-between' : 'justify-center'
            }`}
            title={showOutline ? 'Hide outline' : 'Show outline'}
          >
            {showOutline ? (
              <>
                <span className="text-[10px] font-semibold uppercase tracking-[0.14em]">Outline</span>
                <ChevronRightIcon size={12} />
              </>
            ) : (
              <List size={13} />
            )}
          </button>

          {showOutline && (
            <div className="min-h-0 flex-1 overflow-hidden">
              <OutlinePanel latex={currentLatex} onJump={handleOutlineJump} />
            </div>
          )}
        </aside>

        {/* ── Editor ── */}
        <section className="flex min-h-0 min-w-0 flex-col" style={{ flex: '3 1 0%' }}>
          <div className="flex h-8 shrink-0 items-center gap-2 border-b border-white/[0.05] bg-[#0a0a0a] px-3">
            <div className="flex items-center gap-1.5 rounded-md bg-white/[0.04] px-2.5 py-1 text-[11px] font-medium text-zinc-400">
              <FileText size={11} className="text-zinc-600" />
              {title || 'Untitled'}.tex
            </div>
          </div>
          {/* Page overflow warning banner */}
          {pageCount !== null && pageCount > 1 && (
            <div className="flex shrink-0 items-center justify-between border-b border-amber-500/20 bg-amber-500/10 px-4 py-1.5">
              <span className="text-[11px] text-amber-400">
                ⚠ Your resume is {pageCount} pages. Most recruiters prefer 1 page.
              </span>
              <button
                onClick={handleTrimToOnePage}
                disabled={isAiSubmitting || isAnyRunning}
                className="ml-3 text-[11px] text-amber-300 underline hover:text-amber-100 disabled:opacity-50"
              >
                Trim with AI →
              </button>
            </div>
          )}
          <div className="relative min-h-0 flex-1">
            <LaTeXEditor
              ref={editorRef}
              value={latexContent}
              onChange={setLatexContent}
              logLines={logLines}
              onSave={handleSave}
              onCompile={runCompile}
              onCursorChange={handleCursorChange}
              onCursorLineChange={handleCursorLineChange}
              syncLine={syncFromLine}
              onAutoCompile={autoCompile && !isAnyRunning ? handleAutoCompile : undefined}
              atsScore={quickATSScore}
              atsScoreLoading={quickATSLoading}
              onATSBadgeClick={() => setDeepPanelOpen(true)}
              onExplainError={handleExplainError}
              onWritingAssistantAction={handleWritingAssistantAction}
              pageCount={pageCount}
              onCursorInSummarySection={handleCursorInSummarySection}
              proofreadIssues={proofreadIssues}
              lintIssues={lintIssues}
              spellCheckIssues={spellCheckIssues}
              spellCheckEnabled={spellCheckEnabled}
              spellCheckLoading={spellCheckLoading}
              onSpellCheckToggle={() => {
                setSpellCheckEnabled((prev) => {
                  const next = !prev
                  localStorage.setItem('latexy_spell_check', String(next))
                  return next
                })
              }}
            />

            {/* AI Summary Widget trigger — shown when cursor is in summary section */}
            {cursorInSummarySection && !summaryWidgetOpen && !bulletWidgetOpen && (
              <button
                onClick={handleOpenSummaryWidget}
                title="AI Summary Generator"
                className="absolute left-1 z-20 flex items-center gap-1 rounded-md bg-violet-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-violet-300 ring-1 ring-violet-400/20 transition hover:bg-violet-500/30"
                style={{ top: (editorRef.current?.getCaretPosition()?.top ?? 0) + 2 }}
              >
                <Sparkles size={9} />
                Summary
              </button>
            )}

            <SummaryGeneratorWidget
              isOpen={summaryWidgetOpen}
              onClose={() => setSummaryWidgetOpen(false)}
              onInsert={handleSummaryInsert}
              resumeLatex={latexContent}
              top={summaryWidgetTop}
            />

            <WritingAssistantWidget
              isOpen={writingOpen}
              selectedText={writingSelected}
              context={writingContext}
              onAccept={handleWritingAccept}
              onClose={() => setWritingOpen(false)}
              top={writingTop}
            />

            {/* AI Bullet Widget trigger — shown when cursor is on \item line */}
            {bulletWidgetLine !== null && !bulletWidgetOpen && (
              <button
                onClick={handleOpenBulletWidget}
                title="AI Bullet Generator"
                className="absolute left-1 z-20 flex items-center gap-1 rounded-md bg-violet-500/20 px-1.5 py-0.5 text-[10px] font-semibold text-violet-300 ring-1 ring-violet-400/20 transition hover:bg-violet-500/30"
                style={{ top: (editorRef.current?.getCaretPosition()?.top ?? 0) + 2 }}
              >
                <Sparkles size={9} />
                AI
              </button>
            )}

            <BulletGeneratorWidget
              isOpen={bulletWidgetOpen}
              onClose={() => setBulletWidgetOpen(false)}
              onInsert={handleBulletInsert}
              top={bulletWidgetTop}
            />

            <div className="absolute inset-x-0 bottom-0 z-10">
              <ErrorExplainerPanel
                isOpen={explainerOpen}
                isLoading={explainerLoading}
                data={explainerData}
                errorLine={explainerLine}
                onClose={() => setExplainerOpen(false)}
                onApplyFix={handleApplyExplainerFix}
              />
            </div>
          </div>
        </section>

        {/* ── Resize handle ── */}
        <div
          className="group relative flex w-[5px] shrink-0 cursor-col-resize items-center justify-center"
          onMouseDown={startResize}
        >
          <div className="h-full w-px bg-white/[0.05] transition-colors group-hover:bg-orange-400/30 group-active:bg-orange-400/60" />
        </div>

        {/* ── Right panel ── */}
        <aside
          ref={rightPanelRef}
          className="flex flex-col border-l border-white/[0.05] bg-[#0e0e0e]"
          style={
            rightWidth === null
              ? { flex: '2 1 0%', minWidth: 340 }
              : { width: `${rightWidth}px`, minWidth: `${rightWidth}px`, maxWidth: `${rightWidth}px`, flexShrink: 0 }
          }
        >
          {/* Tab bar */}
          <div className="flex h-9 shrink-0 items-center border-b border-white/[0.05] bg-black/20 px-1">
            {(
              [
                { id: 'preview', label: 'Preview', icon: Eye },
                { id: 'ai', label: 'AI', icon: Sparkles },
                { id: 'logs', label: 'Logs', icon: Terminal },
                { id: 'history', label: 'History', icon: History },
                { id: 'references', label: 'Refs', icon: BookOpen },
                { id: 'interview', label: 'Interview', icon: MessageSquare },
                { id: 'design', label: 'Design', icon: Palette },
                { id: 'proofread', label: 'Proof', icon: ShieldCheck },
                { id: 'packages', label: 'Packages', icon: Package },
                { id: 'linter', label: 'Linter', icon: AlertTriangle },
                { id: 'symbols', label: 'Symbols', icon: Braces },
              ] as const
            ).map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                onClick={() => setRightTab(id)}
                className={`relative flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[11px] font-medium transition ${
                  rightTab === id ? 'text-zinc-100' : 'text-zinc-600 hover:text-zinc-300'
                }`}
              >
                <Icon size={11} />
                {label}
                {rightTab === id && (
                  <span className="absolute inset-x-1 bottom-0 h-[2px] rounded-t-sm bg-orange-400" />
                )}
                {id === 'ai' && isAiRunning && (
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-violet-400" />
                )}
                {id === 'logs' && isCompiling && (
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-orange-400" />
                )}
                {id === 'linter' && lintIssues.length > 0 && (
                  <span className="ml-0.5 rounded bg-amber-500/20 px-1 py-0.5 font-mono text-[8px] text-amber-300">
                    {lintIssues.length}
                  </span>
                )}
              </button>
            ))}

            <div className="flex-1" />

            {pdfUrl && (
              <button
                onClick={handleDownload}
                className="flex items-center gap-1 px-2 py-1 text-[10px] text-zinc-600 transition hover:text-zinc-300"
              >
                <Download size={11} />
                PDF
              </button>
            )}
          </div>

          {/* Tab content */}
          <div className="min-h-0 flex-1 overflow-hidden">
            {rightTab === 'preview' && (
              <PDFPreview
                pdfUrl={pdfUrl}
                isLoading={isAnyRunning}
                jobId={activePdfJobId.current}
                onSyncToSource={handleSyncToSource}
                syncFromLine={cursorLine}
              />
            )}

            {rightTab === 'ai' && (
              <AIPanel
                aiStream={aiStream}
                isRunning={isAiRunning}
                isSubmitting={isAiSubmitting}
                jobDescription={jobDescription}
                setJobDescription={setJobDescription}
                optLevel={optLevel}
                setOptLevel={setOptLevel}
                onRun={runAiOptimize}
                onApplyAnyway={handleApplyAnyway}
                outline={outline}
                targetSections={targetSections}
                setTargetSections={setTargetSections}
                customInstructions={customInstructions}
                setCustomInstructions={setCustomInstructions}
                onOpenDeepAnalysis={handleOpenDeepAnalysis}
                model={model}
                setModel={setModel}
              />
            )}

            {rightTab === 'logs' && (
              <div className="h-full overflow-auto p-3">
                <div className="mb-2 flex items-center justify-between px-1">
                  <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-zinc-700">
                    {isCompiling ? 'Compilation output' : isAiRunning ? 'AI pipeline logs' : 'Last run logs'}
                  </span>
                  <span
                    className={`text-[10px] font-medium capitalize ${
                      isAnyRunning
                        ? 'text-orange-400'
                        : compileStream.status === 'completed' || aiStream.status === 'completed'
                        ? 'text-emerald-400'
                        : 'text-zinc-600'
                    }`}
                  >
                    {isAnyRunning
                      ? 'Running'
                      : compileStream.status !== 'idle'
                      ? compileStream.status
                      : aiStream.status !== 'idle'
                      ? aiStream.status
                      : '—'}
                  </span>
                </div>
                <LogViewer lines={logLines} maxHeight="100%" className="h-full text-[11px]" />
              </div>
            )}

            {rightTab === 'history' && (
              <VersionHistoryPanel
                resumeId={resumeId}
                onRestore={handleHistoryRestore}
                onCompare={handleCompare}
                onBeforeAfter={(orig, opt) => setCompareData({ original: orig, optimized: opt })}
                refreshKey={historyRefreshKey}
              />
            )}

            {rightTab === 'references' && (
              <ReferencesPanel
                onInsertBibTeX={(bibtex) => editorRef.current?.insertAtCursor(bibtex)}
                onInsertCiteKey={(key) => editorRef.current?.insertAtCursor(key)}
              />
            )}

            {rightTab === 'interview' && (
              <div className="min-h-0 flex-1 overflow-hidden">
                <InterviewPrepPanel
                  resumeId={resumeId}
                  defaultJobDescription={jobDescription}
                />
              </div>
            )}

            {rightTab === 'design' && (
              <DesignPanel
                currentLatex={latexContent}
                onPreambleChange={handleDesignPreambleChange}
                onTriggerCompile={autoCompile ? handleDesignTriggerCompile : undefined}
              />
            )}

            {rightTab === 'proofread' && (
              <ProofreadPanel
                resumeLatex={latexContent}
                onApplyFix={(issue) => {
                  if (issue.suggested_text) {
                    editorRef.current?.applyRewrite(
                      issue.line, issue.column_start,
                      issue.line, issue.column_end,
                      issue.suggested_text,
                    )
                    // Remove this issue's decoration immediately
                    setProofreadIssues(prev =>
                      prev.filter(i =>
                        !(i.line === issue.line &&
                          i.column_start === issue.column_start &&
                          i.original_text === issue.original_text)
                      )
                    )
                  }
                }}
                onApplyAllFixes={(issues) => {
                  editorRef.current?.applyMultipleRewrites(
                    issues
                      .filter(i => i.suggested_text)
                      .map(i => ({
                        startLine: i.line,
                        startColumn: i.column_start,
                        endLine: i.line,
                        endColumn: i.column_end,
                        text: i.suggested_text!,
                      }))
                  )
                  // Clear all applied decorations
                  const appliedKeys = new Set(
                    issues.map(i => `${i.line}:${i.column_start}:${i.original_text}`)
                  )
                  setProofreadIssues(prev =>
                    prev.filter(i =>
                      !appliedKeys.has(`${i.line}:${i.column_start}:${i.original_text}`)
                    )
                  )
                }}
                onProofreadComplete={setProofreadIssues}
              />
            )}

            {rightTab === 'packages' && (
              <PackageManagerPanel
                currentLatex={latexContent}
                onAddPackage={(newLatex) => {
                  editorRef.current?.setValue(newLatex)
                  setLatexContent(newLatex)
                }}
              />
            )}

            {rightTab === 'linter' && (
              <LinterPanel
                issues={lintIssues}
                enabled={linterEnabled}
                onToggleEnabled={setLinterEnabled}
                onJumpToLine={(line) => editorRef.current?.highlightLine(line)}
                onApplyFix={(issue) => {
                  if (!issue.fix) return
                  const currentContent = editorRef.current?.getValue() ?? latexContent
                  const lines = currentContent.split('\n')
                  const lineContent = lines[issue.line - 1] ?? ''
                  const fixed = issue.fix(lineContent)
                  editorRef.current?.applyFix(issue.line, fixed)
                  const newLines = [...lines]
                  newLines[issue.line - 1] = fixed
                  setLatexContent(newLines.join('\n'))
                }}
                onAutoFixAll={() => {
                  const currentContent = editorRef.current?.getValue() ?? latexContent
                  const fixed = runLintAutoFixAll(currentContent)
                  editorRef.current?.setValue(fixed)
                  setLatexContent(fixed)
                }}
                extractedPdfText={extractedPdfText}
                pageCount={pageCount}
              />
            )}

            {rightTab === 'symbols' && (
              <SymbolPalette
                onInsert={(cmd) => editorRef.current?.insertAtCursor(cmd)}
              />
            )}
          </div>
        </aside>
      </main>

      {/* Import modal */}
      {showImportModal && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="w-full max-w-md rounded-2xl border border-white/10 bg-zinc-950 shadow-2xl shadow-black/60 p-6">
            <div className="flex justify-between items-center mb-3">
              <h3 className="text-base font-semibold text-zinc-100">Import Resume File</h3>
              <button
                onClick={() => setShowImportModal(false)}
                className="rounded-md p-1.5 text-zinc-500 transition hover:bg-white/[0.06] hover:text-zinc-300"
              >
                <X size={16} />
              </button>
            </div>
            <p className="text-xs text-zinc-500 mb-5">
              This will replace the current editor content. Make sure to save first.
            </p>
            <MultiFormatUpload
              onFileUpload={(content) => {
                if (content) {
                  editorRef.current?.setValue(content)
                  setLatexContent(content)
                  setShowImportModal(false)
                  toast.success('File imported successfully')
                }
              }}
            />
          </div>
        </div>
      )}

      <DeepAnalysisPanel
        isOpen={deepPanelOpen}
        onClose={() => setDeepPanelOpen(false)}
        isLoading={isDeepRunning || deepStream.status === 'queued' || deepStream.status === 'processing'}
        analysis={deepStream.deepAnalysis}
        error={deepAnalysisError}
        usesRemaining={deepAnalysisUsesRemaining}
        onRun={handleOpenDeepAnalysis}
        isRunning={isDeepRunning}
        hideUpgradeCtas={!flags.upgrade_ctas}
        resumeId={resumeId}
      />

      {/* QR Code Inserter (Feature 62) */}
      <QrCodeInserter
        isOpen={qrInserterOpen}
        onClose={() => setQrInserterOpen(false)}
        onInsert={(snippet) => editorRef.current?.insertAtCursor(snippet)}
        getLatex={() => editorRef.current?.getValue() ?? latexContent}
        onLatexChange={(newLatex) => {
          editorRef.current?.setValue(newLatex)
          setLatexContent(newLatex)
        }}
      />

      {/* Date Format Standardizer (Feature 57) */}
      <DateStandardizerPanel
        isOpen={dateStandardizerOpen}
        onClose={() => setDateStandardizerOpen(false)}
        getLatex={() => editorRef.current?.getValue() ?? latexContent}
        onApply={(newLatex) => {
          editorRef.current?.setValue(newLatex)
          setLatexContent(newLatex)
        }}
      />

      {/* Diff viewer modal */}
      {showDiffModal && (
        <DiffViewerModal
          resumeId={resumeId}
          checkpointA={diffCheckpointA}
          checkpointB={diffCheckpointB}
          currentLatex={editorRef.current?.getValue() || latexContent}
          onRestore={handleDiffRestore}
          onClose={handleCloseDiff}
        />
      )}

      {/* Parent diff modal */}
      {showParentDiff && parentDiffData && (
        <DiffViewerModal
          resumeId={resumeId}
          checkpointA={null}
          checkpointB={null}
          onRestore={handleParentDiffRestore}
          onClose={() => setShowParentDiff(false)}
          parentLatex={parentDiffData.parent_latex}
          parentTitle={parentDiffData.parent_title}
          variantLatex={parentDiffData.variant_latex}
          variantTitle={parentDiffData.variant_title}
        />
      )}

      {/* Before/After optimization compare modal */}
      {compareData && (
        <CompareModal
          originalLatex={compareData.original}
          optimizedLatex={compareData.optimized}
          onClose={() => setCompareData(null)}
          onRestore={(latex) => {
            pushUndo('Before restore from compare')
            editorRef.current?.setValue(latex)
            setLatexContent(latex)
            setCompareData(null)
            toast.success('Original restored')
          }}
        />
      )}

      {/* ── TIMEOUT BANNER (compile stream) ── */}
      {compileStream.errorCode === 'compile_timeout' && compileStream.timeoutError && (
        <div className="flex shrink-0 items-center justify-between border-t border-orange-500/20 bg-orange-500/[0.08] px-3 py-1.5">
          <span className="text-[11px] text-orange-300">
            ⏱ Compile timed out — {compileStream.timeoutError.plan} plan limit (
            {compileStream.timeoutError.plan === 'free' ? '30s'
              : compileStream.timeoutError.plan === 'basic' ? '120s'
              : '240s'})
          </span>
          {flags.upgrade_ctas && (
            <a
              href="/billing"
              className="ml-3 shrink-0 text-[11px] font-medium text-orange-200 underline hover:text-orange-100"
            >
              Upgrade for longer timeouts →
            </a>
          )}
        </div>
      )}

      {/* ── Share modal ── */}
      {shareModalOpen && (
        <ShareResumeModal
          resumeId={resumeId}
          resumeTitle={title}
          initialShareToken={shareToken}
          initialShareUrl={shareUrl}
          onClose={() => setShareModalOpen(false)}
          onShareTokenChange={(token, url) => { setShareToken(token); setShareUrl(url) }}
        />
      )}

      {/* Keyboard shortcuts panel (Feature 61) */}
      <KeyboardShortcutsPanel isOpen={shortcutsOpen} onClose={() => setShortcutsOpen(false)} />

      {/* Compile settings modal (Feature 38) */}
      <CompileSettingsModal
        open={compileSettingsOpen}
        resumeId={resumeId}
        initial={compileSettings}
        onClose={() => setCompileSettingsOpen(false)}
        onSaved={(saved) => {
          setCompileSettings(saved)
          if (saved.compiler && saved.compiler !== compiler) {
            setCompiler(saved.compiler)
          }
        }}
      />

      {/* ── STATUS BAR ── */}
      <footer className="flex h-6 shrink-0 items-center justify-between border-t border-white/[0.05] bg-[#0a0a0a] px-3">
        <span
          className={`text-[10px] font-medium ${
            isAnyRunning
              ? 'text-violet-400'
              : compileStream.status === 'completed' || aiStream.status === 'completed'
              ? 'text-emerald-400/80'
              : aiStream.status === 'failed' || compileStream.status === 'failed'
              ? 'text-rose-400/80'
              : 'text-zinc-700'
          }`}
        >
          {statusText}
        </span>
        <div className="flex items-center gap-3">
          {aiStream.atsScore != null && (
            <span
              className={`flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[11px] font-bold tabular-nums ${
                aiStream.atsScore >= 80
                  ? 'bg-emerald-500/15 text-emerald-400 ring-1 ring-emerald-500/20'
                  : aiStream.atsScore >= 60
                  ? 'bg-amber-500/15 text-amber-400 ring-1 ring-amber-500/20'
                  : 'bg-rose-500/15 text-rose-400 ring-1 ring-rose-500/20'
              }`}
              title="ATS compatibility score from last AI optimization"
            >
              ATS {Math.round(aiStream.atsScore)}
            </span>
          )}
          {cursorLine && (
            <span className="text-[10px] tabular-nums text-zinc-700">
              Ln {cursorLine}
            </span>
          )}
          <span className="text-[10px] tabular-nums text-zinc-700">
            {latexContent.length.toLocaleString()} chars
          </span>
        </div>
      </footer>
    </div>
  )
}
