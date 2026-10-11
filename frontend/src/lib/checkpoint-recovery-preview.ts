export type CheckpointRecoveryIdentity = {
  ownerId: string | null
  resumeId: string
  generation: number
}

export type CheckpointRecoveryPreview = CheckpointRecoveryIdentity & {
  source: string
}

/** Build an immutable view of source returned by an authenticated checkpoint restore. */
export function createCheckpointRecoveryPreview(
  source: string,
  identity: CheckpointRecoveryIdentity,
): CheckpointRecoveryPreview | null {
  if (!identity.ownerId) return null
  return { ...identity, source }
}

/** A recovered source snapshot is visible only in the owner/document generation that restored it. */
export function isCurrentCheckpointRecoveryPreview(
  preview: CheckpointRecoveryPreview | null,
  current: CheckpointRecoveryIdentity,
): preview is CheckpointRecoveryPreview {
  return Boolean(
    preview && current.ownerId &&
    preview.ownerId === current.ownerId &&
    preview.resumeId === current.resumeId &&
    preview.generation === current.generation
  )
}

/** Keep preview exports on the recovered snapshot, never on an older shared Monaco buffer. */
export function checkpointRecoverySourceForRead(
  preview: CheckpointRecoveryPreview | null,
  current: CheckpointRecoveryIdentity,
  fallback: string,
): string {
  return isCurrentCheckpointRecoveryPreview(preview, current) ? preview.source : fallback
}
