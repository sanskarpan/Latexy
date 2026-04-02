import { useCallback } from 'react'

const LS_KEY = 'latexy_notifications_enabled'
const PERMISSION_ASKED_KEY = 'latexy_notification_asked'

export function usePushNotifications(enabled?: boolean) {
  const explicitEnabled = enabled

  const requestPermission = useCallback(async () => {
    if (typeof window === 'undefined') return
    if (!('Notification' in window)) return
    if (Notification.permission !== 'default') return
    // Only ask once per session
    if (sessionStorage.getItem(PERMISSION_ASKED_KEY)) return
    sessionStorage.setItem(PERMISSION_ASKED_KEY, '1')
    await Notification.requestPermission()
  }, [])

  const notify = useCallback((title: string, body: string, onClick?: () => void) => {
    if (typeof window === 'undefined') return
    const isEnabled = explicitEnabled !== undefined ? explicitEnabled : getStoredPref()
    if (!isEnabled) return
    if (!('Notification' in window)) return
    if (Notification.permission !== 'granted') return
    // Skip if tab is focused — user can already see the result
    if (document.visibilityState === 'visible') return

    const n = new Notification(title, {
      body,
      icon: '/favicon.ico',
      tag: 'latexy-job',
    })
    if (onClick) {
      n.onclick = () => {
        window.focus()
        onClick()
      }
    }
  }, [explicitEnabled])

  return { requestPermission, notify }
}

function getStoredPref(): boolean {
  if (typeof window === 'undefined') return true
  const val = localStorage.getItem(LS_KEY)
  // Default to enabled if never set
  return val !== 'false'
}

export function setNotificationPref(enabled: boolean) {
  localStorage.setItem(LS_KEY, String(enabled))
}

export function getNotificationPref(): boolean {
  return getStoredPref()
}
