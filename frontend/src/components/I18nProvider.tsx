'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import {
  formatUiMessage,
  formatUiPlural,
  normalizeUiLocale,
  UI_LOCALES,
  type UiLocale,
  type UiMessageKey,
} from '@/lib/i18n'

interface I18nContextValue {
  locale: UiLocale
  setLocale: (locale: UiLocale) => void
  t: (key: UiMessageKey, values?: Record<string, string | number>) => string
  tp: (key: 'workspace.updatedDays' | 'workspace.resumeCount', count: number) => string
}

const I18nContext = createContext<I18nContextValue | null>(null)
export const UI_LOCALE_COOKIE = 'latexy-ui-locale'

function readPersistedLocale(): UiLocale | null {
  if (typeof document === 'undefined') return null
  const cookie = document.cookie.match(/(?:^|;\s*)latexy-ui-locale=([^;]+)/)?.[1]
  if (cookie) {
    try {
      const value = decodeURIComponent(cookie)
      if ((UI_LOCALES as readonly string[]).includes(value)) return value as UiLocale
    } catch {
      // Ignore malformed client-controlled cookie values.
    }
  }
  try {
    const stored = window.localStorage.getItem(UI_LOCALE_COOKIE)
    return stored ? normalizeUiLocale(stored) : null
  } catch {
    return null
  }
}

export function I18nProvider({ children, initialLocale = 'en' }: { children: React.ReactNode; initialLocale?: UiLocale }) {
  const [locale, setLocaleState] = useState<UiLocale>(initialLocale)

  useEffect(() => {
    const persisted = readPersistedLocale()
    if (persisted && persisted !== initialLocale) setLocaleState(persisted)
  }, [initialLocale])

  useEffect(() => {
    document.documentElement.lang = locale
  }, [locale])

  const setLocale = useCallback((next: UiLocale) => {
    const safeLocale = normalizeUiLocale(next)
    setLocaleState(safeLocale)
    document.cookie = `${UI_LOCALE_COOKIE}=${encodeURIComponent(safeLocale)}; Path=/; Max-Age=31536000; SameSite=Lax`
    try {
      window.localStorage.setItem(UI_LOCALE_COOKIE, safeLocale)
    } catch {
      // Private browsing and blocked storage should not prevent the selector.
    }
  }, [])

  const value = useMemo<I18nContextValue>(() => ({
    locale,
    setLocale,
    t: (key, values) => formatUiMessage(locale, key, values),
    tp: (key, count) => formatUiPlural(locale, key, count),
  }), [locale, setLocale])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n(): I18nContextValue {
  const context = useContext(I18nContext)
  if (!context) throw new Error('useI18n must be used within I18nProvider')
  return context
}
