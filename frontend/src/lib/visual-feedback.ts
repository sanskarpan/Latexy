const SOURCE_SNIPPET = /\\[a-zA-Z]+|```/

/** Keep generated layout instructions behind the optional source interface. */
export function visualFeedbackText(value: string): string {
  return SOURCE_SNIPPET.test(value)
    ? 'Advanced formatting feedback is available in Source mode. Your document is preserved.'
    : value
}

export function visualFeedback<T>(value: T): T {
  if (typeof value === 'string') return visualFeedbackText(value) as T
  if (Array.isArray(value)) return value.map(item => visualFeedback(item)) as T
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, visualFeedback(item)])) as T
  return value
}
