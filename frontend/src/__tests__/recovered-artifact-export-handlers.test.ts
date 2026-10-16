import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import ts from 'typescript'
import { describe, expect, it, vi } from 'vitest'
import { sha256Bytes } from '@/hooks/useArtifactPreview'
import {
  isCurrentAcceptedPreviewRecovery,
  isMatchingAcceptedArtifact,
  resolveCurrentAcceptedPreviewRecovery,
  type AcceptedPreviewRecoveryIdentity,
  type AcceptedPreviewRecoveryResponse,
} from '@/lib/accepted-artifact-recovery'

const pageSource = ts.createSourceFile('editor/page.tsx', readFileSync(
  new URL('../app/workspace/[resumeId]/edit/page.tsx', import.meta.url), 'utf8',
), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)
const resumePage = pageSource.statements.find((node) =>
  ts.isFunctionDeclaration(node) && node.name?.text === 'ResumeEditPage') as ts.FunctionDeclaration
const declarations = new Map<string, ts.VariableDeclaration>()
function visit(node: ts.Node) {
  if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name)) declarations.set(node.name.text, node)
  ts.forEachChild(node, visit)
}
visit(resumePage)

function extractHandler(name: string) {
  const initializer = declarations.get(name)?.initializer
  if (!initializer) throw new Error(`Missing ${name} handler`)
  if (ts.isCallExpression(initializer) && ts.isArrowFunction(initializer.arguments[0])) {
    return initializer.arguments[0].getText(pageSource)
  }
  return initializer.getText(pageSource)
}

