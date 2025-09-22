'use client'

import { useState, useCallback } from 'react'
import { NotificationProps } from '@/components/Notification'

type NotificationType = 'success' | 'error' | 'warning' | 'info'

interface NotificationOptions {
  title: string
  message?: string
  duration?: number
}

export function useNotifications() {
  const [notifications, setNotifications] = useState<NotificationProps[]>([])

  const addNotification = useCallback((
    type: NotificationType,
    options: NotificationOptions
  ) => {
    const id = Math.random().toString(36).substr(2, 9)
    const notification: NotificationProps = {
      id,
      type,
      onClose: removeNotification,
      duration: 5000,
      ...options
    }

    setNotifications(prev => [...prev, notification])
    return id
  }, [])

  const removeNotification = useCallback((id: string) => {
    setNotifications(prev => prev.filter(n => n.id !== id))
  }, [])

  const success = useCallback((options: NotificationOptions) => 
    addNotification('success', options), [addNotification])

  const error = useCallback((options: NotificationOptions) => 
    addNotification('error', options), [addNotification])

  const warning = useCallback((options: NotificationOptions) => 
    addNotification('warning', options), [addNotification])

  const info = useCallback((options: NotificationOptions) => 
    addNotification('info', options), [addNotification])

  return {
    notifications,
    success,
    error,
    warning,
    info,
    removeNotification
  }
}