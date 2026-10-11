'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { apiClient } from '@/lib/api-client'
import type { EngineCapability } from '@/lib/engine-capability'

/** Probe once per account or explicit retry, never on typing or mode changes. */
export function useEngineCapability(identity: string) {
  const account = `${identity}:${apiClient.getAuthToken() ?? ''}`
  const currentAccount = useRef(account)
  currentAccount.current = account
  const [snapshot, setSnapshot] = useState<{ account: string; identity: string; capability: EngineCapability; sourceFallback: boolean } | null>(null)
  const [checking, setChecking] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const retry = useCallback(() => setAttempt((value) => value + 1), [])
  useEffect(() => {
    let stopped = false
    const controller = new AbortController()
    setChecking(true)
    const adopt = (capability: EngineCapability) => {
      if (stopped || currentAccount.current !== account) return
      setSnapshot((previous) => ({ account, identity, capability,
        // A failed retry must not replace an already-usable source editor with
        // unavailable fields. Authorization errors alone never start fallback.
        sourceFallback: capability.status === 'unsupported'
          || (capability.status === 'error' && previous?.identity === identity && previous.sourceFallback),
      }))
    }
    void apiClient.getEngineCapability(controller.signal).then(adopt).catch(() => {
      adopt({ status: 'error', reason: 'unavailable' })
    }).finally(() => {
      if (!stopped && currentAccount.current === account) setChecking(false)
    })
    return () => { stopped = true; controller.abort() }
  }, [account, identity, attempt])
  // Keep an unsupported result visible during an explicit retry, so a pending
  // check cannot remount the fields editor or disturb a source edit.
  const capability = snapshot?.account === account ? snapshot.capability : { status: 'loading' as const }
  return { ...capability, sourceFallback: snapshot?.identity === identity && snapshot.sourceFallback, checking: capability.status === 'loading' || checking, retry }
}