function evaluateHandler(name: string, context: Record<string, unknown>) {
  const js = ts.transpileModule(`(${extractHandler(name)})`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText
  return runInNewContext(js, context) as () => Promise<void>
}

const sourceText = '\\documentclass{article}\\begin{document}current\\end{document}'
const recoveryIdentity: AcceptedPreviewRecoveryIdentity = {
  ownerId: 'owner-a', resumeId: 'resume-a', generation: 2, source: sourceText, contentRevision: 7,
}
const artifact = {
  job_id: 'accepted-job', artifact_id: 'a'.repeat(64), document_id: 'resume-a', content_revision: 7,
  source_sha256: 'b'.repeat(64), branch: 'draft' as const, owner_epoch: 1, compiler: 'pdflatex',
  settings_sha256: 'c'.repeat(64), pdf_sha256: 'd'.repeat(64), pdf_size: 100, page_count: 1,
  preview_url: '/download/accepted-job/preview/fixture',
}
const response: AcceptedPreviewRecoveryResponse = {
  artifact, source_sha256: artifact.source_sha256, content_revision: 7,
}

async function baseContext() {
  const sourceHash = await sha256Bytes(new TextEncoder().encode(sourceText))
  const recoveredResponse: AcceptedPreviewRecoveryResponse = {
    source_sha256: sourceHash,
    content_revision: 7,
    artifact: { ...artifact, source_sha256: sourceHash },
  }
  const identityRef = { current: { ownerId: 'owner-a', resumeId: 'resume-a', generation: 2 } }
  const revisionRef = { current: 7 }
  const editor = { getValue: () => sourceText }
  const apiClient = {
    getAuthToken: () => 'owner-token',
    getLatestAcceptedArtifact: vi.fn(async () => recoveredResponse),
    compileLatex: vi.fn(),
  }
  const context: Record<string, unknown> = {
    apiClient, sessionUserId: 'owner-a', resumeId: 'resume-a', offlinePdfOwnerId: 'owner-a',
    ownsRenderedJobState: true, offlinePdfIdentityRef: identityRef,
    resumeContentRevisionRef: revisionRef, editorRef: { current: editor },
    sourceAtRenderRef: { current: sourceText },
    acceptedArtifactRecoveryRetryIdentity: recoveryIdentity,
    currentPreviewJobIdentityRef: { current: { compileJobId: null, aiJobId: null, busy: false } },
    artifactRetryIdentityRef: { current: null }, retryArtifact: null,
    isCurrentOfflinePdfIdentity: (owner: string, resume: string, generation: number) =>
      owner === identityRef.current.ownerId && resume === identityRef.current.resumeId && generation === identityRef.current.generation,
    isCurrentAcceptedPreviewRecovery, resolveCurrentAcceptedPreviewRecovery,
    isMatchingAcceptedArtifact, sha256Bytes, TextEncoder, Date,
    setAcceptedArtifactRecoveryRetryIdentity: vi.fn(), setRecoveredAcceptedArtifact: vi.fn(),
    setOfflinePdfError: vi.fn(), setRightTab: vi.fn(),
  }
  return { context, apiClient, identityRef, revisionRef }
}

describe('recovered accepted PDF actions through the actual page handlers', () => {
  it('retries the latest accepted artifact with a fenced GET and never submits a compile', async () => {
    const h = await baseContext()
    const retry = evaluateHandler('retryOfflinePdf', h.context)
    await retry()

    expect(h.apiClient.getLatestAcceptedArtifact).toHaveBeenCalledOnce()
    const [, requestContext] = h.apiClient.getLatestAcceptedArtifact.mock.calls[0] as unknown as [string, { authToken: string; isCurrent: () => boolean }]
    expect(requestContext.authToken).toBe('owner-token')
    expect(requestContext.isCurrent()).toBe(true)
    expect(h.apiClient.compileLatex).not.toHaveBeenCalled()
    expect(h.context.setRecoveredAcceptedArtifact).toHaveBeenCalledWith(expect.objectContaining({
      ownerId: 'owner-a', resumeId: 'resume-a', generation: 2, source: sourceText, contentRevision: 7,
      artifact: expect.objectContaining({ job_id: 'accepted-job', artifact_id: artifact.artifact_id }),
    }))
  })

  it('does not publish a late accepted-artifact response after revision changes', async () => {
    const h = await baseContext()
    let finish!: (value: AcceptedPreviewRecoveryResponse) => void
    h.apiClient.getLatestAcceptedArtifact.mockReturnValueOnce(new Promise((resolve) => { finish = resolve }))
    const retry = evaluateHandler('retryOfflinePdf', h.context)
    const pending = retry()
    await Promise.resolve()
    h.revisionRef.current = 8
    finish(response)
    await pending

    expect(h.context.setRecoveredAcceptedArtifact).not.toHaveBeenCalled()
    expect(h.apiClient.compileLatex).not.toHaveBeenCalled()
  })

  it('uses the same recovered-artifact export gate for download and share', async () => {
    for (const name of ['handleDownload', 'shareOrDownloadPdf']) {
      const downloadBlob = vi.fn()
      const setOfflinePdfError = vi.fn()
      const toastError = vi.fn()
      const blob = new Blob(['verified pdf'], { type: 'application/pdf' })
      const context: Record<string, unknown> = {
        displayedArtifact: artifact,
        canExportDisplayedArtifact: vi.fn(() => true),
        sourceAtRenderRef: { current: sourceText },
        isAnyRunning: false,
        offlinePdfOwnerId: 'owner-a', resumeId: 'resume-a',
        offlinePdfIdentityRef: { current: { ownerId: 'owner-a', resumeId: 'resume-a', generation: 2 } },
        isCurrentOfflinePdfIdentity: () => true,
        artifactPreview: { verified: { artifact, blob } },
        offlinePdfBlobRef: { current: blob },
        ownsRenderedJobState: false, compileStream: { pdfJobId: null }, aiStream: { pdfJobId: null },
        activePdfJobId: { current: null }, ownedCompileJobId: null, ownedAiJobId: null,
        sourceHash: artifact.source_sha256, title: 'Resume', downloadBlob,
        toast: { error: toastError }, setOfflinePdfError,
        apiClient: { downloadPdf: vi.fn() }, navigator: {}, File,
        sourceFileName: 'resume.tex',
      }
      const handler = evaluateHandler(name, context)
      await handler()
      expect(context.canExportDisplayedArtifact).toHaveBeenCalledWith(artifact)
      expect(downloadBlob).toHaveBeenCalledOnce()
      expect(setOfflinePdfError).not.toHaveBeenCalled()
    }
  })

  it('blocks both download and share when the recovered artifact no longer matches', async () => {
    for (const name of ['handleDownload', 'shareOrDownloadPdf']) {
      const downloadBlob = vi.fn()
      const setOfflinePdfError = vi.fn()
      const toastError = vi.fn()
      const context: Record<string, unknown> = {
        displayedArtifact: artifact,
        canExportDisplayedArtifact: vi.fn(() => false),
        sourceAtRenderRef: { current: sourceText }, isAnyRunning: false,
        offlinePdfOwnerId: 'owner-a', resumeId: 'resume-a',
        offlinePdfIdentityRef: { current: { ownerId: 'owner-a', resumeId: 'resume-a', generation: 2 } },
        isCurrentOfflinePdfIdentity: () => true,
        artifactPreview: { verified: { artifact, blob: new Blob(['pdf']) } },
        offlinePdfBlobRef: { current: new Blob(['pdf']) }, ownsRenderedJobState: false,
        compileStream: { pdfJobId: null }, aiStream: { pdfJobId: null }, activePdfJobId: { current: null },
        ownedCompileJobId: null, ownedAiJobId: null, sourceHash: artifact.source_sha256,
        title: 'Resume', downloadBlob, toast: { error: toastError }, setOfflinePdfError,
        apiClient: { downloadPdf: vi.fn() }, navigator: {}, File,
      }
      const handler = evaluateHandler(name, context)
      await handler()
      expect(downloadBlob).not.toHaveBeenCalled()
      expect(context.canExportDisplayedArtifact).toHaveBeenCalledWith(artifact)
      expect(name === 'handleDownload' ? toastError : setOfflinePdfError).toHaveBeenCalledOnce()
    }
  })
})
