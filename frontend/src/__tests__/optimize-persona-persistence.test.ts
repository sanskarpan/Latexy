import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const OPTIMIZE_SOURCE = readFileSync(
  new URL('../app/workspace/[resumeId]/optimize/page.tsx', import.meta.url),
  'utf8',
)

describe('optimization persona persistence', () => {
  it('rolls back failed saves and prevents overlapping mutations', () => {
    expect(OPTIMIZE_SOURCE).toContain('if (isSavingPersona && personaMutationGenerationRef.current === personaIdentity.generation) return')
    expect(OPTIMIZE_SOURCE).toContain('if (personaMutationBusyRef.current || !sessionUserId) return')
    expect(OPTIMIZE_SOURCE).toContain('setPersona(previous)')
    expect(OPTIMIZE_SOURCE).toContain('Your previous selection was restored.')
    expect(OPTIMIZE_SOURCE).toContain('disabled={isProcessing || isSavingPersona}')
    expect(OPTIMIZE_SOURCE).not.toContain("updateResumeSettings(resumeId, { last_persona: next ?? '' }).catch(() => {})")
  })

  it('invalidates deferred writes across owner or document transitions', () => {
    expect(OPTIMIZE_SOURCE).toContain('generation: personaIdentityRef.current.generation + 1')
    expect(OPTIMIZE_SOURCE).toContain('personaMutationIdRef.current += 1')
    expect(OPTIMIZE_SOURCE).toContain('liveSessionUserIdRef.current === mutationOwnerId')
    expect(OPTIMIZE_SOURCE).toContain('setPersona(savedPersona || null)')
    expect(OPTIMIZE_SOURCE).toContain('mountedRef.current = false')
  })
})
