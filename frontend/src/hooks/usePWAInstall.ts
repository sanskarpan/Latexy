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
    const installed = () => setDeferredPrompt(null)
    window.addEventListener('appinstalled', installed)
    return () => {
      window.removeEventListener('beforeinstallprompt', handler)
      window.removeEventListener('appinstalled', installed)
    }
  }, [])

  const prompt = async () => {
    if (!deferredPrompt) return
    await deferredPrompt.prompt()
    await deferredPrompt.userChoice
    // Browsers fire beforeinstallprompt again when prompting is appropriate;
    // the captured event itself cannot be reused after either outcome.
    setDeferredPrompt(null)
  }

  return { canInstall: deferredPrompt !== null, prompt }
}
