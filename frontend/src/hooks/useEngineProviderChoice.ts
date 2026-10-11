'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { apiClient } from '@/lib/api-client'
import type { EngineProvider, EngineProviderOptions } from '@/lib/resume-engine-types'

export type EngineProviderChoice = { provider: 'automatic' | EngineProvider; model: string }
const automatic: EngineProviderChoice = { provider: 'automatic', model: '' }

/** Selection must remain in the current account's server-advertised list. */
export function engineProviderRequest(options: EngineProviderOptions | null, choice: EngineProviderChoice) {
  if (!options) return null
  if (choice.provider === 'automatic') return options.default.ready ? {} : null
  const provider = options.providers.find((entry) => entry.provider === choice.provider)
  return provider?.key_available && provider.models.includes(choice.model)
    ? { provider: provider.provider, provider_model: choice.model } : null
}

export function useEngineProviderChoice(identity: string) {
  const token = apiClient.getAuthToken()
  const account = `${identity}:${token ?? ''}`
  const currentAccount = useRef(account); currentAccount.current = account
  const isCurrent = useCallback(() => currentAccount.current === account && apiClient.getAuthToken() === token, [account, token])
  const [snapshot, setSnapshot] = useState<{ account: string; options: EngineProviderOptions | null; error: string | null } | null>(null)
  const [selection, setSelection] = useState<{ account: string; choice: EngineProviderChoice } | null>(null)
  const [retry, setRetry] = useState(0)
  const options = snapshot?.account === account ? snapshot.options : null
  const error = snapshot?.account === account ? snapshot.error : null
  const choice = selection?.account === account ? selection.choice : automatic
  useEffect(() => {
    let stopped = false
    const controller = new AbortController()
    setSnapshot(null); setSelection(null)
    if (token) void apiClient.getEngineProviders({
      authToken: token, isCurrent: () => !stopped && isCurrent(),
    }, controller.signal).then((result) => {
      if (stopped || !isCurrent()) return
      if (!result?.default || !Array.isArray(result.providers)) throw new Error('Invalid provider options')
      setSnapshot({ account, options: result, error: null })
    }).catch(() => {
      if (!stopped && isCurrent()) setSnapshot({ account, options: null, error: 'Review options could not be loaded. Try again.' })
    })
    return () => { stopped = true; controller.abort() }
  }, [account, token, retry, isCurrent])
  return {
    options, error, choice, request: engineProviderRequest(options, choice),
    choose: (next: EngineProviderChoice) => setSelection({ account, choice: next }),
    retry: () => setRetry((value) => value + 1),
    accountContext: token ? { authToken: token, isCurrent } : undefined,
  }
}
