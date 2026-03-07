'use client'

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { toast } from 'sonner'

export interface Notification {
  id: string
  type: 'success' | 'error' | 'warning' | 'info'
  title: string
  message: string
  duration?: number
}

interface NotificationContextType {
  notifications: Notification[]
  addNotification: (notification: Omit<Notification, 'id'>) => void
  removeNotification: (id: string) => void
  clearAll: () => void
}

const NotificationContext = createContext<NotificationContextType | null>(null)

export function useNotifications() {
  const context = useContext(NotificationContext)
  if (!context) {
    throw new Error('useNotifications must be used within a NotificationProvider')
  }
  return context
}

export function NotificationProvider({ children }: { children: ReactNode }) {
  const [notifications, setNotifications] = useState<Notification[]>([])

  const removeNotification = useCallback((id: string) => {
    setNotifications((prev) => prev.filter((item) => item.id !== id))
  }, [])

  const addNotification = useCallback(
    (notification: Omit<Notification, 'id'>) => {
      const id = Math.random().toString(36).slice(2, 11)
      const next: Notification = {
        ...notification,
        id,
        duration: notification.duration ?? 5000,
      }

      setNotifications((prev) => [...prev, next])

      const message = next.message?.trim() || undefined
      if (next.type === 'success') toast.success(next.title, { description: message, duration: next.duration })
      if (next.type === 'error') toast.error(next.title, { description: message, duration: next.duration })
      if (next.type === 'warning') toast.warning(next.title, { description: message, duration: next.duration })
      if (next.type === 'info') toast.info(next.title, { description: message, duration: next.duration })

      if (next.duration && next.duration > 0) {
        window.setTimeout(() => removeNotification(id), next.duration)
      }
    },
    [removeNotification]
  )

  const clearAll = useCallback(() => {
    setNotifications([])
    toast.dismiss()
  }, [])

  const value = useMemo(
    () => ({
      notifications,
      addNotification,
      removeNotification,
      clearAll,
    }),
    [notifications, addNotification, removeNotification, clearAll]
  )

  return <NotificationContext.Provider value={value}>{children}</NotificationContext.Provider>
}
