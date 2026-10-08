'use client'

import { useEffect, useRef, useState } from 'react'
import { apiClient } from '@/lib/api-client'
import { previewErrorMessage } from '@/lib/preview-errors'
import { useEngineProviderChoice } from '@/hooks/useEngineProviderChoice'
import type { ResumeEngineDocument, OptimizationEffort, SemanticOptimizationRun } from '@/lib/resume-engine-types'

export default function SemanticOptimizationPanel({ resumeId, identity, document, currentSourceHash, disabled,
  jobDescription, setJobDescription, runId, provisionalPatches = [], onStarted, onApplied }: {
  resumeId: string; identity: string; document: ResumeEngineDocument | null; currentSourceHash: string | null
  provisionalPatches?: import('@/lib/resume-engine-types').SemanticPatch[]
  disabled: boolean; jobDescription: string; setJobDescription: (text: string) => void; runId: string | null
  onStarted: (jobId: string) => void
  onApplied: (document: ResumeEngineDocument, source: string, startedAt: number) => void
}) {
  const [effort, setEffort] = useState<OptimizationEffort>('standard')
  const [run, setRun] = useState<SemanticOptimizationRun | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const providerChoice = useEngineProviderChoice(identity)
  const accountToken = apiClient.getAuthToken()
  const currentIdentity = useRef(identity); currentIdentity.current = identity
  const currentSource = useRef(currentSourceHash); currentSource.current = currentSourceHash
  const currentRevision = useRef(document?.content_revision); currentRevision.current = document?.content_revision
  useEffect(() => { setRun(null); setError(null); setBusy(false) }, [identity, runId])
  // A token refresh can invalidate an in-flight admission without changing the
  // user's identity. Its fenced finally block must not leave this panel busy.
  useEffect(() => { setError(null); setBusy(false) }, [accountToken])
  useEffect(() => {
    if (!runId) return
    let stale = false; let timer: ReturnType<typeof setTimeout> | undefined
    let failures = 0
    const poll = async () => {
      try {
        const response = await apiClient.getEngineRun(resumeId, runId)
        if (stale || currentIdentity.current !== identity) return
        setRun(response); failures = 0
        if (!['completed', 'failed', 'cancelled'].includes(response.job_status ?? '') || response.status === 'running') timer = setTimeout(poll, 1000)
      } catch {
        if (stale) return
        if (++failures < 5) timer = setTimeout(poll, 2000)
        else setError('Review could not be recovered. Reload this resume to reconnect.')
      }
    }
    void poll()
    return () => { stale = true; if (timer) clearTimeout(timer) }
  }, [identity, resumeId, runId])
  const eligible = document && document.source_mode === 'managed' && document.source_sha256 === currentSourceHash && !disabled && !busy
  const start = async () => {
    if (!eligible || !document || !jobDescription.trim() || !providerChoice.request || !providerChoice.accountContext?.isCurrent()) return
    const source = currentSourceHash
    setBusy(true); setError(null)
    try {
      const response = await apiClient.optimizeEngineDocument(resumeId, {
        expected_content_revision: document.content_revision, expected_source_sha256: document.source_sha256,
        job_description: jobDescription.trim(), effort, ...providerChoice.request,
      }, providerChoice.accountContext)
      if (currentIdentity.current !== identity || !providerChoice.accountContext.isCurrent()) return
      if (!response.success || !response.job_id) throw new Error('Admission failed')
      if (source !== currentSource.current) setError('Your resume changed while the review started. Suggestions will require a fresh revision check.')
      onStarted(response.job_id)
    } catch (error) { if (currentIdentity.current === identity && providerChoice.accountContext.isCurrent()) setError(previewErrorMessage(error, true, 'Review could not start. Save your current resume and try again. No suggestions were applied.')) }
    finally { if (currentIdentity.current === identity && providerChoice.accountContext.isCurrent()) setBusy(false) }
  }
  const decide = async (accept: string[], reject: string[]) => {
    if (!eligible || !document || !runId || !run?.acceptance_ready) return
    const actionStarted = performance.now()
    const source = currentSourceHash; const revision = document.content_revision
    setBusy(true); setError(null)
    try {
      const response = await apiClient.decideEngineRun(resumeId, runId, {
        expected_content_revision: revision, expected_source_sha256: document.source_sha256,
        accept_patch_ids: accept, reject_patch_ids: reject,
      })
      if (currentIdentity.current !== identity) return
      if (source !== currentSource.current || revision !== currentRevision.current) {
        setError('A newer edit arrived while saving your decision. Reload to recover the saved revision.'); return
      }
      setRun((previous) => previous ? { ...previous, decisions: response.decisions } : previous)
      onApplied(response.document, response.latex_content, actionStarted)
    } catch { if (currentIdentity.current === identity) setError('This suggestion is out of date or could not be saved. Your current resume is preserved.') }
    finally { if (currentIdentity.current === identity) setBusy(false) }
  }
  const requirements = run?.result?.requirements?.requirements ?? []
  const missingEvidenceMessages = run?.result?.missing_evidence?.map((item) => {
    const excerpt = requirements.find((requirement) => requirement.requirement_id === item)?.excerpt.trim()
    return excerpt || (item.startsWith('jd.') ? 'Add supporting experience for this job requirement.' : item)
  }) ?? []
  const pending = run?.result?.patches.filter((patch) => !run.decisions.patches?.[patch.patch_id]) ?? []
  return <div className="h-full space-y-5 overflow-auto p-4">
    <div><h2 className="text-base font-semibold">Improve your resume</h2>
      <p className="mt-1 text-xs leading-relaxed text-fg-3">Review plain-language suggestions before they change your resume. Unsupported fields stay intact.</p></div>
    <label className="block text-xs font-semibold">Target job
      <textarea value={jobDescription} onChange={(event) => setJobDescription(event.target.value)} rows={5} maxLength={20000}
        className="mt-2 w-full rounded-lg border border-line bg-surface p-3 text-sm font-normal" placeholder="Paste the job description" /></label>
    <div className="space-y-2">
      <label htmlFor={`${resumeId}-review-provider`} className="block text-xs font-semibold">Review provider</label>
        <select id={`${resumeId}-review-provider`} value={providerChoice.choice.provider} disabled={busy || !providerChoice.options} onChange={(event) => {
          const provider = event.target.value as typeof providerChoice.choice.provider
          const models = providerChoice.options?.providers.find((entry) => entry.provider === provider)?.models ?? []
          providerChoice.choose({ provider, model: models.length === 1 ? models[0] : '' })
        }} className="mt-2 w-full rounded-lg border border-line bg-surface p-2 text-sm font-normal">
          <option value="automatic">Automatic</option>
          {providerChoice.options?.providers.map((entry) => <option key={entry.provider} value={entry.provider} disabled={!entry.key_available || !entry.models.length}>
            {{ openai: 'OpenAI', anthropic: 'Anthropic', openrouter: 'OpenRouter' }[entry.provider]}{!entry.key_available ? ' · connect a key' : !entry.models.length ? ' · unavailable' : ' · your key'}
          </option>)}
        </select>
      {providerChoice.choice.provider !== 'automatic' && <>
        <label htmlFor={`${resumeId}-review-model`} className="block text-xs font-semibold">Review model</label>
        <select id={`${resumeId}-review-model`} value={providerChoice.choice.model} disabled={busy} onChange={(event) => providerChoice.choose({ ...providerChoice.choice, model: event.target.value })}
          className="mt-2 w-full rounded-lg border border-line bg-surface p-2 text-sm font-normal">
          <option value="" disabled>Choose a model</option>
          {providerChoice.options?.providers.find((entry) => entry.provider === providerChoice.choice.provider)?.models.map((model) => <option key={model} value={model}>{model}</option>)}
        </select>
      </>}
      <p className="text-xs text-fg-3">{providerChoice.choice.provider === 'automatic'
        ? 'Automatic uses your connected OpenAI key when available, or the default provider.'
        : 'This review uses your selected provider and key. It will stop if that choice becomes unavailable.'} <a href="/byok" className="text-accent-strong hover:underline">Manage API keys</a></p>
      {!providerChoice.options && !providerChoice.error && <p role="status" className="text-xs text-fg-3">Loading review options…</p>}
      {providerChoice.options && providerChoice.choice.provider === 'automatic' && !providerChoice.options.default.ready && <p className="text-xs text-warn">Automatic review is unavailable. Connect an OpenAI key or choose an available provider.</p>}
      {providerChoice.error && <p role="alert" className="text-xs text-err">{providerChoice.error} <button type="button" onClick={providerChoice.retry} className="underline">Retry</button></p>}
    </div>
    <div role="group" aria-label="Review effort" className="grid grid-cols-3 gap-2">
      {(['quick', 'standard', 'deep'] as const).map((level) => <button key={level} type="button" aria-pressed={level === effort}
        onClick={() => setEffort(level)} className={`rounded-lg border p-2 text-xs capitalize ${level === effort ? 'border-accent bg-accent-soft' : 'border-line'}`}>{level}</button>)}
    </div>
    <p className="text-xs text-fg-3">{effort === 'quick' ? 'A focused pass on the most useful changes.' : effort === 'deep' ? 'A more thorough review with a larger time and usage budget.' : 'A balanced review of supported resume sections.'}</p>
    <button disabled={!eligible || !providerChoice.request || !jobDescription.trim() || run?.status === 'running'} onClick={() => void start()}
      className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-fg disabled:opacity-50">{busy ? 'Saving…' : 'Find suggestions'}</button>
    {!document && <p className="text-xs text-fg-3">Loading supported fields…</p>}
    {document && document.source_sha256 !== currentSourceHash && <p className="text-xs text-warn">Save your current resume before starting a review.</p>}
    {error && <p role="alert" className="text-xs text-err">{error}</p>}
    {run && <div role="status" className="rounded-lg border border-line p-3 text-xs">
      <p className="font-semibold capitalize">{run.effort} review · {run.status}</p>
      {!run?.acceptance_ready && ['completed', 'partial'].includes(run.status) && <p className="mt-2">Checking the final PDF before decisions become available…</p>}
      <p className="mt-1 text-fg-3">{run.budget.requests ?? 0} requests · {run.budget.usage_unknown ? 'Usage confirmation pending' : 'Usage recorded'}</p>
      {run.status === 'partial' && <p className="mt-2">The review stopped early. Validated suggestions below are still available.</p>}
    </div>}
    {run?.pdf_quality && <section aria-label="Candidate PDF checks" className="rounded-lg border border-line p-3 text-xs">
      <h3 className="font-semibold">Limited PDF checks</h3>
      <p className="mt-2 text-fg-3">{run.pdf_quality.status === 'checked'
        ? 'Limited checks completed for this candidate PDF. Review its layout before applying suggestions.'
        : 'PDF checks were unavailable. Review the candidate PDF before applying suggestions.'}</p>
      {run.pdf_quality.checks && <ul className="mt-2 space-y-1 text-fg-3">{Object.entries(run.pdf_quality.checks).map(([name, status]) =>
        <li key={name}>{name.replace(/_/g, ' ')}: {status === 'checked' ? 'reviewed' : status === 'partial' ? 'partially reviewed' : 'unavailable'}</li>)}</ul>}
      {run.pdf_quality.warnings.length > 0 && <ul className="mt-2 list-disc space-y-1 pl-4 text-warn">
        {run.pdf_quality.warnings.slice(0, 20).map((warning, index) => <li key={index}>{warning}</li>)}
      </ul>}
    </section>}
    {!run?.result && provisionalPatches.length > 0 && <div className="space-y-3">
      <p role="status" className="text-xs text-fg-3">Early suggestions · final checks are still running. Decisions become available after the review completes.</p>
      {provisionalPatches.map((patch) => <article key={patch.patch_id} className="rounded-lg border border-line p-3 text-xs">
        <p className="text-fg-3">{patch.original_text}</p><p className="mt-2">{patch.text}</p><p className="mt-2 text-fg-3">{patch.reason}</p>
      </article>)}
    </div>}
    {missingEvidenceMessages.length ? <div className="text-xs text-warn"><p>Add evidence for these suggestions:</p><ul className="mt-2 list-disc pl-4">{missingEvidenceMessages.map((item, index) => <li key={index}>{item}</li>)}</ul></div> : null}
    {run?.result?.warnings?.map((warning, index) => <p key={index} className="text-xs text-warn">{warning}</p>)}
    {pending.length > 0 && <button disabled={!eligible || !run?.acceptance_ready} onClick={() => void decide(pending.map((patch) => patch.patch_id), [])}
      className="rounded-lg border border-accent px-3 py-2 text-xs font-semibold disabled:opacity-50">Accept all {pending.length} suggestions</button>}
    {run?.result?.patches.map((patch) => <article key={patch.patch_id} className="space-y-3 rounded-lg border border-line p-3">
      <p className="text-xs font-semibold">{run.document.nodes.find((node) => node.node_id === patch.node_id)?.section ?? 'Resume field'}</p>
      <div><p className="text-[10px] uppercase text-fg-3">Current</p><p className="mt-1 text-xs leading-relaxed">{patch.original_text}</p></div>
      <div><p className="text-[10px] uppercase text-accent-strong">Suggested</p><p className="mt-1 text-xs leading-relaxed">{patch.text}</p></div>
      <p className="text-xs text-fg-3">{patch.reason}</p>
      {patch.review_reason && <p className="text-xs text-warn">{patch.review_reason}</p>}
      {run.decisions.patches?.[patch.patch_id] ? <p className="text-xs capitalize text-fg-3">{run.decisions.patches[patch.patch_id]}</p> : <div className="flex gap-2">
        <button disabled={!eligible || !run?.acceptance_ready} onClick={() => void decide([patch.patch_id], [])} className="rounded bg-accent px-3 py-1.5 text-xs text-accent-fg disabled:opacity-50">Accept</button>
        <button disabled={!eligible || !run?.acceptance_ready} onClick={() => void decide([], [patch.patch_id])} className="rounded border border-line px-3 py-1.5 text-xs disabled:opacity-50">Reject</button>
      </div>}
    </article>)}
  </div>
}
