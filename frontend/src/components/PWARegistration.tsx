'use client'

import { useEffect } from 'react'
import { registerOptionalWorker } from '@/lib/pwa-registration'

export default function PWARegistration() {
  useEffect(() => {
    registerOptionalWorker((window as Window & { workbox?: unknown }).workbox)
  }, [])

  return null
}
