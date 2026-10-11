import { readFileSync } from 'node:fs'
import ts from 'typescript'
import { describe, expect, it, vi } from 'vitest'

const source = ts.createSourceFile('new-resume.tsx', readFileSync(
  new URL('../app/workspace/new/page.tsx', import.meta.url), 'utf8',
), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)

type Element = { type: unknown; props: Record<string, unknown> }
function elements(value: unknown): Element[] {
  if (Array.isArray(value)) return value.flatMap(elements)
  if (!value || typeof value !== 'object' || !('props' in value)) return []
  const element = value as Element
  return [element, ...elements(element.props.children)]
}

describe('retained new-resume PDF import during session refresh', () => {
  it('keeps the admitted PDF wizard mounted with its owner, file, and title during refresh', () => {
    let form: ts.FunctionDeclaration | undefined
    ts.forEachChild(source, (node) => {
      if (ts.isFunctionDeclaration(node) && node.name?.text === 'NewResumePageForm') form = node
    })
    expect(form).toBeDefined()
    const file = new File(['synthetic PDF'], 'resume.pdf', { type: 'application/pdf' })
    const states: unknown[] = ['Reviewed resume title', 'import', '', file]
    const refs: Array<{ current: unknown }> = []
    let stateIndex = 0, refIndex = 0
    const scope = {
      React: { Fragment: 'Fragment', createElement: (type: unknown, props: Record<string, unknown> | null, ...children: unknown[]) => ({ type, props: { ...props, children } }) },
      useEntitlements: () => ({ can: () => true }), useRouter: () => ({ push: vi.fn() }),
      useState: (initial: unknown) => {
        const slot = stateIndex++
        if (!(slot in states)) states[slot] = typeof initial === 'function' ? (initial as () => unknown)() : initial
        return [states[slot], vi.fn()]
      },
      useRef: (initial: unknown) => { const slot = refIndex++; return refs[slot] ?? (refs[slot] = { current: initial }) },
      useEffect: vi.fn(), useCallback: (callback: unknown) => callback, useMemo: (callback: () => unknown) => callback(),
      TEMPLATE_CATEGORY_ORDER: [], apiClient: {}, toast: { error: vi.fn() },
      Link: 'Link', CapabilityGate: 'CapabilityGate', MultiFormatUpload: 'MultiFormatUpload',
      ImportFromBuilderWizard: 'ImportFromBuilderWizard', PdfImportWizard: 'PdfImportWizard',
      TemplateCard: 'TemplateCard', TemplatePreviewModal: 'TemplatePreviewModal', LoadingSpinner: 'LoadingSpinner',
      ExternalLink: 'ExternalLink', Search: 'Search', Upload: 'Upload', LayoutTemplate: 'LayoutTemplate',
      X: 'X', PackageOpen: 'PackageOpen', Sparkles: 'Sparkles', Loader2: 'Loader2', Linkedin: 'Linkedin',
      LINKEDIN_DATA_EXPORT_URL: 'https://www.linkedin.com/',
    }
    const js = ts.transpileModule(`const Form = ${form!.getText(source)}`, {
      compilerOptions: { target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.React },
    }).outputText
    const renderForm = new Function(...Object.keys(scope), `${js}; return Form`)(...Object.values(scope)) as (props: unknown) => Element
    const ownerIdentityRef = { current: { ownerId: 'owner-a', generation: 4 } }
    const render = (sessionLoading: boolean) => {
      stateIndex = 0; refIndex = 0
      return renderForm({ session: { user: { id: 'owner-a' } }, sessionLoading, ownerIdentityRef })
    }
    const before = elements(render(false)).find((element) => element.type === 'PdfImportWizard')
    const during = elements(render(true))
    const retained = during.find((element) => element.type === 'PdfImportWizard')
    expect(before).toBeDefined()
    expect(retained?.type).toBe(before?.type)
    expect(retained?.props).toMatchObject({ file, ownerId: 'owner-a', title: 'Reviewed resume title' })
    expect(during.some((element) => element.type === 'LoadingSpinner')).toBe(false)
    expect(elements(render(false)).find((element) => element.type === 'PdfImportWizard')?.props.file).toBe(file)
  })

  it('preserves the outer unresolved-session boundary and mutation admission guards', () => {
    expect(source.getFullText()).toContain('if (sessionLoading && !session)')
    expect(source.getFullText()).toContain('if (sessionError && !session) return <SessionLoadError')
    expect(source.getFullText()).toContain('if (!session) return null')
    expect(source.getFullText()).toContain('!mountedRef.current || sessionLoading || isCreating')
    expect(source.getFullText()).toContain("!canRef.current('b01') || !canRef.current('c01')")
  })
})
