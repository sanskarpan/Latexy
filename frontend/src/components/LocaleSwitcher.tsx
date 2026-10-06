'use client'

import { UI_LOCALE_LABELS, UI_LOCALES } from '@/lib/i18n'
import { useI18n } from '@/components/I18nProvider'

export default function LocaleSwitcher({ compact = false }: { compact?: boolean }) {
  const { locale, setLocale, t } = useI18n()
  return (
    <label className="inline-flex items-center gap-2 font-ui text-xs text-fg-2">
      <span className={compact ? 'sr-only' : ''}>{t('locale.label')}</span>
      <select
        aria-label={t('locale.uiLanguage')}
        value={locale}
        onChange={(event) => setLocale(event.target.value as typeof locale)}
        className="min-h-[36px] rounded-[var(--radius-md)] border border-line bg-surface px-2 py-1.5 text-xs font-medium text-fg focus:outline-none focus-visible:ring-2 focus-visible:ring-accent"
      >
        {UI_LOCALES.map((code) => <option key={code} value={code}>{UI_LOCALE_LABELS[code]}</option>)}
      </select>
    </label>
  )
}
