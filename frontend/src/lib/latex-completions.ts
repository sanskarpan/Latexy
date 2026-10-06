export type LatexArgumentCompletion = {
  kind: 'citation' | 'reference'
  partial: string
  alreadyUsed: Set<string>
}

const CITE_COMMANDS = [
  'cite',
  'citep',
  'citet',
  'citealp',
  'citealt',
  'citeauthor',
  'citeyear',
  'citeyearpar',
  'nocite',
  'parencite',
  'textcite',
  'autocite',
  'footcite',
  'smartcite',
]

const REF_COMMANDS = [
  'ref',
  'eqref',
  'pageref',
  'autoref',
  'cref',
  'Cref',
  'vref',
  'Vref',
  'nameref',
]

function commandPattern(commands: string[]): string {
  return commands.sort((a, b) => b.length - a.length).join('|')
}

const CITE_ARGUMENT = new RegExp(
  `\\\\(?:${commandPattern([...CITE_COMMANDS])})\\*?(?:\\[[^\\]]*\\]){0,2}\\{([^}]*)$`,
)
const REF_ARGUMENT = new RegExp(
  `\\\\(?:${commandPattern([...REF_COMMANDS])})\\*?\\{([^}]*)$`,
)

function uncommentedSource(source: string): string {
  return source
    .split('\n')
    .map((line) => line.replace(/(^|[^\\])(?:\\\\)*%.*/, '$1'))
    .join('\n')
}

function uniqueMatches(source: string, expression: RegExp): string[] {
  const values = new Set<string>()
  let match: RegExpExecArray | null
  while ((match = expression.exec(source)) !== null) {
    const value = match[1].trim()
    if (value) values.add(value)
  }
  return [...values]
}

export function extractLatexLabels(source: string): string[] {
  return uniqueMatches(uncommentedSource(source), /\\label\s*\{([^}]+)\}/g)
}

export function extractCitationKeys(source: string, bibliography = ''): string[] {
  const keys = new Set(
    uniqueMatches(uncommentedSource(source), /\\bibitem(?:\s*\[[^\]]*\])?\s*\{([^}]+)\}/g),
  )
  const bibtex = uncommentedSource(`${source}\n${bibliography}`)
  const entry = /@(?!string\b|comment\b|preamble\b)[A-Za-z]+\s*[({]\s*([^,\s}]+)\s*,/gi
  for (const key of uniqueMatches(bibtex, entry)) keys.add(key)
  return [...keys]
}

export function matchLatexArgumentCompletion(
  lineBeforeCursor: string,
): LatexArgumentCompletion | null {
  const citation = lineBeforeCursor.match(CITE_ARGUMENT)
  if (citation) {
    const tokens = citation[1].split(',')
    const partial = tokens.pop()?.trimStart() ?? ''
    return {
      kind: 'citation',
      partial,
      alreadyUsed: new Set(tokens.map((token) => token.trim()).filter(Boolean)),
    }
  }

  const reference = lineBeforeCursor.match(REF_ARGUMENT)
  if (reference) {
    return {
      kind: 'reference',
      partial: reference[1].trimStart(),
      alreadyUsed: new Set(),
    }
  }

  return null
}
