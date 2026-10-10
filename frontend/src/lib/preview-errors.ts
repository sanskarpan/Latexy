/** Admission/quota messages are plain text; compile diagnostics belong in Source mode. */
export function previewErrorMessage(error: unknown, plain: boolean, fallback = 'Your PDF could not be updated. Your last preview is preserved.') {
  const message = error instanceof Error ? error.message : typeof error === 'string' ? error : fallback
  if (!plain || /^HTTP (401|402|403|429):/.test(message)) return message
  return fallback
}
