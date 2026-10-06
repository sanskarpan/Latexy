import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const source = readFileSync(new URL('../app/tenant-invite/page.tsx', import.meta.url), 'utf8')

describe('tenant invitation claim lifecycle', () => {
  it('requires an explicit, synchronously locked single-use claim', () => {
    expect(source).toContain('const claimAttemptRef = useRef<ClaimOwner | null>(null)')
    expect(source).toContain('const claimGenerationRef = useRef(0)')
    expect(source).toContain('const handleAcceptInvitation = () => {')
    expect(source).toContain('claimAttemptRef.current = owner')
    expect(source).toContain('onClick={handleAcceptInvitation}')
    expect(source).toContain('claimGenerationRef.current !== owner.generation')
    expect(source).toContain('claimAttemptRef.current = null')
  })

  it('invalidates token/account ownership on lifecycle changes and classifies retries', () => {
    expect(source).toContain('claimGenerationRef.current += 1')
    expect(source).toContain('}, [accountKey, isPending, token])')
    expect(source).toContain('function isRetryableClaimFailure')
    expect(source).toContain('setRetryable(isRetryableClaimFailure(httpStatus(reason)))')
    expect(source).toContain('Try again')
  })
})
