import { describe, expect, it } from 'vitest'
import { selectPdfPreviewJob } from './pdf-preview-selection'

const compiled = { status: 'completed', pdfJobId: 'original-pdf' }
const proposed = { status: 'completed', pdfJobId: 'proposed-pdf' }

describe('PDF proposal approval', () => {
  it('does not render a completed unaccepted rewrite as the current document', () => {
    expect(selectPdfPreviewJob('ai', compiled, proposed, 'rewrite', null)).toBeNull()
  })
  it('selects the accepted rewrite instead of an older completed compile', () => {
    expect(selectPdfPreviewJob('ai', compiled, proposed, 'rewrite', 'rewrite')).toBe('proposed-pdf')
  })
  it('does not reuse approval after a new job or owner transition', () => {
    expect(selectPdfPreviewJob('ai', compiled, proposed, 'new-rewrite', 'rewrite')).toBeNull()
    expect(selectPdfPreviewJob('ai', compiled, proposed, null, 'rewrite')).toBeNull()
  })
  it('uses a newer ordinary compile and refuses incomplete results', () => {
    expect(selectPdfPreviewJob('compile', compiled, proposed, 'rewrite', 'rewrite')).toBe('original-pdf')
    expect(selectPdfPreviewJob('ai', compiled, { status: 'failed', pdfJobId: null }, 'rewrite', 'rewrite')).toBeNull()
  })
})
