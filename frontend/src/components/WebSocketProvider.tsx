'use client'

import React, { createContext, useContext, useEffect, useRef, useState, useCallback } from 'react'
import { getWebSocketUrl } from '@/lib/job-api-client'

interface WebSocketMessage {
  type: 'job_update' | 'subscription_confirmed' | 'pong' | 'error'
  job_id?: string
  data?: any
  error?: string
}

interface JobUpdate {
  status: string
  progress?: number
  message?: string
  result?: any
  error?: string
  completed_at?: number
}

interface WebSocketContextType {
  isConnected: boolean
  connectionId: string | null
  subscribeToJob: (jobId: string) => void
  unsubscribeFromJob: (jobId: string) => void
  sendMessage: (message: any) => void
  jobUpdates: Record<string, JobUpdate>
  clearJobUpdate: (jobId: string) => void
  reconnect: () => void
}

const WebSocketContext = createContext<WebSocketContextType | null>(null)

export const useWebSocket = () => {
  const context = useContext(WebSocketContext)
  if (!context) {
    throw new Error('useWebSocket must be used within a WebSocketProvider')
  }
  return context
}

interface WebSocketProviderProps {
  children: React.ReactNode
  autoConnect?: boolean
  reconnectInterval?: number
}

export const WebSocketProvider: React.FC<WebSocketProviderProps> = ({
  children,
  autoConnect = true,
  reconnectInterval = 5000,
}) => {
  const [isConnected, setIsConnected] = useState(false)
  const [connectionId, setConnectionId] = useState<string | null>(null)
  const [jobUpdates, setJobUpdates] = useState<Record<string, JobUpdate>>({})
  
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const subscribedJobsRef = useRef<Set<string>>(new Set())
  const connectionIdRef = useRef<string | null>(null)

  const generateConnectionId = useCallback(() => {
    return `conn_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`
  }, [])

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return
    }

    const newConnectionId = generateConnectionId()
    setConnectionId(newConnectionId)
    connectionIdRef.current = newConnectionId

    try {
      const wsUrl = getWebSocketUrl(newConnectionId)
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        console.log('WebSocket connected:', newConnectionId)
        setIsConnected(true)
        
        // Clear any pending reconnection attempts
        if (reconnectTimeoutRef.current) {
          clearTimeout(reconnectTimeoutRef.current)
          reconnectTimeoutRef.current = null
        }

        // Re-subscribe to all previously subscribed jobs
        subscribedJobsRef.current.forEach(jobId => {
          ws.send(JSON.stringify({
            type: 'subscribe',
            job_id: jobId
          }))
        })
      }

      ws.onmessage = (event) => {
        try {
          const message: WebSocketMessage = JSON.parse(event.data)
          
          switch (message.type) {
            case 'job_update':
              if (message.job_id && message.data) {
                setJobUpdates(prev => ({
                  ...prev,
                  [message.job_id!]: {
                    ...prev[message.job_id!],
                    ...message.data,
                    updated_at: Date.now()
                  }
                }))
              }
              break
              
            case 'subscription_confirmed':
              console.log('Subscription confirmed for job:', message.job_id)
              break
              
            case 'pong':
              // Handle ping/pong for connection health
              break
              
            case 'error':
              console.error('WebSocket error:', message.error)
              break
              
            default:
              console.log('Unknown WebSocket message type:', message.type)
          }
        } catch (error) {
          console.error('Error parsing WebSocket message:', error)
        }
      }

      ws.onclose = (event) => {
        console.log('WebSocket disconnected:', event.code, event.reason)
        setIsConnected(false)
        wsRef.current = null

        // Attempt to reconnect if not a clean close
        if (event.code !== 1000 && autoConnect) {
          console.log(`Attempting to reconnect in ${reconnectInterval}ms...`)
          reconnectTimeoutRef.current = setTimeout(() => {
            connect()
          }, reconnectInterval)
        }
      }

      ws.onerror = (error) => {
        console.error('WebSocket error:', error)
        setIsConnected(false)
      }

    } catch (error) {
      console.error('Failed to create WebSocket connection:', error)
      setIsConnected(false)
    }
  }, [autoConnect, reconnectInterval, generateConnectionId])

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }

    if (wsRef.current) {
      wsRef.current.close(1000, 'Client disconnect')
      wsRef.current = null
    }

    setIsConnected(false)
    setConnectionId(null)
    connectionIdRef.current = null
  }, [])

  const reconnect = useCallback(() => {
    disconnect()
    setTimeout(() => {
      connect()
    }, 1000)
  }, [connect, disconnect])

  const subscribeToJob = useCallback((jobId: string) => {
    subscribedJobsRef.current.add(jobId)
    
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({
        type: 'subscribe',
        job_id: jobId
      }))
    }
  }, [])

  const unsubscribeFromJob = useCallback((jobId: string) => {
    subscribedJobsRef.current.delete(jobId)
    
    // Note: The backend doesn't have an unsubscribe message type,
    // so we just remove it from our local tracking
  }, [])

  const sendMessage = useCallback((message: any) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message))
    } else {
      console.warn('WebSocket is not connected. Cannot send message:', message)
    }
  }, [])

  const clearJobUpdate = useCallback((jobId: string) => {
    setJobUpdates(prev => {
      const newUpdates = { ...prev }
      delete newUpdates[jobId]
      return newUpdates
    })
  }, [])

  // Auto-connect on mount
  useEffect(() => {
    if (autoConnect) {
      connect()
    }

    return () => {
      disconnect()
    }
  }, [autoConnect, connect, disconnect])

  // Ping/pong for connection health
  useEffect(() => {
    if (!isConnected) return

    const pingInterval = setInterval(() => {
      sendMessage({ type: 'ping' })
    }, 30000) // Ping every 30 seconds

    return () => {
      clearInterval(pingInterval)
    }
  }, [isConnected, sendMessage])

  const contextValue: WebSocketContextType = {
    isConnected,
    connectionId,
    subscribeToJob,
    unsubscribeFromJob,
    sendMessage,
    jobUpdates,
    clearJobUpdate,
    reconnect,
  }

  return (
    <WebSocketContext.Provider value={contextValue}>
      {children}
    </WebSocketContext.Provider>
  )
}

export default WebSocketProvider
