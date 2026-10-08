import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { describe, expect, it, vi } from 'vitest'

const EDITOR = readFileSync(new URL('../app/workspace/builder/[resumeId]/page.tsx', import.meta.url), 'utf8').replace(/\r\n/g, '\n')
const CREATE = readFileSync(new URL('../app/workspace/builder/new/page.tsx', import.meta.url), 'utf8').replace(/\r\n/g, '\n')

function compile(source: string) {
  return ts.transpileModule(source, {
    fileName: 'fixture.tsx',
    compilerOptions: { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React, jsxFactory: 'element' },
  }).outputText
}

// Execute the actual page-local list component with a minimal hook harness.
// Browser tests provide the DOM/caret integration; this checks controlled values.
function listHarness(separator: 'lines' | 'comma') {
  const source = EDITOR.slice(EDITOR.indexOf('function joinComma('), EDITOR.indexOf('function splitLinesWithIds('))
  let state: string | undefined
  const ref = { current: '' }
  let canonical = ''
  const component = runInNewContext(`${compile(source)}\nListTextInput`, {
    useState: (initial: string) => [state ?? initial, (value: string) => { state = value }],
    useRef: () => ref,
    useEffect: (effect: () => void) => effect(),
    element: (_type: unknown, props: Record<string, unknown>) => props,
    TextInput: () => {}, TextArea: () => {},
  })
  const render = () => component({
    value: canonical, separator, multiline: true,
    onChange: (raw: string) => {
      const values = raw.split(separator === 'lines' ? '\n' : ',').map(value => value.trim()).filter(Boolean)
      canonical = values.join(separator === 'lines' ? '\n' : ', ')
    },
  }) as { value: string; onChange: (event: { target: { value: string } }) => void }
  return {
    type(raw: string) { render().onChange({ target: { value: raw } }); return render() },
    canonical: () => canonical,
    replace(value: string) { canonical = value; render(); return render() },
  }
}

function saveHarness() {
  const source = EDITOR.slice(EDITOR.indexOf('const flushSave = useCallback('), EDITOR.indexOf('\n  const isCurrentPdfRequest', EDITOR.indexOf('const flushSave = useCallback(')))
  const updateBuilderResume = vi.fn()
  const context = {
    Error,
    useCallback: (callback: unknown) => callback,
    mountedRef: { current: true }, authVerifiedRef: { current: true },
    saveFlightRef: { current: null }, conflictRef: { current: false },
    builderStatusRef: { current: 'active' }, dirtyRef: { current: true },
    draftRef: { current: { title: 'My résumé', template_id: 'template-1', structured_content: { basics: { name: 'First' } } } },
    editRevision: { current: 1 }, savedVersionRef: { current: 1 }, savedBuilderRef: { current: null },
    savedLatexRef: { current: '' },
    resumeId: 'resume-1', apiClient: { updateBuilderResume },
    setSaving: vi.fn(), setTemplateFamily: vi.fn(), setBuilderStatus: vi.fn(),
    setDirty: vi.fn(), setSaveError: vi.fn(), setSaveConflict: vi.fn(),
  }
  const flush = runInNewContext(`${compile(source)}\nflushSave`, context) as () => Promise<unknown>
  return { context, flush, updateBuilderResume }
}

describe('beginner builder controls', () => {
  it('preserves Enter and spaces while saving normalized bullet lines', () => {
    const field = listHarness('lines')
    expect(field.type('Helped customers').value).toBe('Helped customers')
    expect(field.type('Helped customers\n').value).toBe('Helped customers\n')
    expect(field.type('Helped customers\nImproved service ').value).toBe('Helped customers\nImproved service ')
    expect(field.canonical()).toBe('Helped customers\nImproved service')
  })

  it('preserves a comma before the next skill can be entered', () => {
    const field = listHarness('comma')
    expect(field.type('Customer service,').value).toBe('Customer service,')
    expect(field.type('Customer service, Teamwork').value).toBe('Customer service, Teamwork')
    expect(field.canonical()).toBe('Customer service, Teamwork')
    expect(field.replace('Planning, Communication').value).toBe('Planning, Communication')
  })

  it('associates every nested field label and names section controls', () => {
    expect(EDITOR).not.toContain('<FieldLabel>')
    expect(EDITOR).toContain('aria-label={`Move ${title} up`}')
    expect(EDITOR).toContain('aria-label={`Move ${title} down`}')
    expect(EDITOR).toContain('aria-pressed={hidden}')
    expect(CREATE).toContain('htmlFor="new-builder-resume-title"')
    expect(CREATE).toContain('id="new-builder-resume-title"')
    expect(CREATE).toContain('creating || uploading || loading || authUnverified')
  })
  it('renders the owned PDF with the existing browser canvas viewer instead of a native embed', () => {
    expect(EDITOR).toContain("dynamic(() => import('@/components/PDFPreview')")
    expect(EDITOR).toContain('ssr: false')
    expect(EDITOR).toContain('<PDFPreview pdfUrl={pdfUrl}')
    expect(EDITOR).toContain('data-testid="builder-pdf-preview"')
    expect(EDITOR).not.toContain('<iframe')
  })
})

describe('serialized builder persistence', () => {
  it('waits for the first save, then flushes the newest edit using its returned version', async () => {
    const { context, flush, updateBuilderResume } = saveHarness()
    let completeFirst!: (value: unknown) => void
    let completeSecond!: (value: unknown) => void
    updateBuilderResume.mockImplementationOnce(() => new Promise(resolve => { completeFirst = resolve }))
      .mockImplementationOnce(() => new Promise(resolve => { completeSecond = resolve }))
    const saving = flush()
    const exporting = flush()
    expect(updateBuilderResume).toHaveBeenCalledTimes(1)
    context.editRevision.current += 1
    context.draftRef.current = { ...context.draftRef.current, structured_content: { basics: { name: 'Latest' } } }
    completeFirst({ resume: { structured_version: 2, builder_status: 'active' }, template_family: 'minimal' })
    await vi.waitFor(() => expect(updateBuilderResume).toHaveBeenCalledTimes(2))
    expect(updateBuilderResume.mock.calls[1][1]).toMatchObject({ expected_structured_version: 2, structured_content: { basics: { name: 'Latest' } } })
    completeSecond({ resume: { structured_version: 3, builder_status: 'active' }, template_family: 'minimal' })
    await Promise.all([saving, exporting])
    expect(context.dirtyRef.current).toBe(false)
    expect(context.savedVersionRef.current).toBe(3)
  })

  it('preserves a conflicting draft and blocks exports until the saved copy is reviewed', async () => {
    const { context, flush, updateBuilderResume } = saveHarness()
    updateBuilderResume.mockRejectedValue(new Error('HTTP 409: stale structured version'))
    await expect(flush()).rejects.toThrow('409')
    expect(context.dirtyRef.current).toBe(true)
    expect(context.draftRef.current.structured_content.basics.name).toBe('First')
    expect(context.conflictRef.current).toBe(true)
    await expect(flush()).rejects.toThrow('Reload the saved copy')
    expect(updateBuilderResume).toHaveBeenCalledTimes(1)
  })
})
