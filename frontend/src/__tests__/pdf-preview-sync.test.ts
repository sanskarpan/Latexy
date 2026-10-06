import { describe, expect, test } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { createSynctexRequestGuard } from '../lib/synctex-parser'

const pdfPreviewSource = readFileSync(fileURLToPath(new URL('../components/PDFPreview.tsx', import.meta.url)), 'utf8')

describe('PDFPreview SyncTeX request lifecycle', () => {
  test('a late A response cannot publish after B starts, including ABA', () => {
    const guard = createSynctexRequestGuard()
    const a = guard.begin('job-a')
    const b = guard.begin('job-b')
    expect(guard.isCurrent(a)).toBe(false)
    expect(guard.isCurrent(b)).toBe(true)

    const aAgain = guard.begin('job-a')
    expect(guard.isCurrent(a)).toBe(false)
    expect(guard.isCurrent(aAgain)).toBe(true)
    expect(guard.isCurrent(b)).toBe(false)
  })

  test('cleanup invalidates an in-flight response without blocking a later retry', () => {
    const guard = createSynctexRequestGuard()
    const first = guard.begin('job-a')
    guard.invalidate(first)
    expect(guard.isCurrent(first)).toBe(false)

    const retry = guard.begin('job-a')
    expect(guard.isCurrent(retry)).toBe(true)
    guard.reset()
    expect(guard.isCurrent(retry)).toBe(false)
  })

  test('attaches viewport behavior when the PDF container mounts and preserves a prior PDF while compiling', () => {
    expect(pdfPreviewSource).toContain('const [containerNode, setContainerNode] = useState<HTMLDivElement | null>(null)')
    expect(pdfPreviewSource).toContain('ref={setContainerElement}')
    expect(pdfPreviewSource).toContain('}, [containerNode])')
    expect(pdfPreviewSource).toContain('if (isLoading && !pdfUrl)')
  })
})
