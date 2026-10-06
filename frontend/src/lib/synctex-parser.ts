/**
 * SyncTeX parser for bidirectional editor ↔ PDF sync.
 *
 * SyncTeX's Unit:1 coordinates are TeX scaled points. One PDF point is
 * 65536 * 72.27 / 72 scaled points (65781.76 SP). Native pdfTeX records use
 * `x,y:width,depth` for h/v nodes and `x,y:width,height,depth` for boxes.
 */

export const SP_PER_PT = (65536 * 72.27) / 72
const DEFAULT_PAGE_HEIGHT_PT = 841.89
const DEFAULT_LINE_HEIGHT_PT = 10

export interface SynctexFile {
  id: number
  name: string
}

export interface SynctexBlock {
  fileId: number
  line: number
  /** PDF left (pts). */
  x: number
  /** PDF bottom (pts), with the PDF bottom-left origin. */
  y: number
  width: number
  height: number
  page: number
}

export interface SynctexData {
  files: Record<number, SynctexFile>
  /** Page number → source-position blocks on that page. */
  pageBlocks: Record<number, SynctexBlock[]>
  /** `${fileId}:${line}` → blocks, for forward lookup. */
  lineIndex: Record<string, SynctexBlock[]>
  /** Page number → PDF page height in points. */
  pageHeights: Record<number, number>
}

export interface SynctexRequestToken {
  jobId: string
  generation: number
}

/**
 * Small lifecycle guard shared by PDFPreview's asynchronous SyncTeX fetch.
 * A response may update state only while its job and generation are current;
 * invalidating on cleanup prevents an old job (or an unmounted preview) from
 * re-enabling the current preview.
 */
export function createSynctexRequestGuard() {
  let generation = 0
  let activeJobId: string | null = null
  return {
    begin(jobId: string): SynctexRequestToken {
      generation += 1
      activeJobId = jobId
      return { jobId, generation }
    },
    isCurrent(token: SynctexRequestToken): boolean {
      return activeJobId === token.jobId && generation === token.generation
    },
    invalidate(token: SynctexRequestToken): void {
      if (!this.isCurrent(token)) return
      generation += 1
      activeJobId = null
    },
    reset(): void {
      generation += 1
      activeJobId = null
    },
  }
}

type RawRecord = {
  fileId: number
  line: number
  x: number
  y: number
  width: number
  height: number
  depth: number
  page: number
}

function finiteInt(value: string | undefined): number | null {
  if (!value) return null
  const parsed = Number(value)
  return Number.isSafeInteger(parsed) ? parsed : null
}

function addRecord(data: SynctexData, record: RawRecord) {
  if (record.page <= 0 || record.fileId <= 0 || record.line <= 0) return
  const pageBlocks = (data.pageBlocks[record.page] ??= [])
  const pageHeight = data.pageHeights[record.page] ?? DEFAULT_PAGE_HEIGHT_PT
  const width = Math.max(0, record.width / SP_PER_PT)
  const height = Math.max(1, (record.height + record.depth) / SP_PER_PT)
  const block: SynctexBlock = {
    fileId: record.fileId,
    line: record.line,
    x: record.x / SP_PER_PT,
    // SyncTeX y is the baseline. Depth extends below it, so the PDF bottom is
    // pageHeight - (baseline + depth), not baseline minus the box height.
    y: pageHeight - (record.y + record.depth) / SP_PER_PT,
    width,
    height,
    page: record.page,
  }
  pageBlocks.push(block)
  const key = `${record.fileId}:${record.line}`
  ;(data.lineIndex[key] ??= []).push(block)
}

function parseHvRecord(line: string, page: number): RawRecord | null {
  // Native pdfTeX: h1,4:x,y:width,height,depth. Some older writers omit the
  // height and leave only width,depth; both forms are accepted.
  const native = line.match(/^([hv])(\d+),(\d+):(-?\d+),(-?\d+):(-?\d+),(-?\d+),(-?\d+)\s*$/)
  if (native) {
    const fileId = finiteInt(native[2])
    const sourceLine = finiteInt(native[3])
    const x = finiteInt(native[4])
    const y = finiteInt(native[5])
    const width = finiteInt(native[6])
    const height = finiteInt(native[7])
    const depth = finiteInt(native[8])
    if ([fileId, sourceLine, x, y, width, height, depth].some(value => value === null)) return null
    return { fileId: fileId!, line: sourceLine!, x: x!, y: y!, width: width!, height: height!, depth: depth!, page }
  }

  const nativeShort = line.match(/^([hv])(\d+),(\d+):(-?\d+),(-?\d+):(-?\d+),(-?\d+)\s*$/)
  if (nativeShort) {
    const values = nativeShort.slice(2).map(finiteInt)
    if (values.some(value => value === null)) return null
    const [fileId, sourceLine, x, y, width, depth] = values as number[]
    return { fileId, line: sourceLine, x, y, width, height: DEFAULT_LINE_HEIGHT_PT * SP_PER_PT, depth, page }
  }

  // Accept the older colon-separated form emitted by some SyncTeX variants:
  // h1,4:x:y:width:height.
  const legacy = line.match(/^([hv])(\d+),(\d+):(-?\d+):(-?\d+):(-?\d+):(-?\d+)\s*$/)
  if (!legacy) return null
  const values = legacy.slice(2).map(finiteInt)
  if (values.some(value => value === null)) return null
  const [fileId, sourceLine, x, y, width, height] = values as number[]
  return { fileId, line: sourceLine, x, y, width, height, depth: 0, page }
}

