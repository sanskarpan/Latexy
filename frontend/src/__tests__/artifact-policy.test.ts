import { describe, expect, it } from 'vitest'
import { canExportArtifact } from '@/lib/artifact-policy'
import type { RenderArtifact } from '@/lib/event-types'
const artifact = { branch: 'draft', source_sha256: 'current' } as RenderArtifact

describe('PDF export authority', () => {
  it('allows only the successful completed job for the current draft', () => {
    expect(canExportArtifact(artifact, 'current', 'job', 'completed', 'job')).toBe(true)
    for (const status of ['queued', 'processing', 'failed', 'cancelled', 'idle'])
      expect(canExportArtifact(artifact, 'current', 'job', status, 'job')).toBe(false)
    expect(canExportArtifact(artifact, 'newer', 'job', 'completed', 'job')).toBe(false)
    expect(canExportArtifact(artifact, 'current', 'other', 'completed', 'job')).toBe(false)
    expect(canExportArtifact({ ...artifact, branch: 'candidate' }, 'current', 'job', 'completed', 'job')).toBe(false)
  })
})
