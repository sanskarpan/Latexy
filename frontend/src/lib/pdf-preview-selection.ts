interface PdfResult {
  status: string
  pdfJobId: string | null
}

/** A generated rewrite is a proposal until its exact content is accepted. */
export function selectPdfPreviewJob(
  latestKind: 'compile' | 'ai',
  compile: PdfResult,
  rewrite: PdfResult,
  rewriteJobId: string | null,
  approvedRewriteJobId: string | null,
): string | null {
  if (latestKind === 'compile') return compile.status === 'completed' ? compile.pdfJobId : null
  if (!rewriteJobId || approvedRewriteJobId !== rewriteJobId) return null
  return rewrite.status === 'completed' ? rewrite.pdfJobId : null
}