function parseLineBox(line: string, page: number): RawRecord | null {
  // `(` is a source-associated box with complete width/height/depth. `[` is
  // usually a page/list box and is intentionally excluded from line mapping.
  // The opening `(` record is closed by a standalone `)` after its child
  // records, so the closing character is optional on this line.
  const match = line.match(/^\((\d+),(\d+):(-?\d+),(-?\d+):(-?\d+),(-?\d+),(-?\d+)\)?\s*$/)
  if (!match) return null
  const values = match.slice(1).map(finiteInt)
  if (values.some(value => value === null)) return null
  const [fileId, sourceLine, x, y, width, height, depth] = values as number[]
  return { fileId, line: sourceLine, x, y, width, height, depth, page }
}

function parsePositionRecord(line: string, page: number): RawRecord | null {
  // k/g/x records carry source line positions but not a useful box height.
  // Keeping them provides forward coverage for lines represented only by a
  // kern/glue node; their small/zero width makes them harmless for reverse hit
  // testing compared with the h/v and box records.
  const match = line.match(/^[kgx](\d+),(\d+):(-?\d+),(-?\d+)(?::(-?\d+))?\s*$/)
  if (!match) return null
  const fileId = finiteInt(match[1])
  const sourceLine = finiteInt(match[2])
  const x = finiteInt(match[3])
  const y = finiteInt(match[4])
  const width = finiteInt(match[5]) ?? 0
  if ([fileId, sourceLine, x, y].some(value => value === null)) return null
  return { fileId: fileId!, line: sourceLine!, x: x!, y: y!, width, height: DEFAULT_LINE_HEIGHT_PT * SP_PER_PT, depth: 0, page }
}

/**
 * Parse an uncompressed SyncTeX text file. `pageHeights` should come from the
 * PDF renderer when available; the A4 value is only a safe fallback until the
 * first PDF page viewport has been measured.
 */
export function parseSynctex(
  content: string,
  pageHeights: Record<number, number> = {},
): SynctexData {
  const data: SynctexData = {
    files: {},
    pageBlocks: {},
    lineIndex: {},
    pageHeights: {},
  }
  for (const [page, height] of Object.entries(pageHeights)) {
    if (Number.isFinite(height) && height > 0) data.pageHeights[Number(page)] = height
  }

  const lines = String(content ?? '').replace(/^\uFEFF/, '').split(/\r?\n/)
  let currentPage = 0
  let inContent = false
  let unsupportedHeader = false
  for (const line of lines) {
    if (!inContent) {
      if (line === 'Content:') inContent = true
      const unit = line.match(/^Unit:(-?\d+)$/)
      const magnification = line.match(/^Magnification:(-?\d+)$/)
      const xOffset = line.match(/^X Offset:(-?\d+)$/)
      const yOffset = line.match(/^Y Offset:(-?\d+)$/)
      if (unit && unit[1] !== '1') unsupportedHeader = true
      if (magnification && magnification[1] !== '1000') unsupportedHeader = true
      if ((xOffset && xOffset[1] !== '0') || (yOffset && yOffset[1] !== '0')) unsupportedHeader = true
      const inputMatch = line.match(/^Input:(\d+):(.*)$/)
      if (inputMatch) {
        const id = finiteInt(inputMatch[1])
        const name = inputMatch[2].trim()
        if (id !== null && name) data.files[id] = { id, name }
      }
      continue
    }

    if (line.startsWith('{')) {
      const page = finiteInt(line.slice(1).trim())
      currentPage = page ?? 0
      if (currentPage > 0) {
        data.pageBlocks[currentPage] ??= []
        data.pageHeights[currentPage] ??= DEFAULT_PAGE_HEIGHT_PT
      }
      continue
    }
    if (line.startsWith('}')) {
      currentPage = 0
      continue
    }
    if (currentPage <= 0 || !line) continue

    const record = parseLineBox(line, currentPage) ?? parseHvRecord(line, currentPage) ?? parsePositionRecord(line, currentPage)
    if (record) addRecord(data, record)
  }

  // A non-default unit/magnification/offset requires a coordinate transform
  // that this browser parser does not implement. Disable SyncTeX rather than
  // silently jumping to a wrong location.
  if (unsupportedHeader) return { files: data.files, pageBlocks: {}, lineIndex: {}, pageHeights: {} }

  // Do not advertise empty pages as usable SyncTeX data.
  for (const page of Object.keys(data.pageBlocks)) {
    if (!data.pageBlocks[Number(page)].length) {
      delete data.pageBlocks[Number(page)]
      delete data.pageHeights[Number(page)]
    }
  }
  return data
}

