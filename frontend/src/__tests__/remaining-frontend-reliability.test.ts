import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = (relativePath: string) => readFileSync(new URL(relativePath, import.meta.url), 'utf8')

describe('remaining frontend reliability guards', () => {
  it('invalidates stale spell checks and clears loading when checking is disabled or replaced', () => {
    const spellCheck = source('../hooks/useSpellCheck.ts')

    expect(spellCheck).toContain('const requestGenerationRef = useRef(0)')
    expect(spellCheck).toContain('if (requestGenerationRef.current === generation) requestGenerationRef.current += 1')
    expect(spellCheck).toContain('if (requestGenerationRef.current === generation) setLoading(false)')
    expect(spellCheck).toContain('setRawIssues([])')
  })

  it('guards interview-prep loads and exposes a loading state during resume changes', () => {
    const interviewPrep = source('../components/InterviewPrepPanel.tsx')

    expect(interviewPrep).toContain('const loadGenerationRef = useRef(0)')
    expect(interviewPrep).toContain('if (generation !== loadGenerationRef.current) return')
    expect(interviewPrep).toContain('if (generation === loadGenerationRef.current) setIsLoading(false)')
    expect(interviewPrep).toContain('Loading interview-prep sessions')
    expect(interviewPrep).toContain('Retry')
  })

  it('distinguishes tracker application outages from a true empty list and supports retry', () => {
    const history = source('../components/ElementVersionHistoryPanel.tsx')

    expect(history).toContain('const applicationsRequestGeneration = useRef(0)')
    expect(history).toContain('generation !== applicationsRequestGeneration.current')
    expect(history).toContain('const [applicationsError, setApplicationsError]')
    expect(history).toContain('Tracker applications are unavailable right now.')
    expect(history).toContain('setApplicationsRetry(value => value + 1)')
    expect(history).toContain('No tracker applications are linked to this resume.')
  })

  it('does not present an omitted job-health count as zero', () => {
    const queue = source('../components/JobQueue.tsx')

    expect(queue).toContain("systemHealth?.active_jobs_count ?? 'Unavailable'")
  })
})
