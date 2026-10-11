type PdfJobStream = {
  status: string
  pdfJobId: string | null
}

/**
 * A retry may fetch only the completed artifact that the current owned job
 * stream already selected. It must never turn a stale job id into a new read.
 */
export function resolveRetryableCompletedPdfJobId(
  activePdfJobId: string | null,
  ownsRenderedJobState: boolean,
  compileStream: PdfJobStream,
  aiStream: PdfJobStream,
): string | null {
  if (!activePdfJobId || !ownsRenderedJobState) return null
  const isCurrentCompletedJob = [compileStream, aiStream].some(
    (stream) => stream.status === 'completed' && stream.pdfJobId === activePdfJobId,
  )
  return isCurrentCompletedJob ? activePdfJobId : null
}
