export type CoverLetterSignature =
  | { mode: 'typed'; name: string }
  | { mode: 'image'; name: string; dataUrl: string }

const SIGNATURE_START = '% LATEXY_SIGNATURE_START'
const SIGNATURE_END = '% LATEXY_SIGNATURE_END'
const PACKAGE_START = '% LATEXY_SIGNATURE_PACKAGE_START'
const PACKAGE_END = '% LATEXY_SIGNATURE_PACKAGE_END'
const DATA_PREFIX = '% LATEXY_SIGNATURE_DATA:'

function escapeLatex(value: string): string {
  return value.replace(/[\\{}%$&#_^~]/g, (character) => ({
    '\\': '\\textbackslash{}', '{': '\\{', '}': '\\}', '%': '\\%', '$': '\\$',
    '&': '\\&', '#': '\\#', '_': '\\_', '^': '\\textasciicircum{}', '~': '\\textasciitilde{}',
  }[character] ?? character))
}

function removeBlock(source: string, start: string, end: string): string {
  const startIndex = source.indexOf(start)
  if (startIndex < 0) return source
  const endIndex = source.indexOf(end, startIndex)
  if (endIndex < 0) return source
  const removeFrom = source.slice(Math.max(0, startIndex - 2), startIndex) === '\n\n'
    ? startIndex - 1
    : startIndex
  const afterEnd = endIndex + end.length
  const removeTo = source[afterEnd] === '\n' ? afterEnd + 1 : afterEnd
  return `${source.slice(0, removeFrom)}${source.slice(removeTo)}`
}

export function removeCoverLetterSignature(source: string): string {
  return removeBlock(removeBlock(source, SIGNATURE_START, SIGNATURE_END), PACKAGE_START, PACKAGE_END)
}

export function hasCoverLetterSignature(source: string): boolean {
  return source.includes(SIGNATURE_START) && source.includes(SIGNATURE_END)
}

export function applyCoverLetterSignature(source: string, signature: CoverLetterSignature): string {
  let next = removeCoverLetterSignature(source)
  const endDocument = next.lastIndexOf('\\end{document}')
  if (endDocument < 0) throw new Error('The cover letter is missing \\end{document}.')

  const name = signature.name.trim()
  let packageBlock = ''
  let signatureContent: string
  if (signature.mode === 'typed') {
    if (!name) throw new Error('Enter the name to use as your signature.')
    signatureContent = `\\textit{\\Large ${escapeLatex(name)}}`
  } else {
    const match = signature.dataUrl.match(/^data:image\/(?:png|jpeg|webp);base64,([A-Za-z0-9+/=]+)$/)
    if (!match) throw new Error('Use a valid PNG, JPEG, or WebP signature image.')
    const chunks = match[1].match(/.{1,76}/g) ?? []
    packageBlock = `${PACKAGE_START}\n\\usepackage{graphicx}\n${PACKAGE_END}\n`
    signatureContent = [
      ...chunks.map((chunk) => `${DATA_PREFIX}${chunk}`),
      '\\includegraphics[height=1.4cm,width=5cm,keepaspectratio]{latexy-signature.png}',
      ...(name ? [`\\\\[-0.15em]{\\small ${escapeLatex(name)}}`] : []),
    ].join('\n')
    const beginDocument = next.indexOf('\\begin{document}')
    if (beginDocument < 0) throw new Error('The cover letter is missing \\begin{document}.')
    next = `${next.slice(0, beginDocument)}${packageBlock}${next.slice(beginDocument)}`
  }

  const refreshedEnd = next.lastIndexOf('\\end{document}')
  const block = [
    SIGNATURE_START,
    '\\par\\vspace{1em}',
    '\\noindent',
    signatureContent,
    SIGNATURE_END,
    '',
  ].join('\n')
  return `${next.slice(0, refreshedEnd).trimEnd()}\n\n${block}${next.slice(refreshedEnd)}`
}
