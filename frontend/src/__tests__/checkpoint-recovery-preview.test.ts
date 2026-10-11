import { describe, expect, it } from 'vitest'
import {
  checkpointRecoverySourceForRead,
  createCheckpointRecoveryPreview,
  isCurrentCheckpointRecoveryPreview,
} from '@/lib/checkpoint-recovery-preview'

describe('checkpoint recovery preview', () => {
  const identity = { ownerId: 'owner-a', resumeId: 'resume-a', generation: 7 }

  it('shows the authenticated restore snapshot only for its owner, document, and generation', () => {
    const preview = createCheckpointRecoveryPreview('restored source', identity)
    expect(preview).toEqual({ ...identity, source: 'restored source' })
    expect(isCurrentCheckpointRecoveryPreview(preview, identity)).toBe(true)
    expect(isCurrentCheckpointRecoveryPreview(preview, { ...identity, ownerId: 'owner-b' })).toBe(false)
    expect(isCurrentCheckpointRecoveryPreview(preview, { ...identity, resumeId: 'resume-b' })).toBe(false)
    expect(isCurrentCheckpointRecoveryPreview(preview, { ...identity, generation: 8 })).toBe(false)
    expect(isCurrentCheckpointRecoveryPreview(preview, { ...identity, ownerId: null })).toBe(false)
  })

  it('uses restored source for reads while previewing and shared source after the preview is cleared', () => {
    const preview = createCheckpointRecoveryPreview('checkpoint source', identity)
    expect(checkpointRecoverySourceForRead(preview, identity, 'older shared source')).toBe('checkpoint source')
    expect(checkpointRecoverySourceForRead(null, identity, 'shared source')).toBe('shared source')
    expect(checkpointRecoverySourceForRead(preview, { ...identity, generation: 9 }, 'current source')).toBe('current source')
  })

  it('does not create an unowned recovery snapshot', () => {
    expect(createCheckpointRecoveryPreview('restored source', { ...identity, ownerId: null })).toBeNull()
  })
})
