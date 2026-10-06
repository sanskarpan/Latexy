import { readFileSync } from 'node:fs'
import path from 'node:path'
import { expect, test } from '@playwright/test'
import ts from 'typescript'

type PdfModule = typeof import('../src/lib/offline-pdfs')
const idbSource = readFileSync(require.resolve('idb/build/index.js'), 'utf8')
const helperSource = ts.transpileModule(
  readFileSync(path.join(__dirname, '../src/lib/offline-pdfs.ts'), 'utf8'),
  { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } },
).outputText.replace(/from ['"]idb['"]/, 'from "/__offline-pdf-probe/idb.js"')

// Execute the actual repository helper and real idb library in Chromium. This
// isolated module surface deliberately needs no app session/backend/paid calls.
test.beforeEach(async ({ page }) => {
  await page.route('**/__offline-pdf-probe/**', (route) => {
    const pathname = new URL(route.request().url()).pathname
    if (pathname.endsWith('/pdf.js') || pathname.endsWith('/idb.js')) {
      return route.fulfill({
        contentType: 'text/javascript',
        body: pathname.endsWith('/pdf.js') ? helperSource : idbSource,
      })
    }
    return route.fulfill({ contentType: 'text/html', body: '<!doctype html><title>Isolated PDF transaction probe</title>' })
  })
  await page.goto('/__offline-pdf-probe/index.html')
})

test('reads PDF bytes across browser file I/O without an inactive write transaction', async ({ page }) => {
  const result = await page.evaluate(async () => {
    const modulePath = '/__offline-pdf-probe/pdf.js'
    const pdfs = await import(modulePath) as PdfModule
    const bytes = '%PDF-1.4 transaction fixture'
    await pdfs.saveOfflineCompiledPdf({ ownerId: 'owner', resumeId: 'resume', pdf: new Blob([bytes], { type: 'text/html' }) })
    const text = Blob.prototype.text
    Blob.prototype.text = async function () {
      await new Promise((resolve) => setTimeout(resolve, 25))
      return text.call(this)
    }
    try {
      const cached = await pdfs.getOfflineCompiledPdf('owner', 'resume')
      return { bytes: await cached?.pdf.text(), size: cached?.pdf.size, mime: cached?.pdf.type }
    } finally { Blob.prototype.text = text }
  })
  expect(result).toEqual({ bytes: '%PDF-1.4 transaction fixture', size: 28, mime: 'application/pdf' })
})

test('does not resurrect a cached PDF purged while its header is being read', async ({ page }) => {
  const result = await page.evaluate(async () => {
    const modulePath = '/__offline-pdf-probe/pdf.js'
    const pdfs = await import(modulePath) as PdfModule
    await pdfs.saveOfflineCompiledPdf({ ownerId: 'owner', resumeId: 'resume', pdf: new Blob(['%PDF-1.4 original']) })
    const text = Blob.prototype.text
    Blob.prototype.text = async function () {
      Blob.prototype.text = text
      await pdfs.clearAllOfflineCompiledPdfs()
      return text.call(this)
    }
    try {
      return {
        inFlight: await pdfs.getOfflineCompiledPdf('owner', 'resume'),
        afterwards: await pdfs.getOfflineCompiledPdf('owner', 'resume'),
      }
    } finally { Blob.prototype.text = text }
  })
  expect(result).toEqual({ inFlight: null, afterwards: null })
})

test('preserves a newer save during validation instead of writing the old bytes back', async ({ page }) => {
  const result = await page.evaluate(async () => {
    const modulePath = '/__offline-pdf-probe/pdf.js'
    const pdfs = await import(modulePath) as PdfModule
    await pdfs.saveOfflineCompiledPdf({ ownerId: 'owner', resumeId: 'resume', title: 'Original', pdf: new Blob(['%PDF-1.4 original']) })
    const text = Blob.prototype.text
    Blob.prototype.text = async function () {
      Blob.prototype.text = text
      await pdfs.saveOfflineCompiledPdf({ ownerId: 'owner', resumeId: 'resume', title: 'Newest', pdf: new Blob(['%PDF-1.4 replacement']) })
      return text.call(this)
    }
    try {
      await pdfs.getOfflineCompiledPdf('owner', 'resume')
      const newest = await pdfs.getOfflineCompiledPdf('owner', 'resume')
      return { title: newest?.title, bytes: await newest?.pdf.text() }
    } finally { Blob.prototype.text = text }
  })
  expect(result).toEqual({ title: 'Newest', bytes: '%PDF-1.4 replacement' })
})

test('aborts queued LRU eviction when the save owner changes before commit', async ({ page }) => {
  const result = await page.evaluate(async () => {
    const modulePath = '/__offline-pdf-probe/pdf.js'
    const pdfs = await import(modulePath) as PdfModule
    const makePdf = (fill: number) => {
      const bytes = new Uint8Array(pdfs.MAX_OFFLINE_PDF_BYTES)
      bytes.set(new TextEncoder().encode('%PDF-'))
      bytes.fill(fill, 5)
      return new Blob([bytes], { type: 'application/pdf' })
    }

    const originalKeys = ['a', 'b', 'c', 'd']
    for (const [index, resumeId] of originalKeys.entries()) {
      await pdfs.saveOfflineCompiledPdf({
        ownerId: 'owner',
        resumeId,
        pdf: makePdf(index + 1),
      })
    }

    let checks = 0
    await pdfs.saveOfflineCompiledPdf({
      ownerId: 'new-owner',
      resumeId: 'replacement',
      pdf: makePdf(9),
      // The second check happens immediately before the first delete is
      // queued. Returning false at the next check makes the helper abort the
      // same transaction instead of committing that partial eviction.
      shouldPersist: () => ++checks < 3,
    })

    const remaining = await Promise.all(originalKeys.map(async (resumeId) => {
      const record = await pdfs.getOfflineCompiledPdf('owner', resumeId)
      return record?.pdf.size === pdfs.MAX_OFFLINE_PDF_BYTES
    }))
    return {
      checks,
      remaining,
      replacement: await pdfs.getOfflineCompiledPdf('new-owner', 'replacement'),
    }
  })

  expect(result.checks).toBe(3)
  expect(result.remaining).toEqual([true, true, true, true])
  expect(result.replacement).toBeNull()
})
