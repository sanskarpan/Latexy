import { readFileSync } from 'node:fs'
import ts from 'typescript'
import { describe, expect, it, vi } from 'vitest'

const source = ts.createSourceFile('optimizer.tsx', readFileSync(
  new URL('../app/workspace/[resumeId]/optimize/page.tsx', import.meta.url), 'utf8',
), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)

function compileHarness() {
  let expression: ts.Expression | undefined
  const visit = (node: ts.Node) => {
    if (ts.isVariableDeclaration(node) && node.name.getText(source) === 'compileContent' && node.initializer && ts.isCallExpression(node.initializer)) {
      expression = node.initializer.arguments[0]
    }
    ts.forEachChild(node, visit)
  }
  visit(source)
  expect(expression).toBeDefined()
  let finish!: (value: { success: boolean; job_id: string }) => void
  const response = new Promise<{ success: boolean; job_id: string }>((resolve) => { finish = resolve })
  const scope = {
    canRef: { current: () => true }, isProcessing: false, isSubmitting: false,
    personaIdentityRef: { current: { key: 'owner-a:resume-a', generation: 3 } },
    sessionUserId: 'owner-a', mountedRef: { current: true }, liveSessionUserIdRef: { current: 'owner-a' },
    apiClient: { compileLatex: vi.fn(() => response) }, resumeId: 'resume-a', compiler: 'pdflatex',
    editorRef: { current: { markAutoCompileCompiled: vi.fn() } },
    setIsSubmitting: vi.fn(), setActiveJobId: vi.fn(), setActiveJobKind: vi.fn(),
  }
  const js = ts.transpileModule(`const compile = ${expression!.getText(source)}`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText
  const compile = new Function(...Object.keys(scope), `${js}; return compile`)(...Object.values(scope)) as (content: string) => Promise<string | null>
  return { compile, finish, scope }
}

describe('optimizer preview owner identity', () => {
  it('returns the admitted job ID and updates the current owner', async () => {
    const h = compileHarness()
    const pending = h.compile('current source')
    h.finish({ success: true, job_id: 'compile-job' })
    expect(await pending).toBe('compile-job')
    expect(h.scope.setActiveJobId).toHaveBeenCalledExactlyOnceWith('compile-job')
    expect(h.scope.editorRef.current.markAutoCompileCompiled).toHaveBeenCalledWith('current source')
    expect(h.scope.setIsSubmitting).toHaveBeenLastCalledWith(false)
  })

  it.each(['another owner', 'A to B to A', 'unmounted'])('does not adopt a late response for %s', async (transition) => {
    const h = compileHarness()
    const pending = h.compile('previous source')
    if (transition === 'unmounted') h.scope.mountedRef.current = false
    else {
      h.scope.personaIdentityRef.current = {
        key: transition === 'another owner' ? 'owner-b:resume-b' : 'owner-a:resume-a',
        generation: transition === 'another owner' ? 4 : 5,
      }
      if (transition === 'another owner') h.scope.liveSessionUserIdRef.current = 'owner-b'
    }
    h.finish({ success: true, job_id: 'previous-compile-job' })
    expect(await pending).toBeNull()
    expect(h.scope.setActiveJobId).not.toHaveBeenCalled()
    expect(h.scope.editorRef.current.markAutoCompileCompiled).not.toHaveBeenCalled()
    expect(h.scope.setIsSubmitting).toHaveBeenCalledExactlyOnceWith(true)
  })
})
