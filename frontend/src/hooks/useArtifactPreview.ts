'use client'

import { useEffect, useRef, useState } from 'react'
import { apiClient } from '@/lib/api-client'
import type { ArtifactReadyEvent } from '@/lib/event-types'

export async function sha256Bytes(bytes: BufferSource): Promise<string> {
  const hash = await crypto.subtle.digest('SHA-256', bytes)
  return Array.from(new Uint8Array(hash), (byte) => byte.toString(16).padStart(2, '0')).join('')
}

export function useSourceHash(source: string) {
  const [snapshot, setSnapshot] = useState<{ source: string; hash: string } | null>(null)
  useEffect(() => {
    let stopped = false
    void sha256Bytes(new TextEncoder().encode(source)).then((hash) => {
      if (!stopped) setSnapshot({ source, hash })
    }).catch(() => {})
    return () => { stopped = true }
  }, [source])
  return snapshot?.source === source ? snapshot.hash : null
}

/** Fetch immutable bytes before terminal scoring; never relabel another revision. */
export function useArtifactPreview(options: {
  artifact: ArtifactReadyEvent | null; identity: string; fingerprint?: string
  onReady: (blob: Blob, artifact: ArtifactReadyEvent) => void
}) {
  const [verified, setVerified] = useState<{ artifact: ArtifactReadyEvent; blob: Blob; identity: string } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const onReadyRef = useRef(options.onReady)
  onReadyRef.current = options.onReady
  const identityRef = useRef(options.identity)
  identityRef.current = options.identity
  const artifact = options.artifact
  const artifactRef = useRef(artifact)
  artifactRef.current = artifact
  useEffect(() => {
    const artifact = artifactRef.current
    const identity = options.identity
    setError(null)
    if (!artifact) return
    const controller = new AbortController()
    let stopped = false
    void (async () => {
      try {
        if (!/^[a-f0-9]{64}$/.test(artifact.artifact_id) || !/^[a-f0-9]{64}$/.test(artifact.pdf_sha256)
            || !/^[a-f0-9]{64}$/.test(artifact.source_sha256) || artifact.pdf_size <= 0 || artifact.pdf_size > 20 * 1024 * 1024) {
          throw new Error('Invalid PDF artifact identity')
        }
        const blob = await apiClient.downloadArtifactPdf(artifact.job_id, artifact.artifact_id, options.fingerprint, controller.signal)
        if (blob.size !== artifact.pdf_size || await sha256Bytes(await blob.arrayBuffer()) !== artifact.pdf_sha256) {
          throw new Error('PDF artifact integrity check failed')
        }
        if (stopped || identityRef.current !== identity || artifactRef.current?.artifact_id !== artifact.artifact_id
            || artifactRef.current?.job_id !== artifact.job_id) return
        setVerified({ artifact, blob, identity })
        onReadyRef.current(blob, artifact)
      } catch (cause) {
        if (!stopped && identityRef.current === identity && artifactRef.current?.artifact_id === artifact.artifact_id
            && artifactRef.current?.job_id === artifact.job_id) setError(cause instanceof Error ? cause.message : 'PDF preview could not be loaded')
      }
    })()
    return () => { stopped = true; controller.abort() }
  }, [artifact?.artifact_id, artifact?.job_id, artifact?.source_sha256, artifact?.pdf_sha256, artifact?.pdf_size, options.identity, options.fingerprint])
  return { verified: verified?.identity === options.identity ? verified : null, error }
}
