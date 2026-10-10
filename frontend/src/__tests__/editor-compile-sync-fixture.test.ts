import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { describe, expect, it } from 'vitest'

const fixture = readFileSync(new URL('../../e2e/editor-compile-sync.spec.ts', import.meta.url), 'utf8')

describe('source/PDF synchronization fixture contract', () => {
  it('selects Source for the exact resume before navigation instead of relying on the product default', () => {
    const selection = fixture.indexOf("localStorage.setItem(`latexy_editor_mode_${resumeId}`, 'source')")
    expect(selection).toBeGreaterThan(fixture.indexOf('await page.addInitScript(resumeId =>'))
    expect(selection).toBeLessThan(fixture.indexOf('}, RESUME_ID)'))
    expect(selection).toBeLessThan(fixture.indexOf('await page.goto(`/workspace/${RESUME_ID}/edit`'))
    expect(fixture).toContain('__latexyMonacoEditor?.getValue())).toBe(SOURCE)')
  })

  it('provides exact read-only capability and absent-attachment responses', () => {
    expect(fixture).toContain("path === '/public/engine/capabilities' && route.request().method() === 'GET'")
    expect(fixture).toContain('route.fulfill({ json: { resume_engine_version: 1 } })')
    expect(fixture).toContain("path === `/resumes/${RESUME_ID}/engine/import` && route.request().method() === 'GET'")
    expect(fixture).toContain("status: 404, json: { detail: 'No original PDF for this source fixture' }")
  })

  it('retains unknown-request rejection and real source, PDF and runtime-error assertions', () => {
    expect(fixture).toContain('unknown.push(`${route.request().method()} ${path}`)')
    expect(fixture).toContain('return route.abort()')
    expect(fixture).toContain('errors.push(error.message)')
    expect(fixture).toContain('expect(fixture.unknown).toEqual([])')
    expect(fixture).toContain('expect(fixture.errors).toEqual([])')
    expect(fixture).toContain("page.locator('.react-pdf__Page__canvas').first()).toBeVisible()")
  })
})

// Exercise the actual fixture completion helper with controlled browser state.
// A completed job does not imply global idleness when a successor is queued.
function completionHarness(successor: 'none' | 'running' | 'missing-subscription' | 'enabled' = 'none', publishesPdf = true) {
  const ast = ts.createSourceFile('fixture.ts', fixture, ts.ScriptTarget.Latest, true)
  let method = ''
  function visit(node: ts.Node) {
    if (ts.isMethodDeclaration(node) && node.name.getText(ast) === 'complete') method = node.getText(ast)
    ts.forEachChild(node, visit)
  }
  visit(ast)
  expect(method).not.toBe('')
  const observations: string[] = []
  const submitted = [{ latex_content: 'original' }]
  const requestedPdfJobs: string[] = []
  let button = { name: 'Preparing…', disabled: true }
  const subscribers = new Map<string, () => void>()
  subscribers.set('editor-fixture-job-1', () => {
    observations.push('completed-job-1')
    if (publishesPdf) requestedPdfJobs.push('editor-fixture-job-1')
    if (successor === 'none') button = { name: 'Compile', disabled: false }
    else {
      submitted.push({ latex_content: 'newer queued source' })
      if (successor !== 'missing-subscription') subscribers.set('editor-fixture-job-2', () => {})
      if (successor === 'enabled') button.disabled = false
    }
  })
  const page = {
    locator: () => ({ first: () => ({ canvas: true }) }),
    getByRole: (_role: string, options: { name: string; exact: boolean }) => {
      observations.push(`button:${options.name}`)
      expect(options.exact).toBe(true)
      return { present: options.name === button.name, disabled: button.disabled }
    },
  }
  const fixtureExpect = Object.assign((actual: { canvas?: boolean; present?: boolean; disabled?: boolean }) => ({
    toBeVisible: async () => { expect(actual.canvas).toBe(true) },
    toBeEnabled: async () => { expect(actual.present).toBe(true); expect(actual.disabled).toBe(false) },
    toBeDisabled: async () => { expect(actual.present).toBe(true); expect(actual.disabled).toBe(true) },
  }), { poll: (read: () => unknown) => ({ toBe: async (expected: unknown) => { expect(read()).toBe(expected) } }) })
  const js = ts.transpileModule(`const helpers = { ${method} }`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText
  const complete = runInNewContext(`${js}\nhelpers.complete`, { page, expect: fixtureExpect, subscribers, submitted, requestedPdfJobs })
  return { complete, submitted, observations }
}

describe('source/PDF fixture completion state', () => {
  it('requires enabled Compile when the final job leaves no queued successor', async () => {
    const harness = completionHarness()
    await harness.complete(1)
    expect(harness.observations).toEqual(['completed-job-1', 'button:Compile'])
    expect(harness.submitted).toHaveLength(1)
  })

  it('requires the next admitted/subscribed job and disabled busy control when a queued edit is released', async () => {
    const harness = completionHarness('running')
    await harness.complete(1, 'next-preview')
    expect(harness.observations).toEqual(['completed-job-1', 'button:Preparing…'])
    expect(harness.submitted).toEqual([{ latex_content: 'original' }, { latex_content: 'newer queued source' }])
  })

  it.each(['none', 'missing-subscription', 'enabled'] as const)('rejects a %s successor instead of skipping the busy/next-preview assertion', async successor => {
    await expect(completionHarness(successor).complete(1, 'next-preview')).rejects.toThrow()
  })

  it('requires this completed job’s PDF request rather than only an older visible canvas', async () => {
    await expect(completionHarness('none', false).complete(1)).rejects.toThrow()
    const recorded = fixture.indexOf("requestedPdfJobs.push(path.split('/')[2])")
    expect(recorded).toBeGreaterThanOrEqual(0)
    expect(recorded).toBeLessThan(fixture.indexOf("await pdfDownloadGates.get(path.split('/')[2])"))
  })

  it('does not treat a running successor as a completed idle queue', async () => {
    await expect(completionHarness('running').complete(1)).rejects.toThrow()
  })

  it('keeps both queued-edit cases explicit and preserves cadence, final idle and no-duplicate checks', () => {
    expect(fixture.match(/fixture\.complete\(1, 'next-preview'\)/g)).toHaveLength(2)
    expect(fixture).toContain('fixture.submittedAt[1] - fixture.submittedAt[0]).toBeGreaterThanOrEqual(9_800)')
    expect(fixture).toContain("toBe(SOURCE.replace('Second line.', `Second line.${words} pending latest`))")
    expect(fixture).toContain("toBe(SOURCE.replace('Second line.', 'Second line. edited content'))")
    expect(fixture).toMatch(/await fixture\.complete\(3\)[\s\S]*?waitForTimeout\(12_000\)[\s\S]*?submitted\)\.toHaveLength\(3\)[\s\S]*?name: 'Compile', exact: true[\s\S]*?toBeEnabled\(\)/)
    expect(fixture).not.toContain("name: 'Compiling…', exact: true")
  })
})
