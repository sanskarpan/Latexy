import { describe, expect, it } from 'vitest'
import { isCurrentArtifactRetry, resolveCurrentArtifactRetry, type ArtifactRetryIdentity } from '@/lib/artifact-retry-guard'

const oldArtifact: ArtifactRetryIdentity = {
  ownerId: 'owner-a', resumeId: 'resume-a', generation: 4, source: 'source-v1',
  activeJobId: 'job-old', jobId: 'job-old', artifactId: 'artifact-old',
}

describe('artifact retry identity', () => {
  it('rejects an old GET result after a newer artifact becomes current', () => {
    const newerArtifact = { ...oldArtifact, activeJobId: 'job-new', jobId: 'job-new', artifactId: 'artifact-new' }
    expect(isCurrentArtifactRetry(oldArtifact, newerArtifact)).toBe(false)
  })

  it.each([
    { ownerId: 'owner-b' },
    { resumeId: 'resume-b' },
    { generation: 5 },
    { source: 'source-v2' },
    { activeJobId: 'job-new' },
  ])('rejects retry completion after identity changes: %o', (change) => {
    expect(isCurrentArtifactRetry(oldArtifact, { ...oldArtifact, ...change })).toBe(false)
  })

  it('accepts the same live owner/source/job/artifact', () => {
    expect(isCurrentArtifactRetry(oldArtifact, { ...oldArtifact })).toBe(true)
  })

  it('discards an older GET that resolves after a newer artifact arrives', async () => {
    let current: ArtifactRetryIdentity | null = { ...oldArtifact }
    let resolveGet!: (value: string) => void
    const get = new Promise<string>((resolve) => { resolveGet = resolve })
    const pending = resolveCurrentArtifactRetry(oldArtifact, () => current, get)

    current = { ...oldArtifact, activeJobId: 'job-new', jobId: 'job-new', artifactId: 'artifact-new' }
    resolveGet('old PDF bytes')

    await expect(pending).resolves.toBeNull()
  })
})
