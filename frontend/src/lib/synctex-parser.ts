/**
 * Minimal SyncTeX parser for bidirectional editor ↔ PDF sync.
 *
 * Coordinate system:
 *   SyncTeX stores positions in Scaled Points (SP).
 *   1 PDF pt = 65781.76 SP  (= 65536 SP/TeX pt × 72.27 TeX pt/inch / 72 PDF pt/inch)
 *
 *   SyncTeX Y origin = TOP of page (increases downward).
 *   PDF Y origin     = BOTTOM of page (increases upward).
 *   ∴  pdf_y = pageHeight_pts − synctex_y / SP_PER_PT
 */

const SP_PER_PT = 65781.76

export interface SynctexFile {
  id: number
  name: string
}

export interface SynctexBlock {
  fileId: number
  line: number
  /** PDF left (pts) */
  x: number
  /** PDF bottom (pts) — already Y-flipped from synctex */
  y: number
  width: number
  height: number
  page: number
}

export interface SynctexData {
  files: Record<number, SynctexFile>
  /** page number → blocks on that page */
  pageBlocks: Record<number, SynctexBlock[]>
  /** `${fileId}:${line}` → blocks, for forward lookup */
  lineIndex: Record<string, SynctexBlock[]>
  /** page number → natural page height in PDF pts (A4 default) */
  pageHeights: Record<number, number>
}

/**
 * Parse a (uncompressed) synctex text file.
 * Call this on the result of pako.inflate(..., { to: 'string' }) or
 * a server-decompressed plain-text response.
 */
