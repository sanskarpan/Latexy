'use client'

/**
 * Offline Status Banner (Feature 79F).
 *
 * Subscribes to the browser `online` / `offline` events and renders an
 * amber banner when the connection is lost.  Accepts an optional
 * `pendingCount` prop to display a badge indicating how many unsynced
 * drafts / queued compiles are waiting.
 */

import { useEffect, useState } from 'react'
import { WifiOff } from 'lucide-react'

export function useOnlineStatus(): boolean {
  const [online, setOnline] = useState(
    typeof navigator !== 'undefined' ? navigator.onLine : true,
  )

  useEffect(() => {
    const handleOnline = () => setOnline(true)
    const handleOffline = () => setOnline(false)
    window.addEventListener('online', handleOnline)
    window.addEventListener('offline', handleOffline)
    return () => {
      window.removeEventListener('online', handleOnline)
      window.removeEventListener('offline', handleOffline)
    }
  }, [])

  return online
}

interface OfflineBannerProps {
  /** Number of unsynced items waiting to be flushed on reconnect. */
  pendingCount?: number
}

export default function OfflineBanner({ pendingCount = 0 }: OfflineBannerProps) {
  const isOnline = useOnlineStatus()

  if (isOnline) return null

  return (
    <div className="flex shrink-0 items-center justify-between border-b border-amber-500/20 bg-amber-500/10 px-4 py-1.5">
      <div className="flex items-center gap-2">
        <WifiOff size={13} className="text-amber-400" />
        <span className="text-[11px] text-amber-300">
          You&apos;re offline — edits are saved locally and will sync when you reconnect
        </span>
      </div>
      {pendingCount > 0 && (
        <span className="ml-3 shrink-0 rounded-full bg-amber-500/20 px-2 py-0.5 text-[10px] font-semibold text-amber-300">
          {pendingCount} pending
        </span>
      )}
    </div>
  )
}
