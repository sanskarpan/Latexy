'use client'

import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import { createPortal } from 'react-dom'
import dynamic from 'next/dynamic'
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
  Settings2,
  QrCode,
  Calendar,
  Users,
  Clock,
  Phone,
  DollarSign,
  SlidersHorizontal,
  Cloud,
  Code2,
  LayoutTemplate,
  TrendingUp,
  Keyboard,
  Pencil,
  GraduationCap,
  MoreHorizontal,
} from 'lucide-react'
import { Github } from '@/components/icons/brand-icons'
import { apiClient, type AcademicCVReport, type CheckpointEntry, type CompileSettings, type DiffWithParentResponse, type ExplainErrorResponse, type GitHubResumeStatus, type DropboxResumeStatus, type LatexCompiler, type PresenceUser, type ProofreadIssue, type ResumeResponse } from '@/lib/api-client'
import { downloadBlob } from '@/lib/download'
import { useRequireAuth } from '@/hooks/useRequireAuth'
import WritingAssistantWidget from '@/components/WritingAssistantWidget'
import { useJobStream, type JobStreamState } from '@/hooks/useJobStream'
import LaTeXEditor from '@/components/DeferredLaTeXEditor'
import type { LaTeXEditorRef } from '@/components/LaTeXEditor'
import LoadingSpinner from '@/components/LoadingSpinner'
import SessionLoadError from '@/components/SessionLoadError'
import BulletGeneratorWidget from '@/components/BulletGeneratorWidget'
import SummaryGeneratorWidget from '@/components/SummaryGeneratorWidget'
import QrCodeInserter from '@/components/QrCodeInserter'
import DateStandardizerPanel from '@/components/DateStandardizerPanel'
import AgeAnalysisPanel from '@/components/AgeAnalysisPanel'
import ContactFormatterPanel from '@/components/ContactFormatterPanel'
import SalaryEstimatorPanel from '@/components/SalaryEstimatorPanel'
import SectionReorderPanel from '@/components/SectionReorderPanel'
import WatermarkDownloadPopover from '@/components/WatermarkDownloadPopover'
import CompilerSelector from '@/components/CompilerSelector'
import TemplateCustomizerPanel from '@/components/TemplateCustomizerPanel'
import ImportProjectsModal from '@/components/ImportProjectsModal'
import type { TrackedChange } from '@/lib/yjs-track-changes'
import CollaboratorChat, { useCollaboratorChat } from '@/components/CollaboratorChat'
import type { ChatTransport } from '@/lib/collab-chat'
import { boundSuggestionPresence, canCreateSuggestion, canResolveSuggestion, createSuggestion, mergeSuggestionPresence, type Suggestion, type SuggestionDecision, type SuggestionPresence } from '@/lib/suggestions'
import { GitMerge } from 'lucide-react'
import { useAutoCompile } from '@/hooks/useAutoCompile'
import { usePreviewScheduler, recordPreviewFirstPaint, recordPreviewAction } from '@/hooks/usePreviewScheduler'
import { useArtifactPreview, useSourceHash } from '@/hooks/useArtifactPreview'
import type { ArtifactReadyEvent } from '@/lib/event-types'
import type { ResumeEngineDocument, ResumeEngineNode, ArtifactGeometry } from '@/lib/resume-engine-types'
import { previewErrorMessage } from '@/lib/preview-errors'
import { canExportArtifact } from '@/lib/artifact-policy'
import { editableGeometry } from '@/lib/artifact-geometry'
import ImportedOptimizationPanel from '@/components/ImportedOptimizationPanel'
import SemanticOptimizationPanel from '@/components/SemanticOptimizationPanel'
import ResumeFieldsEditor from '@/components/ResumeFieldsEditor'
import EngineCapabilityNotice from '@/components/EngineCapabilityNotice'
import { useEngineCapability } from '@/hooks/useEngineCapability'
import { engineEditorMode } from '@/lib/engine-capability'
import ResumeOriginalPdf from '@/components/ResumeOriginalPdf'
import { useQuickATSScore } from '@/hooks/useQuickATSScore'
import { buildATSCategories, type SimulatorIssueSignal } from '@/lib/ats-categories'
import ModeToggle from '@/components/theme/ModeToggle'
import ContrastToggle from '@/components/theme/ContrastToggle'
import ConfirmDialog from '@/components/ConfirmDialog'
import { useConfidenceScore } from '@/hooks/useConfidenceScore'
import { useLatexLinter } from '@/hooks/useLatexLinter'
import { useSpellCheck } from '@/hooks/useSpellCheck'
import { useFeatureFlags } from '@/contexts/FeatureFlagsContext'
import { usePushNotifications } from '@/hooks/usePushNotifications'
import MobileEditor from '@/components/MobileEditor'
import OfflineBanner, { useOnlineStatus } from '@/components/OfflineBanner'
import { saveDraft, getDraft, getPendingDrafts, deleteDraftIfUnchanged, pendingDraftCount } from '@/lib/offline-drafts'
import { clearAllOfflineCompiledPdfs, getOfflineCompiledPdf, getRememberedOfflinePdfOwner, OFFLINE_PDF_OWNER_KEY, rememberOfflinePdfOwner, saveOfflineCompiledPdf } from '@/lib/offline-pdfs'
import { enqueueCompile, getQueuedCompiles, dequeueCompile } from '@/lib/compile-queue'
import { acquireReconnectReservation, compileReconnectReservationKey, draftReconnectReservationKey } from '@/lib/reconnect-reservations'
import { canEditResume, type ResumeAccessRole } from '@/lib/resume-access'
import { buildLatexOutline, type LatexOutlineItem } from '@/lib/latex-outline'
import { visualFeedbackText } from '@/lib/visual-feedback'
import SourcePdfDivider, { type PdfSelectionLocation } from '@/components/SourcePdfDivider'
const ShareResumeModal = dynamic(() => import('@/components/ShareResumeModal'))
const DocumentAssistantPanel = dynamic(() => import('@/components/DocumentAssistantPanel'))
const LogViewer = dynamic(() => import('@/components/LogViewer'))
const PDFPreview = dynamic(() => import('@/components/PDFPreview'))
const DeepAnalysisPanel = dynamic(() => import('@/components/ats/DeepAnalysisPanel'))
const InterviewPrepPanel = dynamic(() => import('@/components/InterviewPrepPanel'))
const ExportDropdown = dynamic(() => import('@/components/ExportDropdown'))
const MultiFormatUpload = dynamic(() => import('@/components/MultiFormatUpload'))
const VersionHistoryPanel = dynamic(() => import('@/components/VersionHistoryPanel'))
const SaveCheckpointPopover = dynamic(() => import('@/components/SaveCheckpointPopover'))
const DiffViewerModal = dynamic(() => import('@/components/DiffViewerModal'))
const CompareModal = dynamic(() => import('@/components/CompareModal'))
const ErrorExplainerPanel = dynamic(() => import('@/components/ErrorExplainerPanel'))
const ReferencesPanel = dynamic(() => import('@/components/ReferencesPanel'))
const DesignPanel = dynamic(() => import('@/components/DesignPanel'))
const ProofreadPanel = dynamic(() => import('@/components/ProofreadPanel'))
const PackageManagerPanel = dynamic(() => import('@/components/PackageManagerPanel'))
const LinterPanel = dynamic(() => import('@/components/LinterPanel'))
const SymbolPalette = dynamic(() => import('@/components/SymbolPalette'))
const LatexGeneratorPanel = dynamic(() => import('@/components/LatexGeneratorPanel'))
const CompileSettingsModal = dynamic(() => import('@/components/CompileSettingsModal'))
const CollaboratorPanel = dynamic(() => import('@/components/CollaboratorPanel'))
const CommentsPanel = dynamic(() => import('@/components/CommentsPanel'))
const ReviewCommentsPanel = dynamic(() => import('@/components/ReviewCommentsPanel'))
const ChangesPanel = dynamic(() => import('@/components/ChangesPanel'))
const SuggestionsPanel = dynamic(() => import('@/components/SuggestionsPanel'))
const LaTeXDocPanel = dynamic(() => import('@/components/LaTeXDocPanel'))
const ConfidenceScorePanel = dynamic(() => import('@/components/ConfidenceScorePanel'))
const KeyboardShortcutsPanel = dynamic(() => import('@/components/KeyboardShortcutsPanel'))
const VisualResumeEditor = dynamic(() => import('@/components/VisualResumeEditor'))
const VisualChangeReviewModal = dynamic(() => import('@/components/VisualChangeReviewModal'))
const SnippetMarketplace = dynamic(() => import('@/components/SnippetMarketplace'))
const MacroLibraryPanel = dynamic(() => import('@/components/MacroLibraryPanel'))
const TikZEditor = dynamic(() => import('@/components/TikZEditor'))
const SlideViewer = dynamic(() => import('@/components/SlideViewer'))
const CompileErrorHistory = dynamic(() => import('@/components/CompileErrorHistory'))


type RightTab = 'preview' | 'ai' | 'logs' | 'history' | 'comments' | 'review' | 'chat' | 'references' | 'interview' | 'generate' | 'design' | 'proofread' | 'packages' | 'linter' | 'symbols' | 'changes' | 'suggestions' | 'docs' | 'layout' | 'snippets' | 'macros' | 'tikz'
type OptLevel = 'conservative' | 'balanced' | 'aggressive'
type AIModel = 'gpt-4o-mini' | 'gpt-4o'

// ─── Outline ────────────────────────────────────────────────────────────────

