import { describe, expect, test, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
import { createSynctexRequestGuard } from '../lib/synctex-parser'

const pdfPreviewSource = readFileSync(fileURLToPath(new URL('../components/PDFPreview.tsx', import.meta.url)), 'utf8')
const preview = ts.createSourceFile('PDFPreview.tsx', pdfPreviewSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
function find(predicate: (node: ts.Node) => boolean) {
  const matches: ts.Node[] = []
  function visit(node: ts.Node) { if (predicate(node)) matches.push(node); ts.forEachChild(node, visit) }
  visit(preview)
  return matches
}
function execute(expression: ts.Node, scope: Record<string, unknown>) {
  const js = ts.transpileModule(`const value = (${expression.getText(preview)})`, { compilerOptions: { target: ts.ScriptTarget.ES2022 } }).outputText
  return new Function(...Object.keys(scope), `${js}; return value`)(...Object.values(scope))
}
const syncAdmission = (find((node) => ts.isVariableDeclaration(node) && node.name.getText(preview) === 'syncAllowed')[0] as ts.VariableDeclaration).initializer!
const syncDefault = (find((node) => ts.isBindingElement(node) && node.name.getText(preview) === 'syncEnabled')[0] as ts.BindingElement).initializer!
const syncEffect = find((node) => ts.isCallExpression(node) && node.expression.getText(preview) === 'useEffect' && node.arguments[0].getText(preview).includes('downloadArtifactSynctex'))[0] as ts.CallExpression
function syncRequest(syncAllowed: boolean, artifact = true, pending = Promise.resolve('current-map')) {
  const guard = createSynctexRequestGuard()
  const previous = guard.begin('previous-job')
  const parseCurrentSynctex = vi.fn()
  const downloadArtifactSynctex = vi.fn<(jobId: string, artifactId: string, fingerprint: string, signal: AbortSignal) => Promise<string>>(() => pending)
  const downloadSynctex = vi.fn<(jobId: string, signal: AbortSignal) => Promise<string>>(() => pending)
  const synctexDataRef = { current: 'previous-map' }, synctexTextRef = { current: 'previous-text' }
  const effect = execute(syncEffect.arguments[0], {
    synctexRequestGuardRef: { current: guard }, pageDimsRef: { current: {} }, pageRefs: { current: {} },
    setPageDimsVersion: vi.fn(), setSynctexReady: vi.fn(), setRenderError: vi.fn(),
    synctexDataRef, synctexTextRef, syncAllowed, synctexJobId: 'owned-job',
    synctexArtifactId: artifact ? 'owned-artifact' : undefined, synctexFingerprint: 'owned-fingerprint',
    apiClient: { downloadArtifactSynctex, downloadSynctex }, parseCurrentSynctex,
  }) as () => (() => void) | undefined
  return { effect, guard, previous, parseCurrentSynctex, downloadArtifactSynctex, downloadSynctex, synctexDataRef, synctexTextRef }
}

describe('PDFPreview SyncTeX request lifecycle', () => {
  test('caller sync admission defaults to existing C10 behavior and cannot override independent denial', () => {
    const defaultEnabled = execute(syncDefault, {})
    expect(defaultEnabled).toBe(true)
    for (const c10 of [false, true]) {
      expect(execute(syncAdmission, { can: () => c10, syncEnabled: defaultEnabled })).toBe(c10)
      expect(execute(syncAdmission, { can: () => c10, syncEnabled: false })).toBe(false)
    }
  })

  test.each([
    { path: 'legacy job', artifact: false, denied: 'caller admission', c10: true, syncEnabled: false },
    { path: 'artifact identity', artifact: true, denied: 'caller admission', c10: true, syncEnabled: false },
    { path: 'legacy job', artifact: false, denied: 'C10', c10: false, syncEnabled: true },
    { path: 'artifact identity', artifact: true, denied: 'C10', c10: false, syncEnabled: true },
  ])('suppresses $path SyncTeX requests when $denied is revoked', async ({ artifact, c10, syncEnabled }) => {
    const syncAllowed = execute(syncAdmission, { can: () => c10, syncEnabled }) as boolean
    const request = syncRequest(syncAllowed, artifact)
    expect(request.effect()).toBeUndefined()
    await Promise.resolve()
    expect(request.downloadArtifactSynctex).not.toHaveBeenCalled()
    expect(request.downloadSynctex).not.toHaveBeenCalled()
    expect(request.parseCurrentSynctex).not.toHaveBeenCalled()
    expect(request.synctexDataRef.current).toBeNull()
    expect(request.synctexTextRef.current).toBeNull()
    expect(request.guard.isCurrent(request.previous)).toBe(false)
  })

  test('invalidates a retained artifact request on denial and restores only the current request after regrant', async () => {
    let resolvePrevious!: (value: string) => void
    const pending = new Promise<string>((resolve) => { resolvePrevious = resolve })
    const admitted = syncRequest(true, true, pending)
    const cleanup = admitted.effect()!
    const signal = admitted.downloadArtifactSynctex.mock.calls[0][3] as AbortSignal
    expect(signal.aborted).toBe(false)
    cleanup()
    expect(signal.aborted).toBe(true)
    resolvePrevious('stale-map')
    await Promise.resolve()
    expect(admitted.parseCurrentSynctex).not.toHaveBeenCalled()

    const denied = syncRequest(false)
    denied.effect()
    expect(denied.downloadArtifactSynctex).not.toHaveBeenCalled()
    const restored = syncRequest(true)
    const restoredCleanup = restored.effect()!
    await Promise.resolve()
    expect(restored.downloadArtifactSynctex).toHaveBeenCalledWith('owned-job', 'owned-artifact', 'owned-fingerprint', expect.any(AbortSignal))
    expect(restored.parseCurrentSynctex).toHaveBeenCalledWith('current-map')
    restoredCleanup()
  })

  test('revocation clears remembered PDF selection, sync hint and highlight overlays', () => {
    const reset = find((node) => ts.isCallExpression(node) && node.expression.getText(preview) === 'useEffect' && node.arguments[0].getText(preview).includes('selectionCallbackRef.current'))[0] as ts.CallExpression
    const dependencies = reset.arguments[1] as ts.ArrayLiteralExpression
    expect(dependencies.elements.map((node) => node.getText(preview))).toContain('syncAllowed')
    const selectionChanged = vi.fn(), setSyncHint = vi.fn(), clearFlashOverlays = vi.fn()
    const effect = execute(reset.arguments[0], { selectionCallbackRef: { current: selectionChanged }, syncHintTimerRef: { current: null }, setSyncHint, clearFlashOverlays }) as () => void
    effect()
    expect(selectionChanged).toHaveBeenCalledWith(null)
    expect(setSyncHint).toHaveBeenCalledWith(false)
    expect(clearFlashOverlays).toHaveBeenCalledOnce()
  })

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
