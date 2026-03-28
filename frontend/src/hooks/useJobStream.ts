/**
 * useJobStream - accumulates all typed WebSocket events into UI state.
 */

import { useEffect, useReducer, useCallback } from 'react'
import { wsClient } from '@/lib/ws-client'
import type { AnyEvent } from '@/lib/event-types'
import {
  jobStreamReducer,
  initialState,
} from './useJobStream.reducer'

// Re-export everything so existing imports keep working
export type {
  LogLine,
  TimeoutError,
  JobStreamState,
  ReducerAction,
} from './useJobStream.reducer'
export { jobStreamReducer, initialState } from './useJobStream.reducer'

// ------------------------------------------------------------------ //
//  Hook                                                               //
// ------------------------------------------------------------------ //

export interface UseJobStreamResult {
  state: ReturnType<typeof jobStreamReducer>
  cancel: () => void
  reset: () => void
}

export function useJobStream(jobId: string | null): UseJobStreamResult {
  const [state, dispatch] = useReducer(jobStreamReducer, initialState)

  useEffect(() => {
    if (!jobId) return

    const handleEvent = (event: AnyEvent) => {
      if (event.job_id === jobId) {
        dispatch(event)
      }
    }

    wsClient.on('event', handleEvent)
    wsClient.subscribe(jobId)

    return () => {
      wsClient.off('event', handleEvent)
      wsClient.unsubscribe(jobId)
    }
  }, [jobId])

  const cancel = useCallback(() => {
    if (jobId) wsClient.cancelJob(jobId)
  }, [jobId])

  const reset = useCallback(() => {
    dispatch({ type: '__reset__' })
  }, [])

  return { state, cancel, reset }
}
