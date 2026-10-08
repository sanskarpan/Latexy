import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { describe, expect, it, vi } from 'vitest'

const source = readFileSync(new URL('../components/ExportDropdown.tsx', import.meta.url), 'utf8')
const ast = ts.createSourceFile('export.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
let handler = ''
function visit(node: ts.Node) {
  if (ts.isFunctionDeclaration(node) && node.name?.text === 'handleExport') handler = node.getText(ast)
  ts.forEachChild(node, visit)
}
visit(ast)

function harness(beforeExport: (format: string) => Promise<void>) {
  const api = {
    exportResume: vi.fn().mockResolvedValue(new Blob(['document'])),
    emailResumePdf: vi.fn().mockResolvedValue({ retry_behavior: 'provider_idempotent' }),
    getGoogleDriveStatus: vi.fn().mockResolvedValue({ connected: true }),
    exportResumeToGoogleDrive: vi.fn().mockResolvedValue({ action: 'created' }),
  }
  const pdf = vi.fn().mockResolvedValue(undefined)
  const errors = vi.fn()
  const loading = vi.fn()
  const handle = runInNewContext(`${ts.transpileModule(handler, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText}\nhandleExport`, {
    isExporting: false, resumeId: 'owned', latexContent: undefined, visualOnly: false,
    beforeExport, onPdfExport: pdf, apiClient: api, Error,
    setIsOpen: vi.fn(), setLoading: loading, setExportError: errors, setDriveNeedsConnection: vi.fn(),
    toast: { error: vi.fn(), info: vi.fn(), success: vi.fn() }, downloadBlob: vi.fn(), EXPORT_FORMATS: [],
  }) as (format: string) => Promise<void>
  return { handle, api, pdf, errors, loading }
}

function builderBeforeExport(flushSave: () => Promise<unknown>, previewPdf: () => Promise<void>) {
  const source = readFileSync(new URL('../app/workspace/builder/[resumeId]/page.tsx', import.meta.url), 'utf8')
  const ast = ts.createSourceFile('builder.tsx', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
  let callback = ''
  function visit(node: ts.Node) {
    if (ts.isJsxAttribute(node) && node.name.getText(ast) === 'beforeExport' && node.initializer && ts.isJsxExpression(node.initializer) && node.initializer.expression) {
      callback = node.initializer.expression.getText(ast)
    }
    ts.forEachChild(node, visit)
  }
  visit(ast)
  expect(callback).not.toBe('')
  const script = ts.transpileModule(`const beforeExport = ${callback}`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
  return runInNewContext(`${script}\nbeforeExport`, { flushSave, previewPdf }) as (format: string) => Promise<void>
}

describe('exports flush builder saves', () => {
  it('waits before reading saved document formats', async () => {
    let complete!: () => void
    const h = harness(() => new Promise<void>(resolve => { complete = resolve }))
    const pending = h.handle('docx')
    expect(h.api.exportResume).not.toHaveBeenCalled()
    complete()
    await pending
    expect(h.api.exportResume).toHaveBeenCalledWith('owned', 'docx')
  })
  it('does not export when the save conflicts', async () => {
    const h = harness(() => Promise.reject(new Error('HTTP 409: another tab changed')))
    await h.handle('docx')
    expect(h.api.exportResume).not.toHaveBeenCalled()
    expect(h.errors).toHaveBeenLastCalledWith({ format: 'docx', message: 'HTTP 409: another tab changed' })
  })
  it('awaits saving before PDF generation and surfaces failures', async () => {
    const h = harness(() => Promise.reject(new Error('save failed')))
    await h.handle('pdf')
    expect(h.pdf).not.toHaveBeenCalled()
    expect(h.errors).toHaveBeenLastCalledWith({ format: 'pdf', message: 'save failed' })
    expect(h.loading).toHaveBeenLastCalledWith(null)
  })
  it.each(['svg', 'jpeg', 'email', 'google_drive'])('refreshes the saved PDF before exporting %s', async format => {
    let finishSave!: () => void
    let finishPdf!: () => void
    const save = vi.fn(() => new Promise<void>(resolve => { finishSave = resolve }))
    const preview = vi.fn(() => new Promise<void>(resolve => { finishPdf = resolve }))
    const h = harness(builderBeforeExport(save, preview))
    const pending = h.handle(format)
    expect(save).toHaveBeenCalledTimes(1)
    expect(preview).not.toHaveBeenCalled()
    expect(h.api.exportResume).not.toHaveBeenCalled()
    finishSave()
    await vi.waitFor(() => expect(preview).toHaveBeenCalledTimes(1))
    expect(h.api.exportResume).not.toHaveBeenCalled()
    expect(h.api.emailResumePdf).not.toHaveBeenCalled()
    expect(h.api.getGoogleDriveStatus).not.toHaveBeenCalled()
    finishPdf()
    await pending
    if (format === 'email') expect(h.api.emailResumePdf).toHaveBeenCalledWith('owned')
    else if (format === 'google_drive') expect(h.api.exportResumeToGoogleDrive).toHaveBeenCalledWith('owned')
    else expect(h.api.exportResume).toHaveBeenCalledWith('owned', format)
  })
  it('does not send an old compiled document if PDF refresh fails', async () => {
    const h = harness(builderBeforeExport(vi.fn().mockResolvedValue(undefined), vi.fn().mockRejectedValue(new Error('PDF generation failed'))))
    await h.handle('svg')
    expect(h.api.exportResume).not.toHaveBeenCalled()
    expect(h.errors).toHaveBeenLastCalledWith({ format: 'svg', message: 'PDF generation failed' })
  })
  it.each(['pdf', 'json', 'docx', 'txt'])('does not request a second PDF in the pre-export hook for %s', async format => {
    const save = vi.fn().mockResolvedValue(undefined)
    const preview = vi.fn().mockResolvedValue(undefined)
    const h = harness(builderBeforeExport(save, preview))
    await h.handle(format)
    expect(save).toHaveBeenCalledTimes(1)
    expect(preview).not.toHaveBeenCalled()
    if (format === 'pdf') expect(h.pdf).toHaveBeenCalledTimes(1)
  })
})