function OutlinePanel({
  latex,
  onJump,
}: {
  latex: string
  onJump: (line: number) => void
}) {
  const items = useMemo(() => buildLatexOutline(latex), [latex])

  if (items.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-2 py-8 px-4">
        <List size={18} className="text-fg-3" />
        <p className="text-[11px] text-fg-3 text-center">
          No sections found.<br />Add \section{} to your document.
        </p>
      </div>
    )
  }

  return (
    <nav className="overflow-y-auto py-1" aria-label="Document outline">
      {items.map((item, idx) => (
        <button
          key={`${item.command}:${item.line}:${idx}`}
          onClick={() => onJump(item.line)}
          aria-label={`${item.label}, line ${item.line}`}
          className="flex w-full items-baseline gap-1 px-2 py-1 text-left text-[11px] text-fg-3 transition hover:bg-surface-2 hover:text-fg"
          style={{ paddingLeft: `${8 + item.level * 10}px` }}
          title={`Line ${item.line}`}
        >
          <span className="shrink-0 text-fg-3" style={{ fontSize: 9 }}>
            {'─'.repeat(item.level > 0 ? 1 : 0)}
          </span>
          <span className="truncate">{item.label}</span>
        </button>
      ))}
    </nav>
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
        <div className="absolute left-4 right-4 top-3.5 h-px bg-line" />
        {STAGES.map((s, i) => {
          const done = i < current
          const active = i === current
          return (
            <div key={s.key} className="relative z-10 flex flex-col items-center gap-2">
              <div
                className={`flex h-7 w-7 items-center justify-center rounded-full border text-[10px] font-bold transition-all duration-300 ${
                  done
                    ? 'border-ok/40 bg-ok/15 text-ok'
                    : active
                    ? 'border-accent/50 bg-accent/20 text-accent-strong'
                    : 'border-line bg-surface-2 text-fg-3'
                }`}
              >
                {done ? <CheckCircle2 size={13} /> : <span>{i + 1}</span>}
              </div>
              <span
                className={`text-[10px] font-medium ${
                  done ? 'text-ok' : active ? 'text-accent-strong' : 'text-fg-3'
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
          <span className="text-fg-3 truncate">{message || 'Processing…'}</span>
          <span className="shrink-0 pl-2 tabular-nums text-fg-3">{percent}%</span>
        </div>
        <div className="h-[3px] w-full overflow-hidden rounded-full bg-surface-2">
          <div
            className="h-full rounded-full bg-accent transition-all duration-500"
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
      <label className="mb-2 block text-[10px] font-semibold uppercase tracking-[0.14em] text-fg-3">
        Optimization Level
      </label>
      <div className="grid grid-cols-3 gap-1 rounded-[var(--radius-lg)] border border-line bg-surface-2 p-1">
        {(['conservative', 'balanced', 'aggressive'] as OptLevel[]).map((level) => (
          <button
            key={level}
            onClick={() => onChange(level)}
            className={`rounded-[var(--radius-md)] py-2 text-[11px] font-medium capitalize transition ${
              value === level
                ? 'bg-accent/20 text-accent-strong ring-1 ring-accent/30'
                : 'text-fg-3 hover:text-fg-2'
            }`}
          >
            {level}
          </button>
        ))}
      </div>
      {!compact && (
        <p className="mt-1.5 text-[10px] text-fg-3">{descriptions[value]}</p>
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
      <label className="mb-2 block text-[10px] font-semibold uppercase tracking-[0.14em] text-fg-3">
        Model
      </label>
      <div className="grid grid-cols-2 gap-1 rounded-[var(--radius-lg)] border border-line bg-surface-2 p-1">
        {models.map((m) => (
          <button
            key={m.id}
            onClick={() => onChange(m.id)}
            className={`rounded-[var(--radius-md)] py-2 text-[11px] font-medium transition ${
              value === m.id
                ? 'bg-accent/20 text-accent-strong ring-1 ring-accent/30'
                : 'text-fg-3 hover:text-fg-2'
            }`}
          >
            {m.label}
          </button>
        ))}
      </div>
      {!compact && (
        <p className="mt-1.5 text-[10px] text-fg-3">
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
        <label className="text-[10px] font-semibold uppercase tracking-[0.14em] text-fg-3">
          Job Description
        </label>
        <span className="text-[10px] text-fg-3">optional</span>
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
        className="w-full resize-none rounded-[var(--radius-lg)] border border-line bg-surface-2 p-3 text-[12px] text-fg outline-none transition placeholder:text-fg-3 focus:border-accent"
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
  outline: LatexOutlineItem[]
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
        <label className="text-[10px] font-semibold uppercase tracking-[0.14em] text-fg-3">
          Sections
        </label>
        <button
          onClick={() => onChange([])}
          className="text-[10px] text-fg-3 transition hover:text-fg-2"
        >
          {allSelected ? 'all' : `${selected.length} selected`}
        </button>
      </div>
      <div className="max-h-32 overflow-y-auto rounded-[var(--radius-lg)] border border-line bg-surface-2 p-2 space-y-0.5">
        {outline.map((item) => {
          const checked = selected.length === 0 || selected.includes(item.label)
          return (
            <label
              key={item.label}
              className="flex cursor-pointer items-center gap-2 rounded-[var(--radius-md)] px-2 py-1 text-[11px] transition hover:bg-surface-2"
            >
              <input
                type="checkbox"
                checked={checked}
                onChange={() => toggle(item.label)}
                className="h-3 w-3 accent-[var(--accent)]"
              />
              <span
                className="truncate text-fg-2"
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
  visualOnly?: boolean
  aiStream: JobStreamState
  isRunning: boolean
  isSubmitting: boolean
  jobDescription: string
  setJobDescription: (v: string) => void
  optLevel: OptLevel
  setOptLevel: (v: OptLevel) => void
  onRun: () => void
  stagedLatex: string | null
  onApply: () => void
  onDiscard: () => void
  onReview: () => void
  onApplyAnyway: () => void
  outline: LatexOutlineItem[]
  targetSections: string[]
  setTargetSections: (v: string[]) => void
  customInstructions: string
  setCustomInstructions: (v: string) => void
  onOpenDeepAnalysis: () => void
  model: AIModel
  setModel: (v: AIModel) => void
}

function AIPanel({
  visualOnly = false,
  aiStream,
  isRunning,
  isSubmitting,
  jobDescription,
  setJobDescription,
  optLevel,
  setOptLevel,
  onRun,
  stagedLatex,
  onApply,
  onDiscard,
  onReview,
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
              <div className="flex h-5 w-5 items-center justify-center rounded-full bg-accent/20">
                <Sparkles size={11} className="animate-pulse text-accent-strong" />
              </div>
              <span className="text-xs font-semibold text-fg-2">AI is working…</span>
            </div>
            <AIStagePipeline
              stage={aiStream.stage}
              percent={aiStream.percent}
              message={visualOnly ? 'Improving your résumé and preparing a preview…' : aiStream.message}
            />
          </div>
          {aiStream.streamingLatex && (
            <div className="flex items-center gap-2 rounded-[var(--radius-md)] border border-accent/20 bg-accent/5 px-3 py-2 text-[11px] text-accent-strong">
              <Sparkles size={11} />
              <span>Preparing a review candidate…</span>
            </div>
          )}
        </div>
      )}

      {isDone && (
        <div className="space-y-4 p-4">
          <div className="flex items-center gap-3 rounded-[var(--radius-lg)] border border-ok/20 bg-ok/10 p-3">
            <CheckCircle2 size={16} className="shrink-0 text-ok" />
            <div className="min-w-0">
              <p className="text-sm font-semibold text-ok">Optimization ready to review</p>
              <p className="truncate text-[10px] text-fg-3">
                {aiStream.changesMade?.length ?? 0} changes ·{' '}
                {visualOnly ? 'Ready for your review' : aiStream.tokensUsed ? `${aiStream.tokensUsed.toLocaleString()} tokens` : 'PDF ready'}
              </p>
            </div>
          </div>

          {stagedLatex && (
            <div className="space-y-2 rounded-[var(--radius-lg)] border border-accent/25 bg-accent/10 p-3">
              <p className="text-[11px] text-fg-2">
                Your editor is unchanged. Review the candidate, then apply or discard it.
              </p>
              <button
                onClick={onReview}
                className="w-full rounded-[var(--radius-md)] border border-line-2 py-2 text-[11px] font-semibold text-fg-2 transition hover:bg-surface-2"
              >
                Review changes
              </button>
              <div className="grid grid-cols-2 gap-2">
                <button
                  onClick={onDiscard}
                  className="rounded-[var(--radius-md)] border border-line-2 py-2 text-[11px] font-semibold text-fg-2 transition hover:bg-surface-2"
                >
                  Discard
                </button>
                <button
                  onClick={onApply}
                  className="rounded-[var(--radius-md)] bg-accent py-2 text-[11px] font-semibold text-accent-fg transition hover:brightness-110"
                >
                  Apply optimization
                </button>
              </div>
            </div>
          )}

          {aiStream.atsScore != null && (
            <div className="flex items-center gap-4 rounded-[var(--radius-lg)] border border-line bg-surface-2 p-4">
              <div className="relative shrink-0">
                <svg className="h-[68px] w-[68px] -rotate-90" viewBox="0 0 36 36">
                  <circle cx="18" cy="18" r="15.9" fill="none" stroke="var(--line)" strokeWidth="3" />
                  <circle
                    cx="18" cy="18" r="15.9" fill="none"
                    stroke={aiStream.atsScore >= 80 ? 'var(--ok)' : aiStream.atsScore >= 60 ? 'var(--warn)' : 'var(--err)'}
                    strokeWidth="3"
                    strokeDasharray={`${aiStream.atsScore} ${100 - aiStream.atsScore}`}
                    strokeLinecap="round"
                  />
                </svg>
                <span
                  className={`absolute inset-0 flex items-center justify-center text-base font-bold ${
                    aiStream.atsScore >= 80 ? 'text-ok' : aiStream.atsScore >= 60 ? 'text-warn' : 'text-err'
                  }`}
                >
                  {Math.round(aiStream.atsScore)}
                </span>
              </div>
              <div>
                <p className="text-sm font-semibold text-fg">ATS Score</p>
                <p className="mt-0.5 text-[11px] leading-relaxed text-fg-3">
                  {aiStream.atsScore >= 80
                    ? 'Excellent — highly compatible'
                    : aiStream.atsScore >= 60
                    ? 'Good — minor improvements possible'
                    : 'Needs improvement'}
                </p>
                {aiStream.atsDetails?.recommendations?.[0] && (
                  <p className="mt-1 text-[10px] italic text-fg-3">
                    {visualOnly ? visualFeedbackText(aiStream.atsDetails.recommendations[0]) : aiStream.atsDetails.recommendations[0]}
                  </p>
                )}
              </div>
            </div>
          )}

          <button
            onClick={onRun}
            disabled={isSubmitting}
            className="flex w-full items-center justify-center gap-1.5 rounded-[var(--radius-lg)] bg-accent/20 py-2.5 text-xs font-semibold text-accent-strong ring-1 ring-accent/20 transition hover:bg-accent/25"
          >
            <Sparkles size={12} /> Run again
          </button>

          <button
            onClick={onOpenDeepAnalysis}
            className="flex w-full items-center justify-center gap-2 rounded-[var(--radius-lg)] border border-accent/20 bg-accent/10 py-2.5 text-xs font-semibold text-accent-strong transition hover:bg-accent/20"
          >
            <Brain size={12} /> Deep AI Analysis
          </button>

          <div className="border-t border-line" />
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-fg-3">
            Settings for next run
          </p>
          <LevelSelector value={optLevel} onChange={setOptLevel} compact />
          <ModelSelector value={model} onChange={setModel} compact />
          <JDInput value={jobDescription} onChange={setJobDescription} compact />
        </div>
      )}

      {isFailed && (
        <div className="space-y-4 p-4">
          <div className="flex items-start gap-3 rounded-[var(--radius-lg)] border border-err/20 bg-err/10 p-3">
            <AlertCircle size={15} className="mt-0.5 shrink-0 text-err" />
            <div>
              <p className="text-sm font-semibold text-err">Optimization failed</p>
              <p className="mt-0.5 text-[11px] text-fg-3">{visualOnly ? 'Your draft is preserved. Please try again.' : aiStream.error || 'An error occurred'}</p>
            </div>
          </div>

          {/* Timeout upgrade CTA */}
          {aiStream.errorCode === 'compile_timeout' && (
            <div className="flex items-center justify-between rounded-[var(--radius-lg)] border border-accent/20 bg-accent/10 px-3 py-2.5">
              <span className="text-[11px] text-accent-strong">
                ⏱ {aiStream.timeoutError?.plan ?? 'free'} plan limit reached (
                {aiStream.timeoutError?.seconds ?? 30}s)
              </span>
              {flags.upgrade_ctas && (
                <a
                  href="/billing"
                  className="ml-3 shrink-0 text-[11px] font-medium text-accent-strong underline hover:text-accent-strong"
                >
                  Upgrade →
                </a>
              )}
            </div>
          )}

          {/* Fix 3: Apply anyway when LLM succeeded but compile failed */}
          {aiStream.streamingLatex && (
            <div className="rounded-[var(--radius-lg)] border border-warn/20 bg-warn/10 p-3">
              <div className="flex items-center gap-2 mb-2">
                <AlertTriangle size={13} className="text-warn" />
                <p className="text-[11px] font-semibold text-warn">AI rewrite is available</p>
              </div>
              <p className="text-[10px] text-fg-3 mb-3">
                {visualOnly ? 'The rewrite is available, but its preview could not be prepared. You can keep the current draft or try the candidate and update the preview again.' : 'The LaTeX rewrite completed but failed to compile. You can apply it to the editor and fix the errors manually.'}
              </p>
              <button
                onClick={onApplyAnyway}
                className="w-full rounded-[var(--radius-md)] border border-warn/30 bg-warn/10 py-2 text-[11px] font-semibold text-warn transition hover:bg-warn/20"
              >
                Apply optimized LaTeX anyway
              </button>
            </div>
          )}

          <button
            onClick={onRun}
            className="flex w-full items-center justify-center gap-2 rounded-[var(--radius-lg)] bg-accent/20 py-2.5 text-sm font-semibold text-accent-strong ring-1 ring-accent/20 transition hover:bg-accent/25"
          >
            <Sparkles size={13} /> Try again
          </button>
        </div>
      )}

      {isIdle && (
        <div className="space-y-5 p-4">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-[var(--radius-lg)] bg-accent-soft ring-1 ring-accent/20">
              <Sparkles size={16} className="text-accent-strong" />
            </div>
            <div>
              <p className="text-sm font-semibold text-fg">AI Optimization</p>
              <p className="text-[10px] text-fg-3">GPT-4o · Optimize + Compile + Score</p>
            </div>
          </div>

          <p className="text-[12px] leading-relaxed text-fg-3">
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
              className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-fg-3 transition hover:text-fg-2"
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
                className="mt-2 w-full resize-none rounded-[var(--radius-lg)] border border-line bg-surface-2 p-3 text-[12px] text-fg outline-none transition placeholder:text-fg-3 focus:border-accent"
              />
            )}
          </div>

          <button
            onClick={onRun}
            disabled={isSubmitting}
            className="flex w-full items-center justify-center gap-2 rounded-[var(--radius-lg)] bg-accent py-3 text-sm font-semibold text-accent-fg shadow-[var(--shadow-2)] ring-1 ring-accent/20 transition hover:brightness-110 disabled:opacity-50"
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
  const { session: sessionData, isPending: sessionLoading, error: sessionError } = useRequireAuth()
  const sessionUserId = sessionData?.user?.id ?? null
  const dictionaryScope = {
    ownerId: sessionUserId,
    authToken: sessionData?.session?.token ?? null,
    // useRequireAuth preserves a known owner during transient refresh/error.
    confirmed: sessionUserId !== null || (!sessionLoading && !sessionError),
  }

  // Core state
  const [title, setTitle] = useState('')
  const [latexContent, setLatexContent] = useState('')
  const sourceAtRenderRef = useRef(latexContent)
  sourceAtRenderRef.current = latexContent
  const [bibliographyBibTeX, setBibliographyBibTeX] = useState('')
  const [isLoading, setIsLoading] = useState(true)
  const [resumeLoadError, setResumeLoadError] = useState<string | null>(null)
  const [offlineDraftLoaded, setOfflineDraftLoaded] = useState(false)
  const [offlinePdfLoaded, setOfflinePdfLoaded] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  // Unsaved-changes guard: last-persisted snapshot + autosave status
  const [savedSnapshot, setSavedSnapshot] = useState<{ title: string; latex: string }>({ title: '', latex: '' })
  const [autoSaving, setAutoSaving] = useState(false)
  const [lastSavedAt, setLastSavedAt] = useState<number | null>(null)
  const isDirtyRef = useRef(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [compileJobId, setCompileJobId] = useState<string | null>(null)
  const [lastStartedJobKind, setLastStartedJobKind] = useState<'compile' | 'ai'>('compile')
  const userInitiatedJobRef = useRef(false)
  const [isAutoFitSubmitting, setIsAutoFitSubmitting] = useState(false)
  const [autoFitIntensity, setAutoFitIntensity] = useState(50)
  const autoFitJobRef = useRef<string | null>(null)
  const handledAutoFitJobRef = useRef<string | null>(null)
  const autoFitIdentityRef = useRef<{ ownerId: string | null; resumeId: string; generation: number } | null>(null)
  const autoFitBaselineRef = useRef<string | null>(null)
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  // The job whose successfully downloaded blob is currently rendered. This is
  // intentionally separate from activePdfJobId, which is the in-flight fetch
  // de-duplication marker.
  const [renderedPdfJobId, setRenderedPdfJobId] = useState<string | null>(null)
  const [displayedArtifact, setDisplayedArtifact] = useState<ArtifactReadyEvent | null>(null)
  const [isOfflinePdf, setIsOfflinePdf] = useState(false)
  const [offlinePdfError, setOfflinePdfError] = useState<string | null>(null)
  const [documentType, setDocumentType] = useState<string>('resume')
  const [showImportModal, setShowImportModal] = useState(false)
  const [qrInserterOpen, setQrInserterOpen] = useState(false)
  const [dateStandardizerOpen, setDateStandardizerOpen] = useState(false)
  const [ageAnalysisOpen, setAgeAnalysisOpen] = useState(false)
  const [contactFormatterOpen, setContactFormatterOpen] = useState(false)
  const [salaryEstimatorOpen, setSalaryEstimatorOpen] = useState(false)
  const [sectionReorderOpen, setSectionReorderOpen] = useState(false)
  const [importModalOpen, setImportModalOpen] = useState(false)
  const [showErrorHistory, setShowErrorHistory] = useState(false)
  const [docCommand, setDocCommand] = useState<string | undefined>(undefined)

  // Priority queue badge (Feature 34)
  const [userPlan, setUserPlan] = useState<string>('free')

  // Layout
  const [rightTab, setRightTab] = useState<RightTab>('preview')
  const rightTabBarRef = useRef<HTMLDivElement>(null)
  const activeRightTabRef = useRef<HTMLButtonElement>(null)
  // Keep the active right-panel tab scrolled into view within the horizontal scroller
  useEffect(() => {
    activeRightTabRef.current?.scrollIntoView({ block: 'nearest', inline: 'nearest' })
  }, [rightTab])
  const [rightWidth, setRightWidth] = useState<number | null>(null)
  const [rightMaxWidth, setRightMaxWidth] = useState(980)
  const [showOutline, setShowOutline] = useState(false)
  const [isDraggingResize, setIsDraggingResize] = useState(false)
  const isResizingRef = useRef(false)
  const resizeStartX = useRef(0)
  const resizeStartWidth = useRef(0)

  // AI
  const [aiJobId, setAiJobId] = useState<string | null>(null)
  const [semanticRunId, setSemanticRunId] = useState<string | null>(null)
  const [jobDescription, setJobDescription] = useState('')
  const [optLevel, setOptLevel] = useState<OptLevel>('balanced')
  const [model, setModel] = useState<AIModel>('gpt-4o-mini')
  const [isAiSubmitting, setIsAiSubmitting] = useState(false)
  const [stagedAiLatex, setStagedAiLatex] = useState<string | null>(null)
  const aiBaselineRef = useRef<string | null>(null)
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
  // Whether the currently in-flight/active compile job was triggered by
  // auto-compile rather than a manual Compile click — so a failed auto-compile
  // gets the same failure toast a manual compile's submit-catch already gives
  // it, without spamming a toast on every debounce tick for the same error.
  const autoCompileTriggeredRef = useRef(false)
  const lastAutoCompileErrorRef = useRef<string | null>(null)

  // SyncTeX
  const [syncFromLine, setSyncFromLine] = useState<number | null>(null)
  const [syncFromRequestId, setSyncFromRequestId] = useState(0)
  const [cursorLine, setCursorLine] = useState<number | null>(null)
  const [sourceSyncLine, setSourceSyncLine] = useState<number | null>(null)
  const [sourceSyncRequestId, setSourceSyncRequestId] = useState(0)
  const [pdfSelection, setPdfSelection] = useState<PdfSelectionLocation | null>(null)
  const [pdfSyncReady, setPdfSyncReady] = useState(false)

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
  const {
    issues: spellCheckIssues,
    loading: spellCheckLoading,
    getPersonalDictionary,
    addWordToDictionary,
  } = useSpellCheck(
    latexContent,
    spellCheckEnabled,
    'en-US',
    5000,
    dictionaryScope,
  )

  // Deep analysis (Layer 2)
  const [deepPanelOpen, setDeepPanelOpen] = useState(false)
  // Textkernel simulator findings for the multi-dimensional score card (#1367).
  // Fetched lazily when the panel opens (the strictest parser profile surfaces
  // the most structural issues; the universal quality checks run for any profile).
  const [simIssues, setSimIssues] = useState<SimulatorIssueSignal[]>([])
  const [deepAnalysisJobId, setDeepAnalysisJobId] = useState<string | null>(null)
  const [deepAnalysisUsesRemaining, setDeepAnalysisUsesRemaining] = useState<number | null>(null)
  const [isDeepRunning, setIsDeepRunning] = useState(false)
  const [deepAnalysisError, setDeepAnalysisError] = useState<string | null>(null)

  // Variant awareness
  const [parentResumeId, setParentResumeId] = useState<string | null>(null)
  const [parentTitle, setParentTitle] = useState<string | null>(null)
  const [isLinkedVariant, setIsLinkedVariant] = useState(false)
  const [linkedEditEnabled, setLinkedEditEnabled] = useState(false)
  const [parentDiffData, setParentDiffData] = useState<DiffWithParentResponse | null>(null)
  const [showParentDiff, setShowParentDiff] = useState(false)
  const [forkPopoverOpen, setForkPopoverOpen] = useState(false)
  const [forkTitleInput, setForkTitleInput] = useState('')
  const [isForkingResume, setIsForkingResume] = useState(false)
  const forkTriggerRef = useRef<HTMLButtonElement>(null)
  const [forkPopoverPos, setForkPopoverPos] = useState<{ top: number; right: number } | null>(null)
  const openForkPopover = useCallback(() => {
    const rect = forkTriggerRef.current?.getBoundingClientRect()
    if (rect) {
      setForkPopoverPos({
        top: rect.bottom + 6,
        right: Math.max(12, window.innerWidth - rect.right),
      })
    }
    setForkTitleInput(`${title} — Variant`)
    setForkPopoverOpen(true)
  }, [title])
  // Toolbar "Tools" overflow menu + right-panel "More" tab menu (Finding: flat toolbar hierarchy)
  const [toolsMenuOpen, setToolsMenuOpen] = useState(false)
  const [toolsMenuPos, setToolsMenuPos] = useState<{ top: number; right: number } | null>(null)
  const toolsTriggerRef = useRef<HTMLButtonElement>(null)
  const openToolsMenu = useCallback(() => {
    const rect = toolsTriggerRef.current?.getBoundingClientRect()
    if (rect) setToolsMenuPos({ top: rect.bottom + 6, right: Math.max(12, window.innerWidth - rect.right) })
    setToolsMenuOpen(true)
  }, [])
  const [moreTabsOpen, setMoreTabsOpen] = useState(false)
  const [moreTabsPos, setMoreTabsPos] = useState<{ top: number; right: number } | null>(null)
  const moreTabsTriggerRef = useRef<HTMLButtonElement>(null)
  const [academicReport, setAcademicReport] = useState<AcademicCVReport | null>(null)
  const [academicConvertOpen, setAcademicConvertOpen] = useState(false)
  const [academicTargetIndustry, setAcademicTargetIndustry] = useState<'tech' | 'data_science' | 'finance' | 'consulting' | 'product' | 'other'>('tech')
  const [academicRoleDescription, setAcademicRoleDescription] = useState('')
  const [isAcademicConverting, setIsAcademicConverting] = useState(false)

  // Error explainer
  const [explainerOpen, setExplainerOpen] = useState(false)
  const [explainerLoading, setExplainerLoading] = useState(false)
  const [explainerData, setExplainerData] = useState<ExplainErrorResponse | null>(null)
  const [explainerLine, setExplainerLine] = useState<number | null>(null)

  // Writing assistant
  const [writingOpen, setWritingOpen] = useState(false)
  const [documentAssistantOpen, setDocumentAssistantOpen] = useState(false)
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
  const [shareAnonymous, setShareAnonymous] = useState(false)
  const [shareReviewComments, setShareReviewComments] = useState(false)

  // Keyboard shortcuts panel (Feature 61)
  const [shortcutsOpen, setShortcutsOpen] = useState(false)

  // Push notifications (Feature 65)
  const { requestPermission, notify } = usePushNotifications()

  // GitHub sync (Feature 37)
  const [ghConnected, setGhConnected] = useState(false)
  const [ghSyncEnabled, setGhSyncEnabled] = useState(false)
  const [ghPushing, setGhPushing] = useState(false)
  // Themed confirmation for the destructive GitHub/Dropbox "pull" (overwrites the buffer).
  const [confirmPull, setConfirmPull] = useState<null | 'github' | 'dropbox'>(null)
  const [ghTogglingSync, setGhTogglingSync] = useState(false)

  // Dropbox sync (Feature 77)
  const [dbxConnected, setDbxConnected] = useState(false)
  const [dbxSyncEnabled, setDbxSyncEnabled] = useState(false)
  const [dbxSyncing, setDbxSyncing] = useState(false)
  const [dbxTogglingSync, setDbxTogglingSync] = useState(false)

  // Resume mode uses the versioned engine; legacy Visual is a source-preserving projection.
  const engineCapability = useEngineCapability(sessionUserId ?? 'signed-out')
  const engineSupported = engineCapability.status === 'supported'
  const [preferredEditorMode, setEditorMode] = useState<'source' | 'wysiwyg' | 'pdf'>('pdf')
  const editorMode = engineEditorMode(preferredEditorMode, engineCapability.status, engineCapability.sourceFallback)
  const visualPanels: RightTab[] = ['preview', 'ai', 'comments', 'interview', 'layout']
  const visibleRightTab = (editorMode === 'pdf' && !['preview', 'ai', 'comments', 'interview'].includes(rightTab))
    || (editorMode === 'wysiwyg' && !visualPanels.includes(rightTab)) ? 'preview' : rightTab
  useEffect(() => {
    if (visibleRightTab !== rightTab) setRightTab(visibleRightTab)
  }, [visibleRightTab, rightTab])
  useEffect(() => {
    if (!sessionUserId) return
    try { setSemanticRunId(localStorage.getItem(`latexy_semantic_run:${sessionUserId}:${resumeId}`)) } catch {}
  }, [sessionUserId, resumeId])

  useEffect(() => {
    try {
      const saved = localStorage.getItem(`latexy_editor_mode_${resumeId}`)
      setEditorMode(saved === 'source' || saved === 'wysiwyg' ? saved : 'pdf')
    } catch { /* Browser preferences are optional. */ }
  }, [resumeId])
  const [engineDocument, setEngineDocument] = useState<ResumeEngineDocument | null>(null)
  const engineDocumentIdentityRef = useRef<string | null>(null)
  const [engineGeometry, setEngineGeometry] = useState<ArtifactGeometry | null>(null)
  const [selectedEngineNode, setSelectedEngineNode] = useState<string | null>(null)
  const [engineDocumentError, setEngineDocumentError] = useState<string | null>(null)


  // PWA / offline (Feature 79)
  const isOnline = useOnlineStatus()
  const [rememberedOfflineOwner, setRememberedOfflineOwner] = useState<string | null>(() => getRememberedOfflinePdfOwner())
  const offlinePdfOwnerId = sessionUserId ?? rememberedOfflineOwner
  const [isMobile, setIsMobile] = useState(false)
  const [offlinePendingCount, setOfflinePendingCount] = useState(0)

  // Collaboration (Feature 40)
  const [collabOpen, setCollabOpen] = useState(false)
  const [collabIsOwner, setCollabIsOwner] = useState(true)
  const [collabRole, setCollabRole] = useState<ResumeAccessRole>('owner')
  const [presenceUsers, setPresenceUsers] = useState<import('@/lib/api-client').PresenceUser[]>([])
  const [chatTransport, setChatTransport] = useState<ChatTransport | null>(null)
  const collaboratorChat = useCollaboratorChat({
    roomKey: resumeId,
    authKey: sessionUserId ?? '',
    transport: chatTransport,
    canChat: !!sessionData?.session?.token,
  })
  const collabCanEdit = canEditResume(collabRole)
  const canEditDocument = collabCanEdit && (!isLinkedVariant || linkedEditEnabled)

  // Track Changes (Feature 41)
  const [trackedChanges, setTrackedChanges] = useState<TrackedChange[]>([])
  const [suggestions, setSuggestions] = useState<Suggestion[]>([])
  const [remoteSuggestionPeers, setRemoteSuggestionPeers] = useState<SuggestionPresence[]>([])
  const [suggestionDecisions, setSuggestionDecisions] = useState<SuggestionDecision[]>([])
  const [suggestionMode, setSuggestionMode] = useState(false)
  const [suggestionError, setSuggestionError] = useState<string | null>(null)
  const lastSuggestionDraftRef = useRef<{ findText: string; replacementText: string } | null>(null)
  const lastSuggestionActionRef = useRef<{ kind: 'accept' | 'reject'; id: string } | null>(null)

  const searchParams = useSearchParams()
  // Mention email deep links should open the Comments panel so the highlighted
  // comment is reachable immediately, even though Comments lives under More.
  useEffect(() => {
    if (searchParams.get('comment_id')) setRightTab('comments')
  }, [searchParams])
  const activePdfJobId = useRef<string | null>(null)
  const editorRef = useRef<LaTeXEditorRef>(null)
  const [macroEditor, setMacroEditor] = useState<import('monaco-editor').editor.IStandaloneCodeEditor | null>(null)
  const deepAnalysisSubmissionRef = useRef<{ ownerId: string | null; resumeId: string; generation: number } | null>(null)
  const pdfUrlRef = useRef<string | null>(null)
  const offlinePdfBlobRef = useRef<Blob | null>(null)
  const pendingOfflinePdfSaveRef = useRef<{ blob: Blob; ownerId: string; resumeId: string; generation: number } | null>(null)
  const offlinePdfMountedRef = useRef(false)
  const offlinePdfRenderIdentityRef = useRef<{ ownerId: string | null; resumeId: string }>({ ownerId: offlinePdfOwnerId, resumeId })
  const offlinePdfIdentityRef = useRef<{ ownerId: string | null; resumeId: string; generation: number }>({ ownerId: null, resumeId, generation: 0 })
  offlinePdfRenderIdentityRef.current = { ownerId: offlinePdfOwnerId, resumeId }

  const isCurrentOfflinePdfIdentity = useCallback((ownerId: string | null, routeResumeId: string, generation: number) => (
    offlinePdfMountedRef.current &&
    offlinePdfRenderIdentityRef.current.ownerId === ownerId &&
    offlinePdfRenderIdentityRef.current.resumeId === routeResumeId &&
    offlinePdfIdentityRef.current.ownerId === ownerId &&
    offlinePdfIdentityRef.current.resumeId === routeResumeId &&
    offlinePdfIdentityRef.current.generation === generation
  ), [])

  useEffect(() => {
    offlinePdfMountedRef.current = true
    return () => {
      offlinePdfMountedRef.current = false
      offlinePdfIdentityRef.current.generation += 1
    }
  }, [])

  useEffect(() => {
    const previous = offlinePdfIdentityRef.current
    const changed = previous.ownerId !== offlinePdfOwnerId || previous.resumeId !== resumeId
    const generation = previous.generation + 1
    offlinePdfIdentityRef.current = { ownerId: offlinePdfOwnerId, resumeId, generation }
    if (previous.ownerId !== offlinePdfOwnerId) {
      setGhConnected(false)
      setDbxConnected(false)
      setUserPlan('free')
      setGhTogglingSync(false)
      setGhPushing(false)
      setDbxTogglingSync(false)
      setDbxSyncing(false)
    }
    if (changed && previous.ownerId !== null) {
      if (pdfUrlRef.current) URL.revokeObjectURL(pdfUrlRef.current)
      pdfUrlRef.current = null
      offlinePdfBlobRef.current = null
      setPdfUrl(null)
      setRenderedPdfJobId(null)
      setDisplayedArtifact(null)
      setIsOfflinePdf(false)
      setOfflinePdfLoaded(false)
    }
    if (changed) {
      setShareModalOpen(false)
      setShareToken(null)
      setShareUrl(null)
      setShareAnonymous(false)
      setShareReviewComments(false)
      setCompileJobId(null)
      setAiJobId(null)
      setSemanticRunId(null)
      setIsSubmitting(false)
      setIsAiSubmitting(false)
      setIsAutoFitSubmitting(false)
      setDeepAnalysisJobId(null)
      setDeepAnalysisUsesRemaining(null)
      setIsDeepRunning(false)
      setDeepAnalysisError(null)
      setDeepPanelOpen(false)
      deepAnalysisSubmissionRef.current = null
      userInitiatedJobRef.current = false
      setStagedAiLatex(null)
      setCompareData(null)
      aiBaselineRef.current = null
      autoCompileTriggeredRef.current = false
      activePdfJobId.current = null
      autoFitJobRef.current = null
      handledAutoFitJobRef.current = null
      autoFitIdentityRef.current = null
      autoFitBaselineRef.current = null
    }
    const pending = pendingOfflinePdfSaveRef.current
    if (pending && (pending.ownerId !== offlinePdfOwnerId || pending.resumeId !== resumeId)) {
      pendingOfflinePdfSaveRef.current = null
    }
  }, [offlinePdfOwnerId, resumeId])

  const autoCompileIdentityReady = Boolean(
    dictionaryScope.confirmed &&
    offlinePdfOwnerId &&
    offlinePdfMountedRef.current &&
    offlinePdfIdentityRef.current.ownerId === offlinePdfOwnerId &&
    offlinePdfIdentityRef.current.resumeId === resumeId,
  )

  useEffect(() => {
    const handleStorage = (event: StorageEvent) => {
      if (event.key === OFFLINE_PDF_OWNER_KEY || event.key === null) {
        setRememberedOfflineOwner(getRememberedOfflinePdfOwner())
      }
    }
    window.addEventListener('storage', handleStorage)
    return () => window.removeEventListener('storage', handleStorage)
  }, [])

  // Only server-confirmed local decisions affect status. The Y.Map is a live
  // notification transport, not an authorization or decision source; trusting
  // peer-written accepted values would let any document editor forge outcomes.
  const allSuggestions = useMemo(() => mergeSuggestionPresence(suggestions, remoteSuggestionPeers, suggestionDecisions), [remoteSuggestionPeers, suggestionDecisions, suggestions])
  const suggestionPresence = useMemo<SuggestionPresence>(() => boundSuggestionPresence({
    items: suggestions.filter((item) => item.status === 'pending').slice(0, 50),
    // Proposals are awareness-only; resolver decisions come from the server
    // and are mirrored through the Y.Map only as a live UI notification.
    decisions: [],
  }), [suggestions])

  const handleRemoteSuggestionPresence = useCallback((peers: SuggestionPresence[]) => {
    setRemoteSuggestionPeers(peers)
  }, [])

  const confirmRemoteSuggestionDecisions = useCallback((decisions: SuggestionDecision[]) => {
    // Y.Map values are only hints. Confirm each one through the authenticated
    // REST authority before allowing it to hide a pending proposal.
    for (const candidate of decisions) {
      void apiClient.getSuggestionDecision(resumeId, candidate.id)
        .then((confirmed) => {
          setSuggestionDecisions((current) => current.some((item) => item.id === confirmed.suggestion_id)
            ? current
            : [...current, {
              id: confirmed.suggestion_id,
              status: confirmed.status,
              decidedByRole: confirmed.decided_by_role,
              decidedAt: Date.parse(confirmed.decided_at),
            }])
        })
        .catch(() => {
          // Stale/forged notifications have no effect on suggestion state.
        })
    }
  }, [resumeId])

  const canSuggest = canCreateSuggestion(collabRole)
  const handleCreateSuggestion = useCallback((findText: string, replacementText: string) => {
    if (!canSuggest) {
      setSuggestionError('Viewers cannot create suggestions.')
      return
    }
    lastSuggestionDraftRef.current = { findText, replacementText }
    const source = editorRef.current?.getValue() ?? latexContent
    const suggestion = createSuggestion({
      source,
      findText,
      replacementText,
      authorId: sessionUserId ?? 'current-user',
      authorName: sessionData?.user?.name || sessionData?.user?.email || 'You',
    })
    if (!suggestion) {
      setSuggestionError('That text is not present in the current document. Edit the text or retry.')
      return
    }
    setSuggestions((current) => [...current, suggestion])
    setSuggestionError(null)
  }, [canSuggest, latexContent, sessionData?.user?.email, sessionData?.user?.name, sessionUserId])

  const handleAcceptSuggestion = useCallback(async (id: string) => {
    if (!canResolveSuggestion(collabRole) || !canEditDocument) {
      setSuggestionError('Only owners and editors can accept suggestions.')
      return
    }
    const suggestion = allSuggestions.find((item) => item.id === id && item.status === 'pending')
    if (!suggestion) return
    const source = editorRef.current?.getValue() ?? latexContent
    lastSuggestionActionRef.current = { kind: 'accept', id }
    try {
      const result = await apiClient.decideSuggestion(resumeId, {
        suggestion_id: id,
        status: 'accepted',
        expected_content: source,
        original_text: suggestion.originalText,
        replacement_text: suggestion.replacementText,
        prefix: suggestion.prefix,
        suffix: suggestion.suffix,
      })
      const decision = { id, status: result.status, decidedByRole: result.decided_by_role, decidedAt: Date.parse(result.decided_at) }
      if (result.status !== 'accepted') {
        setSuggestions((current) => current.map((item) => item.id === id ? { ...item, status: result.status, conflictReason: 'Another decision already won for this suggestion.' } : item))
        setSuggestionDecisions((current) => [...current, decision])
        lastSuggestionActionRef.current = null
        return
      }
      // The server already committed this exact source. Apply it once to the
      // local Y.Text only if no collaborative edit arrived while the request
      // was in flight; never overwrite newer local content.
      const applied = editorRef.current?.applySuggestionResult(source, result.latex_content) ?? false
      if (!applied) {
        setSuggestionError('The suggestion was accepted on the server, but this editor changed concurrently. Reload to reconcile it safely.')
        setSuggestions((current) => current.map((item) => item.id === id ? { ...item, status: 'accepted' } : item))
        setSuggestionDecisions((current) => [...current, decision])
        return
      }
      setSuggestions((current) => current.map((item) => item.id === id ? { ...item, status: 'accepted' } : item))
      setSuggestionDecisions((current) => [...current, decision])
      // The authoritative result is now the CAS baseline for subsequent
      // autosaves. Without this update, the next debounced save could send
      // the pre-suggestion source and overwrite the accepted document.
      setLatexContent(result.latex_content)
      setSavedSnapshot({ title, latex: result.latex_content })
      setLastSavedAt(Date.now())
      setSuggestionError(null)
      lastSuggestionActionRef.current = null
    } catch (error) {
      // CAS conflicts and transport failures leave the awareness proposal
      // pending so the user can retry against the latest source.
      setSuggestionError(error instanceof Error ? error.message : 'Could not decide this suggestion. It remains pending.')
    }
  }, [allSuggestions, canEditDocument, collabRole, latexContent, resumeId, title])

  const handleRejectSuggestion = useCallback(async (id: string) => {
    const suggestion = allSuggestions.find((item) => item.id === id && item.status === 'pending')
    if (!suggestion) return
    const canWithdrawOwn = suggestion?.authorId === sessionUserId
    if ((!canResolveSuggestion(collabRole) || !canEditDocument) && !canWithdrawOwn) {
      setSuggestionError('Only owners and editors can reject suggestions; authors can withdraw their own.')
      return
    }
    const isResolver = collabRole === 'owner' || collabRole === 'editor'
    if (!isResolver) {
      // Authors may withdraw their own ephemeral proposal without creating a
      // shared resolver decision.
      setSuggestions((current) => current.map((item) => item.id === id ? { ...item, status: 'rejected' } : item))
      setSuggestionError(null)
      return
    }
    const source = editorRef.current?.getValue() ?? latexContent
    lastSuggestionActionRef.current = { kind: 'reject', id }
    try {
      const result = await apiClient.decideSuggestion(resumeId, {
        suggestion_id: id,
        status: 'rejected',
        expected_content: source,
        original_text: suggestion?.originalText ?? '',
        replacement_text: suggestion?.replacementText ?? '',
        prefix: suggestion?.prefix ?? '',
        suffix: suggestion?.suffix ?? '',
      })
      const decision = { id, status: result.status, decidedByRole: result.decided_by_role, decidedAt: Date.parse(result.decided_at) }
      setSuggestions((current) => current.map((item) => item.id === id ? { ...item, status: result.status } : item))
      setSuggestionDecisions((current) => [...current, decision])
      setSuggestionError(null)
      lastSuggestionActionRef.current = null
    } catch (error) {
      setSuggestionError(error instanceof Error ? error.message : 'Could not reject this suggestion. It remains pending.')
    }
  }, [allSuggestions, canEditDocument, collabRole, latexContent, resumeId, sessionUserId])

  const retrySuggestion = useCallback(() => {
    const action = lastSuggestionActionRef.current
    if (action) {
      if (action.kind === 'accept') void handleAcceptSuggestion(action.id)
      else void handleRejectSuggestion(action.id)
      return
    }
    const draft = lastSuggestionDraftRef.current
    if (draft) handleCreateSuggestion(draft.findText, draft.replacementText)
    else setSuggestionError(null)
  }, [handleAcceptSuggestion, handleCreateSuggestion, handleRejectSuggestion])

  const setPreviewBlob = useCallback((blob: Blob, fromOffline = false, renderedJobId: string | null = null) => {
    const nextUrl = URL.createObjectURL(blob)
    if (pdfUrlRef.current) URL.revokeObjectURL(pdfUrlRef.current)
    pdfUrlRef.current = nextUrl
    offlinePdfBlobRef.current = blob
    setPdfUrl(nextUrl)
    setRenderedPdfJobId(fromOffline ? null : renderedJobId)
    setIsOfflinePdf(fromOffline)
    setOfflinePdfError(null)
  }, [])

  const loadOfflinePdf = useCallback(async () => {
    const ownerId = offlinePdfOwnerId
    const generation = offlinePdfIdentityRef.current.generation
    if (!ownerId) return
    setOfflinePdfError(null)
    try {
      const cached = await getOfflineCompiledPdf(ownerId, resumeId)
      if (!isCurrentOfflinePdfIdentity(ownerId, resumeId, generation)) return
      if (cached) {
        if (!title.trim()) setTitle(cached.title)
        setPreviewBlob(cached.pdf, true)
        setOfflinePdfLoaded(true)
        setRightTab('preview')
      }
    } catch {
      if (isCurrentOfflinePdfIdentity(ownerId, resumeId, generation)) {
        setOfflinePdfError('The offline PDF could not be opened. Check storage access and retry.')
      }
    }
  }, [isCurrentOfflinePdfIdentity, offlinePdfOwnerId, resumeId, setPreviewBlob, title])

  const saveCachedPdf = useCallback(async (blob: Blob) => {
    const ownerId = sessionUserId
    const generation = offlinePdfIdentityRef.current.generation
    if (!ownerId || !isCurrentOfflinePdfIdentity(ownerId, resumeId, generation)) return
    const pending = { blob, ownerId, resumeId, generation }
    pendingOfflinePdfSaveRef.current = pending
    try {
      await saveOfflineCompiledPdf({
        ownerId,
        resumeId,
        title,
        pdf: blob,
        shouldPersist: () => isCurrentOfflinePdfIdentity(ownerId, resumeId, generation),
      })
      if (pendingOfflinePdfSaveRef.current !== pending || !isCurrentOfflinePdfIdentity(ownerId, resumeId, generation)) return
      pendingOfflinePdfSaveRef.current = null
      setOfflinePdfError(null)
    } catch {
      if (pendingOfflinePdfSaveRef.current === pending && isCurrentOfflinePdfIdentity(ownerId, resumeId, generation)) {
        setOfflinePdfError('The PDF is ready, but could not be saved for offline reading. Retry to save it.')
      }
    }
  }, [isCurrentOfflinePdfIdentity, resumeId, sessionUserId, title])

  const retryOfflinePdf = useCallback(async () => {
    const pending = pendingOfflinePdfSaveRef.current
    const generation = offlinePdfIdentityRef.current.generation
    if (pending && sessionUserId && pending.ownerId === sessionUserId && pending.resumeId === resumeId && pending.generation === generation && isCurrentOfflinePdfIdentity(sessionUserId, resumeId, generation)) {
      await saveCachedPdf(pending.blob)
      return
    }
    await loadOfflinePdf()
  }, [isCurrentOfflinePdfIdentity, loadOfflinePdf, resumeId, saveCachedPdf, sessionUserId])

  // PWA: detect mobile breakpoint (Feature 79E)
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 768px)')
    setIsMobile(mq.matches)
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])

  // Remember only a confirmed authenticated identity. This non-secret binding
  // lets an already-authenticated browser reopen the exact resume offline; it
  // is never used to enumerate documents or make an API request.
  useEffect(() => {
    if (sessionUserId) rememberOfflinePdfOwner(sessionUserId)
    else setRememberedOfflineOwner(getRememberedOfflinePdfOwner())
  }, [sessionUserId])

  // PWA: flush offline drafts and compile queue when connection restores (Feature 79C/79D)
  useEffect(() => {
    let cancelled = false
    const ownerAtStart = offlinePdfOwnerId
    const generationAtStart = offlinePdfIdentityRef.current.generation
    const isActive = () => !cancelled && isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart)
    if (!isOnline) {
      // Recount pending items so the banner badge stays current
      if (offlinePdfOwnerId) void pendingDraftCount(offlinePdfOwnerId).then(count => { if (isActive()) setOfflinePendingCount(count) }).catch(() => {})
      return () => { cancelled = true }
    }
    // Initial loading restores a pending local draft before any successful
    // reconnect flush is allowed to delete it from IndexedDB.
    if (isLoading || !sessionUserId) return
    // Flush pending drafts
    void getPendingDrafts(sessionUserId).then(async (drafts) => {
      if (!isActive()) return
      for (const draft of drafts) {
        if (!isActive()) return
        const releaseReservation = acquireReconnectReservation(draftReconnectReservationKey(draft))
        if (!releaseReservation) continue
        try {
          // Older drafts may not carry a base snapshot. Before allowing one
          // to write, prove that the server still has exactly the draft's
          // source; otherwise leave it pending for explicit reconciliation.
          let expectedLatexContent = draft.expectedLatexContent
          if (expectedLatexContent === undefined) {
            const current = await apiClient.getResume(draft.resumeId)
            if (!isActive()) return
            if (current.latex_content !== draft.latexContent) {
              throw new Error('Offline draft conflicts with newer server content')
            }
            expectedLatexContent = current.latex_content
          }
          await apiClient.updateResume(draft.resumeId, {
            title: draft.title,
            latex_content: draft.latexContent,
            expected_latex_content: expectedLatexContent,
          })
          // A newer local revision may have been saved while the HTTP request
          // was in flight. Acknowledge only this captured owner's exact revision.
          await deleteDraftIfUnchanged(draft)
          if (!isActive()) return
        } catch {
          // Leave in pending state; will retry on next reconnect
        } finally {
          releaseReservation()
        }
      }
      if (!isActive()) return
      const count = await pendingDraftCount(sessionUserId)
      if (isActive()) setOfflinePendingCount(count)
    }).catch(() => {})
    // Flush queued compiles
    void getQueuedCompiles(sessionUserId).then(async (queued) => {
      if (!isActive()) return
      for (const job of queued) {
        if (!isActive()) return
        const releaseReservation = acquireReconnectReservation(compileReconnectReservationKey(sessionUserId, job))
        if (!releaseReservation) continue
        try {
          const r = await apiClient.compileLatex({
            latex_content: job.latexContent,
            resume_id: job.resumeId,
          })
          if (r.success) {
            await dequeueCompile(sessionUserId, job.id)
            if (!isActive()) return
            toast.success('Queued compilation submitted')
          }
        } catch {
          // Leave in queue; will retry on next reconnect
        } finally {
          releaseReservation()
        }
      }
    }).catch(() => {})
    return () => { cancelled = true }
  }, [isCurrentOfflinePdfIdentity, isOnline, isLoading, offlinePdfOwnerId, resumeId, sessionUserId])

  // A compiled PDF is deliberately not in the service-worker cache. When the
  // editor goes offline, restore only this authenticated owner/resume pair
  // from the explicit IndexedDB cache.
  useEffect(() => {
    if (isOnline || !offlinePdfOwnerId) return
    void loadOfflinePdf()
  }, [isOnline, loadOfflinePdf, offlinePdfOwnerId])

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
    if (sessionLoading || !sessionData) return
    let cancelled = false
    const ownerAtStart = offlinePdfOwnerId
    const generationAtStart = offlinePdfIdentityRef.current.generation
    const isActive = () => !cancelled && isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart)
    apiClient.getGitHubStatus()
      // A public-import-only OAuth grant is connected, but cannot read or
      // write the private repository used by resume sync.
      .then(s => { if (isActive()) setGhConnected(s.private_sync) })
      .catch(e => { if (isActive()) console.error('Failed to load GitHub connection status', e) })
    return () => { cancelled = true }
  }, [isCurrentOfflinePdfIdentity, offlinePdfOwnerId, resumeId, sessionData, sessionLoading])

  // Check Dropbox user connection (Feature 77)
  useEffect(() => {
    if (sessionLoading || !sessionData) return
    let cancelled = false
    const ownerAtStart = offlinePdfOwnerId
    const generationAtStart = offlinePdfIdentityRef.current.generation
    const isActive = () => !cancelled && isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart)
    apiClient.getDropboxStatus()
      .then(s => { if (isActive()) setDbxConnected(s.connected) })
      .catch(e => { if (isActive()) console.error('Failed to load Dropbox connection status', e) })
    return () => { cancelled = true }
  }, [isCurrentOfflinePdfIdentity, offlinePdfOwnerId, resumeId, sessionData, sessionLoading])

  // Fetch user plan for priority queue badge (Feature 34)
  useEffect(() => {
    if (sessionLoading || !sessionData) return
    let cancelled = false
    const ownerAtStart = offlinePdfOwnerId
    const generationAtStart = offlinePdfIdentityRef.current.generation
    const isActive = () => !cancelled && isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart)
    apiClient.getCurrentPlan()
      .then(plan => { if (isActive()) setUserPlan(plan) })
      .catch(e => { if (isActive()) console.error('Failed to load subscription plan', e) })
    return () => { cancelled = true }
  }, [isCurrentOfflinePdfIdentity, offlinePdfOwnerId, resumeId, sessionData, sessionLoading])

  const {
    score: quickATSScore,
    loading: quickATSLoading,
    refetch: refetchATS,
    grade: quickATSGrade,
    sectionsFound: quickSectionsFound,
    missingSections: quickMissingSections,
    keywordMatchPercent: quickKeywordMatch,
  } = useQuickATSScore(latexContent)

  // Fetch simulator findings when the analysis panel opens (and refresh on
  // meaningful content change while it stays open). Best-effort — a failure
  // just leaves the card driven by the quick-score signals alone.
  useEffect(() => {
    if (!deepPanelOpen || documentType === 'presentation') return
    if (!latexContent || latexContent.length < 200) { setSimIssues([]); return }
    let cancelled = false
    apiClient
      .simulateAts({ latex_content: latexContent, ats_name: 'taleo' })
      .then((res) => { if (!cancelled) setSimIssues(res.issues ?? []) })
      .catch(() => { if (!cancelled) setSimIssues([]) })
    return () => { cancelled = true }
  }, [deepPanelOpen, latexContent, documentType])

  // Fold quick-score + simulator findings into the five named categories (#1367).
  const atsCategories = useMemo(() => {
    if (documentType === 'presentation') return []
    return buildATSCategories({
      quick: {
        grade: quickATSGrade,
        sectionsFound: quickSectionsFound,
        missingSections: quickMissingSections,
        keywordMatchPercent: quickKeywordMatch,
      },
      simulatorIssues: simIssues,
      latexContent,
    })
  }, [documentType, quickATSGrade, quickSectionsFound, quickMissingSections, quickKeywordMatch, simIssues, latexContent])

  // Deep-link a finding to its editor line, then step out of the way.
  const handleJumpToFinding = useCallback((line: number) => {
    setSyncFromLine(line)
    setSyncFromRequestId((value) => value + 1)
    setDeepPanelOpen(false)
  }, [])

  const { result: confidenceResult, loading: confidenceLoading, error: confidenceError, refetch: refetchConfidence } = useConfidenceScore(latexContent)
  const [confidencePanelOpen, setConfidencePanelOpen] = useState(false)

  // Account/resume changes render once before the identity effect clears the
  // job state. Hide raw ids during that transition so the stream hook cannot
  // keep an old subscription alive, and so completed-job effects cannot fetch
  // an old owner's PDF under the new identity.
  const ownsRenderedJobState = (
    offlinePdfIdentityRef.current.ownerId === offlinePdfOwnerId &&
    offlinePdfIdentityRef.current.resumeId === resumeId
  )
  const ownedCompileJobId = ownsRenderedJobState ? compileJobId : null
  const ownedAiJobId = ownsRenderedJobState ? aiJobId : null
  const { state: compileStream } = useJobStream(ownedCompileJobId)
  const { state: aiStream } = useJobStream(ownedAiJobId)
  const sourceHash = useSourceHash(latexContent)
  const artifactPreview = useArtifactPreview({
    artifact: lastStartedJobKind === 'ai' ? aiStream.artifact : compileStream.artifact,
    identity: `${sessionUserId ?? 'signed-out'}:${resumeId}`, onReady: (blob, artifact) => {
      activePdfJobId.current = artifact.job_id
      setPreviewBlob(blob)
      setRenderedPdfJobId(artifact.job_id)
      setDisplayedArtifact(artifact)
    },
  })
  useEffect(() => {
    if (artifactPreview.error) toast.error(editorMode === 'source' ? artifactPreview.error : 'The PDF preview could not be loaded. Try updating the PDF again.')
  }, [artifactPreview.error, editorMode])
  useEffect(() => {
    if (!engineSupported || editorMode !== 'pdf' || !sessionUserId) return
    let stopped = false
    setEngineDocumentError(null)
    void apiClient.getEngineDocument(resumeId).then((response) => {
      if (!stopped) { engineDocumentIdentityRef.current = `${sessionUserId}:${resumeId}`; setEngineDocument(response.document) }
    }).catch(() => { if (!stopped) setEngineDocumentError('Resume fields could not be loaded. Save your resume and retry.') })
    return () => { stopped = true }
  }, [engineSupported, resumeId, sessionUserId, editorMode, sourceHash, displayedArtifact?.artifact_id])

  useEffect(() => {
    if (!displayedArtifact?.geometry_url || editorMode !== 'pdf') { setEngineGeometry(null); return }
    let stopped = false
    const controller = new AbortController()
    void apiClient.getArtifactGeometry(displayedArtifact.job_id, displayedArtifact.artifact_id, undefined, controller.signal)
      .then((geometry) => { if (!stopped) setEngineGeometry(geometry) }).catch(() => { if (!stopped) setEngineGeometry(null) })
    return () => { stopped = true; controller.abort() }
  }, [displayedArtifact, editorMode])
  const visibleEngineDocument = engineDocumentIdentityRef.current === `${sessionUserId}:${resumeId}` ? engineDocument : null
  const verifiedGeometry = editableGeometry(displayedArtifact, engineGeometry, visibleEngineDocument, sourceHash)



  const shareOrDownloadPdf = useCallback(async () => {
    const sourceAtStart = sourceAtRenderRef.current
    if (displayedArtifact && !canExportArtifact(displayedArtifact, sourceHash, lastStartedJobKind === 'ai' ? aiJobId : compileJobId, lastStartedJobKind === 'ai' ? aiStream.status : compileStream.status, displayedArtifact.job_id)) { setOfflinePdfError('Compile your accepted current resume before sharing this PDF.'); return }
    const ownerAtStart = offlinePdfOwnerId
    const generationAtStart = offlinePdfIdentityRef.current.generation
    const isActive = () => isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart)
    let blob = offlinePdfBlobRef.current
    const id = ownsRenderedJobState
      ? (compileStream.pdfJobId ?? aiStream.pdfJobId ?? activePdfJobId.current ?? ownedCompileJobId ?? ownedAiJobId)
      : null
    try {
      if (!blob && id) blob = await apiClient.downloadPdf(id)
      if (!isActive() || sourceAtRenderRef.current !== sourceAtStart) return
      if (!blob) throw new Error('No compiled PDF is available yet')
      const filename = `${title.replace(/\s+/g, '_') || 'resume'}.pdf`
      const file = new File([blob], filename, { type: 'application/pdf' })
      const canShareFiles = typeof navigator !== 'undefined' && typeof navigator.share === 'function' &&
        (!navigator.canShare || navigator.canShare({ files: [file] }))
      if (canShareFiles) {
        try {
          await navigator.share({ files: [file], title: title || 'Resume PDF' })
          return
        } catch (error) {
          // User cancellation is not an error; other Web Share failures use the
          // same explicit download fallback as browsers without Web Share.
          if (error instanceof DOMException && error.name === 'AbortError') return
        }
      }
      if (!isActive() || sourceAtRenderRef.current !== sourceAtStart) return
      downloadBlob(blob, filename)
    } catch {
      if (isActive()) setOfflinePdfError('Sharing or downloading the PDF failed. Retry when storage or network access is available.')
    }
  }, [aiStream.pdfJobId, compileStream.pdfJobId, isCurrentOfflinePdfIdentity, offlinePdfOwnerId, ownedAiJobId, ownedCompileJobId, ownsRenderedJobState, resumeId, title, displayedArtifact, sourceHash, lastStartedJobKind, aiJobId, compileJobId, aiStream.status, compileStream.status])
  // A session/resume switch is rendered before the identity effect below can
  // clear the previous job id. Do not let useJobStream re-subscribe to that
  // old id during the transition render.
  const ownedDeepAnalysisJobId = (
    offlinePdfIdentityRef.current.ownerId === offlinePdfOwnerId &&
    offlinePdfIdentityRef.current.resumeId === resumeId
  ) ? deepAnalysisJobId : null
  const { state: deepStream } = useJobStream(ownedDeepAnalysisJobId)

  // Load the server copy and prefer a pending local draft when one exists.
  // This makes offline storage recoverable after refresh instead of write-only.
  useEffect(() => {
    if (sessionLoading) return
    let cancelled = false
    const ownerAtStart = offlinePdfOwnerId
    const generationAtStart = offlinePdfIdentityRef.current.generation
    const isActive = () => !cancelled && isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart)

    if (!sessionData) {
      if (typeof navigator === 'undefined' || navigator.onLine) {
        setIsLoading(false)
        return
      }

      setIsLoading(true)
      setResumeLoadError(null)
      if (!ownerAtStart) {
        setResumeLoadError('No offline document is available for this browser profile.')
        setIsLoading(false)
        return
      }
      // Cold offline recovery uses the last confirmed owner in this browser
      // profile; an unlocked browser profile cannot distinguish an unclean physical
      // handoff, so confirmed login/account switch and logout perform purges.
      void getDraft(ownerAtStart, resumeId)
        .then(async (draft) => {
          if (!isActive()) return
          if (!draft) {
            // A compiled PDF can be read without restoring editable source.
            // Keep the exact route scoped to the last confirmed owner id.
            if (ownerAtStart) {
              const cachedPdf = await getOfflineCompiledPdf(ownerAtStart, resumeId).catch(() => null)
              if (isActive() && cachedPdf) {
                setOfflinePdfLoaded(true)
                return
              }
            }
            if (!isActive()) return
            setResumeLoadError('No offline draft is available for this resume.')
            return
          }
          if (!isActive()) return
          setTitle(draft.title)
          setLatexContent(draft.latexContent)
          setSavedSnapshot({ title: draft.title, latex: draft.latexContent })
          editorRef.current?.setValue(draft.latexContent)
          setOfflineDraftLoaded(true)
          setLastSavedAt(new Date(draft.savedAt).getTime())
        })
        .catch(() => {
          if (isActive()) setResumeLoadError('The offline draft could not be loaded from this device.')
        })
        .finally(() => {
          if (isActive()) setIsLoading(false)
        })

      return () => { cancelled = true }
    }

    const fetchResume = async () => {
      setIsLoading(true)
      setResumeLoadError(null)
      try {
        const [data, localDraft] = await Promise.all([
          apiClient.getResume(resumeId),
          sessionUserId ? getDraft(sessionUserId, resumeId).catch(() => null) : Promise.resolve(null),
        ])
        if (!isActive()) return
        const pendingDraft = localDraft?.syncStatus === 'pending' ? localDraft : null
        const effectiveTitle = pendingDraft?.title ?? data.title
        const effectiveLatex = pendingDraft?.latexContent ?? data.latex_content
        setTitle(effectiveTitle)
        setLatexContent(effectiveLatex)
        // Keep the server copy as the CAS baseline even while showing a
        // pending local draft. A reconnect must never overwrite a newer
        // collaborative edit with this full-document draft.
        setSavedSnapshot({ title: data.title, latex: data.latex_content })
        editorRef.current?.setValue(effectiveLatex)
        if (pendingDraft) {
          setOfflineDraftLoaded(true)
          setLastSavedAt(new Date(pendingDraft.savedAt).getTime())
        }
        // Load compiler preference from resume metadata
        const savedCompiler = data.metadata?.compiler as LatexCompiler | undefined
        if (savedCompiler && ['pdflatex', 'xelatex', 'lualatex'].includes(savedCompiler)) {
          setCompiler(savedCompiler)
        }
        // Load all compile settings for the modal (Feature 38)
        const meta = data.metadata as Record<string, unknown> | null | undefined
        setBibliographyBibTeX(typeof meta?.bibtex === 'string' ? meta.bibtex : '')
        setCompileSettings({
          compiler: savedCompiler ?? 'pdflatex',
          texlive_version: (meta?.texlive_version as string | null | undefined) ?? null,
          main_file: (meta?.main_file as string | undefined) ?? 'resume.tex',
          latexmk_flags: ((meta?.latexmk_flags as string[] | undefined) ?? []) as CompileSettings['latexmk_flags'],
          extra_packages: (meta?.extra_packages as string[] | undefined) ?? [],
          halt_on_error: meta?.halt_on_error !== false,
          draft_mode: meta?.draft_mode === true,
        })
        // Load share token state
        setShareToken(data.share_token ?? null)
        setShareUrl(data.share_url ?? null)
        setShareAnonymous(data.share_anonymous ?? false)
        setShareReviewComments(data.share_review_comments ?? false)
        // Feature 86 — presentation support
        setDocumentType(data.document_type ?? 'resume')
        setAcademicReport(null)
        if ((data.document_type ?? 'resume') !== 'presentation') {
          apiClient.getAcademicCVReport(resumeId).then(report => {
            if (isActive()) setAcademicReport(report)
          }).catch(() => {})
        }

        // GitHub sync state
        setGhSyncEnabled(data.github_sync_enabled ?? false)
        // Dropbox sync state (Feature 77)
        setDbxSyncEnabled(data.dropbox_sync_enabled ?? false)

        // Collaboration ownership (Feature 40)
        setCollabIsOwner(data.user_id === sessionUserId)
        setCollabRole(data.access_role ?? (data.user_id === sessionUserId ? 'owner' : 'viewer'))

        const nextParentResumeId = data.parent_resume_id ?? null
        setParentResumeId(nextParentResumeId)
        setParentTitle(null)
        setIsLinkedVariant(data.content_source === 'builder_variant')
        // Fetch parent title if this is a variant
        if (nextParentResumeId) {
          apiClient.getResume(nextParentResumeId).then(p => {
            if (isActive()) setParentTitle(p.title)
          }).catch(() => {
            if (isActive()) {
              setParentResumeId(null) // parent was deleted
              setParentTitle(null)
            }
          })
        }

        // Auto-compile on load so user sees PDF immediately
        if (effectiveLatex && effectiveLatex.length >= 100) {
          try {
            const initCompiler = (data.metadata?.compiler as LatexCompiler | undefined) ?? 'pdflatex'
            const r = await apiClient.compileLatex({ latex_content: effectiveLatex, resume_id: resumeId, compiler: initCompiler })
            if (isActive() && r.success && r.job_id) { setCompileJobId(r.job_id); setLastStartedJobKind('compile') }
          } catch {
            // Silent — user can compile manually
          }
        }
      } catch (error) {
        if (isActive()) {
          setResumeLoadError(error instanceof Error ? error.message : 'Resume could not be loaded.')
        }
      } finally {
        if (isActive()) setIsLoading(false)
      }
    }
    void fetchResume()
    return () => { cancelled = true }
  }, [isCurrentOfflinePdfIdentity, offlinePdfOwnerId, resumeId, sessionData, sessionLoading, sessionUserId])

  // A completed rewrite remains staged until the user explicitly applies it.
  // Streaming tokens never touch Monaco/React state, so autosave and collaboration
  // continue to see the original document throughout the run and review period.
  useEffect(() => {
    if (ownedAiJobId !== semanticRunId && aiStream.status === 'completed' && aiStream.streamingLatex) {
      setStagedAiLatex(aiStream.streamingLatex)
    }
  }, [aiStream.status, aiStream.streamingLatex, semanticRunId, ownedAiJobId])

  // Track compilation completion for analytics
  useEffect(() => {
    if (compileStream.status === 'completed' && compileJobId) {
      apiClient.trackCompilation(compileJobId, 'completed')
      apiClient.trackFeatureUsage('compile')
      if (documentType !== 'presentation') refetchATS()
    } else if (compileStream.status === 'failed' && compileJobId) {
      apiClient.trackCompilation(compileJobId, 'failed')
    }
  }, [compileStream.status, compileJobId, documentType, refetchATS])

  // Load PDF after either job completes
  useEffect(() => {
    if (lastStartedJobKind === 'ai' ? aiStream.artifact : compileStream.artifact) return
    const pdfJobId = lastStartedJobKind === 'ai' ? aiStream.pdfJobId : compileStream.pdfJobId
    const anyCompleted =
      (compileStream.status === 'completed' && compileStream.pdfJobId) ||
      (aiStream.status === 'completed' && aiStream.pdfJobId)

    if (anyCompleted && pdfJobId) {
      // A session/account refresh changes this effect's dependencies. Do not
      // restart a completed job's one-use PDF fetch for the new owner: the
      // original request is already guarded by its captured identity, while a
      // second request would let an old job become current again.
      if (activePdfJobId.current === pdfJobId) return
      activePdfJobId.current = pdfJobId
      const ownerAtStart = sessionUserId
      const generationAtStart = offlinePdfIdentityRef.current.generation
      apiClient.downloadPdf(pdfJobId).then((blob) => {
        if (!ownerAtStart || !isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart) || activePdfJobId.current !== pdfJobId) return
        setPreviewBlob(blob, false, pdfJobId)
        // This is a successful response for the authenticated compile job tied
        // to this owned resume; failed/anonymous or stale responses never enter
        // the local cache.
        void saveCachedPdf(blob)
        setRightTab('preview')
      }).catch(() => {
        if (!ownerAtStart || !isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart) || activePdfJobId.current !== pdfJobId) return
        setOfflinePdfError('Failed to load the PDF preview. Retry to load the latest compiled PDF.')
        if (!isOnline) void loadOfflinePdf()
      })
    }

    // Keep the last successful preview while a replacement compiles. A failed
    // compile should not destroy the only usable PDF the user still has; the
    // object URL is swapped and revoked only after the next PDF downloads.
  }, [
    compileStream.status, compileStream.pdfJobId, compileStream.artifact,
    aiStream.status, aiStream.pdfJobId, aiStream.artifact, lastStartedJobKind,
    isCurrentOfflinePdfIdentity, isOnline, loadOfflinePdf, resumeId, saveCachedPdf, sessionUserId, setPreviewBlob,
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
    const onViewportResize = () => {
      const maximum = Math.max(280, window.innerWidth - 300)
      setRightMaxWidth(maximum)
      setRightWidth(current => current === null ? null : Math.min(current, maximum))
    }
    onViewportResize()
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
    window.addEventListener('resize', onViewportResize)
    return () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
      window.removeEventListener('resize', onViewportResize)
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
    const ownerAtStart = offlinePdfOwnerId
    const generationAtStart = offlinePdfIdentityRef.current.generation
    const isActive = () => isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart)
    setGhTogglingSync(true)
    try {
      if (ghSyncEnabled) {
        await apiClient.disableGitHubSync(resumeId)
        if (!isActive()) return
        setGhSyncEnabled(false)
        toast.success('GitHub sync disabled')
      } else {
        await apiClient.enableGitHubSync(resumeId)
        if (!isActive()) return
        setGhSyncEnabled(true)
        toast.success('GitHub sync enabled')
      }
    } catch (e) {
      if (isActive()) toast.error(e instanceof Error ? e.message : 'Failed to toggle sync')
    } finally {
      if (isActive()) setGhTogglingSync(false)
    }
  }

  const handlePushToGitHub = async () => {
    if (ghPushing || autoSaving || isSaving) return
    if (!canEditDocument) {
      toast.error('Detach this linked variant before pushing editor changes')
      return
    }
    const ownerAtStart = offlinePdfOwnerId
    const generationAtStart = offlinePdfIdentityRef.current.generation
    const isActive = () => isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart)
    setGhPushing(true)
    try {
      // Save first to ensure latest content is pushed
      const content = editorRef.current?.getValue() || latexContent
      await apiClient.updateResume(resumeId, {
        title,
        latex_content: content,
        expected_latex_content: savedSnapshot.latex,
      })
      if (!isActive()) return
      setLatexContent(content)
      setSavedSnapshot({ title, latex: content })
      setLastSavedAt(Date.now())
      const result = await apiClient.pushToGitHub(resumeId)
      if (!isActive()) return
      toast.success(result.message)
    } catch (e) {
      if (isActive()) toast.error(e instanceof Error ? e.message : 'GitHub push failed')
    } finally {
      if (isActive()) setGhPushing(false)
    }
  }

  const handlePullFromGitHub = () => {
    if (ghPushing || autoSaving || isSaving) return
    setConfirmPull('github')
  }
  const doPullFromGitHub = async () => {
    const ownerAtStart = offlinePdfOwnerId
    const generationAtStart = offlinePdfIdentityRef.current.generation
    const isActive = () => isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart)
    setGhPushing(true)
    try {
      const result = await apiClient.pullFromGitHub(resumeId)
      if (!isActive()) return
      pushUndo('Before GitHub pull')
      editorRef.current?.setValue(result.latex_content)
      setLatexContent(result.latex_content)
      setSavedSnapshot({ title, latex: result.latex_content })
      setLastSavedAt(Date.now())
      toast.success('Pulled latest content from GitHub')
    } catch (e) {
      if (isActive()) toast.error(e instanceof Error ? e.message : 'GitHub pull failed')
    } finally {
      if (isActive()) setGhPushing(false)
    }
  }

  // ── Dropbox sync handlers (Feature 77) ───────────────────────────────────
  const handleToggleDropboxSync = async () => {
    const ownerAtStart = offlinePdfOwnerId
    const generationAtStart = offlinePdfIdentityRef.current.generation
    const isActive = () => isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart)
    setDbxTogglingSync(true)
    try {
      if (dbxSyncEnabled) {
        await apiClient.disableDropboxSync(resumeId)
        if (!isActive()) return
        setDbxSyncEnabled(false)
        toast.success('Dropbox sync disabled')
      } else {
        await apiClient.enableDropboxSync(resumeId)
        if (!isActive()) return
        setDbxSyncEnabled(true)
        toast.success('Dropbox sync enabled — initial push complete')
      }
    } catch (e) {
      if (isActive()) toast.error(e instanceof Error ? e.message : 'Failed to toggle Dropbox sync')
    } finally {
      if (isActive()) setDbxTogglingSync(false)
    }
  }

  const handlePushToDropbox = async () => {
    if (!canEditDocument) {
      toast.error('Detach this linked variant before pushing editor changes')
      return
    }
    const ownerAtStart = offlinePdfOwnerId
    const generationAtStart = offlinePdfIdentityRef.current.generation
    const isActive = () => isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart)
    setDbxSyncing(true)
    try {
      const content = editorRef.current?.getValue() || latexContent
      await apiClient.updateResume(resumeId, {
        title,
        latex_content: content,
        expected_latex_content: savedSnapshot.latex,
      })
      if (!isActive()) return
      const result = await apiClient.pushToDropbox(resumeId)
      if (!isActive()) return
      toast.success(result.message)
    } catch (e) {
      if (isActive()) toast.error(e instanceof Error ? e.message : 'Dropbox push failed')
    } finally {
      if (isActive()) setDbxSyncing(false)
    }
  }

  const handlePullFromDropbox = () => setConfirmPull('dropbox')
  const doPullFromDropbox = async () => {
    const ownerAtStart = offlinePdfOwnerId
    const generationAtStart = offlinePdfIdentityRef.current.generation
    const isActive = () => isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart)
    setDbxSyncing(true)
    try {
      const result = await apiClient.pullFromDropbox(resumeId)
      if (!isActive()) return
      editorRef.current?.setValue(result.latex_content)
      setLatexContent(result.latex_content)
      toast.success('Pulled latest content from Dropbox')
    } catch (e) {
      if (isActive()) toast.error(e instanceof Error ? e.message : 'Dropbox pull failed')
    } finally {
      if (isActive()) setDbxSyncing(false)
    }
  }

  // Switching views never serializes source or replaces a user's saved preference
  // with the temporary mode selected by an unsupported engine capability.
  const handleToggleEditorMode = useCallback((mode: 'source' | 'wysiwyg' | 'pdf') => {
    if (mode === preferredEditorMode || (mode === 'pdf' && !engineSupported)) return
    if (editorMode === 'source') setLatexContent(editorRef.current?.getValue() || latexContent)
    if (mode === 'pdf') setRightTab('preview')
    setEditorMode(mode)
    try { localStorage.setItem(`latexy_editor_mode_${resumeId}`, mode) } catch { /* optional preference */ }
  }, [engineSupported, preferredEditorMode, editorMode, latexContent, resumeId])

  const handleSave = async () => {
    const ownerAtStart = offlinePdfOwnerId
    const generationAtStart = offlinePdfIdentityRef.current.generation
    const isActive = () => isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart)
    if (!canEditDocument) {
      if (isLinkedVariant) {
        toast.error('Choose “Detach and edit LaTeX” before saving editor changes')
        return
      }
      toast.error('This collaborator role has read-only access')
      return
    }
    if (!title.trim()) {
      setSaveError('A resume title is required')
      toast.error('Enter a resume title before saving')
      return
    }
    if (title.length > 255) {
      setSaveError('Resume titles must be 255 characters or fewer')
      toast.error('Resume title is too long')
      return
    }
    const content = editorRef.current?.getValue() || latexContent
    // Offline: persist to IndexedDB instead of API (Feature 79C)
    if (!navigator.onLine) {
      if (!ownerAtStart) {
        setSaveError('Sign in once on this browser before saving drafts offline')
        toast.error('Could not save the offline draft')
        return
      }
      try {
        await saveDraft({
          ownerId: ownerAtStart,
          resumeId,
          title,
          latexContent: content,
          expectedLatexContent: savedSnapshot.latex,
          savedAt: new Date(),
          syncStatus: 'pending',
        })
        if (!isActive()) return
        setLatexContent(content)
        setSavedSnapshot({ title, latex: content })
        setLastSavedAt(Date.now())
        setSaveError(null)
        const count = await pendingDraftCount(ownerAtStart)
        if (!isActive()) return
        setOfflinePendingCount(count)
        toast.info('Saved locally — will sync when back online')
      } catch (error) {
        if (!isActive()) return
        const message = error instanceof Error ? error.message : 'Local draft storage failed'
        setSaveError(message)
        toast.error('Could not save the offline draft')
      }
      return
    }
    setIsSaving(true)
    try {
      await apiClient.updateResume(resumeId, {
        title,
        latex_content: content,
        expected_latex_content: savedSnapshot.latex,
      })
      if (!isActive()) return
      setLatexContent(content)
      setSavedSnapshot({ title, latex: content })
      setLastSavedAt(Date.now())
      setSaveError(null)
      if (isLinkedVariant) {
        setIsLinkedVariant(false)
        setLinkedEditEnabled(false)
      }
      toast.success('Saved')
    } catch (error) {
      if (!isActive()) return
      const message = error instanceof Error ? error.message : 'Failed to save'
      setSaveError(message)
      toast.error(message)
    } finally {
      if (isActive()) setIsSaving(false)
    }
  }

  const runCompile = async () => {
    if (isAnyRunning || isSubmitting) return
    const actionStarted = performance.now()
    const ownerAtStart = offlinePdfOwnerId
    const generationAtStart = offlinePdfIdentityRef.current.generation
    const isActive = () => isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart)
    const content = editorRef.current?.getValue() || latexContent
    if (!content.trim()) { toast.error('Nothing to compile'); return }
    // Offline: queue the compile for later (Feature 79D)
    if (!navigator.onLine) {
      try {
        if (!ownerAtStart) throw new Error('Sign in once on this browser before queuing compiles offline')
        await enqueueCompile(ownerAtStart, resumeId, content)
        if (isActive()) toast.info('Queued — will compile when back online')
      } catch (error) {
        if (isActive()) toast.error(error instanceof Error ? error.message : 'Could not queue the offline compile')
      }
      return
    }
    return queuePreview.submitManual(content, async () => {
      setIsSubmitting(true)
      autoCompileTriggeredRef.current = false
      try {
        const r = await apiClient.compileLatex({ latex_content: content, resume_id: resumeId, compiler })
        if (!r.success || !r.job_id) throw new Error(r.message)
        if (!isActive()) return null
        editorRef.current?.markAutoCompileCompiled?.(content)
        userInitiatedJobRef.current = true
        setCompileJobId(r.job_id)
        recordPreviewAction(r.job_id, actionStarted)
        setLastStartedJobKind('compile')
        setRightTab(editorMode === 'source' ? 'logs' : 'preview')
        toast.success(editorMode === 'source' ? 'Compilation started' : 'Preparing your PDF preview')
        return r.job_id
      } catch (e) {
        if (isActive()) toast.error(previewErrorMessage(e, editorMode === 'pdf'))
        return null
      } finally {
        if (isActive()) setIsSubmitting(false)
      }
    })
  }

  // ── 84E: TikZ compile preview ────────────────────────────────────────────────
  const handleTikZPreview = async (tikzCode: string) => {
    const standaloneDoc = [
      '\\documentclass[border=4pt]{standalone}',
      '\\usepackage{tikz}',
      '\\usetikzlibrary{shapes.geometric, arrows.meta, positioning}',
      '\\begin{document}',
      tikzCode,
      '\\end{document}',
    ].join('\n')
    try {
      const r = await apiClient.compileLatex({
        latex_content: standaloneDoc,
        compiler,
      })
      if (!r.success || !r.job_id) throw new Error(r.message)
      userInitiatedJobRef.current = true
      setCompileJobId(r.job_id)
      setLastStartedJobKind('compile')
      setRightTab('preview')
      toast.success('TikZ preview compiling…')
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Preview failed')
    }
  }

  const runAiOptimize = async () => {
    const ownerAtStart = offlinePdfOwnerId
    const generationAtStart = offlinePdfIdentityRef.current.generation
    const isActive = () => isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart)
    const content = editorRef.current?.getValue() || latexContent
    aiBaselineRef.current = content
    setStagedAiLatex(null)
    setCompareData(null)
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
      if (!isActive()) return
      userInitiatedJobRef.current = true
      setAiJobId(r.job_id)
      setLastStartedJobKind('ai')
      toast.success('AI optimization started')
    } catch (e) {
      if (isActive()) toast.error(editorMode === 'source' ? e instanceof Error ? e.message : 'AI optimization failed' : 'Could not improve the résumé right now. Your draft is preserved.')
    } finally {
      if (isActive()) setIsAiSubmitting(false)
    }
  }

  const applyOptimizationCandidate = useCallback((candidate: string, record: boolean) => {
    const current = editorRef.current?.getValue() || latexContent
    const baseline = aiBaselineRef.current
    if (baseline != null && current !== baseline) {
      toast.error('Your resume changed while AI was working. Run optimization again to avoid losing edits.')
      return false
    }

    pushUndo('Before AI optimization')
    editorRef.current?.setValue(candidate, { reveal: false })
    setLatexContent(candidate)
    setStagedAiLatex(null)
    setCompareData(null)

    if (record && aiJobId) {
      apiClient.recordOptimization(resumeId, {
        original_latex: baseline || current,
        optimized_latex: candidate,
        changes_made: aiStream.changesMade,
        ats_score: aiStream.atsScore ?? undefined,
        tokens_used: aiStream.tokensUsed ?? undefined,
        job_description: jobDescription.trim() || undefined,
      }).catch(() => {})
      apiClient.trackOptimization(aiJobId, 'openai', model, aiStream.tokensUsed ?? undefined)
      apiClient.trackFeatureUsage('ai_optimization')
    }
    aiBaselineRef.current = null
    return true
  }, [aiJobId, aiStream.atsScore, aiStream.changesMade, aiStream.tokensUsed, jobDescription, latexContent, model, pushUndo, resumeId])

  const handleApplyOptimization = useCallback((reviewedLatex?: string) => {
    if (!stagedAiLatex) return
    const candidate = reviewedLatex ?? stagedAiLatex
    if (applyOptimizationCandidate(candidate, candidate === stagedAiLatex)) {
      toast.success(candidate === stagedAiLatex ? 'Applied AI optimization' : 'Applied your reviewed wording. Update the PDF preview to see the final layout.')
      if (documentType !== 'presentation') {
        const ownerAtStart = offlinePdfOwnerId
        const generationAtStart = offlinePdfIdentityRef.current.generation
        apiClient.getAcademicCVReport(resumeId).then(report => {
          if (isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart)) setAcademicReport(report)
        }).catch(() => {})
      }
    }
  }, [applyOptimizationCandidate, documentType, isCurrentOfflinePdfIdentity, offlinePdfOwnerId, resumeId, stagedAiLatex])

  const handleDiscardOptimization = useCallback(() => {
    setStagedAiLatex(null)
    setCompareData(null)
    aiBaselineRef.current = null
    toast.success('Discarded AI optimization')
  }, [])

  const handleReviewOptimization = useCallback(() => {
    if (!stagedAiLatex) return
    setCompareData({
      original: aiBaselineRef.current || latexContent,
      optimized: stagedAiLatex,
    })
  }, [latexContent, stagedAiLatex])

  // Explicit escape hatch when the rewrite completed but its compile failed.
  const handleApplyAnyway = useCallback(() => {
    if (!aiStream.streamingLatex) return
    if (applyOptimizationCandidate(aiStream.streamingLatex, false)) {
      toast.success(editorMode === 'source' ? 'Applied optimized LaTeX — fix the compile errors manually' : 'Rewrite applied. Update the preview to check the layout.')
    }
  }, [aiStream.streamingLatex, applyOptimizationCandidate, editorMode])

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
    const sourceAtStart = sourceAtRenderRef.current
    if (isAnyRunning) { toast.error("Wait for the updated PDF to finish"); return }
    if (displayedArtifact && !canExportArtifact(displayedArtifact, sourceHash, lastStartedJobKind === 'ai' ? aiJobId : compileJobId, lastStartedJobKind === 'ai' ? aiStream.status : compileStream.status, displayedArtifact.job_id)) {
      toast.error('Compile your current resume before downloading. Review AI suggestions before accepting them.')
      return
    }
    const ownerAtStart = offlinePdfOwnerId
    const generationAtStart = offlinePdfIdentityRef.current.generation
    const isActive = () => isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart)
    const id = ownsRenderedJobState
      ? (compileStream.pdfJobId ?? aiStream.pdfJobId ?? activePdfJobId.current ?? ownedCompileJobId ?? ownedAiJobId)
      : null
    try {
      const blob = artifactPreview.verified && artifactPreview.verified.artifact.artifact_id === displayedArtifact?.artifact_id
        ? artifactPreview.verified.blob : id ? await apiClient.downloadPdf(id) : offlinePdfBlobRef.current
      if (!isActive() || sourceAtRenderRef.current !== sourceAtStart) return
      if (!blob) throw new Error('No compiled PDF is available yet')
      downloadBlob(blob, `${title.replace(/\s+/g, '_') || 'resume'}.pdf`)
    } catch {
      if (isActive()) setOfflinePdfError('Download failed. Retry when the PDF or network is available.')
    }
  }

  const handleOpenDeepAnalysis = useCallback(async (industryOverride?: string) => {
    const ownerAtStart = offlinePdfOwnerId
    const generationAtStart = offlinePdfIdentityRef.current.generation
    const isActive = () => isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart)
    setDeepPanelOpen(true)
    const activeSubmission = deepAnalysisSubmissionRef.current
    if (deepAnalysisJobId || (activeSubmission && activeSubmission.ownerId === ownerAtStart && activeSubmission.resumeId === resumeId && activeSubmission.generation === generationAtStart)) return // already have a job running/done
    const content = editorRef.current?.getValue() || latexContent
    if (!content.trim()) { toast.error('Add LaTeX content first'); return }
    const submission = { ownerId: ownerAtStart, resumeId, generation: generationAtStart }
    deepAnalysisSubmissionRef.current = submission
    setIsDeepRunning(true)
    setDeepAnalysisError(null)
    try {
      const response = await apiClient.deepAnalyzeResume({
        latex_content: content,
        job_description: jobDescription.trim() || undefined,
        industry_override: industryOverride,
      })
      if (response.success && response.job_id) {
        if (!isActive()) return
        setDeepAnalysisJobId(response.job_id)
        setDeepAnalysisUsesRemaining(response.uses_remaining ?? null)
      } else {
        throw new Error(response.message || 'Deep analysis failed')
      }
    } catch (error) {
      if (!isActive()) return
      const msg = error instanceof Error ? error.message : 'Deep analysis failed'
      setDeepAnalysisError(msg)
      toast.error(msg)
      if (msg.startsWith('HTTP 402:')) {
        setDeepAnalysisUsesRemaining(0)
      }
    } finally {
      if (deepAnalysisSubmissionRef.current === submission) deepAnalysisSubmissionRef.current = null
      if (isActive()) setIsDeepRunning(false)
    }
  }, [deepAnalysisJobId, isCurrentOfflinePdfIdentity, jobDescription, latexContent, offlinePdfOwnerId, resumeId])

  const handleSyncToSource = useCallback((line: number) => {
    if (!Number.isInteger(line) || line < 1) return
    setSyncFromLine(line)
    setSyncFromRequestId((value) => value + 1)
    if (isMobile) editorRef.current?.highlightLine(line)
  }, [isMobile])

  const handleSourceToPdf = useCallback(() => {
    if (cursorLine === null || cursorLine < 1 || !pdfSyncReady) return
    setSourceSyncLine(cursorLine)
    setSourceSyncRequestId((value) => value + 1)
  }, [cursorLine, pdfSyncReady])

  const handlePdfToSource = useCallback(() => {
    const line = pdfSelection?.line
    if (!line || line < 1) return
    handleSyncToSource(line)
  }, [handleSyncToSource, pdfSelection])

  // A source/PDF selection belongs to one authenticated document and one
  // compiled job. Never let a late SyncTeX response or highlight survive an
  // owner, route, or job identity change.
  useEffect(() => {
    setPdfSelection(null)
    setPdfSyncReady(false)
    setSourceSyncLine(null)
    setSyncFromLine(null)
    setSyncFromRequestId((value) => value + 1)
    setSourceSyncRequestId((value) => value + 1)
  }, [resumeId, sessionUserId, renderedPdfJobId])

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
      // Fork copies the last-saved server state — persist the live editor buffer
      // first so unsaved edits are carried into the new variant (Finding: stale fork).
      if (isDirtyRef.current) {
        const content = editorRef.current?.getValue() || latexContent
        await apiClient.updateResume(resumeId, {
          title,
          latex_content: content,
          expected_latex_content: savedSnapshot.latex,
        })
        setSavedSnapshot({ title, latex: content })
        setLastSavedAt(Date.now())
      }
      const newResume = await apiClient.forkResume(resumeId, forkTitleInput || undefined)
      setForkPopoverOpen(false)
      setForkTitleInput('')
      router.push(
        newResume.content_source === 'builder_variant'
          ? `/workspace/variant/${newResume.id}`
          : `/workspace/${newResume.id}/edit`
      )
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to create variant')
    } finally {
      setIsForkingResume(false)
    }
  }, [resumeId, forkTitleInput, isForkingResume, router, title, latexContent, savedSnapshot.latex])

  const handleAcademicConvert = useCallback(async () => {
    if (isAcademicConverting) return
    setIsAcademicConverting(true)
    try {
      // Convert operates on saved server content — persist live edits first
      // so the industry variant reflects what the user currently sees.
      if (isDirtyRef.current) {
        const content = editorRef.current?.getValue() || latexContent
        await apiClient.updateResume(resumeId, {
          title,
          latex_content: content,
          expected_latex_content: savedSnapshot.latex,
        })
        setSavedSnapshot({ title, latex: content })
        setLastSavedAt(Date.now())
      }
      const result = await apiClient.convertAcademicCV(resumeId, {
        target_industry: academicTargetIndustry,
        target_role_description: academicRoleDescription.trim() || undefined,
        force: !!academicReport && !academicReport.is_academic_cv,
      })
      setAcademicReport(result.report)
      setAcademicConvertOpen(false)
      setAcademicRoleDescription('')
      toast.success('Industry resume variant created')
      router.push(`/workspace/${result.variant_resume_id}/edit`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to convert academic CV')
    } finally {
      setIsAcademicConverting(false)
    }
  }, [resumeId, academicTargetIndustry, academicRoleDescription, academicReport, isAcademicConverting, router, title, latexContent, savedSnapshot.latex])

  const isCompiling = compileStream.status === 'queued' || compileStream.status === 'processing'
  const isAiRunning = aiStream.status === 'queued' || aiStream.status === 'processing'
  const isAnyRunning = isCompiling || isAiRunning

  // ── Unsaved-changes guard (Finding: silent data loss on navigation) ──────
  const isDirty = title !== savedSnapshot.title || latexContent !== savedSnapshot.latex
  useEffect(() => { isDirtyRef.current = isDirty }, [isDirty])

  // Silent debounced autosave — persists edits without an explicit Save click.
  const autoSave = useCallback(async () => {
    const ownerAtStart = offlinePdfOwnerId
    const generationAtStart = offlinePdfIdentityRef.current.generation
    const isActive = () => isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart)
    if (!canEditDocument) return
    if (!title.trim() || title.length > 255) {
      setSaveError(
        !title.trim()
          ? 'A resume title is required'
          : 'Resume titles must be 255 characters or fewer',
      )
      return
    }
    // The imperative wrapper exists before Monaco itself mounts and reports
    // an empty value during that transition. React state is the authoritative
    // fallback; if the user intentionally clears the document, it is empty too.
    const content = editorRef.current?.getValue() || latexContent
    setAutoSaving(true)
    try {
      await apiClient.updateResume(resumeId, {
        title,
        latex_content: content,
        expected_latex_content: savedSnapshot.latex,
      })
      if (!isActive()) return
      setLatexContent(content)
      setSavedSnapshot({ title, latex: content })
      setLastSavedAt(Date.now())
      setSaveError(null)
      if (isLinkedVariant) {
        setIsLinkedVariant(false)
        setLinkedEditEnabled(false)
      }
    } catch (error) {
      if (!isActive()) return
      setSaveError(error instanceof Error ? error.message : 'Autosave failed')
    } finally {
      if (isActive()) setAutoSaving(false)
    }
  }, [canEditDocument, isCurrentOfflinePdfIdentity, isLinkedVariant, latexContent, offlinePdfOwnerId, resumeId, savedSnapshot.latex, title])

  useEffect(() => {
    // Never autosave mid-job (AI/compile mutate the buffer) or while offline.
    if (
      !canEditDocument
      || !isDirty
      || isAnyRunning
      || autoSaving
      || isSaving
      || ghPushing
      || dbxSyncing
      || confirmPull !== null
    ) return
    if (typeof navigator !== 'undefined' && !navigator.onLine) return
    const t = setTimeout(() => { void autoSave() }, 2500)
    return () => clearTimeout(t)
  }, [
    canEditDocument,
    isDirty,
    isAnyRunning,
    autoSaving,
    isSaving,
    ghPushing,
    dbxSyncing,
    confirmPull,
    title,
    latexContent,
    autoSave,
  ])

  // Warn before tab close / refresh / external navigation while dirty.
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (!isDirtyRef.current) return
      e.preventDefault()
      e.returnValue = ''
    }
    window.addEventListener('beforeunload', handler)
    return () => window.removeEventListener('beforeunload', handler)
  }, [])

  // Guard in-app navigation (breadcrumb / cover-letter / career links).
  const confirmDiscardIfDirty = useCallback(() => {
    if (!isDirtyRef.current) return true
    return window.confirm('You have unsaved changes. Leave this page without saving?')
  }, [])

  // Auto-compile handler (compile-only, not optimize)
  const handleAutoCompile = useCallback(async (content: string) => {
    const ownerAtStart = offlinePdfOwnerId
    const generationAtStart = offlinePdfIdentityRef.current.generation
    const isActive = () => isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart)
    if (isSubmitting || isAnyRunning || !canEditDocument || isLoading || !isOnline || !autoCompileIdentityReady) return null
    setIsSubmitting(true)
    try {
      const r = await apiClient.compileLatex({ latex_content: content, resume_id: resumeId, compiler })
      if (!r.success || !r.job_id) throw new Error(r.message)
      if (!isActive()) return null
      editorRef.current?.markAutoCompileCompiled?.(content)
      autoCompileTriggeredRef.current = true
      setCompileJobId(r.job_id)
      setLastStartedJobKind('compile')
      return r.job_id
    } catch (e) {
      // Auto-compile fires on a debounce rather than a click, so a hard failure to
      // even submit (network/API error, etc.) needs the same toast.error runCompile's
      // catch already gives a manual compile — deduped so a persistent failure
      // doesn't re-toast on every debounce tick while the user keeps typing.
      const msg = editorMode === 'source' ? e instanceof Error ? e.message : 'Auto-compile failed' : 'Could not refresh the preview. Please try again.'
      if (isActive() && lastAutoCompileErrorRef.current !== msg) {
        lastAutoCompileErrorRef.current = msg
        toast.error(msg)
      }
    } finally {
      if (isActive()) setIsSubmitting(false)
    }
  }, [autoCompileIdentityReady, canEditDocument, compiler, isAnyRunning, isCurrentOfflinePdfIdentity, isLoading, isOnline, isSubmitting, offlinePdfOwnerId, resumeId, editorMode])

  const queuePreview = usePreviewScheduler({ identity: `${sessionUserId ?? 'signed-out'}:${resumeId}:${compiler}`,
    enabled: (autoCompile || (engineSupported && editorMode === 'pdf')) && canEditDocument && !isLoading && isOnline && autoCompileIdentityReady, blocked: isAnyRunning || isSubmitting || isAiSubmitting,
    jobId: compileJobId, status: compileStream.status, submit: async (source) => await handleAutoCompile(source) ?? null,
  })

  // Visual edits share the same durable admission fence and latest-revision queue
  // as Source and Resume edits, including work already pending across mode changes.
  const handleVisualChange = useCallback((source: string) => {
    if (!canEditDocument) return
    setLatexContent(source)
    if (autoCompile) queuePreview(source)
  }, [canEditDocument, autoCompile, queuePreview])

  const saveResumeField = useCallback(async (node: ResumeEngineNode, text: string) => {
    const actionStarted = performance.now()
    const sourceAtStart = sourceAtRenderRef.current
    if (!engineSupported || !visibleEngineDocument || engineDocumentIdentityRef.current !== `${sessionUserId}:${resumeId}` || visibleEngineDocument.source_sha256 !== sourceHash || !canEditDocument) throw new Error('Stale document')
    const ownerAtStart = offlinePdfOwnerId
    const generationAtStart = offlinePdfIdentityRef.current.generation
    const token = apiClient.getAuthToken()
    if (!token) throw new Error('Session not ready')
    const result = await apiClient.patchEngineDocument(resumeId, {
      expected_content_revision: visibleEngineDocument.content_revision, expected_source_sha256: visibleEngineDocument.source_sha256,
      merge_disjoint: false, patches: [{ node_id: node.node_id, expected_node_revision: node.node_revision, text }],
    }, { authToken: token, isCurrent: () => isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart) && sourceAtRenderRef.current === sourceAtStart })
    if (!isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart)) return
    if (sourceAtRenderRef.current !== sourceAtStart) throw new Error('A newer local edit must be saved before applying this field response')
    setEngineDocument(result.document)
    setLatexContent(result.latex_content)
    setSavedSnapshot((previous) => ({ ...previous, latex: result.latex_content }))
    queuePreview(result.latex_content, actionStarted, true)
  }, [engineSupported, visibleEngineDocument, sourceHash, canEditDocument, resumeId, queuePreview, sessionUserId, offlinePdfOwnerId, isCurrentOfflinePdfIdentity])

  const reorderResumeStructure = useCallback(async (containerId: string, orderedIds: string[]) => {
    const actionStarted = performance.now()
    const sourceAtStart = sourceAtRenderRef.current
    if (!engineSupported || !visibleEngineDocument || visibleEngineDocument.source_mode !== 'managed'
      || engineDocumentIdentityRef.current !== `${sessionUserId}:${resumeId}`
      || visibleEngineDocument.source_sha256 !== sourceHash || !canEditDocument) throw new Error('Stale document')
    const ownerAtStart = offlinePdfOwnerId
    const generationAtStart = offlinePdfIdentityRef.current.generation
    const token = apiClient.getAuthToken()
    if (!token) throw new Error('Session not ready')
    const result = await apiClient.reorderEngineDocument(resumeId, {
      expected_content_revision: visibleEngineDocument.content_revision, expected_source_sha256: visibleEngineDocument.source_sha256,
      container_id: containerId, ordered_ids: orderedIds,
    }, { authToken: token, isCurrent: () => isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart) && sourceAtRenderRef.current === sourceAtStart })
    if (!isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart)) return
    if (sourceAtRenderRef.current !== sourceAtStart) throw new Error('A newer local edit must be saved before applying this order')
    setEngineDocument(result.document)
    setLatexContent(result.latex_content)
    setSavedSnapshot((previous) => ({ ...previous, latex: result.latex_content }))
    queuePreview(result.latex_content, actionStarted, true)
  }, [engineSupported, visibleEngineDocument, sourceHash, canEditDocument, resumeId, queuePreview, sessionUserId, offlinePdfOwnerId, isCurrentOfflinePdfIdentity])

  // Surface auto-compile job failures (e.g. invalid LaTeX) the same way a manual
  // compile is — runCompile switches to the Logs tab on submit so a failure is
  // immediately visible there; auto-compile deliberately does NOT steal focus away
  // from the editor on every debounce tick, so a toast is the only prompt that
  // reaches a user who isn't already looking at the Logs tab. One toast per
  // distinct error, not one per debounce tick — cleared on the next successful compile.
  useEffect(() => {
    if (!autoCompileTriggeredRef.current) return
    if (compileStream.status === 'failed') {
      const msg = editorMode === 'source' ? compileStream.error || 'Auto-compile failed — open the Logs tab for details' : 'Could not refresh the preview. Your edits are saved in this draft.'
      if (lastAutoCompileErrorRef.current !== msg) {
        lastAutoCompileErrorRef.current = msg
        toast.error(previewErrorMessage(msg, editorMode === 'pdf'), { description: editorMode === 'source' ? 'Open the Logs tab for details.' : 'Try again or choose another layout.' })
      }
    } else if (compileStream.status === 'completed') {
      lastAutoCompileErrorRef.current = null
    }
  }, [compileStream.status, compileStream.error, editorMode])

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

  const handleAutoFit = useCallback(async (intensity?: number) => {
    if (!canEditDocument) {
      toast.error('Detach this linked variant before changing its formatting')
      return
    }
    const content = editorRef.current?.getValue() || latexContent
    if (!content.trim()) return
    const ownerAtStart = offlinePdfOwnerId
    const generationAtStart = offlinePdfIdentityRef.current.generation
    const isActive = () => isCurrentOfflinePdfIdentity(ownerAtStart, resumeId, generationAtStart)
    setIsAutoFitSubmitting(true)
    autoFitBaselineRef.current = content
    autoFitIdentityRef.current = { ownerId: ownerAtStart, resumeId, generation: generationAtStart }
    try {
      const response = await apiClient.autoFitResume({
        latex_content: content,
        resume_id: resumeId,
        compiler,
        intensity,
      })
      if (!response.success || !response.job_id) throw new Error(response.message)
      if (!isActive()) return
      autoFitJobRef.current = response.job_id
      handledAutoFitJobRef.current = null
      userInitiatedJobRef.current = true
      setCompileJobId(response.job_id)
      setLastStartedJobKind('compile')
      setRightTab(editorMode === 'source' ? 'logs' : 'preview')
      toast.success(intensity == null ? 'Finding the lightest one-page fit…' : `Testing ${intensity}% fit strength…`)
    } catch (error) {
      if (!isActive()) return
      autoFitBaselineRef.current = null
      setIsAutoFitSubmitting(false)
      toast.error(error instanceof Error ? error.message : 'Auto-fit could not start')
    }
  }, [canEditDocument, compiler, isCurrentOfflinePdfIdentity, latexContent, offlinePdfOwnerId, resumeId, editorMode])

  useEffect(() => {
    const jobId = autoFitJobRef.current
    const identity = autoFitIdentityRef.current
    const isActive = () => identity !== null && isCurrentOfflinePdfIdentity(identity.ownerId, identity.resumeId, identity.generation)
    if (!jobId || !identity || !isActive() || compileJobId !== jobId || handledAutoFitJobRef.current === jobId) return
    if (compileStream.status === 'failed' || compileStream.status === 'cancelled') {
      handledAutoFitJobRef.current = jobId
      autoFitBaselineRef.current = null
      setIsAutoFitSubmitting(false)
      toast.error('Auto-fit did not complete; your document was not changed')
      return
    }
    if (compileStream.status !== 'completed') return
    handledAutoFitJobRef.current = jobId
    void apiClient.getJobResult(jobId).then((result) => {
      if (!isActive()) return
      const candidate = result.fitted_latex
      if (!result.fit_succeeded || !candidate) {
        toast.error('The resume still exceeds one page at the safe readability limit. No changes were applied.')
        return
      }
      const current = editorRef.current?.getValue() || latexContent
      if (current !== autoFitBaselineRef.current) {
        toast.error('Your resume changed while auto-fit was running. Run it again to avoid overwriting edits.')
        return
      }
      pushUndo('Before one-page auto-fit')
      editorRef.current?.setValue(candidate, { reveal: false })
      setLatexContent(candidate)
      toast.success(`One-page formatting applied at ${result.fit_intensity ?? 0}% strength`)
    }).catch((error) => {
      if (isActive()) toast.error(error instanceof Error ? error.message : 'Auto-fit result could not be loaded')
    }).finally(() => {
      if (isActive()) {
        autoFitBaselineRef.current = null
        setIsAutoFitSubmitting(false)
      }
    })
  }, [compileJobId, compileStream.status, isCurrentOfflinePdfIdentity, latexContent, pushUndo])

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

  const statusText = editorMode === 'wysiwyg'
    ? isAnyRunning ? 'Preparing your résumé…' : compileStream.status === 'failed' || aiStream.status === 'failed' ? 'Preview unavailable. Your draft is preserved.' : pdfUrl ? 'Preview ready' : 'Résumé ready to edit'
    : isAiRunning
    ? `AI: ${aiStream.message || aiStream.stage || 'processing…'}`
    : isCompiling
    ? `Compiling… ${compileStream.percent}%`
    : compileStream.status === 'completed'
    ? 'Compiled successfully'
    : aiStream.status === 'completed'
    ? `AI complete · ATS ${aiStream.atsScore != null ? Math.round(aiStream.atsScore) : '—'}`
    : aiStream.status === 'failed'
    ? `AI failed: ${aiStream.error || 'error'}`
    : compileStream.status === 'failed'
    ? `Compile failed: ${compileStream.error || 'error'}`
    : 'LaTeX editor ready'

  const currentLatex = editorMode === 'source' ? editorRef.current?.getValue() || latexContent : latexContent
  const outline = buildLatexOutline(currentLatex)

  // Right-panel tab hierarchy: a few primary tabs stay inline; the rest live in
  // a "More" overflow menu (Finding: 17 equally-weighted tabs).
  const moreTabIds: RightTab[] = ['generate', 'comments', 'review', 'chat', 'references', 'interview', 'proofread', 'packages', 'linter', 'symbols', 'changes', 'suggestions', 'docs', 'layout', 'snippets', 'macros', 'tikz']

  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-bg">
        <LoadingSpinner />
      </div>
    )
  }

  if (resumeLoadError) {
    return (
      <div className="flex h-screen items-center justify-center bg-bg px-6">
        <div role="alert" className="max-w-md rounded-[var(--radius-xl)] border border-line bg-surface p-6 text-center shadow-[var(--shadow-2)]">
          <AlertCircle className="mx-auto mb-3 text-danger" size={24} />
          <h1 className="text-base font-semibold text-fg">Resume could not be loaded</h1>
          <p className="mt-2 text-sm text-fg-3">{resumeLoadError}</p>
          <div className="mt-5 flex justify-center gap-2">
            <Link href="/workspace" className="rounded-[var(--radius-md)] border border-line px-4 py-2 text-sm text-fg-2 hover:bg-surface-2">
              Back to workspace
            </Link>
            <button onClick={() => window.location.reload()} className="rounded-[var(--radius-md)] bg-accent px-4 py-2 text-sm font-medium text-accent-fg hover:brightness-110">
              Retry
            </button>
          </div>
        </div>
      </div>
    )
  }

  if (sessionError && !sessionData && !offlineDraftLoaded && !offlinePdfLoaded) {
    return <SessionLoadError area="Resume editor" />
  }

  if (!sessionData && !offlineDraftLoaded && !offlinePdfLoaded) return null

  return (
    <div data-editor-mode={editorMode === 'source' ? 'source' : 'visual'} className="flex h-screen flex-col overflow-hidden bg-bg">

      {/* ── TOP HEADER ── */}
      <header className="flex h-11 shrink-0 items-center gap-2 border-b border-line bg-surface px-4">
        <div className="flex min-w-0 max-w-[40%] shrink-0 items-center gap-1.5 text-xs">
          <Link
            href="/workspace"
            onClick={(e) => { if (!confirmDiscardIfDirty()) e.preventDefault() }}
            className="hidden shrink-0 text-fg-3 transition hover:text-fg-2 sm:inline"
          >
            Workspace
          </Link>
          <ChevronRight size={12} className="hidden shrink-0 text-fg-3 sm:block" />
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            disabled={!canEditDocument}
            maxLength={255}
            aria-invalid={Boolean(saveError && (!title.trim() || title.length > 255))}
            className="w-[120px] min-w-0 max-w-[280px] bg-transparent text-sm font-medium text-fg-2 outline-none transition placeholder:text-fg-3 hover:text-fg focus:text-fg sm:w-auto"
            placeholder="Untitled"
          />
          {/* Save status indicator */}
          <span
            role="status"
            aria-live="polite"
            title={lastSavedAt ? `Last saved ${new Date(lastSavedAt).toLocaleTimeString()}` : undefined}
            className={`hidden shrink-0 items-center gap-1 text-[10px] font-medium sm:flex ${
              autoSaving ? 'text-accent-strong' : saveError ? 'text-err' : isDirty ? 'text-warn' : 'text-fg-3'
            }`}
          >
            {autoSaving ? (
              <Loader2 size={10} className="animate-spin" />
            ) : (
              <span className={`h-1.5 w-1.5 rounded-full ${saveError ? 'bg-err' : isDirty ? 'bg-warn' : 'bg-ok'}`} />
            )}
            {autoSaving ? 'Saving…' : saveError ? `Save failed: ${saveError}` : isDirty ? 'Unsaved changes' : 'Saved'}
          </span>
        </div>

        <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto whitespace-nowrap scrollbar-none [&>*]:shrink-0 [&>*:first-child]:ml-auto">
          <button
            onClick={() => setShowImportModal(true)}
            className="flex items-center gap-1.5 rounded-[var(--radius-md)] px-2.5 py-1.5 text-[11px] font-medium text-fg-3 transition hover:bg-surface-2 hover:text-fg"
          >
            <Upload size={12} />
            Import
          </button>

          <ContrastToggle />
          <ModeToggle />

          <ExportDropdown
            visualOnly={editorMode !== 'source'}
            resumeId={resumeId}
            latexContent={latexContent}
            onPdfExport={handleDownload}
            variant="toolbar"
          />

          {/* Tools overflow menu — collapses niche formatting/analysis tools */}
          <div className="relative">
            <button
              ref={toolsTriggerRef}
              onClick={() => { if (toolsMenuOpen) { setToolsMenuOpen(false) } else { openToolsMenu() } }}
              aria-haspopup="menu"
              aria-expanded={toolsMenuOpen}
              hidden={editorMode !== 'source'}
              title="Formatting & analysis tools"
              className={`flex items-center gap-1.5 rounded-[var(--radius-md)] px-2.5 py-1.5 text-[11px] font-medium transition ${
                academicReport?.is_academic_cv
                  ? 'text-accent-strong hover:bg-accent/10 hover:text-accent-strong'
                  : 'text-fg-3 hover:bg-surface-2 hover:text-fg'
              }`}
            >
              <SlidersHorizontal size={12} />
              Tools
              <ChevronDown size={11} />
            </button>
            {editorMode === 'source' && toolsMenuOpen && toolsMenuPos && createPortal(
              <>
                <div className="fixed inset-0 z-[200]" onClick={() => setToolsMenuOpen(false)} />
                <div
                  role="menu"
                  aria-label="Formatting and analysis tools"
                  className="z-[201] w-56 rounded-[var(--radius-md)] border border-line bg-surface p-1 shadow-[var(--shadow-2)]"
                  style={{ position: 'fixed', top: toolsMenuPos.top, right: toolsMenuPos.right }}
                >
                  {([
                    { icon: QrCode, label: 'Insert QR code', action: () => setQrInserterOpen(true) },
                    { icon: Calendar, label: 'Standardize dates', action: () => setDateStandardizerOpen(true) },
                    { icon: Clock, label: 'Analyze experience age', action: () => setAgeAnalysisOpen(true) },
                    { icon: Phone, label: 'Normalize contacts', action: () => setContactFormatterOpen(true) },
                    { icon: DollarSign, label: 'Estimate salary', action: () => setSalaryEstimatorOpen(true) },
                    { icon: SlidersHorizontal, label: 'Reorder sections (AI)', action: () => setSectionReorderOpen(true) },
                    { icon: Github, label: 'Import top projects', action: () => setImportModalOpen(true) },
                  ] as const).map(({ icon: Icon, label, action }) => (
                    <button
                      key={label}
                      role="menuitem"
                      onClick={() => { action(); setToolsMenuOpen(false) }}
                      className="flex w-full items-center gap-2 rounded-[var(--radius-sm)] px-2.5 py-1.5 text-left text-[11px] font-medium text-fg-2 transition hover:bg-surface-2 hover:text-fg"
                    >
                      <Icon size={12} className="shrink-0 text-fg-3" />
                      {label}
                    </button>
                  ))}
                  <div className="my-1 h-px bg-line" />
                  <button
                    role="menuitem"
                    onClick={() => { setAcademicConvertOpen(true); setToolsMenuOpen(false) }}
                    className={`flex w-full items-center gap-2 rounded-[var(--radius-sm)] px-2.5 py-1.5 text-left text-[11px] font-medium transition hover:bg-surface-2 ${
                      academicReport?.is_academic_cv ? 'text-accent-strong' : 'text-fg-2 hover:text-fg'
                    }`}
                  >
                    <GraduationCap size={12} className="shrink-0" />
                    Convert CV → Industry
                    {academicReport?.is_academic_cv && (
                      <span className="ml-auto h-1.5 w-1.5 rounded-full bg-accent-strong" />
                    )}
                  </button>
                </div>
              </>,
              document.body
            )}
          </div>

          <Link
            href={`/workspace/${resumeId}/cover-letter`}
            onClick={(e) => { if (!confirmDiscardIfDirty()) e.preventDefault() }}
            className="flex items-center gap-1.5 rounded-[var(--radius-md)] px-2.5 py-1.5 text-[11px] font-medium text-accent-strong transition hover:bg-accent/10 hover:text-accent-strong"
          >
            <Mail size={12} />
            Cover Letter
          </Link>

          <Link
            href={`/workspace/${resumeId}/career`}
            onClick={(e) => { if (!confirmDiscardIfDirty()) e.preventDefault() }}
            className="flex items-center gap-1.5 rounded-[var(--radius-md)] px-2.5 py-1.5 text-[11px] font-medium text-ok transition hover:bg-ok/10 hover:text-ok"
          >
            <TrendingUp size={12} />
            Career Path
          </Link>

          {/* Create Variant button */}
          <div className="relative">
            <button
              ref={forkTriggerRef}
              onClick={() => { if (forkPopoverOpen) { setForkPopoverOpen(false) } else { openForkPopover() } }}
              className="flex items-center gap-1.5 rounded-[var(--radius-md)] px-2.5 py-1.5 text-[11px] font-medium text-fg-3 transition hover:bg-surface-2 hover:text-fg"
            >
              <GitFork size={12} />
              Variant
            </button>
            {forkPopoverOpen && forkPopoverPos && createPortal(
              <>
                {/* Backdrop */}
                <div className="fixed inset-0 z-[200]" onClick={() => setForkPopoverOpen(false)} />
                {/* Popover — fixed positioning from trigger rect so the scrolling toolbar can't clip it */}
                <div
                  className="z-[201] w-64 rounded-[var(--radius-md)] border border-line bg-surface p-3 shadow-[var(--shadow-2)]"
                  style={{ position: 'fixed', top: forkPopoverPos.top, right: forkPopoverPos.right }}
                >
                  <input
                    type="text"
                    value={forkTitleInput}
                    onChange={e => setForkTitleInput(e.target.value)}
                    onKeyDown={e => { if (e.key === 'Enter') handleCreateVariant(); if (e.key === 'Escape') setForkPopoverOpen(false) }}
                    placeholder="Variant title"
                    autoFocus
                    className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-2 py-1.5 text-xs text-fg outline-none focus:border-accent mb-2"
                  />
                  <div className="flex gap-2 justify-end">
                    <button onClick={() => setForkPopoverOpen(false)} className="px-2 py-1 text-[10px] text-fg-3 hover:text-fg-2">Cancel</button>
                    <button onClick={handleCreateVariant} disabled={isForkingResume} className="rounded-[var(--radius-md)] bg-accent/20 px-3 py-1 text-[10px] font-semibold text-accent-strong ring-1 ring-accent/20 hover:bg-accent/25 disabled:opacity-50">
                      {isForkingResume ? 'Creating...' : 'Create'}
                    </button>
                  </div>
                </div>
              </>,
              document.body
            )}
          </div>

          <button
            onClick={handleSave}
            disabled={isSaving || !canEditDocument}
            className="flex items-center gap-1.5 rounded-[var(--radius-md)] px-2.5 py-1.5 text-[11px] font-medium text-fg-3 transition hover:bg-surface-2 hover:text-fg disabled:opacity-40"
          >
            <Save size={12} />
            {isSaving ? 'Saving…' : 'Save'}
          </button>

          <SaveCheckpointPopover resumeId={resumeId} onSaved={handleCheckpointSaved} />

          <button
            type="button"
            onClick={() => setDocumentAssistantOpen(true)}
            disabled={!collabIsOwner || documentType === 'presentation'}
            title="Chat with the document assistant"
            className="flex items-center gap-1.5 rounded-[var(--radius-md)] px-2.5 py-1.5 text-[11px] font-medium text-fg-3 transition hover:bg-surface-2 hover:text-fg disabled:opacity-40"
          >
            <MessageSquare size={12} />
            Ask AI
          </button>

          <button
            onClick={() => setShareModalOpen(true)}
            title={shareToken ? 'Manage share link' : 'Share resume'}
            aria-label={shareToken ? 'Manage share link' : 'Share resume'}
            className={`flex items-center gap-1.5 rounded-[var(--radius-md)] px-2.5 py-1.5 text-[11px] font-medium transition ${
              shareToken
                ? 'text-accent-strong hover:bg-accent/10 hover:text-accent-strong'
                : 'text-fg-3 hover:bg-surface-2 hover:text-fg'
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
                className={`flex items-center gap-1 rounded-[var(--radius-md)] px-2 py-1.5 text-[11px] font-medium transition ${
                  ghSyncEnabled
                    ? 'bg-surface-2 text-fg ring-1 ring-line'
                    : 'text-fg-3 hover:text-fg-2'
                }`}
              >
                {ghTogglingSync ? <Loader2 size={11} className="animate-spin" /> : <Github size={11} />}
                Sync
              </button>
              {ghSyncEnabled && (
                <>
                  <button
                    onClick={handlePushToGitHub}
                    disabled={ghPushing || autoSaving || isSaving}
                    title="Push to GitHub"
                    className="flex items-center gap-1 rounded-[var(--radius-md)] px-2 py-1.5 text-[11px] font-medium text-fg-3 transition hover:bg-surface-2 hover:text-fg disabled:opacity-40"
                  >
                    {ghPushing ? <Loader2 size={11} className="animate-spin" /> : <Upload size={11} />}
                    Push
                  </button>
                  <button
                    onClick={handlePullFromGitHub}
                    disabled={ghPushing || autoSaving || isSaving}
                    title="Pull from GitHub"
                    className="flex items-center gap-1 rounded-[var(--radius-md)] px-2 py-1.5 text-[11px] font-medium text-fg-3 transition hover:bg-surface-2 hover:text-fg disabled:opacity-40"
                  >
                    <Download size={11} />
                    Pull
                  </button>
                </>
              )}
            </>
          )}

          {/* Dropbox sync (Feature 77) — only show if user has connected Dropbox */}
          {dbxConnected && (
            <>
              <button
                onClick={handleToggleDropboxSync}
                disabled={dbxTogglingSync}
                title={dbxSyncEnabled ? 'Disable Dropbox sync' : 'Enable Dropbox sync'}
                className={`flex items-center gap-1 rounded-[var(--radius-md)] px-2 py-1.5 text-[11px] font-medium transition ${
                  dbxSyncEnabled
                    ? 'bg-surface-2 text-fg ring-1 ring-line'
                    : 'text-fg-3 hover:text-fg-2'
                }`}
              >
                {dbxTogglingSync ? <Loader2 size={11} className="animate-spin" /> : <Cloud size={11} />}
                Dropbox
              </button>
              {dbxSyncEnabled && (
                <>
                  <button
                    onClick={handlePushToDropbox}
                    disabled={dbxSyncing}
                    title="Push to Dropbox"
                    className="flex items-center gap-1 rounded-[var(--radius-md)] px-2 py-1.5 text-[11px] font-medium text-fg-3 transition hover:bg-surface-2 hover:text-fg disabled:opacity-40"
                  >
                    {dbxSyncing ? <Loader2 size={11} className="animate-spin" /> : <Upload size={11} />}
                    Push
                  </button>
                  <button
                    onClick={handlePullFromDropbox}
                    disabled={dbxSyncing}
                    title="Pull from Dropbox"
                    className="flex items-center gap-1 rounded-[var(--radius-md)] px-2 py-1.5 text-[11px] font-medium text-fg-3 transition hover:bg-surface-2 hover:text-fg disabled:opacity-40"
                  >
                    <Download size={11} />
                    Pull
                  </button>
                </>
              )}
            </>
          )}

          <div className="mx-1 h-3.5 w-px bg-line" />

          {editorMode === 'source' && <CompilerSelector
            resumeId={resumeId}
            current={compiler}
            onChange={(c) => {
              setCompiler(c)
              setCompileSettings((prev) => ({ ...prev, compiler: c }))
            }}
            disabled={isAnyRunning}
          />}

          <button
            hidden={editorMode !== 'source'}
            onClick={() => setCompileSettingsOpen(true)}
            title="Compile settings"
            aria-label="Compile settings"
            className="flex items-center gap-1 rounded-[var(--radius-md)] px-2 py-1.5 text-[11px] font-medium text-fg-3 transition hover:bg-surface-2 hover:text-fg-2"
          >
            <Settings2 size={11} />
          </button>

          {/* Collaborators button (Feature 40) */}
          <button
            onClick={() => setCollabOpen(true)}
            title="Collaborators"
            className="relative flex items-center gap-1 rounded-[var(--radius-md)] px-2 py-1.5 text-[11px] font-medium text-fg-3 transition hover:bg-surface-2 hover:text-fg-2"
          >
            <Users size={11} />
            {presenceUsers.length > 0 && (
              <span className="absolute -right-0.5 -top-0.5 flex h-3 w-3 items-center justify-center rounded-full bg-accent text-[8px] font-bold text-accent-fg">
                {presenceUsers.length}
              </span>
            )}
          </button>

          <div className="mx-1 h-3.5 w-px bg-line" />

          <button
            onClick={toggleAutoCompile}
            title="Refresh the preview automatically after editing"
            aria-label={editorMode === 'source' ? 'Auto-compile on change' : 'Automatic preview'}
            aria-pressed={autoCompile}
            className={`flex items-center gap-1 rounded-[var(--radius-md)] px-2 py-1.5 text-[11px] font-medium transition ${
              autoCompile
                ? 'bg-accent/20 text-accent-strong ring-1 ring-accent/30'
                : 'text-fg-3 hover:text-fg-2'
            }`}
          >
            <Zap size={11} />
            Auto
          </button>

          {(userPlan === 'pro' || userPlan === 'byok') && (
            <span
              title="Your compilations are processed with priority in the queue"
              className="flex items-center gap-1 rounded-[var(--radius-md)] bg-accent/15 px-2 py-1.5 text-[10px] font-semibold text-accent-strong ring-1 ring-accent/20"
            >
              <Zap size={9} className="fill-current" />
              Priority
            </span>
          )}

          <button
            onClick={runCompile}
            disabled={isSubmitting || isAnyRunning}
            className="flex items-center gap-1.5 rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-1.5 text-[11px] font-semibold text-fg transition hover:bg-surface-2 disabled:opacity-40"
          >
            {isCompiling
              ? <Loader2 size={11} className="animate-spin" />
              : <Play size={11} className="fill-current" />}
            {isCompiling ? 'Preparing…' : editorMode === 'source' ? 'Compile' : 'Update preview'}
          </button>

          <button
            onClick={() => setRightTab('ai')}
            className={`flex items-center gap-1.5 rounded-[var(--radius-md)] border px-3 py-1.5 text-[11px] font-semibold transition ${
              isAiRunning
                ? 'border-accent bg-accent/15 text-accent-strong'
                : 'border-accent/20 bg-accent-soft text-accent-strong hover:brightness-110'
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
        <div className="flex h-7 shrink-0 items-center justify-between border-b border-accent/10 bg-accent/5 px-4">
          <span className="text-xs text-fg-2">
            Variant of: <span className="font-medium text-fg-2">{parentTitle}</span>
            {isLinkedVariant && ' · source-linked'}
          </span>
          <div className="flex items-center gap-3">
            {isLinkedVariant && (
              <Link href={`/workspace/variant/${resumeId}`} className="text-xs font-semibold text-accent-strong hover:underline">
                Manage visibility
              </Link>
            )}
            {isLinkedVariant && !linkedEditEnabled && (
              <button
                type="button"
                onClick={() => setLinkedEditEnabled(true)}
                className="text-xs font-semibold text-warn hover:underline"
              >
                Detach and edit LaTeX
              </button>
            )}
            <button
              onClick={handleCompareWithParent}
              className="text-xs font-semibold text-accent-strong transition hover:text-accent-strong"
            >
              Compare with Parent
            </button>
          </div>
        </div>
      )}

      {/* Resize drag overlay */}
      {isDraggingResize && (
        <div className="fixed inset-0 z-50" style={{ cursor: 'col-resize' }} />
      )}

      {/* ── MAIN BODY ── */}
      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto md:flex-row md:overflow-hidden">

        {/* ── Left: Outline sidebar (collapsible) ── */}
        {editorMode === 'source' && <aside
          id="document-outline"
          className={`flex shrink-0 flex-col border-b border-line bg-surface transition-all duration-200 md:border-b-0 md:border-r ${
            showOutline ? 'max-h-52 w-full md:max-h-none md:w-48' : 'h-8 w-full md:h-auto md:w-8'
          }`}
        >
          <button
            onClick={() => setShowOutline((v) => !v)}
            aria-controls="document-outline-items"
            aria-expanded={showOutline}
            aria-label={showOutline ? 'Hide document outline' : 'Show document outline'}
            className={`flex h-8 w-full shrink-0 items-center border-b border-line px-1.5 text-fg-3 transition hover:text-fg-2 ${
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

          {showOutline && editorMode === 'source' && (
            <div id="document-outline-items" className="min-h-0 flex-1 overflow-hidden">
              <OutlinePanel latex={currentLatex} onJump={handleOutlineJump} />
            </div>
          )}
        </aside>}

        {/* ── Editor ── */}
        <section className="flex min-h-[55vh] w-full min-w-0 flex-col md:min-h-0 md:w-auto" style={{ flex: '3 1 0%' }}>
          <div className="flex h-8 shrink-0 items-center gap-2 border-b border-line bg-surface px-3">
            <div className="flex items-center gap-1.5 rounded-[var(--radius-md)] bg-surface-2 px-2.5 py-1 text-[11px] font-medium text-fg-2">
              <FileText size={11} className="text-fg-3" />
              {title || 'Untitled'}{editorMode === 'source' ? '.tex' : ''}
            </div>
            {engineSupported && sessionUserId && <ResumeOriginalPdf key={`${sessionUserId}:${resumeId}`} resumeId={resumeId} ownerId={sessionUserId} />}
            <div className="ml-auto flex items-center gap-0.5 rounded-[var(--radius-md)] bg-surface-2 p-0.5">
              <button disabled={!engineSupported} onClick={() => handleToggleEditorMode('pdf')} aria-pressed={editorMode === 'pdf'}
                className={`rounded px-2 py-0.5 text-[10px] font-medium disabled:opacity-50 ${editorMode === 'pdf' ? 'bg-surface text-fg' : 'text-fg-3'}`}>
                Resume
              </button>
              <button
                onClick={() => handleToggleEditorMode('source')}
                aria-pressed={editorMode === 'source'}
                className={`flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-medium transition ${
                  editorMode === 'source'
                    ? 'bg-surface-2 text-fg'
                    : 'text-fg-3 hover:text-fg-2'
                }`}
              >
                <Code2 size={10} />
                Source
              </button>
              <button
                onClick={() => handleToggleEditorMode('wysiwyg')}
                aria-pressed={editorMode === 'wysiwyg'}
                className={`flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-medium transition ${
                  editorMode === 'wysiwyg'
                    ? 'bg-surface-2 text-fg'
                    : 'text-fg-3 hover:text-fg-2'
                }`}
              >
                <LayoutTemplate size={10} />
                Visual
              </button>
            </div>
          </div>
          <EngineCapabilityNotice capability={engineCapability} />
          {/* Offline status banner (Feature 79F) */}
          <OfflineBanner pendingCount={offlinePendingCount} />
          {academicReport?.is_academic_cv && (
            <div className="flex shrink-0 items-center justify-between border-b border-accent/20 bg-accent/10 px-4 py-1.5">
              <span className="text-[11px] text-accent-strong">
                Academic CV detected ({academicReport.estimated_pages} pages, {academicReport.detected_sections.join(', ') || 'academic signals'}). Convert it into an industry resume variant.
              </span>
              <button
                onClick={() => setAcademicConvertOpen(true)}
                className="ml-3 text-[11px] text-accent-strong underline hover:text-fg"
              >
                Convert with AI →
              </button>
            </div>
          )}
          {/* Page overflow warning banner.
              Suppressed for document types where >1 page is legitimate: slide/
              presentation decks and academic CVs (which routinely run long — the
              "1 page" convention is a resume norm, not a CV one). Mirrors the
              document-type gating already used for the live ATS badge below. */}
          {pageCount !== null && pageCount > 1 && documentType !== 'presentation' && !academicReport?.is_academic_cv && (
            <div className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-b border-warn/20 bg-warn/10 px-4 py-2">
              <span className="text-[11px] text-warn">
                ⚠ Your resume is {pageCount} pages. Most recruiters prefer 1 page.
              </span>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => void handleAutoFit()}
                  disabled={isAutoFitSubmitting || isAnyRunning || !canEditDocument}
                  className="rounded border border-warn/30 bg-surface px-2 py-1 text-[11px] font-semibold text-warn disabled:opacity-50"
                >
                  Auto-fit formatting
                </button>
                <label className="flex items-center gap-1 text-[11px] text-warn">
                  Strength
                  <input
                    aria-label="Fit strength"
                    type="range"
                    min={25}
                    max={100}
                    step={25}
                    value={autoFitIntensity}
                    onChange={(event) => setAutoFitIntensity(Number(event.target.value))}
                    className="w-20 accent-[var(--warn)]"
                  />
                  {autoFitIntensity}%
                </label>
                <button
                  type="button"
                  onClick={() => void handleAutoFit(autoFitIntensity)}
                  disabled={isAutoFitSubmitting || isAnyRunning || !canEditDocument}
                  className="text-[11px] text-warn underline disabled:opacity-50"
                >
                  Try strength
                </button>
                <button
                  type="button"
                  aria-label="Trim with AI →"
                  onClick={handleTrimToOnePage}
                  disabled={isAiSubmitting || isAnyRunning || !canEditDocument}
                  className="text-[11px] text-warn underline disabled:opacity-50"
                >
                  Trim content with AI →
                </button>
              </div>
            </div>
          )}
          <div className="relative min-h-0 flex-1">
            {/* WYSIWYG mode (Feature 78) */}
            {editorMode === 'pdf' ? (
              <ResumeFieldsEditor document={visibleEngineDocument} currentSourceHash={sourceHash} selectedNode={selectedEngineNode}
                onSelect={setSelectedEngineNode} onSave={saveResumeField} onReorder={reorderResumeStructure} readOnly={!canEditDocument || !engineSupported} error={engineCapability.status === 'error' ? 'Resume fields are unavailable. Check the message above, or choose Source.' : engineDocumentError} />
            ) : editorMode === 'wysiwyg' ? (
              <VisualResumeEditor value={latexContent} onChange={handleVisualChange} readOnly={!canEditDocument} />
            ) : isMobile ? (
              /* Mobile: lightweight CodeMirror editor (Feature 79E) */
              <MobileEditor
                ref={editorRef}
                value={latexContent}
                onChange={setLatexContent}
                onSave={handleSave}
                onCompile={runCompile}
                readOnly={!canEditDocument}
              />
            ) : (
            <LaTeXEditor
              editorRef={editorRef}
              onEditorReady={setMacroEditor}
              value={latexContent}
              onChange={setLatexContent}
              bibliographyBibTeX={bibliographyBibTeX}
              readOnly={!canEditDocument}
              logLines={logLines}
              onSave={handleSave}
              onCompile={runCompile}
              onCursorChange={handleCursorChange}
              onCursorLineChange={handleCursorLineChange}
              syncLine={syncFromLine}
              syncRequestId={syncFromRequestId}
              onSyncToPdf={(line) => {
                setCursorLine(line)
                setSourceSyncLine(line)
                setSourceSyncRequestId((value) => value + 1)
              }}
              onAutoCompile={autoCompile ? queuePreview : undefined}
              autoCompileEnabled={autoCompile && canEditDocument && !isLoading && isOnline && autoCompileIdentityReady}
              autoCompileBusy={false}
              autoCompileDocumentKey={`${sessionUserId ?? 'anonymous'}:${resumeId}`}
              autoCompileDebounceMs={0}
              atsScore={documentType === 'presentation' ? null : quickATSScore}
              atsScoreLoading={documentType === 'presentation' ? false : quickATSLoading}
              onATSBadgeClick={() => setDeepPanelOpen(true)}
              confidenceScore={confidenceResult?.overall ?? null}
              confidenceScoreLoading={confidenceLoading}
              onConfidenceBadgeClick={() => setConfidencePanelOpen(true)}
              onExplainError={handleExplainError}
              onWritingAssistantAction={handleWritingAssistantAction}
              pageCount={pageCount}
              warnOnMultiplePages={documentType !== 'presentation' && !academicReport?.is_academic_cv}
              renderedText={extractedPdfText}
              onCursorInSummarySection={handleCursorInSummarySection}
              proofreadIssues={proofreadIssues}
              lintIssues={lintIssues}
              spellCheckIssues={spellCheckIssues}
              spellCheckEnabled={spellCheckEnabled}
              spellCheckLoading={spellCheckLoading}
              getPersonalDictionary={getPersonalDictionary}
              onAddWordToDictionary={addWordToDictionary}
              onSpellCheckToggle={() => {
                setSpellCheckEnabled((prev) => {
                  const next = !prev
                  localStorage.setItem('latexy_spell_check', String(next))
                  return next
                })
              }}
              collabEnabled={!!(sessionData?.session?.token)}
              collabResumeId={resumeId}
              collabUser={sessionData?.session?.token ? {
                // Email addresses are never sent as collaboration display
                // metadata. The relay supplies the authenticated chat label.
                name: sessionData.user?.name || 'Collaborator',
                color: `hsl(${Math.abs(sessionData.user?.id?.charCodeAt(0) ?? 0) % 360}, 70%, 60%)`,
              } : undefined}
              collabRole={collabRole}
              onPresenceChange={setPresenceUsers}
              onChatTransport={setChatTransport}
              suggestionPresence={suggestionPresence}
              onSuggestionPresenceChange={handleRemoteSuggestionPresence}
              suggestionDecisions={suggestionDecisions}
              onSuggestionDecisionsChange={confirmRemoteSuggestionDecisions}
              trackedChanges={trackedChanges}
              onTrackedChangesUpdate={setTrackedChanges}
              onShowDocs={(cmd) => {
                setDocCommand(cmd)
                setRightTab('docs')
              }}
            />
            )} {/* end desktop LaTeXEditor */}

            {/* AI Summary Widget trigger — shown when cursor is in summary section */}
            {cursorInSummarySection && !summaryWidgetOpen && !bulletWidgetOpen && (
              <button
                onClick={handleOpenSummaryWidget}
                title="AI Summary Generator"
                className="absolute left-1 z-20 flex items-center gap-1 rounded-[var(--radius-md)] bg-accent/20 px-1.5 py-0.5 text-[10px] font-semibold text-accent-strong ring-1 ring-accent/20 transition hover:bg-accent/25"
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
              resumeId={resumeId}
              jobDescription={jobDescription}
              documentLatex={latexContent}
              onAccept={handleWritingAccept}
              onClose={() => setWritingOpen(false)}
              top={writingTop}
            />

            {/* AI Bullet Widget trigger — shown when cursor is on \item line */}
            {bulletWidgetLine !== null && !bulletWidgetOpen && (
              <button
                onClick={handleOpenBulletWidget}
                title="AI Bullet Generator"
                className="absolute left-1 z-20 flex items-center gap-1 rounded-[var(--radius-md)] bg-accent/20 px-1.5 py-0.5 text-[10px] font-semibold text-accent-strong ring-1 ring-accent/20 transition hover:bg-accent/25"
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
              {editorMode === 'source' && <ErrorExplainerPanel
                isOpen={explainerOpen}
                isLoading={explainerLoading}
                data={explainerData}
                errorLine={explainerLine}
                onClose={() => setExplainerOpen(false)}
                onApplyFix={handleApplyExplainerFix}
              />}
            </div>
          </div>
        </section>

        {/* ── Resize handle — desktop only ── */}
        <div
          className="group relative hidden w-[5px] shrink-0 cursor-col-resize items-center justify-center md:flex"
        >
          {editorMode === 'source' && <SourcePdfDivider
            sourceLine={cursorLine}
            pdfSelection={pdfSelection}
            pdfReady={pdfSyncReady}
            onSourceToPdf={handleSourceToPdf}
            onPdfToSource={handlePdfToSource}
          />}
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize editor and preview panes"
            aria-valuenow={Math.round(rightWidth ?? rightPanelRef.current?.getBoundingClientRect().width ?? 560)}
            aria-valuemin={280}
            aria-valuemax={rightMaxWidth}
            tabIndex={0}
            onMouseDown={startResize}
            onDoubleClick={() => setRightWidth(null)}
            onKeyDown={(event) => {
              if (!['ArrowLeft', 'ArrowRight', 'Home'].includes(event.key)) return
              event.preventDefault()
              if (event.key === 'Home') { setRightWidth(null); return }
              const current = rightWidth ?? rightPanelRef.current?.getBoundingClientRect().width ?? 560
              const delta = event.key === 'ArrowLeft' ? 16 : -16
              setRightWidth(Math.max(280, Math.min(window.innerWidth - 300, current + delta)))
            }}
            title="Drag to resize · double-click or Home to reset · arrow keys to nudge"
            className="flex h-full w-full items-center justify-center focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent"
          >
            <div className="h-full w-px bg-line transition-colors group-hover:bg-accent/30 group-active:bg-accent/60" />
          </div>
        </div>

        {/* ── Right panel ── */}
        <aside
          ref={rightPanelRef}
          className="flex min-h-[60vh] w-full min-w-0 flex-col border-t border-line bg-surface md:min-h-0 md:w-auto md:border-l md:border-t-0"
          style={
            isMobile
              ? undefined
              : rightWidth === null
              ? { flex: '2 1 0%', minWidth: 340 }
              : { width: `${rightWidth}px`, minWidth: `${rightWidth}px`, maxWidth: `${rightWidth}px`, flexShrink: 0 }
          }
        >
          {/* Tab bar */}
          <div
            ref={rightTabBarRef}
            className="flex h-9 shrink-0 snap-x items-center overflow-x-auto whitespace-nowrap border-b border-line bg-surface px-1 pr-3 scrollbar-none"
            style={{ WebkitOverflowScrolling: 'touch' }}
          >
            {(
              [
                { id: 'preview', label: 'Preview', icon: Eye },
                { id: 'ai', label: 'AI', icon: Sparkles },
                { id: 'logs', label: 'Logs', icon: Terminal },
                { id: 'history', label: 'History', icon: History },
                { id: 'design', label: 'Design', icon: Palette },
              ] as const
            ).filter(({ id }) => editorMode === 'source' || (editorMode === 'pdf' ? id === 'preview' || id === 'ai' : visualPanels.includes(id))).map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                ref={visibleRightTab === id ? activeRightTabRef : undefined}
                onClick={() => setRightTab(id)}
                className={`relative flex shrink-0 snap-start items-center gap-1.5 rounded-[var(--radius-md)] px-3 py-1.5 text-[11px] font-medium transition ${
                  visibleRightTab === id ? 'text-fg' : 'text-fg-3 hover:text-fg-2'
                }`}
              >
                <Icon size={11} />
                {label}
                {visibleRightTab === id && (
                  <span className="absolute inset-x-1 bottom-0 h-[2px] rounded-t-sm bg-accent" />
                )}
                {id === 'ai' && isAiRunning && (
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
                )}
                {id === 'logs' && isCompiling && (
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-accent" />
                )}
              </button>
            ))}

            {/* More tabs — groups the remaining panels behind an overflow menu */}
            <div className="relative shrink-0">
              <button
                ref={moreTabsTriggerRef}
                onClick={() => {
                  if (moreTabsOpen) { setMoreTabsOpen(false); return }
                  const rect = moreTabsTriggerRef.current?.getBoundingClientRect()
                  if (rect) setMoreTabsPos({ top: rect.bottom + 6, right: Math.max(12, window.innerWidth - rect.right) })
                  setMoreTabsOpen(true)
                }}
                aria-haspopup="menu"
                aria-expanded={moreTabsOpen}
                className={`relative flex shrink-0 items-center gap-1.5 rounded-[var(--radius-md)] px-3 py-1.5 text-[11px] font-medium transition ${
                  moreTabIds.includes(visibleRightTab) ? 'text-fg' : 'text-fg-3 hover:text-fg-2'
                }`}
              >
                <MoreHorizontal size={11} />
                More
                <ChevronDown size={10} />
                {moreTabIds.includes(visibleRightTab) && (
                  <span className="absolute inset-x-1 bottom-0 h-[2px] rounded-t-sm bg-accent" />
                )}
                {(lintIssues.length > 0 || trackedChanges.length > 0) && !moreTabIds.includes(visibleRightTab) && (
                  <span className="h-1.5 w-1.5 rounded-full bg-warn" />
                )}
              </button>
              {moreTabsOpen && moreTabsPos && createPortal(
                <>
                  <div className="fixed inset-0 z-[200]" onClick={() => setMoreTabsOpen(false)} />
                  <div
                    role="menu"
                    aria-label="More panels"
                    className="z-[201] max-h-[70vh] w-52 overflow-y-auto rounded-[var(--radius-md)] border border-line bg-surface p-1 shadow-[var(--shadow-2)]"
                    style={{ position: 'fixed', top: moreTabsPos.top, right: moreTabsPos.right }}
                  >
                    {([
                      { id: 'generate', label: 'Generate LaTeX', icon: Sparkles },
                      { id: 'comments', label: 'Comments', icon: MessageSquare },
                      { id: 'review', label: 'Review', icon: MessageSquare },
                      { id: 'chat', label: 'Chat', icon: MessageSquare },
                      { id: 'references', label: 'References', icon: BookOpen },
                      { id: 'interview', label: 'Interview Prep', icon: MessageSquare },
                      { id: 'proofread', label: 'Proofread', icon: ShieldCheck },
                      { id: 'packages', label: 'Packages', icon: Package },
                      { id: 'linter', label: 'Linter', icon: AlertTriangle },
                      { id: 'symbols', label: 'Symbols', icon: Braces },
                      { id: 'changes', label: 'Changes', icon: GitMerge },
                      { id: 'suggestions', label: 'Suggestions', icon: Sparkles },
                      { id: 'docs', label: 'Docs', icon: BookOpen },
                      { id: 'layout', label: 'Layout', icon: SlidersHorizontal },
                      { id: 'snippets', label: 'Snippets', icon: Package },
                      { id: 'macros', label: 'Macros', icon: Keyboard },
                      { id: 'tikz', label: 'TikZ', icon: Pencil },
                    ] as const).filter(({ id }) => editorMode === 'source' || (editorMode === 'pdf' ? id === 'comments' || id === 'interview' : visualPanels.includes(id))).map(({ id, label, icon: Icon }) => (
                      <button
                        key={id}
                        role="menuitem"
                        onClick={() => { setRightTab(id); setMoreTabsOpen(false) }}
                        className={`flex w-full items-center gap-2 rounded-[var(--radius-sm)] px-2.5 py-1.5 text-left text-[11px] font-medium transition hover:bg-surface-2 ${
                          visibleRightTab === id ? 'bg-surface-2 text-fg' : 'text-fg-2 hover:text-fg'
                        }`}
                      >
                        <Icon size={12} className="shrink-0 text-fg-3" />
                        {label}
                        {id === 'linter' && lintIssues.length > 0 && (
                          <span className="ml-auto rounded bg-warn/20 px-1 py-0.5 font-mono text-[8px] text-warn">
                            {lintIssues.length}
                          </span>
                        )}
                        {id === 'changes' && trackedChanges.length > 0 && (
                          <span className="ml-auto rounded bg-ok/20 px-1 py-0.5 font-mono text-[8px] text-ok">
                            {trackedChanges.length}
                          </span>
                        )}
                        {id === 'suggestions' && suggestions.some((item) => item.status === 'pending') && (
                          <span className="ml-auto rounded bg-accent/20 px-1 py-0.5 font-mono text-[8px] text-accent-strong">
                            {suggestions.filter((item) => item.status === 'pending').length}
                          </span>
                        )}
                      </button>
                    ))}
                  </div>
                </>,
                document.body
              )}
            </div>

            <div className="min-w-[8px] flex-1" />

            {pdfUrl && (
              <>
                <button
                  onClick={handleDownload}
                  className="flex shrink-0 items-center gap-1 px-2 py-1 text-[10px] text-fg-3 transition hover:text-fg-2"
                >
                  <Download size={11} />
                  PDF
                </button>
                <WatermarkDownloadPopover
                  getLatex={() => editorRef.current?.getValue() ?? latexContent}
                  filename={title}
                />
              </>
            )}
          </div>

          {/* Tab content */}
          <div className="min-h-0 flex-1 overflow-hidden">
            {visibleRightTab === 'preview' && documentType === 'presentation' && (
              <SlideViewer
                pdfUrl={pdfUrl}
                isLoading={isAnyRunning}
                slideCount={compileStream.pageCount ?? aiStream.pageCount}
              />
            )}
            {visibleRightTab === 'preview' && documentType !== 'presentation' && (
              <PDFPreview
                artifactIdentity={displayedArtifact ? { jobId: displayedArtifact.job_id, artifactId: displayedArtifact.artifact_id, fingerprint: undefined } : null}
            onFirstPaint={() => { const jobId = displayedArtifact?.job_id ?? activePdfJobId.current; if (jobId) recordPreviewFirstPaint(jobId) }}
            revisionLabel={displayedArtifact?.branch === 'candidate' ? 'AI candidate preview · review and accept suggestions before exporting.'
              : displayedArtifact && displayedArtifact.source_sha256 !== sourceHash ? 'Previous resume version · updating your current PDF.' : null}
                pdfUrl={pdfUrl}
                isLoading={isAnyRunning}
                onDownload={handleDownload}
                onShare={shareOrDownloadPdf}
                isOfflinePreview={isOfflinePdf}
                offlineError={offlinePdfError}
                onRetryOffline={retryOfflinePdf}
                jobId={renderedPdfJobId}
                onSyncToSource={editorMode === 'source' && (!displayedArtifact || displayedArtifact.source_sha256 === sourceHash) ? handleSyncToSource : undefined}
                onPdfSelectionChange={setPdfSelection}
                onSyncReadyChange={setPdfSyncReady}
                syncFromLine={editorMode === 'source' && (!displayedArtifact || displayedArtifact.source_sha256 === sourceHash) ? sourceSyncLine : null}
                syncFromRequestId={sourceSyncRequestId}
                sourceFileName={compileSettings.main_file}
                semanticGeometry={editorMode === 'pdf' ? verifiedGeometry : null}
                onSemanticSelect={setSelectedEngineNode}
                latexContent={latexContent}
                onJumpToLine={(line) => editorRef.current?.highlightLine(line)}
              />
            )}

            {visibleRightTab === 'ai' && (editorMode === 'pdf' ? (visibleEngineDocument?.source_mode === 'imported' ?
              <ImportedOptimizationPanel jobDescription={jobDescription} setJobDescription={setJobDescription}
                disabled={!canEditDocument || !collabIsOwner || isAnyRunning} running={isAiRunning || isAiSubmitting}
                candidate={stagedAiLatex != null} changes={aiStream.changesMade}
                onRun={() => { setSemanticRunId(null); void runAiOptimize() }} onPreview={() => setRightTab('preview')}
                onApply={() => { if (stagedAiLatex && applyOptimizationCandidate(stagedAiLatex, true)) queuePreview(stagedAiLatex, undefined, true) }} onDiscard={handleDiscardOptimization} /> : engineSupported ? <SemanticOptimizationPanel resumeId={resumeId} identity={`${sessionUserId}:${resumeId}`}
                document={visibleEngineDocument} currentSourceHash={sourceHash} disabled={!canEditDocument || !collabIsOwner || isAnyRunning}
                jobDescription={jobDescription} setJobDescription={setJobDescription} runId={semanticRunId} provisionalPatches={aiJobId === semanticRunId ? aiStream.semanticPatches : []}
                onStarted={(jobId) => { try { localStorage.setItem(`latexy_semantic_run:${sessionUserId}:${resumeId}`, jobId) } catch {} setSemanticRunId(jobId); setAiJobId(jobId); setLastStartedJobKind('ai'); setStagedAiLatex(null) }}
                onApplied={(document, source, startedAt) => {
                  setEngineDocument(document); setLatexContent(source); setSavedSnapshot((previous) => ({ ...previous, latex: source }))
                  queuePreview(source, startedAt, true)
                }} /> : <EngineCapabilityNotice capability={engineCapability} />) : <AIPanel
                visualOnly={editorMode !== 'source'}
                aiStream={aiStream}
                isRunning={isAiRunning}
                isSubmitting={isAiSubmitting}
                jobDescription={jobDescription}
                setJobDescription={setJobDescription}
                optLevel={optLevel}
                setOptLevel={setOptLevel}
                onRun={runAiOptimize}
                stagedLatex={stagedAiLatex}
                onApply={() => handleApplyOptimization()}
                onDiscard={handleDiscardOptimization}
                onReview={handleReviewOptimization}
                onApplyAnyway={handleApplyAnyway}
                outline={outline}
                targetSections={targetSections}
                setTargetSections={setTargetSections}
                customInstructions={customInstructions}
                setCustomInstructions={setCustomInstructions}
                onOpenDeepAnalysis={() => { void handleOpenDeepAnalysis() }}
                model={model}
                setModel={setModel}
              />
            )}

            {editorMode === 'source' && visibleRightTab === 'logs' && (
              <div className="h-full overflow-auto p-3">
                <div className="mb-2 flex items-center justify-between px-1">
                  <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-fg-3">
                    {isCompiling ? 'Compilation output' : isAiRunning ? 'AI pipeline logs' : 'Last run logs'}
                  </span>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setShowErrorHistory(true)}
                      className="text-[10px] font-medium text-fg-3 hover:text-accent-strong transition"
                      title="View error history"
                    >
                      Error History
                    </button>
                    <span
                      className={`text-[10px] font-medium capitalize ${
                        isAnyRunning
                          ? 'text-accent-strong'
                          : compileStream.status === 'completed' || aiStream.status === 'completed'
                          ? 'text-ok'
                          : 'text-fg-3'
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
                </div>
                <LogViewer lines={logLines} maxHeight="100%" className="h-full text-[11px]" />
              </div>
            )}

            {visibleRightTab === 'history' && (
              <VersionHistoryPanel
                resumeId={resumeId}
                onRestore={handleHistoryRestore}
                onCompare={handleCompare}
                onBeforeAfter={(orig, opt) => setCompareData({ original: orig, optimized: opt })}
                refreshKey={historyRefreshKey}
              />
            )}

            {visibleRightTab === 'comments' && (
              <CommentsPanel
                resumeId={resumeId}
                canComment={collabRole !== 'viewer'}
                highlightCommentId={searchParams.get('comment_id') ?? undefined}
              />
            )}

            {visibleRightTab === 'review' && (
              <ReviewCommentsPanel
                resumeId={resumeId}
                pdfUrl={pdfUrl}
                enabled={Boolean(sessionData?.session?.token)}
                canResolve={collabRole === 'owner' || collabRole === 'editor'}
                title="Review comments"
              />
            )}

            {visibleRightTab === 'chat' && (
              <CollaboratorChat chat={collaboratorChat} />
            )}

            {visibleRightTab === 'references' && (
              <ReferencesPanel
                resumeId={resumeId}
                onInsertBibTeX={(bibtex) => editorRef.current?.insertAtCursor(bibtex)}
                onInsertCiteKey={(key) => editorRef.current?.insertAtCursor(key)}
                onLibraryChange={setBibliographyBibTeX}
              />
            )}

            {visibleRightTab === 'generate' && (
              <LatexGeneratorPanel
                documentContext={latexContent}
                onInsert={(fragment) => editorRef.current?.insertAtCursor(fragment)}
              />
            )}

            {visibleRightTab === 'interview' && (
              <div className="min-h-0 flex-1 overflow-hidden">
                <InterviewPrepPanel
                  resumeId={resumeId}
                  defaultJobDescription={jobDescription}
                />
              </div>
            )}

            {visibleRightTab === 'design' && (
              <DesignPanel
                currentLatex={latexContent}
                onPreambleChange={handleDesignPreambleChange}
                onTriggerCompile={autoCompile ? handleDesignTriggerCompile : undefined}
              />
            )}

            {visibleRightTab === 'proofread' && (
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

            {visibleRightTab === 'packages' && (
              <PackageManagerPanel
                currentLatex={latexContent}
                onAddPackage={(newLatex, packageName) => {
                  pushUndo(`Before adding package: ${packageName}`)
                  editorRef.current?.setValue(newLatex)
                  setLatexContent(newLatex)
                }}
              />
            )}

            {visibleRightTab === 'linter' && (
              <LinterPanel
                issues={lintIssues}
                enabled={linterEnabled}
                onToggleEnabled={setLinterEnabled}
                onJumpToLine={(line) => editorRef.current?.highlightLine(line)}
                onApplyFix={(issue) => {
                  if (!issue.fix) return
                  const currentContent = editorRef.current?.getValue() || latexContent
                  const lines = currentContent.split('\n')
                  const lineContent = lines[issue.line - 1] ?? ''
                  const fixed = issue.fix(lineContent)
                  editorRef.current?.applyFix(issue.line, fixed)
                  const newLines = [...lines]
                  newLines[issue.line - 1] = fixed
                  setLatexContent(newLines.join('\n'))
                }}
                onAutoFixAll={() => {
                  const currentContent = editorRef.current?.getValue() || latexContent
                  const fixed = runLintAutoFixAll(currentContent)
                  editorRef.current?.setValue(fixed)
                  setLatexContent(fixed)
                }}
                extractedPdfText={extractedPdfText}
                pageCount={pageCount}
              />
            )}

            {visibleRightTab === 'symbols' && (
              <SymbolPalette
                onInsert={(cmd) => editorRef.current?.insertAtCursor(cmd)}
              />
            )}

            {visibleRightTab === 'changes' && (
              <ChangesPanel
                changes={trackedChanges}
                onAccept={(id) => editorRef.current?.acceptTrackedChange(id)}
                onReject={(id) => editorRef.current?.rejectTrackedChange(id)}
                onAcceptAll={() => editorRef.current?.acceptAllTrackedChanges()}
                onRejectAll={() => editorRef.current?.rejectAllTrackedChanges()}
              />
            )}

            {visibleRightTab === 'suggestions' && (
              <SuggestionsPanel
                suggestions={allSuggestions}
                canSuggest={canSuggest}
                canResolve={canResolveSuggestion(collabRole) && canEditDocument}
                canReject={(suggestion) => (canResolveSuggestion(collabRole) && canEditDocument) || suggestion.authorId === sessionUserId}
                modeEnabled={suggestionMode}
                onToggleMode={() => setSuggestionMode((enabled) => !enabled)}
                onCreate={handleCreateSuggestion}
                onAccept={handleAcceptSuggestion}
                onReject={handleRejectSuggestion}
                error={suggestionError}
                onRetry={retrySuggestion}
              />
            )}

            {visibleRightTab === 'docs' && (
              <LaTeXDocPanel command={docCommand} />
            )}

            {visibleRightTab === 'layout' && (
              <TemplateCustomizerPanel
                currentLatex={latexContent}
                onPreambleChange={handleDesignPreambleChange}
                onTriggerCompile={autoCompile ? handleDesignTriggerCompile : undefined}
              />
            )}

            {visibleRightTab === 'snippets' && (
              <SnippetMarketplace
                onInsert={(content) => {
                  const editor = editorRef.current
                  if (editor && 'insertText' in editor && typeof (editor as any).insertText === 'function') {
                    (editor as any).insertText(content)
                  } else {
                    // Fallback: append at end of document
                    setLatexContent((prev) => prev + '\n' + content)
                  }
                }}
              />
            )}
            {editorMode === 'source' && <MacroLibraryPanel
              className={visibleRightTab === 'macros' ? undefined : 'hidden'}
              editor={macroEditor}
            />}

            {visibleRightTab === 'tikz' && (
              <TikZEditor
                onInsert={(code) => editorRef.current?.insertAtCursor(code)}
                onPreview={handleTikZPreview}
              />
            )}
          </div>
        </aside>
      </div>

      {/* Import modal */}
      {showImportModal && (
        <div className="fixed inset-0 bg-[var(--overlay)] flex items-center justify-center z-50 p-4">
          <div className="w-full max-w-md rounded-[var(--radius-lg)] border border-line bg-surface shadow-[var(--shadow-2)] p-6">
            <div className="flex justify-between items-center mb-3">
              <h3 className="text-base font-semibold text-fg">Import Resume File</h3>
              <button
                onClick={() => setShowImportModal(false)}
                className="rounded-[var(--radius-md)] p-1.5 text-fg-3 transition hover:bg-surface-2 hover:text-fg-2"
              >
                <X size={16} />
              </button>
            </div>
            <div className="mb-5 flex items-start justify-between gap-3">
              <p className="text-xs text-fg-3">
                This will replace the current editor content. The previous version is added to your undo history, so you can revert.
              </p>
              <button
                onClick={handleSave}
                disabled={isSaving || !isDirty}
                title={isDirty ? 'Save current content before importing' : 'No unsaved changes'}
                className="flex shrink-0 items-center gap-1.5 rounded-[var(--radius-md)] border border-line bg-surface-2 px-2.5 py-1.5 text-[11px] font-medium text-fg-2 transition hover:text-fg disabled:opacity-40"
              >
                <Save size={12} />
                {isSaving ? 'Saving…' : 'Save current first'}
              </button>
            </div>
            <MultiFormatUpload
              visualOnly={editorMode !== 'source'}
              onFileUpload={(content) => {
                if (content) {
                  // Push the pre-import buffer onto the undo stack so the replace
                  // is reversible (Finding: import overwrites with no undo).
                  pushUndo('Before import')
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
        visualOnly={editorMode !== 'source'}
        isOpen={deepPanelOpen}
        onClose={() => setDeepPanelOpen(false)}
        isLoading={isDeepRunning || deepStream.status === 'queued' || deepStream.status === 'processing'}
        analysis={deepStream.deepAnalysis}
        error={deepAnalysisError ?? deepStream.error}
        usesRemaining={deepAnalysisUsesRemaining}
        onRun={handleOpenDeepAnalysis}
        isRunning={isDeepRunning}
        hideUpgradeCtas={!flags.upgrade_ctas}
        resumeId={resumeId}
        categories={atsCategories}
        onJumpToLine={handleJumpToFinding}
        quickGrade={quickATSGrade}
      />

      <ConfirmDialog
        open={confirmPull !== null}
        title={confirmPull === 'dropbox' ? 'Pull from Dropbox?' : 'Pull from GitHub?'}
        message={`Replace the local content with the latest version from ${confirmPull === 'dropbox' ? 'Dropbox' : 'GitHub'}? Unsaved changes will be overwritten.`}
        confirmLabel="Replace"
        destructive
        onConfirm={() => { const which = confirmPull; setConfirmPull(null); if (which === 'github') doPullFromGitHub(); else if (which === 'dropbox') doPullFromDropbox() }}
        onCancel={() => setConfirmPull(null)}
      />

      <ConfidenceScorePanel
        isOpen={confidencePanelOpen}
        onClose={() => setConfidencePanelOpen(false)}
        score={confidenceResult}
        loading={confidenceLoading}
        error={confidenceError}
        onRefresh={refetchConfidence}
      />

      {/* QR Code Inserter (Feature 62) */}
      <QrCodeInserter
        isOpen={qrInserterOpen}
        onClose={() => setQrInserterOpen(false)}
        onInsert={(snippet) => editorRef.current?.insertAtCursor(snippet)}
        getLatex={() => editorRef.current?.getValue() || latexContent}
        onLatexChange={(newLatex) => {
          editorRef.current?.setValue(newLatex)
          setLatexContent(newLatex)
        }}
      />

      {/* Date Format Standardizer (Feature 57) */}
      <DateStandardizerPanel
        isOpen={dateStandardizerOpen}
        onClose={() => setDateStandardizerOpen(false)}
        getLatex={() => editorRef.current?.getValue() || latexContent}
        onApply={(newLatex) => {
          pushUndo('Before date standardization')
          editorRef.current?.setValue(newLatex)
          setLatexContent(newLatex)
        }}
      />

      {/* Age Analysis Panel (Feature 55) */}
      <AgeAnalysisPanel
        isOpen={ageAnalysisOpen}
        onClose={() => setAgeAnalysisOpen(false)}
        getLatex={() => editorRef.current?.getValue() || latexContent}
        onJumpToLine={(line) => editorRef.current?.highlightLine(line)}
      />

      {/* Contact Formatter Panel (Feature 64) */}
      <ContactFormatterPanel
        isOpen={contactFormatterOpen}
        onClose={() => setContactFormatterOpen(false)}
        getLatex={() => editorRef.current?.getValue() || latexContent}
        onApply={(newLatex) => {
          pushUndo('Before contact normalization')
          editorRef.current?.setValue(newLatex)
          setLatexContent(newLatex)
        }}
      />

      {/* Salary Estimator Panel (Feature 45) */}
      <SalaryEstimatorPanel
        isOpen={salaryEstimatorOpen}
        onClose={() => setSalaryEstimatorOpen(false)}
        getLatex={() => editorRef.current?.getValue() || latexContent}
      />

      {/* Section Reorder Panel (Feature 53) */}
      <SectionReorderPanel
        isOpen={sectionReorderOpen}
        onClose={() => setSectionReorderOpen(false)}
        getLatex={() => editorRef.current?.getValue() || latexContent}
        onApply={(newLatex) => {
          pushUndo('Before section reorder')
          editorRef.current?.setValue(newLatex)
          setLatexContent(newLatex)
        }}
      />

      {/* Project import — GitHub / URL / LinkedIn (F1 — external sources to resume) */}
      {editorMode === 'source' && <ImportProjectsModal
        isOpen={importModalOpen}
        onClose={() => setImportModalOpen(false)}
        onInsert={(latex) => {
          pushUndo('Before project import')
          editorRef.current?.insertAtCursor(latex)
          setLatexContent(editorRef.current?.getValue() || latexContent)
        }}
      />}

      {/* Compile Error History (Feature 88) */}
      {editorMode === 'source' && showErrorHistory && (
        <CompileErrorHistory onClose={() => setShowErrorHistory(false)} />
      )}

      {/* Diff viewer modal */}
      {editorMode === 'source' && showDiffModal && (
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
      {editorMode === 'source' && showParentDiff && parentDiffData && (
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

      {editorMode === 'wysiwyg' && compareData && (
        <VisualChangeReviewModal
          original={compareData.original}
          proposed={compareData.optimized}
          onApply={stagedAiLatex ? handleApplyOptimization : undefined}
          onClose={() => setCompareData(null)}
        />
      )}

      {/* Before/After optimization compare modal */}
      {editorMode === 'source' && compareData && (
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
        <div role="status" aria-live="polite" aria-label="Compile timeout" className="flex shrink-0 items-center justify-between border-t border-accent/20 bg-accent/10 px-3 py-1.5">
          <span className="text-[11px] text-accent-strong">
            ⏱ Compile timed out — {compileStream.timeoutError.plan} plan limit (
            {compileStream.timeoutError.seconds}s)
          </span>
          {flags.upgrade_ctas && (
            <a
              href="/billing"
              className="ml-3 shrink-0 text-[11px] font-medium text-accent-strong underline hover:text-accent-strong"
            >
              Upgrade for longer timeouts →
            </a>
          )}
        </div>
      )}

      {/* ── Share modal ── */}
      {shareModalOpen && ownsRenderedJobState && (
        <ShareResumeModal
          key={JSON.stringify([offlinePdfOwnerId, resumeId])}
          ownerId={offlinePdfOwnerId}
          resumeId={resumeId}
          resumeTitle={title}
          initialShareToken={shareToken}
          initialShareUrl={shareUrl}
          initialAnonymous={shareAnonymous}
          initialReviewComments={shareReviewComments}
          onClose={() => setShareModalOpen(false)}
          onShareTokenChange={(token, url, anonymous, reviewComments = false) => {
            if (!offlinePdfMountedRef.current || offlinePdfRenderIdentityRef.current.ownerId !== offlinePdfOwnerId || offlinePdfRenderIdentityRef.current.resumeId !== resumeId) return
            setShareToken(token)
            setShareUrl(url)
            setShareAnonymous(anonymous)
            setShareReviewComments(reviewComments)
          }}
        />
      )}

      <DocumentAssistantPanel
        visualOnly={editorMode !== 'source'}
        isOpen={documentAssistantOpen}
        resumeId={resumeId}
        documentLatex={latexContent}
        onClose={() => setDocumentAssistantOpen(false)}
        onApply={(nextLatex) => {
          editorRef.current?.setValue(nextLatex)
          setLatexContent(nextLatex)
          toast.success('Assistant edit applied')
        }}
      />

      {academicConvertOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] px-4" onClick={() => setAcademicConvertOpen(false)}>
          <div className="w-full max-w-2xl rounded-[var(--radius-lg)] border border-line bg-surface p-5 shadow-[var(--shadow-2)]" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between gap-4">
              <div>
                <h2 className="text-base font-semibold text-fg">Academic CV → Industry Resume</h2>
                <p className="mt-1 text-sm text-fg-2">
                  Create a new variant that reframes academic work into industry outcomes without overwriting the original CV.
                </p>
              </div>
              <button onClick={() => setAcademicConvertOpen(false)} className="rounded-[var(--radius-md)] p-1.5 text-fg-3 transition hover:bg-surface-2 hover:text-fg-2">
                <X size={16} />
              </button>
            </div>

            {academicReport && (
              <div className="mt-4 rounded-[var(--radius-lg)] border border-accent/15 bg-accent/10 p-3 text-xs text-accent-strong">
                <div>Detection confidence: {Math.round(academicReport.confidence * 100)}%</div>
                <div className="mt-1">Signals: {academicReport.detected_sections.join(', ') || 'general academic structure'}</div>
              </div>
            )}

            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <label className="grid gap-2 text-sm text-fg-2">
                <span>Target industry</span>
                <select
                  value={academicTargetIndustry}
                  onChange={(e) => setAcademicTargetIndustry(e.target.value as typeof academicTargetIndustry)}
                  className="rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg outline-none focus:border-accent"
                >
                  <option value="tech">Software Engineering / Tech</option>
                  <option value="data_science">Data Science / ML</option>
                  <option value="finance">Finance / Quant</option>
                  <option value="consulting">Consulting</option>
                  <option value="product">Product Management</option>
                  <option value="other">Other</option>
                </select>
              </label>
              <div className="rounded-[var(--radius-md)] border border-line bg-surface-2 p-3 text-xs text-fg-3">
                The output is saved as a child variant. You keep the original academic CV unchanged.
              </div>
            </div>

            <label className="mt-4 grid gap-2 text-sm text-fg-2">
              <span>Optional target role or job description</span>
              <textarea
                value={academicRoleDescription}
                onChange={(e) => setAcademicRoleDescription(e.target.value)}
                rows={7}
                placeholder="Paste a target role description to bias the conversion toward the right framing and keywords."
                className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg outline-none placeholder:text-fg-3 focus:border-accent"
              />
            </label>

            <div className="mt-5 flex items-center justify-end gap-2">
              <button
                onClick={() => setAcademicConvertOpen(false)}
                className="rounded-[var(--radius-md)] px-3 py-2 text-sm text-fg-3 transition hover:text-fg-2"
              >
                Cancel
              </button>
              <button
                onClick={handleAcademicConvert}
                disabled={isAcademicConverting}
                className="inline-flex items-center gap-2 rounded-[var(--radius-md)] bg-accent/20 px-3 py-2 text-sm font-medium text-accent-strong ring-1 ring-accent/20 transition hover:bg-accent/25 disabled:opacity-50"
              >
                {isAcademicConverting ? <Loader2 size={14} className="animate-spin" /> : <GraduationCap size={14} />}
                {isAcademicConverting ? 'Creating Variant…' : 'Create Industry Variant'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Keyboard shortcuts panel (Feature 61) */}
      <KeyboardShortcutsPanel isOpen={editorMode === 'source' && shortcutsOpen} onClose={() => setShortcutsOpen(false)} />

      {/* Compile settings modal (Feature 38) */}
      {editorMode === 'source' && <CompileSettingsModal
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
      />}

      {/* Collaborator Panel (Feature 40) */}
      <CollaboratorPanel
        open={collabOpen}
        resumeId={resumeId}
        isOwner={collabIsOwner}
        presenceUsers={presenceUsers}
        onClose={() => setCollabOpen(false)}
      />

      {/* ── STATUS BAR ── */}
      <footer className="flex h-6 shrink-0 items-center justify-between border-t border-line bg-surface px-3">
        <span
          className={`text-[10px] font-medium ${
            isAnyRunning
              ? 'text-accent-strong'
              : compileStream.status === 'completed' || aiStream.status === 'completed'
              ? 'text-ok'
              : aiStream.status === 'failed' || compileStream.status === 'failed'
              ? 'text-err'
              : 'text-fg-3'
          }`}
        >
          {statusText}
        </span>
        <div className="flex items-center gap-3">
          {aiStream.atsScore != null && (
            <span
              className={`flex items-center gap-1.5 rounded-[var(--radius-md)] px-2 py-0.5 text-[11px] font-bold tabular-nums ${
                aiStream.atsScore >= 80
                  ? 'bg-ok/15 text-ok ring-1 ring-ok/20'
                  : aiStream.atsScore >= 60
                  ? 'bg-warn/15 text-warn ring-1 ring-warn/20'
                  : 'bg-err/15 text-err ring-1 ring-err/20'
              }`}
              title="ATS compatibility score from last AI optimization"
            >
              ATS {Math.round(aiStream.atsScore)}
            </span>
          )}
          {cursorLine && (
            <span className="text-[10px] tabular-nums text-fg-3">
              Ln {cursorLine}
            </span>
          )}
          <span className="text-[10px] tabular-nums text-fg-3">
            {latexContent.length.toLocaleString()} chars
          </span>
        </div>
      </footer>
    </div>
  )
}