function basename(name: string): string {
  return name.replace(/\\/g, '/').split('/').pop() ?? name
}

function fileHasLines(data: SynctexData, fileId: number): boolean {
  return Object.keys(data.lineIndex).some(key => key.startsWith(`${fileId}:`))
}

/** Whether the selected/primary source has at least one forward-sync block. */
export function synctexHasMappableSource(data: SynctexData, fileName?: string): boolean {
  const file = findFile(data, fileName)
  return file !== null && fileHasLines(data, file.id)
}

function findFile(data: SynctexData, requested?: string): SynctexFile | null {
  if (requested?.trim()) {
    const normalized = requested.trim().replace(/\\/g, '/')
    const files = Object.values(data.files)
    // Prefer an exact compiler path.  A basename fallback is only safe when
    // it is unique; silently choosing the first `main.tex` would jump into a
    // different included source file in multi-file documents.
    const exact = files.find(file => file.name === requested.trim() || file.name === normalized)
    if (exact) return exact
    const suffixMatches = files.filter(file => file.name.endsWith(`/${normalized}`))
    if (suffixMatches.length === 1) return suffixMatches[0]
    const basenameMatches = files.filter(file => basename(file.name) === basename(normalized))
    return basenameMatches.length === 1 ? basenameMatches[0] : null
  }
  // SyncTeX Input:1 is the document passed to the compiler. Only use that
  // deterministic main input, never an arbitrary package/include file.
  const main = data.files[1]
  return main && fileHasLines(data, main.id) ? main : null
}

/** Reverse lookup: PDF click coordinates use a bottom-left PDF origin. */
export function synctexReverse(
  data: SynctexData,
  page: number,
  pdfX: number,
  pdfY: number,
  fileName?: string,
): { fileId: number; line: number; file: string } | null {
  if (!Number.isFinite(pdfX) || !Number.isFinite(pdfY)) return null
  const sourceFile = findFile(data, fileName)
  if (!sourceFile) return null
  const blocks = data.pageBlocks[page]?.filter(block => block.fileId === sourceFile.id)
  if (!blocks?.length) return null

  let best: SynctexBlock | null = null
  let bestDist = Infinity
  for (const block of blocks) {
    const tolerance = 5
    if (pdfX >= block.x - tolerance && pdfX <= block.x + block.width + tolerance && pdfY >= block.y - tolerance && pdfY <= block.y + block.height + tolerance) {
      const dist = Math.hypot(pdfX - (block.x + block.width / 2), pdfY - (block.y + block.height / 2))
      if (dist < bestDist) { bestDist = dist; best = block }
    }
  }
  if (!best) {
    for (const block of blocks) {
      const dist = Math.hypot(pdfX - (block.x + block.width / 2), pdfY - (block.y + block.height / 2))
      if (dist < bestDist) { bestDist = dist; best = block }
    }
  }
  if (!best) return null
  const file = data.files[best.fileId]
  if (!file) return null
  return { fileId: best.fileId, line: best.line, file: file.name }
}

/** Forward lookup: source line → PDF block. */
export function synctexForward(data: SynctexData, line: number, fileName?: string): SynctexBlock | null {
  if (!Number.isInteger(line) || line <= 0) return null
  const file = findFile(data, fileName)
  if (!file) return null

  for (let candidateLine = line; candidateLine >= Math.max(1, line - 10); candidateLine -= 1) {
    const blocks = data.lineIndex[`${file.id}:${candidateLine}`]
    if (blocks?.length) return coalesceForwardRow(blocks)[0] ?? null
  }
  return null
}

/**
 * Native SyncTeX emits one h node followed by x/g/k nodes for the same source
 * line.  Returning only the first h node highlights an indentation fragment;
 * merge nodes on the same page and nearby baseline into one row, while keeping
 * separate rows/pages separate so a repeated EOF line cannot become a page-wide
 * union.
 */
function coalesceForwardRow(blocks: SynctexBlock[]): SynctexBlock[] {
  const rows: SynctexBlock[][] = []
  const sorted = [...blocks].sort((a, b) => a.page - b.page || a.y - b.y || a.x - b.x)
  for (const block of sorted) {
    const row = rows.find((candidate) =>
      candidate[0].page === block.page && Math.abs(candidate[0].y - block.y) <= 2,
    )
    if (row) row.push(block)
    else rows.push([block])
  }
  return rows.map((row) => {
    const first = row[0]
    const right = Math.max(...row.map((block) => block.x + block.width))
    const bottom = Math.min(...row.map((block) => block.y))
    const top = Math.max(...row.map((block) => block.y + block.height))
    return {
      ...first,
      x: Math.min(...row.map((block) => block.x)),
      y: bottom,
      width: Math.max(0, right - Math.min(...row.map((block) => block.x))),
      height: Math.max(1, top - bottom),
    }
  })
}
