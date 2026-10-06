'use client'

import { useState } from 'react'
import { AlertCircle, Check, FileImage, Loader2, Sigma, Sparkles, Table2, X } from 'lucide-react'
import { apiClient } from '@/lib/api-client'

interface LatexGeneratorPanelProps {
  documentContext: string
  onInsert: (latex: string) => void
}

type GeneratorMode = 'structure' | 'table' | 'math'
type MathDisplayMode = 'inline' | 'display' | 'equation'

export default function LatexGeneratorPanel({ documentContext, onInsert }: LatexGeneratorPanelProps) {
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

  const resetResult = () => {
    setGenerated('')
    setCached(false)
    setTableShape(null)
    setError(null)
    setInserted(false)
  }

  const switchMode = (nextMode: GeneratorMode) => {
    setMode(nextMode)
    resetResult()
  }

  const generateStructure = async () => {
    const normalizedIntent = intent.trim()
    if (normalizedIntent.length < 5 || loading) return
    setLoading(true)
    resetResult()
    try {
      const response = await apiClient.generateLatex({
        intent: normalizedIntent,
        document_context: documentContext.slice(0, 20_000),
      })
      setGenerated(response.latex)
      setCached(response.cached)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'LaTeX generation failed')
    } finally {
      setLoading(false)
    }
  }

  const generateTable = async () => {
    if ((!tableFile && tableText.trim().length < 3) || loading) return
    setLoading(true)
    resetResult()
    try {
      const response = tableFile
        ? await apiClient.generateLatexTableFromImage(tableFile, firstRowHeader)
        : await apiClient.generateLatexTable({
            table_text: tableText,
            first_row_header: firstRowHeader,
          })
      setGenerated(response.latex)
      setTableShape({ rows: response.rows, columns: response.columns })
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Table conversion failed')
    } finally {
      setLoading(false)
    }
  }

  const generateMath = async () => {
    if ((!mathFile && mathText.trim().length < 2) || loading) return
    setLoading(true)
    resetResult()
    try {
      const response = mathFile
        ? await apiClient.generateLatexMathFromImage(mathFile, mathDisplayMode)
        : await apiClient.generateLatexMath({
            math_text: mathText,
            display_mode: mathDisplayMode,
          })
      setGenerated(response.latex)
      setCached(response.cached)
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Math conversion failed')
    } finally {
      setLoading(false)
    }
  }

  const tableReady = Boolean(tableFile) || tableText.trim().length >= 3
  const mathReady = Boolean(mathFile) || mathText.trim().length >= 2

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
          <ModeButton active={mode === 'structure'} onClick={() => switchMode('structure')} icon={<Sparkles size={11} />}>
            Describe
          </ModeButton>
          <ModeButton active={mode === 'table'} onClick={() => switchMode('table')} icon={<Table2 size={11} />}>
            Table
          </ModeButton>
          <ModeButton active={mode === 'math'} onClick={() => switchMode('math')} icon={<Sigma size={11} />}>
            Math
          </ModeButton>
        </div>
      </div>

      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        {mode === 'structure' ? (
          <>
            <label className="block text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3">
              What should be created?
              <textarea
                value={intent}
                onChange={(event) => {
                  setIntent(event.target.value)
                  resetResult()
                }}
                maxLength={2000}
                rows={6}
                placeholder="e.g. Create a Projects section with two concise placeholder items"
                className="mt-2 w-full resize-y rounded-[var(--radius-md)] border border-line-2 bg-surface px-3 py-2 text-xs font-normal normal-case tracking-normal text-fg outline-none transition placeholder:text-fg-3 focus:border-accent/40"
              />
            </label>
            <div className="flex items-center justify-between text-[9px] text-fg-3">
              <span>Existing document text is used only as a style reference.</span>
              <span>{intent.length}/2000</span>
            </div>
            <GenerateButton
              loading={loading}
              disabled={intent.trim().length < 5}
              generated={Boolean(generated)}
              onClick={() => void generateStructure()}
              label="fragment"
            />
          </>
        ) : mode === 'table' ? (
          <>
            <label className="block text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3">
              Paste CSV or TSV
              <textarea
                value={tableText}
                onChange={(event) => {
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
            <div className="flex items-center gap-2 text-[9px] uppercase tracking-[0.12em] text-fg-3">
              <span className="h-px flex-1 bg-line" />
              or use an image
              <span className="h-px flex-1 bg-line" />
            </div>
            {tableFile ? (
              <div className="flex items-center gap-2 rounded-[var(--radius-md)] border border-line bg-surface p-2.5">
                <FileImage size={14} className="shrink-0 text-accent-strong" aria-hidden="true" />
                <span className="min-w-0 flex-1 truncate text-[11px] text-fg-2">{tableFile.name}</span>
                <button
                  type="button"
                  onClick={() => {
                    setTableFile(null)
                    resetResult()
                  }}
                  aria-label="Remove table image"
                  className="rounded p-1 text-fg-3 hover:bg-surface-2 hover:text-fg"
                >
                  <X size={12} aria-hidden="true" />
                </button>
              </div>
            ) : (
              <label className="flex cursor-pointer items-center justify-center gap-2 rounded-[var(--radius-md)] border border-dashed border-line-2 bg-surface px-3 py-3 text-[11px] font-medium text-fg-2 transition hover:border-accent/40 hover:text-accent-strong">
                <FileImage size={13} aria-hidden="true" />
                Choose PNG, JPEG, or WebP
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp,.png,.jpg,.jpeg,.webp"
                  className="sr-only"
                  onChange={(event) => {
                    const selected = event.target.files?.[0] ?? null
                    event.target.value = ''
                    if (!selected) return
                    resetResult()
                    if (selected.size > 5_000_000) {
                      setError('Table image must be 5 MB or smaller')
                      return
                    }
                    setTableFile(selected)
                    setTableText('')
                  }}
                />
              </label>
            )}
            <label className="flex items-center gap-2 text-[11px] text-fg-2">
              <input
                type="checkbox"
                checked={firstRowHeader}
                onChange={(event) => {
                  setFirstRowHeader(event.target.checked)
                  resetResult()
                }}
                className="accent-accent"
              />
              Treat first row as a header
            </label>
            <p className="text-[9px] leading-relaxed text-fg-3">
              Pasted CSV/TSV stays local to deterministic conversion. Images are sent to the configured AI provider for cell transcription.
            </p>
            <GenerateButton
              loading={loading}
              disabled={!tableReady}
              generated={Boolean(generated)}
              onClick={() => void generateTable()}
              label="table"
            />
          </>
        ) : (
          <>
            <label className="block text-[10px] font-semibold uppercase tracking-[0.12em] text-fg-3">
              Describe or paste math
              <textarea
                value={mathText}
                onChange={(event) => {
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
            <div className="flex items-center gap-2 text-[9px] uppercase tracking-[0.12em] text-fg-3">
              <span className="h-px flex-1 bg-line" />
              or use an image
              <span className="h-px flex-1 bg-line" />
            </div>
            {mathFile ? (
              <div className="flex items-center gap-2 rounded-[var(--radius-md)] border border-line bg-surface p-2.5">
                <FileImage size={14} className="shrink-0 text-accent-strong" aria-hidden="true" />
                <span className="min-w-0 flex-1 truncate text-[11px] text-fg-2">{mathFile.name}</span>
                <button
                  type="button"
                  onClick={() => {
                    setMathFile(null)
                    resetResult()
                  }}
                  aria-label="Remove math image"
                  className="rounded p-1 text-fg-3 hover:bg-surface-2 hover:text-fg"
                >
                  <X size={12} aria-hidden="true" />
                </button>
              </div>
            ) : (
              <label className="flex cursor-pointer items-center justify-center gap-2 rounded-[var(--radius-md)] border border-dashed border-line-2 bg-surface px-3 py-3 text-[11px] font-medium text-fg-2 transition hover:border-accent/40 hover:text-accent-strong">
                <FileImage size={13} aria-hidden="true" />
                Choose PNG, JPEG, or WebP
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp,.png,.jpg,.jpeg,.webp"
                  className="sr-only"
                  onChange={(event) => {
                    const selected = event.target.files?.[0] ?? null
                    event.target.value = ''
                    if (!selected) return
                    resetResult()
                    if (selected.size > 5_000_000) {
                      setError('Math image must be 5 MB or smaller')
                      return
                    }
                    setMathFile(selected)
                    setMathText('')
                  }}
                />
              </label>
            )}
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
            <p className="text-[9px] leading-relaxed text-fg-3">
              Text and images are sent to the configured AI provider. Image transcription preserves the expression and does not solve it.
            </p>
            <GenerateButton
              loading={loading}
              disabled={!mathReady}
              generated={Boolean(generated)}
              onClick={() => void generateMath()}
              label="math"
            />
          </>
        )}

        {error && (
          <div role="alert" className="flex gap-2 rounded-[var(--radius-md)] border border-err/30 bg-err/10 p-3 text-[11px] leading-relaxed text-err">
            <AlertCircle size={13} className="mt-0.5 shrink-0" aria-hidden="true" />
            <span>{error}</span>
          </div>
        )}

        {generated && (
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
              {generated}
            </pre>
            <button
              type="button"
              onClick={() => {
                onInsert(generated)
                setInserted(true)
              }}
              disabled={inserted}
              className="flex w-full items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-accent-soft py-2 text-[11px] font-semibold text-accent-strong ring-1 ring-accent/30 transition hover:brightness-110 disabled:cursor-default disabled:opacity-70"
            >
              {inserted ? <Check size={12} aria-hidden="true" /> : <Sparkles size={12} aria-hidden="true" />}
              {inserted ? 'Inserted at cursor' : 'Insert at cursor'}
            </button>
          </div>
        )}
      </div>
    </section>
  )
}

function ModeButton({
  active,
  onClick,
  icon,
  children,
}: {
  active: boolean
  onClick: () => void
  icon: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
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
