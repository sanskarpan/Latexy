'use client'

/**
 * PWA Install Prompt (Feature 79G).
 *
 * Captures the browser's `beforeinstallprompt` event and exposes a
 * `prompt()` function that the UI can call to show the native install
 * dialog.
 */

import { useEffect, useState } from 'react'

interface BeforeInstallPromptEvent extends Event {
  prompt(): Promise<void>
  userChoice: Promise<{ outcome: 'accepted' | 'dismissed' }>
}

export interface PWAInstallState {
  /** True when the browser supports installation and it hasn't been triggered yet. */
  canInstall: boolean
  /** Call this to show the native "Add to Home Screen" dialog. */
  prompt: () => Promise<void>
}

export function usePWAInstall(): PWAInstallState {
  const [deferredPrompt, setDeferredPrompt] =
    useState<BeforeInstallPromptEvent | null>(null)

  useEffect(() => {
    const handler = (e: Event) => {
      e.preventDefault()
      setDeferredPrompt(e as BeforeInstallPromptEvent)
    }
    window.addEventListener('beforeinstallprompt', handler)
    return () => window.removeEventListener('beforeinstallprompt', handler)
  }, [])

  const prompt = async () => {
    if (!deferredPrompt) return
    await deferredPrompt.prompt()
    const { outcome } = await deferredPrompt.userChoice
    if (outcome === 'accepted') {
      setDeferredPrompt(null)
    }
  }

  return { canInstall: deferredPrompt !== null, prompt }
}
