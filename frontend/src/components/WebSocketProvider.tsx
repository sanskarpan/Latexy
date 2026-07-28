'use client'

/**
 * WebSocketProvider - wraps wsClient in a React context.
 *
 * Exposes:
 *   connected:    boolean - current WebSocket connection state
 *   lastError:    last {code, message} error frame sent by the server, or null
 *   subscribe:    (jobId, lastEventId?) => void
 *   unsubscribe:  (jobId) => void
 *   cancelJob:    (jobId) => void
 *
 * Uses the WSClient singleton from @/lib/ws-client.
 * Connects on mount, disconnects on unmount.
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from 'react'
import { toast } from 'sonner'
import { wsClient } from '@/lib/ws-client'

// ------------------------------------------------------------------ //
//  Context types                                                       //
// ------------------------------------------------------------------ //

export interface WSServerError {
  code: string
  message: string
}

export interface WSContextValue {
  connected: boolean
  lastError: WSServerError | null
  subscribe: (jobId: string, lastEventId?: string) => void
  unsubscribe: (jobId: string) => void
  cancelJob: (jobId: string) => void
}

const WSContext = createContext<WSContextValue>({
  connected: false,
  lastError: null,
  subscribe: () => {},
  unsubscribe: () => {},
  cancelJob: () => {},
})

/** Server error codes → user-facing copy. Anything else falls back to the
 *  server's own message so a new code is still visible instead of silent. */
const ERROR_COPY: Record<string, string> = {
  forbidden: 'You do not have access to this job.',
  rate_limited: 'Too many live updates — slowing down.',
  invalid_request: 'The live-updates request was rejected by the server.',
  invalid_json: 'The live-updates connection sent a malformed message.',
}

// ------------------------------------------------------------------ //
//  Provider                                                            //
// ------------------------------------------------------------------ //

interface WSProviderProps {
  children: React.ReactNode
}

export const WSProvider: React.FC<WSProviderProps> = ({ children }) => {
  const [connected, setConnected] = useState(false)
  const [lastError, setLastError] = useState<WSServerError | null>(null)

  useEffect(() => {
    const onConnected = () => setConnected(true)
    const onDisconnected = () => setConnected(false)
    const onServerError = (err: WSServerError) => {
      // Without this the server's rejection frames were dropped on the floor and
      // the user just watched a job that never progressed.
      setLastError(err)
      toast.error(ERROR_COPY[err.code] ?? err.message ?? 'Live updates failed')
    }

    wsClient.on('connected', onConnected)
    wsClient.on('disconnected', onDisconnected)
    wsClient.on('error', onServerError)

    // Connect the singleton (noop if already connected)
    wsClient.connect()

    // Reflect current state in case the socket was already open
    setConnected(wsClient.connected)

    return () => {
      wsClient.off('connected', onConnected)
      wsClient.off('disconnected', onDisconnected)
      wsClient.off('error', onServerError)
      wsClient.disconnect()
    }
  }, [])

  const subscribe = useCallback(
    (jobId: string, lastEventId?: string) => wsClient.subscribe(jobId, lastEventId),
    []
  )

  const unsubscribe = useCallback(
    (jobId: string) => wsClient.unsubscribe(jobId),
    []
  )

  const cancelJob = useCallback(
    (jobId: string) => wsClient.cancelJob(jobId),
    []
  )

  return (
    <WSContext.Provider value={{ connected, lastError, subscribe, unsubscribe, cancelJob }}>
      {children}
    </WSContext.Provider>
  )
}

// ------------------------------------------------------------------ //
//  Convenience hook                                                    //
// ------------------------------------------------------------------ //

export function useWS(): WSContextValue {
  return useContext(WSContext)
}

// Legacy alias - keeps existing useWebSocket() callers working
export const useWebSocket = useWS

// Named alias so layout.tsx can do: import { WebSocketProvider } from '@/components/WebSocketProvider'
export const WebSocketProvider = WSProvider

export default WSProvider
