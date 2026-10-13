'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertCircle, Check, FileImage, Loader2, Sigma, Sparkles, Table2, X } from 'lucide-react'
import { apiClient } from '@/lib/api-client'
import { useSession } from '@/lib/auth-client'
import { useEntitlements } from '@/contexts/EntitlementsContext'
import { useAccountContentScope } from '@/contexts/AccountContentScope'
import { isConfirmedSessionUnauthorized } from '@/lib/session-authority'

interface LatexGeneratorPanelProps {
  documentId: string
  admissionAllowed?: boolean
  admissionGuard?: () => boolean
  insertionAllowed?: boolean
  insertionGuard?: () => boolean
  documentContext: string
  onInsert: (latex: string) => void
  onRecoveryChange?: (available: boolean) => void
}

type GeneratorMode = 'structure' | 'table' | 'math'
type MathDisplayMode = 'inline' | 'display' | 'equation'

export default function LatexGeneratorPanel({ documentId, documentContext, onInsert, onRecoveryChange, admissionAllowed = true, insertionAllowed = true, admissionGuard, insertionGuard }: LatexGeneratorPanelProps) {
  const [mode, setMode] = useState<GeneratorMode>('structure')
  const [intent, setIntent] = useState('')
  const [tableText, setTableText] = useState('')
  const [tableFile, setTableFile] = useState<File | null>(null)
  const [firstRowHeader, setFirstRowHeader] = useState(true)
  const [tableShape, setTableShape] = useState<{ rows: number; columns: number } | null>(null)
  const [mathText, setMathText] = useState('')
  const [mathFile, setMathFile] = useState<File | null>(null)
  const [mathDisplayMode, setMathDisplayMode] = useState<MathDisplayMode>('display')
  const [generated, setGenerated] = useState('')
  const [cached, setCached] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [inserted, setInserted] = useState(false)

  const { can } = useEntitlements()
  const { data: session, isPending, isRefetching = false, error: sessionError } = useSession()
  const accountScope = useAccountContentScope()
  const ownsAccountScope = () => accountScope?.isCurrent() ?? false
  const sessionUnauthorized = isConfirmedSessionUnauthorized(sessionError)
  const recoveryIdentity = accountScope?.recoveryIdentity
  const scope = useRef({ owner: session?.user?.id ?? 'anonymous', documentId, recoveryIdentity, epoch: 0 })
  // A missing session during a refresh/error does not establish a new owner.
  // Confirmed logout, account/document changes and ABA renew the recovery scope.
  const owner = sessionUnauthorized ? 'anonymous' : session?.user?.id
    ?? ((!isPending && !isRefetching && !sessionError) ? 'anonymous' : scope.current.owner)
  const ready = Boolean(session?.user?.id && !isPending && !isRefetching && !sessionError
    && (accountScope?.canAdmit() ?? false))
  const alive = useRef(true)
  const readyRef = useRef(ready)
  readyRef.current = ready
  const requests = useRef({ sequence: 0, active: null as null | { sequence: number; epoch: number } })
  const inputScope = useRef(scope.current.epoch)
  const resultScope = useRef<number | null>(null)
  if (scope.current.owner !== owner || scope.current.documentId !== documentId || scope.current.recoveryIdentity !== recoveryIdentity) {
    scope.current = { owner, documentId, recoveryIdentity, epoch: scope.current.epoch + 1 }
    requests.current.sequence += 1
    requests.current.active = null
  }
  const epoch = scope.current.epoch
  const ownedInputs = ownsAccountScope() && inputScope.current === epoch && owner !== 'anonymous'
  const ownedIntent = ownedInputs ? intent : ''
  const ownedTableText = ownedInputs ? tableText : ''
  const ownedTableFile = ownedInputs ? tableFile : null
  const ownedMathText = ownedInputs ? mathText : ''
  const ownedMathFile = ownedInputs ? mathFile : null
  // Retained callbacks use current grants, exact branch and document scope.
  // Same-owner refresh/token rotation never destroys already-admitted recovery.
  const current = useRef({ can, admissionAllowed, insertionAllowed, admissionGuard, insertionGuard, mode, intent: ownedIntent, tableText: ownedTableText, tableFile: ownedTableFile, firstRowHeader,
    mathText: ownedMathText, mathFile: ownedMathFile, mathDisplayMode, documentContext, onInsert, generated, inserted })
  current.current = { can, admissionAllowed, insertionAllowed, admissionGuard, insertionGuard, mode, intent: ownedIntent, tableText: ownedTableText, tableFile: ownedTableFile, firstRowHeader,
    mathText: ownedMathText, mathFile: ownedMathFile, mathDisplayMode, documentContext, onInsert, generated, inserted }

  const resetResult = useCallback(() => {
    requests.current.sequence += 1
    requests.current.active = null
    resultScope.current = null
    setGenerated('')
    setCached(false)
    setTableShape(null)
    setError(null)
    setInserted(false)
    setLoading(false)
  }, [])

  useEffect(() => {
    alive.current = true
    inputScope.current = epoch
    resetResult()
    setIntent('')
    setTableText('')
    setTableFile(null)
    setMathText('')
    setMathFile(null)
    const requestState = requests.current
    const aliveState = alive
    return () => {
      aliveState.current = false
      requestState.sequence += 1
      requestState.active = null
    }
  }, [epoch, resetResult])

  const isCurrentCallback = () => alive.current && epoch === scope.current.epoch && ownsAccountScope()
  const allows = (leaf: string) => isCurrentCallback() && (accountScope?.canAdmit() ?? false) && readyRef.current && current.current.admissionAllowed && (current.current.admissionGuard?.() ?? true) && current.current.can(leaf)
    && current.current.can('d14') && current.current.can('ai_writing')
  const modeAllowed = (nextMode: GeneratorMode) => nextMode === 'structure'
    ? allows('d14_latex') : nextMode === 'table'
      ? allows('d14_table_text') || allows('d14_table_image')
      : allows('d14_math_text') || allows('d14_math_image')
  const switchMode = (nextMode: GeneratorMode) => {
    if (!isCurrentCallback()) return
    const savedInput = nextMode === 'structure' ? current.current.intent : nextMode === 'table'
      ? current.current.tableText || current.current.tableFile : current.current.mathText || current.current.mathFile
    if (nextMode === current.current.mode || (!modeAllowed(nextMode) && !savedInput)) return
    current.current.mode = nextMode
    setMode(nextMode)
    resetResult()
  }
  const beginRequest = (requestedMode: GeneratorMode, leaf: string) => {
    if (current.current.mode !== requestedMode || !allows(leaf) || requests.current.active) return null
    resetResult()
    const request = { sequence: requests.current.sequence, epoch: scope.current.epoch }
    requests.current.active = request
    setLoading(true)
    return request
  }
  const ownsRequest = (request: NonNullable<typeof requests.current.active>) => isCurrentCallback() && requests.current.active === request
    && scope.current.owner !== 'anonymous' && request.epoch === scope.current.epoch
  const finishRequest = (request: NonNullable<typeof requests.current.active>) => {
    if (!isCurrentCallback() || requests.current.active !== request || request.epoch !== scope.current.epoch) return
    requests.current.active = null
    setLoading(false)
  }

  const generateStructure = async () => {
    const input = current.current
    const normalizedIntent = input.intent.trim()
    if (normalizedIntent.length < 5) return
    const request = beginRequest('structure', 'd14_latex')
    if (!request) return
    try {
      const response = await apiClient.generateLatex({
        intent: normalizedIntent,
        document_context: input.documentContext.slice(0, 20_000),
      })
      if (!ownsRequest(request)) return
      resultScope.current = request.epoch
      setGenerated(response.latex)
      setCached(response.cached)
    } catch (caught) {
      if (ownsRequest(request)) setError(caught instanceof Error ? caught.message : 'LaTeX generation failed')
    } finally {
      finishRequest(request)
    }
  }

  const generateTable = async () => {
    const input = current.current
    if (!input.tableFile && input.tableText.trim().length < 3) return
    const request = beginRequest('table', input.tableFile ? 'd14_table_image' : 'd14_table_text')
    if (!request) return
    try {
      const response = input.tableFile
        ? await apiClient.generateLatexTableFromImage(input.tableFile, input.firstRowHeader)
        : await apiClient.generateLatexTable({ table_text: input.tableText, first_row_header: input.firstRowHeader })
      if (!ownsRequest(request)) return
      resultScope.current = request.epoch
      setGenerated(response.latex)
      setTableShape({ rows: response.rows, columns: response.columns })
    } catch (caught) {
      if (ownsRequest(request)) setError(caught instanceof Error ? caught.message : 'Table conversion failed')
    } finally {
      finishRequest(request)
    }
  }

  const generateMath = async () => {
    const input = current.current
    if (!input.mathFile && input.mathText.trim().length < 2) return
    const request = beginRequest('math', input.mathFile ? 'd14_math_image' : 'd14_math_text')
    if (!request) return
    try {
      const response = input.mathFile
        ? await apiClient.generateLatexMathFromImage(input.mathFile, input.mathDisplayMode)
        : await apiClient.generateLatexMath({ math_text: input.mathText, display_mode: input.mathDisplayMode })
      if (!ownsRequest(request)) return
      resultScope.current = request.epoch
      setGenerated(response.latex)
      setCached(response.cached)
    } catch (caught) {
      if (ownsRequest(request)) setError(caught instanceof Error ? caught.message : 'Math conversion failed')
    } finally {
      finishRequest(request)
    }
  }

  const visibleGenerated = ownsAccountScope() && owner !== 'anonymous' && resultScope.current === epoch ? generated : ''
  const tableReady = Boolean(ownedTableFile) || ownedTableText.trim().length >= 3
  const mathReady = Boolean(ownedMathFile) || ownedMathText.trim().length >= 2
  const canInsert = ready && insertionAllowed && (insertionGuard?.() ?? true) && can('c01') && Boolean(visibleGenerated)
  const insertFragment = () => {
    if (!isCurrentCallback() || !(accountScope?.canAdmit() ?? false) || !readyRef.current || !current.current.insertionAllowed || !(current.current.insertionGuard?.() ?? true) || resultScope.current !== scope.current.epoch || !current.current.can('c01')
      || !current.current.generated || current.current.inserted) return
    current.current.onInsert(current.current.generated)
    current.current.inserted = true
    setInserted(true)
  }
  const copyFragment = async () => {
    if (!isCurrentCallback() || scope.current.owner === 'anonymous' || resultScope.current !== scope.current.epoch || !current.current.generated) return
    const copyScope = scope.current
    try { await navigator.clipboard.writeText(current.current.generated) }
    catch { if (!isCurrentCallback() || scope.current !== copyScope) return; setError('Could not copy the fragment. You can select and copy the preview.') }
  }

  const hasStructureDraft = Boolean(ownedIntent)
  const hasTableDraft = Boolean(ownedTableText || ownedTableFile)
  const hasMathDraft = Boolean(ownedMathText || ownedMathFile)
  const recoveryAvailable = Boolean(hasStructureDraft || hasTableDraft || hasMathDraft || visibleGenerated || requests.current.active)
  useEffect(() => { onRecoveryChange?.(recoveryAvailable) }, [onRecoveryChange, recoveryAvailable])
  const selectedModeAvailable = modeAllowed(mode)
  const selectedModeHasRecovery = Boolean(visibleGenerated || requests.current.active || (mode === 'structure' ? hasStructureDraft : mode === 'table' ? hasTableDraft : hasMathDraft))
  const nextAvailableMode = modeAllowed('structure') ? 'structure' : modeAllowed('table') ? 'table' : modeAllowed('math') ? 'math' : null
  useEffect(() => {
    if (!selectedModeAvailable && !selectedModeHasRecovery && nextAvailableMode) {
      current.current.mode = nextAvailableMode
      setMode(nextAvailableMode)
    }
  }, [selectedModeAvailable, selectedModeHasRecovery, nextAvailableMode])


  return (
    <section className="flex h-full min-h-0 flex-col" aria-labelledby="latex-generator-heading">
      <div className="border-b border-line px-4 py-3">
        <div className="flex items-center gap-2">
          <Sparkles size={14} className="text-accent-strong" aria-hidden="true" />
          <h2 id="latex-generator-heading" className="text-xs font-semibold text-fg">
            Generate LaTeX
          </h2>
        </div>
        <p className="mt-1.5 text-[10px] leading-relaxed text-fg-3">
          Create a reviewable fragment, then choose whether to insert it at your cursor.
        </p>
        <div className="mt-3 grid grid-cols-3 gap-1 rounded-[var(--radius-md)] bg-surface-2 p-1" role="tablist" aria-label="LaTeX generator mode">
          {(modeAllowed('structure') || hasStructureDraft || (mode === 'structure' && Boolean(visibleGenerated || loading))) && <ModeButton active={mode === 'structure'} disabled={!modeAllowed('structure') && !hasStructureDraft} onClick={() => switchMode('structure')} icon={<Sparkles size={11} />}>
            Describe
          </ModeButton>}
          {(modeAllowed('table') || hasTableDraft || (mode === 'table' && Boolean(visibleGenerated || loading))) && <ModeButton active={mode === 'table'} disabled={!modeAllowed('table') && !hasTableDraft} onClick={() => switchMode('table')} icon={<Table2 size={11} />}>
            Table
          </ModeButton>}
          {(modeAllowed('math') || hasMathDraft || (mode === 'math' && Boolean(visibleGenerated || loading))) && <ModeButton active={mode === 'math'} disabled={!modeAllowed('math') && !hasMathDraft} onClick={() => switchMode('math')} icon={<Sigma size={11} />}>
            Math
          </ModeButton>}
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        {mode === 'structure' ? (
          <>
            {allows('d14_latex') ? (
            <label className="block text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3">
              What should be created?
              <textarea
                value={ownedIntent}
                disabled={!allows('d14_latex')}
                onChange={(event) => {
                  if (!allows('d14_latex')) return
                  current.current.intent = event.target.value
                  setIntent(event.target.value)
                  resetResult()
                }}
                maxLength={2000}
                rows={6}
                placeholder="e.g. Create a Projects section with two concise placeholder items"
                className="mt-2 w-full resize-y rounded-[var(--radius-md)] border border-line-2 bg-surface px-3 py-2 text-xs font-normal normal-case tracking-normal text-fg outline-none transition placeholder:text-fg-3 focus:border-accent/40"
              />
            </label>
            ) : ownedIntent ? (<div aria-label="Saved intent input" className="rounded border border-line p-2 text-xs text-fg-2"><p>Saved input</p><pre className="whitespace-pre-wrap">{ownedIntent}</pre></div>) : null}
            <div className="flex items-center justify-between text-[9px] text-fg-3">
              <span>Existing document text is used only as a style reference.</span>
              <span>{ownedIntent.length}/2000</span>
            </div>
            {allows('d14_latex') && (
            <GenerateButton
              loading={loading}
              disabled={ownedIntent.trim().length < 5 || !allows('d14_latex')}
              generated={Boolean(visibleGenerated)}
              onClick={() => void generateStructure()}
              label="fragment"
            />
            )}
          </>
        ) : mode === 'table' ? (
          <>
            {allows('d14_table_text') ? (
            <label className="block text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3">
              Paste CSV or TSV
              <textarea
                value={ownedTableText}
                disabled={!allows('d14_table_text')}
                onChange={(event) => {
                  if (!allows('d14_table_text')) return
                  current.current.tableText = event.target.value
                  current.current.tableFile = null
                  setTableText(event.target.value)
                  setTableFile(null)
                  resetResult()
                }}
                maxLength={50_000}
                rows={7}
                placeholder={'Name,Score\nAda,99\nLinus,87'}
                className="mt-2 w-full resize-y rounded-[var(--radius-md)] border border-line-2 bg-surface px-3 py-2 font-mono text-[11px] font-normal normal-case tracking-normal text-fg outline-none transition placeholder:text-fg-3 focus:border-accent/40"
              />
            </label>
            ) : ownedTableText ? (<div aria-label="Saved table text input" className="rounded border border-line p-2 text-xs text-fg-2"><p>Saved input</p><pre className="whitespace-pre-wrap">{ownedTableText}</pre></div>) : null}
            {allows('d14_table_image') && (
            <div className="flex items-center gap-2 text-[9px] uppercase tracking-[0.12em] text-fg-3">
              <span className="h-px flex-1 bg-line" />
              or use an image
              <span className="h-px flex-1 bg-line" />
            </div>
            )}
            {ownedTableFile ? (
              <div className="flex items-center gap-2 rounded-[var(--radius-md)] border border-line bg-surface p-2.5">
                <FileImage size={14} className="shrink-0 text-accent-strong" aria-hidden="true" />
                <span className="min-w-0 flex-1 truncate text-[11px] text-fg-2">{ownedTableFile.name}</span>
                <button
                  type="button"
                  onClick={() => {
                    if (!isCurrentCallback()) return
                    current.current.tableFile = null
                    setTableFile(null)
                    resetResult()
                  }}
                  aria-label="Remove table image"
                  className="rounded p-1 text-fg-3 hover:bg-surface-2 hover:text-fg"
                >
                  <X size={12} aria-hidden="true" />
                </button>
              </div>
            ) : allows('d14_table_image') ? (
              <label className="flex cursor-pointer items-center justify-center gap-2 rounded-[var(--radius-md)] border border-dashed border-line-2 bg-surface px-3 py-3 text-[11px] font-medium text-fg-2 transition hover:border-accent/40 hover:text-accent-strong">
                <FileImage size={13} aria-hidden="true" />
                Choose PNG, JPEG, or WebP
                <input
                  type="file"
                  disabled={!allows('d14_table_image')}
                  accept="image/png,image/jpeg,image/webp,.png,.jpg,.jpeg,.webp"
                  className="sr-only"
                  onChange={(event) => {
                    const selected = event.target.files?.[0] ?? null
                    event.target.value = ''
                    if (!selected || !allows('d14_table_image')) return
                    resetResult()
                    if (selected.size > 5_000_000) {
                      setError('Table image must be 5 MB or smaller')
                      return
                    }
                    current.current.tableFile = selected
                    current.current.tableText = ''
                    setTableFile(selected)
                    setTableText('')
                  }}
                />
              </label>
            ) : null}
            {modeAllowed('table') && (
            <label className="flex items-center gap-2 text-[11px] text-fg-2">
              <input
                type="checkbox"
                checked={firstRowHeader}
                onChange={(event) => {
                  if (!modeAllowed('table') || current.current.mode !== 'table') return
                  current.current.firstRowHeader = event.target.checked
                  setFirstRowHeader(event.target.checked)
                  resetResult()
                }}
                className="accent-accent"
              />
              Treat first row as a header
            </label>
            )}
            <p className="text-[9px] leading-relaxed text-fg-3">
              Pasted CSV/TSV stays local to deterministic conversion. Images are sent to the configured AI provider for cell transcription.
            </p>
            {allows(ownedTableFile ? 'd14_table_image' : 'd14_table_text') && (
            <GenerateButton
              loading={loading}
              disabled={!tableReady || !allows(ownedTableFile ? 'd14_table_image' : 'd14_table_text')}
              generated={Boolean(visibleGenerated)}
              onClick={() => void generateTable()}
              label="table"
            />
            )}
          </>
        ) : (
          <>
            {allows('d14_math_text') ? (
            <label className="block text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3">
              Describe or paste math
              <textarea
                value={ownedMathText}
                disabled={!allows('d14_math_text')}
                onChange={(event) => {
                  if (!allows('d14_math_text')) return
                  current.current.mathText = event.target.value
                  current.current.mathFile = null
                  setMathText(event.target.value)
                  setMathFile(null)
                  resetResult()
                }}
                maxLength={5000}
                rows={6}
                placeholder="e.g. the integral from zero to infinity of e to the minus x squared"
                className="mt-2 w-full resize-y rounded-[var(--radius-md)] border border-line-2 bg-surface px-3 py-2 text-xs font-normal normal-case tracking-normal text-fg outline-none transition placeholder:text-fg-3 focus:border-accent/40"
              />
            </label>
            ) : ownedMathText ? (<div aria-label="Saved math text input" className="rounded border border-line p-2 text-xs text-fg-2"><p>Saved input</p><pre className="whitespace-pre-wrap">{ownedMathText}</pre></div>) : null}
            {allows('d14_math_image') && (
            <div className="flex items-center gap-2 text-[9px] uppercase tracking-[0.12em] text-fg-3">
              <span className="h-px flex-1 bg-line" />
              or use an image
              <span className="h-px flex-1 bg-line" />
            </div>
            )}
            {ownedMathFile ? (
              <div className="flex items-center gap-2 rounded-[var(--radius-md)] border border-line bg-surface p-2.5">
                <FileImage size={14} className="shrink-0 text-accent-strong" aria-hidden="true" />
                <span className="min-w-0 flex-1 truncate text-[11px] text-fg-2">{ownedMathFile.name}</span>
                <button
                  type="button"
                  onClick={() => {
                    if (!isCurrentCallback()) return
                    current.current.mathFile = null
                    setMathFile(null)
                    resetResult()
                  }}
                  aria-label="Remove math image"
                  className="rounded p-1 text-fg-3 hover:bg-surface-2 hover:text-fg"
                >
                  <X size={12} aria-hidden="true" />
                </button>
              </div>
            ) : allows('d14_math_image') ? (
              <label className="flex cursor-pointer items-center justify-center gap-2 rounded-[var(--radius-md)] border border-dashed border-line-2 bg-surface px-3 py-3 text-[11px] font-medium text-fg-2 transition hover:border-accent/40 hover:text-accent-strong">
                <FileImage size={13} aria-hidden="true" />
                Choose PNG, JPEG, or WebP
                <input
                  type="file"
                  disabled={!allows('d14_math_image')}
                  accept="image/png,image/jpeg,image/webp,.png,.jpg,.jpeg,.webp"
                  className="sr-only"
                  onChange={(event) => {
                    const selected = event.target.files?.[0] ?? null
                    event.target.value = ''
                    if (!selected || !allows('d14_math_image')) return
                    resetResult()
                    if (selected.size > 5_000_000) {
                      setError('Math image must be 5 MB or smaller')
                      return
                    }
                    current.current.mathFile = selected
                    current.current.mathText = ''
                    setMathFile(selected)
                    setMathText('')
                  }}
                />
              </label>
            ) : null}
            {modeAllowed('math') && (
            <div>
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3">
                Insert as
              </p>
              <div className="grid grid-cols-3 gap-1" role="radiogroup" aria-label="Math display mode">
                {(['inline', 'display', 'equation'] as const).map((displayMode) => (
                  <button
                    key={displayMode}
                    type="button"
                    role="radio"
                    aria-checked={mathDisplayMode === displayMode}
                    onClick={() => {
                      if (!modeAllowed('math') || current.current.mode !== 'math') return
                      current.current.mathDisplayMode = displayMode
                      setMathDisplayMode(displayMode)
                      resetResult()
                    }}
                    className={`rounded-[var(--radius-sm)] px-2 py-1.5 text-[10px] font-medium capitalize transition ${
                      mathDisplayMode === displayMode
                        ? 'bg-accent-soft text-accent-strong ring-1 ring-accent/30'
                        : 'bg-surface-2 text-fg-3 hover:text-fg-2'
                    }`}
                  >
                    {displayMode}
                  </button>
                ))}
              </div>
            </div>
            )}
            <p className="text-[9px] leading-relaxed text-fg-3">
              Text and images are sent to the configured AI provider. Image transcription preserves the expression and does not solve it.
            </p>
            {allows(ownedMathFile ? 'd14_math_image' : 'd14_math_text') && (
            <GenerateButton
              loading={loading}
              disabled={!mathReady || !allows(ownedMathFile ? 'd14_math_image' : 'd14_math_text')}
              generated={Boolean(visibleGenerated)}
              onClick={() => void generateMath()}
              label="math"
            />
            )}
          </>
        )}

        {error && (
          <div role="alert" className="flex gap-2 rounded-[var(--radius-md)] border border-err/30 bg-err/10 p-3 text-[11px] leading-relaxed text-err">
            <AlertCircle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
            <span>{error}</span>
          </div>
        )}

        {visibleGenerated && (
          <div className="space-y-2.5 rounded-[var(--radius-md)] border border-line bg-surface p-3">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3">
                Review fragment
              </span>
              {cached && <span className="text-[9px] text-fg-3">Cached result</span>}
              {tableShape && (
                <span className="text-[9px] text-fg-3">
                  {tableShape.rows} rows × {tableShape.columns} columns
                </span>
              )}
            </div>
            <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-[var(--radius-sm)] bg-bg p-2.5 font-mono text-[10px] leading-relaxed text-fg-2">
              {visibleGenerated}
            </pre>
            {ready && insertionAllowed && (insertionGuard?.() ?? true) && can('c01') && (
            <button
              type="button"
              onClick={insertFragment}
              disabled={inserted || !canInsert}
              className="flex w-full items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-accent-soft py-2 text-[11px] font-semibold text-accent-strong ring-1 ring-accent/30 transition hover:brightness-110 disabled:cursor-default disabled:opacity-70"
            >
              {inserted ? <Check size={12} aria-hidden="true" /> : <Sparkles size={12} aria-hidden="true" />}
              {inserted ? 'Inserted at cursor' : 'Insert at cursor'}
            </button>
            )}
            <button type="button" onClick={() => void copyFragment()} className="w-full text-[11px] text-fg-2 underline">
              Copy fragment
            </button>
          </div>
        )}
      </div>
    </section>
  )
}

function ModeButton({
  active,
  disabled,
  onClick,
  icon,
  children,
}: {
  active: boolean
  disabled: boolean
  onClick: () => void
  icon: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      disabled={disabled}
      onClick={onClick}
      className={`flex items-center justify-center gap-1.5 rounded-[var(--radius-sm)] px-2 py-1.5 text-[10px] font-semibold transition ${
        active ? 'bg-surface text-fg shadow-sm' : 'text-fg-3 hover:text-fg-2'
      }`}
    >
      {icon}
      {children}
    </button>
  )
}

function GenerateButton({
  loading,
  disabled,
  generated,
  onClick,
  label,
}: {
  loading: boolean
  disabled: boolean
  generated: boolean
  onClick: () => void
  label: 'fragment' | 'table' | 'math'
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || loading}
      className="flex w-full items-center justify-center gap-2 rounded-[var(--radius-md)] bg-accent px-3 py-2 text-xs font-semibold text-accent-fg transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {loading ? <Loader2 size={13} className="animate-spin" aria-hidden="true" /> : <Sparkles size={13} aria-hidden="true" />}
      {loading ? 'Generating…' : generated ? `Generate ${label} again` : `Generate ${label}`}
    </button>
  )
}
