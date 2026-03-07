'use client'

/**
 * WebSocketProvider — wraps wsClient in a React context.
 *
 * Exposes:
 *   connected:    boolean — current WebSocket connection state
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
import { wsClient } from '@/lib/ws-client'

// ------------------------------------------------------------------ //
//  Context types                                                       //
// ------------------------------------------------------------------ //

export interface WSContextValue {
  connected: boolean
  subscribe: (jobId: string, lastEventId?: string) => void
  unsubscribe: (jobId: string) => void
  cancelJob: (jobId: string) => void
}

const WSContext = createContext<WSContextValue>({
  connected: false,
  subscribe: () => {},
  unsubscribe: () => {},
  cancelJob: () => {},
})

// ------------------------------------------------------------------ //
//  Provider                                                            //
// ------------------------------------------------------------------ //

interface WSProviderProps {
  children: React.ReactNode
}

export const WSProvider: React.FC<WSProviderProps> = ({ children }) => {
  const [connected, setConnected] = useState(false)

  useEffect(() => {
    const onConnected = () => setConnected(true)
    const onDisconnected = () => setConnected(false)

    wsClient.on('connected', onConnected)
    wsClient.on('disconnected', onDisconnected)

    // Connect the singleton (noop if already connected)
    wsClient.connect()

    // Reflect current state in case the socket was already open
    setConnected(wsClient.connected)

    return () => {
      wsClient.off('connected', onConnected)
      wsClient.off('disconnected', onDisconnected)
      // Do NOT call wsClient.disconnect() here — the singleton should
      // outlive any single provider mount/unmount cycle.
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
    <WSContext.Provider value={{ connected, subscribe, unsubscribe, cancelJob }}>
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

// Legacy alias — keeps existing useWebSocket() callers working
export const useWebSocket = useWS

// Named alias so layout.tsx can do: import { WebSocketProvider } from '@/components/WebSocketProvider'
export const WebSocketProvider = WSProvider

export default WSProvider
