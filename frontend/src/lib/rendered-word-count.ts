const RENDERED_WORD = /[\p{L}\p{N}][\p{L}\p{M}\p{N}]*(?:['’\-‑][\p{L}\p{N}][\p{L}\p{M}\p{N}]*)*/gu

/** Count visible lexical tokens from pdftotext output, never from LaTeX source. */
export function countRenderedWords(extractedPdfText: string): number {
  return extractedPdfText.normalize('NFC').match(RENDERED_WORD)?.length ?? 0
}
