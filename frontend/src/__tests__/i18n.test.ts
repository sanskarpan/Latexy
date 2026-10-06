import { describe, expect, it } from 'vitest'
import {
  UI_LOCALES,
  UI_MESSAGES,
  formatUiMessage,
  formatUiPlural,
  negotiateUiLocale,
} from '@/lib/i18n'

describe('B55 UI localisation contract', () => {
  it('negotiates persisted UI language before browser preference and safely falls back', () => {
    expect(negotiateUiLocale('mr', 'hi-IN,hi;q=0.9')).toBe('mr')
    expect(negotiateUiLocale(undefined, 'te-IN,te;q=0.9,en;q=0.8')).toBe('te')
    expect(negotiateUiLocale(undefined, 'fr-FR,fr;q=0.9')).toBe('en')
    expect(negotiateUiLocale('not-a-locale', 'bn-BD')).toBe('bn')
  })

  it('keeps every supported locale fully covered with safe interpolation', () => {
    const keys = Object.keys(UI_MESSAGES.en).sort()
    for (const locale of UI_LOCALES) expect(Object.keys(UI_MESSAGES[locale]).sort()).toEqual(keys)
    expect(formatUiMessage('hi', 'workspace.noSearchResults', { query: '<script>' })).toContain('<script>')
    expect(formatUiPlural('bn', 'workspace.resumeCount', 1)).toContain('1')
    expect(formatUiPlural('bn', 'workspace.resumeCount', 2)).toContain('2')
    expect(formatUiMessage('te', 'onboarding.next')).toBe('తదుపరి')
  })

  it('does not make UI locale the document translation locale', () => {
    expect(formatUiMessage('hi', 'locale.documentLanguageHint')).toMatch(/इंटरफ़ेस|रिज़्यूमे/)
    expect(UI_MESSAGES.en['workspace.documentLanguage']).toBe('Document language')
  })
})
