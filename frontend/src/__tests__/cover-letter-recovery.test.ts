import { readFileSync } from 'node:fs'
import { describe, expect, test } from 'vitest'

const PAGE = readFileSync(
  new URL('../app/workspace/[resumeId]/cover-letter/page.tsx', import.meta.url),
  'utf8',
)
const HOOK = readFileSync(new URL('../hooks/useJobStream.ts', import.meta.url), 'utf8')
const SIGNATURE_PANEL = readFileSync(new URL('../components/CoverLetterSignaturePanel.tsx', import.meta.url), 'utf8')

describe('cover-letter recovered generation lifecycle', () => {
  test('guards the generated completion compile before starting async work', () => {
    expect(PAGE).toContain('const generationCompileStartedRef = useRef<string | null>(null)')
    expect(PAGE).toContain('generationCompileStartedRef.current !== activeJobId')
    expect(PAGE).toContain('generationCompileStartedRef.current = generationJobId')
    expect(PAGE).toContain('completionTrackedJobIdRef.current !== activeJobId')
  })

  test('rejects late PDF and compile responses from another route, user, or job', () => {
    expect(PAGE).toContain('resumeIdRef.current === completedResumeId')
    expect(PAGE).toContain('sessionUserIdRef.current === completedUserId')
    expect(PAGE).toContain('activeJobIdRef.current === completedJobId')
    expect(PAGE).toContain('if (!isCurrentRoute() || activeJobIdRef.current !== completedJobId) return')
    expect(PAGE).toContain('if (isCurrentRun() && r.success && r.job_id)')
    expect(PAGE).toContain('const isCurrentPage = useCallback')
    expect(PAGE).toContain('const ownerKey = JSON.stringify([resumeId, sessionUserId, requestedCoverLetterId])')
    expect(PAGE).toContain('requestedCoverLetterIdRef.current === requestedCoverLetterId')
    expect(PAGE).toContain('invalidatedOwnerKeyRef.current = ownerKey')
    expect(PAGE).toContain("setExistingCoverLetters([])")
    expect(PAGE).toContain('if (!isCurrentPage(requestResumeId, requestUserId)) return')
    expect(PAGE).toContain('if (isCurrentPage(requestResumeId, requestUserId, requestCoverLetterId)) setIsSubmitting(false)')
  })

  test('drops stale polling responses and preserves an explicit null PDF id', () => {
    expect(HOOK).toContain('!stopped && requestedJobIdRef.current === jobId')
    expect(HOOK).toContain('const stateForJob = committedJobIdRef.current === jobId ? state : initialState')
    expect(HOOK).toContain('requestedJobIdRef.current === jobId && event.job_id === jobId')
    expect(HOOK).toContain('dispatch({ type: \'__reset__\' })')
    expect(HOOK).toContain('pdf_job_id: result?.pdf_job_id ?? null')
    expect(HOOK).not.toContain('pdf_job_id: result?.pdf_job_id ?? jobId')
    expect(HOOK).toContain('if (!result || result.job_id !== jobId) return events')
    expect(HOOK).toContain('if (recoveryEvents.length === 0)')
  })

  test('does not report signature success when the page declines the save', () => {
    expect(SIGNATURE_PANEL).toContain('onApply: (latex: string) => Promise<boolean>')
    expect(SIGNATURE_PANEL).toContain("if (await onApply(next)) toast.success('Signature saved and added to the cover letter')")
    expect(PAGE).toContain('const saveSignature = async (nextLatex: string): Promise<boolean>')
    expect(PAGE).toContain("if (isCurrentPage(requestResumeId, requestUserId, requestCoverLetterId)) toast.error('Failed to save signature')")
  })
})
