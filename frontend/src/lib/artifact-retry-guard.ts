export interface ArtifactRetryIdentity {
  ownerId: string | null
  resumeId: string
  generation: number
  source: string
  activeJobId: string | null
  jobId: string
  artifactId: string
}

/** True only while the same owner, source, active job, and immutable artifact remain current. */
export function isCurrentArtifactRetry(
  expected: ArtifactRetryIdentity,
  current: ArtifactRetryIdentity | null,
): boolean {
  return Boolean(current
    && current.ownerId === expected.ownerId
    && current.resumeId === expected.resumeId
    && current.generation === expected.generation
    && current.source === expected.source
    && current.activeJobId === expected.activeJobId
    && current.jobId === expected.jobId
    && current.artifactId === expected.artifactId
    && current.activeJobId === current.jobId)
}

/** Resolve a retry only if its identity is still current when the GET completes. */
export async function resolveCurrentArtifactRetry<T>(
  expected: ArtifactRetryIdentity,
  getCurrent: () => ArtifactRetryIdentity | null,
  operation: Promise<T>,
): Promise<T | null> {
  const result = await operation
  return isCurrentArtifactRetry(expected, getCurrent()) ? result : null
}
