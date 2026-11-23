export const numberFormatter = new Intl.NumberFormat('en-IN')

export function formatNumber(value: number | null | undefined): string {
  return numberFormatter.format(Number.isFinite(value ?? NaN) ? Number(value) : 0)
}

export function formatMoney(
  value: number | null | undefined,
  currency: string | null | undefined = 'INR',
  maximumFractionDigits = 2,
): string {
  // Provider rows created before multi-currency support may carry a null code.
  // Intl.NumberFormat throws on an invalid currency, which would blank the whole
  // admin panel; fall back to the ledger's primary currency instead.
  const code = typeof currency === 'string' && /^[A-Za-z]{3}$/.test(currency)
    ? currency.toUpperCase()
    : 'INR'
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: code,
    maximumFractionDigits,
  }).format(Number.isFinite(value ?? NaN) ? Number(value) : 0)
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleString()
}

export function shortId(value: string | null | undefined, length = 10): string {
  if (!value) return '—'
  return value.length > length ? `${value.slice(0, length)}…` : value
}

export function summarize(value: unknown, maxLength = 160): string {
  if (value == null) return '—'
  let text: string
  try {
    text = typeof value === 'string' ? value : JSON.stringify(value)
  } catch {
    text = String(value)
  }
  return text.length > maxLength ? `${text.slice(0, maxLength)}…` : text
}

export function percentage(value: number, total: number): string {
  if (!Number.isFinite(value) || !Number.isFinite(total) || total <= 0) return '0.0%'
  return `${((value / total) * 100).toFixed(1)}%`
}
