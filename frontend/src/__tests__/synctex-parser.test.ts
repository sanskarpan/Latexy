import { describe, expect, test } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { parseSynctex, SP_PER_PT, synctexForward, synctexHasMappableSource, synctexReverse } from '../lib/synctex-parser'

const nativeSynctex = readFileSync(fileURLToPath(new URL('./fixtures/native-resume.synctex', import.meta.url)), 'utf8')

describe('SyncTeX parser', () => {
  test('parses native pdfTeX h/k/box records and uses measured PDF height', () => {
    const data = parseSynctex(nativeSynctex, { 1: 841.89 })
    expect(data.files[1].name).toBe('/fixture/resume.tex')
    expect(data.files[2].name).toContain('article.cls')
    expect(data.pageBlocks[1].length).toBeGreaterThan(0)
    expect(data.pageHeights).toEqual({ 1: 841.89 })

    const lineFour = data.lineIndex['1:4'][0]
    expect(lineFour.x).toBeCloseTo(8799518 / SP_PER_PT, 4)
    expect(lineFour.x).toBeCloseTo(133.768356, 3)
    expect(lineFour.width).toBeCloseTo(22609920 / SP_PER_PT, 4)
    expect(lineFour.height).toBeCloseTo(455111 / SP_PER_PT, 4)
    expect(lineFour.y).toBeCloseTo(841.89 - 8865054 / SP_PER_PT, 4)
  })

  test('matches the actual main input and refuses an unrelated requested file', () => {
    const data = parseSynctex(nativeSynctex, { 1: 841.89 })
    expect(synctexForward(data, 3, '/fixture/resume.tex')?.fileId).toBe(1)
    expect(synctexForward(data, 3, 'resume.tex')?.fileId).toBe(1)
    expect(synctexForward(data, 1, 'other-document.tex')).toBeNull()
    expect(synctexForward(data, 3)?.fileId).toBe(1)
  })

  test('reverse lookup returns the source filename and line at a native block', () => {
    const data = parseSynctex(nativeSynctex, { 1: 841.89 })
    const block = data.lineIndex['1:4'][0]
    expect(synctexReverse(data, 1, block.x + block.width / 2, block.y + block.height / 2)).toEqual({
      fileId: 1,
      line: 4,
      file: '/fixture/resume.tex',
    })
    expect(synctexReverse(data, 1, block.x, block.y, 'other-document.tex')).toBeNull()
    expect(synctexReverse(data, 99, 0, 0)).toBeNull()
    expect(synctexReverse(data, 1, Number.NaN, 0)).toBeNull()
  })

  test('matches the native editor oracle with a measured 792pt page height', () => {
    const data = parseSynctex(nativeSynctex, { 1: 792 })
    // Native synctex edit reports 1:170:134.765 for this fixture.  The
    // parser's reverse coordinates use the PDF bottom-left origin.
    expect(synctexReverse(data, 1, 170, 792 - 134.765)?.line).toBe(3)
    const forward = synctexForward(data, 3, '/fixture/resume.tex')
    expect(forward?.page).toBe(1)
    expect(forward?.x).toBeLessThanOrEqual(170)
    expect((forward?.x ?? 0) + (forward?.width ?? 0)).toBeGreaterThanOrEqual(191.27)
    // Use the unrounded native forward result when testing strict bounds.
    expect(forward?.y).toBeLessThanOrEqual(792 - 134.764618)
    expect((forward?.y ?? 0) + (forward?.height ?? 0)).toBeGreaterThanOrEqual(792 - 134.764618)
    expect(synctexHasMappableSource(data, '/fixture/resume.tex')).toBe(true)
  })

  test('uses the measured height independently for different pages', () => {
    const content = nativeSynctex.replace(
      '{1\n',
      '{2\n',
    )
    const data = parseSynctex(`${nativeSynctex}\n${content}`, { 1: 792, 2: 612 })
    const pageOne = synctexForward(data, 3, '/fixture/resume.tex')
    const pageTwo = data.lineIndex['1:3'].find((block) => block.page === 2)
    expect(pageOne?.page).toBe(1)
    expect(pageTwo?.page).toBe(2)
    expect(pageOne?.y).not.toBe(pageTwo?.y)
    expect(data.pageHeights[1]).toBe(792)
    expect(data.pageHeights[2]).toBe(612)
  })

  test('does not union disjoint rows for a repeated source line', () => {
    const content = `SyncTeX Version:1\nInput:1:/fixture/resume.tex\nContent:\n{1\nh1,3:100000,200000:10000,5000,0\nx1,3:120000,200000\nh1,3:100000,500000:10000,5000,0\nx1,3:120000,500000\n}\n`
    const data = parseSynctex(content, { 1: 792 })
    const forward = synctexForward(data, 3, '/fixture/resume.tex')
    expect(forward?.x).toBeCloseTo(100000 / SP_PER_PT, 4)
    expect(forward?.width).toBeLessThan(100000 / SP_PER_PT)
    expect(forward?.height).toBeLessThan(20)
  })

  test('does not guess when two included files share a basename', () => {
    const collision = `SyncTeX Version:1\nInput:1:/docs/a/main.tex\nInput:2:/docs/b/main.tex\nContent:\n{1\nh1,3:100000,200000:10000,5000,0\n}\n{1\nh2,3:200000,200000:10000,5000,0\n}\n`
    const data = parseSynctex(collision, { 1: 792 })
    expect(synctexForward(data, 3, 'main.tex')).toBeNull()
    expect(synctexForward(data, 3, '/docs/b/main.tex')?.fileId).toBe(2)
    expect(synctexReverse(data, 1, 100000 / SP_PER_PT, 792 - 200000 / SP_PER_PT, 'main.tex')).toBeNull()
  })

  test('does not invent blocks or readiness for empty and malformed content', () => {
    const data = parseSynctex('SyncTeX Version:1\nInput:1:main.tex\nContent:\n{1\nhnot-a-record\n}\n')
    expect(data.pageBlocks).toEqual({})
    expect(data.lineIndex).toEqual({})
    expect(synctexForward(data, 1)).toBeNull()
  })

  test('disables mapping when the SyncTeX coordinate transform is unsupported', () => {
    const unsupported = nativeSynctex.replace('Magnification:1000', 'Magnification:1200')
    const data = parseSynctex(unsupported, { 1: 792, 2: 792 })
    expect(data.files[1].name).toBe('/fixture/resume.tex')
    expect(data.pageBlocks).toEqual({})
    expect(synctexForward(data, 1)).toBeNull()
  })
})