export function parseSynctex(content: string): SynctexData {
  const data: SynctexData = {
    files: {},
    pageBlocks: {},
    lineIndex: {},
    pageHeights: {},
  }

  const lines = content.split('\n')
  let i = 0
  let pageHeightSP = 0

  // ── Header ───────────────────────────────────────────────────────────
  while (i < lines.length) {
    const line = lines[i++]
    if (line.startsWith('Content:')) break

    const inputMatch = line.match(/^Input:(\d+):(.+)$/)
    if (inputMatch) {
      const id = parseInt(inputMatch[1], 10)
      data.files[id] = { id, name: inputMatch[2].replace(/^\.\//, '') }
    }

    // The Page header contains physical dimensions
    // "Page:NxM" or sometimes stored elsewhere — grab from first h record's y if needed
  }

  // ── Content ───────────────────────────────────────────────────────────
  let currentPage = 0

  while (i < lines.length) {
    const line = lines[i++]
    if (!line) continue
    const ch = line[0]

    if (ch === '{') {
      // Start of page
      currentPage = parseInt(line.slice(1), 10)
      if (!data.pageBlocks[currentPage]) data.pageBlocks[currentPage] = []
      continue
    }

    if (ch === '}') {
      continue
    }

    // h record: h<fileId>,<line>:<x>:<y>:<w>:<h>
    if (ch === 'h') {
      const m = line.match(/^h(\d+),(\d+):(-?\d+):(-?\d+):(-?\d+):(-?\d+)/)
      if (m && currentPage > 0) {
        const synctexY = parseInt(m[4], 10)
        // Track max Y seen on this page to estimate page height
        if (synctexY > pageHeightSP) pageHeightSP = synctexY

        // Defer Y-flip until we know the page height; store raw synctex Y for now
        const rawBlock = {
          fileId: parseInt(m[1], 10),
          line: parseInt(m[2], 10),
          x: parseInt(m[3], 10) / SP_PER_PT,
          _rawY: synctexY,
          width: parseInt(m[5], 10) / SP_PER_PT,
          height: parseInt(m[6], 10) / SP_PER_PT,
          page: currentPage,
        }
        ;(data.pageBlocks[currentPage] as any[]).push(rawBlock)

        const key = `${rawBlock.fileId}:${rawBlock.line}`
        if (!data.lineIndex[key]) data.lineIndex[key] = []
        ;(data.lineIndex[key] as any[]).push(rawBlock)
      }
    }

    // v record (same format as h): v<fileId>,<line>:<x>:<y>:<w>:<h>
    if (ch === 'v') {
      const m = line.match(/^v(\d+),(\d+):(-?\d+):(-?\d+):(-?\d+):(-?\d+)/)
      if (m && currentPage > 0) {
        const synctexY = parseInt(m[4], 10)
        if (synctexY > pageHeightSP) pageHeightSP = synctexY
        const rawBlock = {
          fileId: parseInt(m[1], 10),
          line: parseInt(m[2], 10),
          x: parseInt(m[3], 10) / SP_PER_PT,
          _rawY: synctexY,
          width: parseInt(m[5], 10) / SP_PER_PT,
          height: parseInt(m[6], 10) / SP_PER_PT,
          page: currentPage,
        }
        ;(data.pageBlocks[currentPage] as any[]).push(rawBlock)
        const key = `${rawBlock.fileId}:${rawBlock.line}`
        if (!data.lineIndex[key]) data.lineIndex[key] = []
        ;(data.lineIndex[key] as any[]).push(rawBlock)
      }
    }
  }

  // ── Post-process: apply Y-flip ─────────────────────────────────────
  // Typical A4 page height = 841.89 pts = 55,392,516 SP
  // Use max Y seen as a proxy for the page height (usually close enough)
  const estimatedPageHeightPts = pageHeightSP / SP_PER_PT

  for (const pageNum of Object.keys(data.pageBlocks)) {
    const blocks = data.pageBlocks[parseInt(pageNum, 10)]
    for (const block of blocks as any[]) {
      if ('_rawY' in block) {
        block.y = estimatedPageHeightPts - block._rawY / SP_PER_PT
        delete block._rawY
      }
    }
    data.pageHeights[parseInt(pageNum, 10)] = estimatedPageHeightPts
  }

  return data
}

/**
 * Reverse lookup: PDF click (page, pdfX, pdfY in pts) → source line.
 * pdfX/pdfY must be in PDF coordinate space (origin: bottom-left).
 */
export function synctexReverse(
  data: SynctexData,
  page: number,
  pdfX: number,
  pdfY: number
): { fileId: number; line: number; file: string } | null {
  const blocks = data.pageBlocks[page]
  if (!blocks?.length) return null

  let best: SynctexBlock | null = null
  let bestDist = Infinity

  for (const block of blocks) {
    // Check bounding box with some tolerance
    const tol = 5
    if (
      pdfX >= block.x - tol &&
      pdfX <= block.x + block.width + tol &&
      pdfY >= block.y - tol &&
      pdfY <= block.y + block.height + tol
    ) {
      const cx = block.x + block.width / 2
      const cy = block.y + block.height / 2
      const dist = Math.hypot(pdfX - cx, pdfY - cy)
      if (dist < bestDist) {
        bestDist = dist
        best = block
      }
    }
  }

  // Fallback: find nearest block by center distance
  if (!best) {
    for (const block of blocks) {
      const cx = block.x + block.width / 2
      const cy = block.y + block.height / 2
      const dist = Math.hypot(pdfX - cx, pdfY - cy)
      if (dist < bestDist) {
        bestDist = dist
        best = block
      }
    }
  }

  if (!best) return null

  const file = data.files[best.fileId]
  return { fileId: best.fileId, line: best.line, file: file?.name ?? 'main.tex' }
}

/**
 * Forward lookup: source line → PDF block (page + coordinates).
 */
export function synctexForward(
  data: SynctexData,
  line: number,
  fileName = 'main.tex'
): SynctexBlock | null {
  // Find matching file ID
  const fileEntry = Object.values(data.files).find(
    (f) => f.name === fileName || f.name.endsWith(fileName)
  )
  if (!fileEntry) {
    // Fallback: use file 1
    const fallback = data.files[1]
    if (!fallback) return null
  }

  const fileId = fileEntry?.id ?? 1

  // Find the block closest to the requested line
  let best: SynctexBlock | null = null
  let bestLineDiff = Infinity

  for (let l = line; l >= Math.max(1, line - 10); l--) {
    const key = `${fileId}:${l}`
    const blocks = data.lineIndex[key]
    if (blocks?.length) {
      const diff = Math.abs(l - line)
      if (diff < bestLineDiff) {
        bestLineDiff = diff
        best = blocks[0]
      }
      break
    }
  }

  return best
}
