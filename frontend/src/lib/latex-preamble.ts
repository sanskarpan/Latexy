// Utilities for reading/writing common LaTeX preamble settings.
// Shared by DesignPanel (Feature 20) and future preamble-aware features.

// ─── Font data ────────────────────────────────────────────────────────────────

export interface FontOption {
  name: string
  package: string | null    // \usepackage argument, null for Computer Modern
  command: string | null    // extra line to add after \usepackage (e.g. \renewcommand...)
  category: 'serif' | 'sans-serif' | 'monospace'
  webPreview: string        // CSS font-family for browser preview only
}

export const LATEX_FONTS: FontOption[] = [
  // ── Serif ──────────────────────────────────────────────────────────────────
  {
    name: 'Computer Modern',
    package: null,
    command: null,
    category: 'serif',
    webPreview: '"CMU Serif", "Computer Modern", Georgia, serif',
  },
  {
    name: 'Latin Modern',
    package: 'lmodern',
    command: null,
    category: 'serif',
    webPreview: '"Latin Modern", Georgia, serif',
  },
  {
    name: 'Times New Roman',
    package: 'mathptmx',
    command: null,
    category: 'serif',
    webPreview: '"Times New Roman", Times, serif',
  },
  {
    name: 'Palatino',
    package: 'palatino',
    command: null,
    category: 'serif',
    webPreview: '"Palatino Linotype", Palatino, Georgia, serif',
  },
  {
    name: 'EB Garamond',
    package: 'ebgaramond',
    command: null,
    category: 'serif',
    webPreview: '"EB Garamond", Garamond, Georgia, serif',
  },
  {
    name: 'Charter',
    package: 'charter',
    command: null,
    category: 'serif',
    webPreview: '"Bitstream Charter", Georgia, serif',
  },
  {
    name: 'Utopia',
    package: 'fourier',
    command: null,
    category: 'serif',
    webPreview: '"Utopia", Georgia, serif',
  },
  {
    name: 'Bookman',
    package: 'bookman',
    command: null,
    category: 'serif',
    webPreview: '"Bookman Old Style", Georgia, serif',
  },
  {
    name: 'New Century Schoolbook',
    package: 'newcent',
    command: null,
    category: 'serif',
    webPreview: '"Century Schoolbook", Georgia, serif',
  },
  {
    name: 'Baskervald',
    package: 'baskervaldx',
    command: null,
    category: 'serif',
    webPreview: '"Libre Baskerville", Baskerville, Georgia, serif',
  },
  {
    name: 'Libre Baskerville',
    package: 'librebaskerville',
    command: null,
    category: 'serif',
    webPreview: '"Libre Baskerville", Baskerville, Georgia, serif',
  },
  {
    name: 'Linux Libertine',
    package: 'libertine',
    command: null,
    category: 'serif',
    webPreview: '"Linux Libertine", Palatino, Georgia, serif',
  },
  {
    name: 'Merriweather',
    package: 'merriweather',
    command: null,
    category: 'serif',
    webPreview: 'Merriweather, Georgia, serif',
  },
  {
    name: 'Crimson',
    package: 'crimson',
    command: null,
    category: 'serif',
    webPreview: '"Crimson Text", Garamond, Georgia, serif',
  },
  {
    name: 'Source Serif Pro',
    package: 'sourceserifpro',
    command: null,
    category: 'serif',
    webPreview: '"Source Serif Pro", Georgia, serif',
  },
  // ── Sans-Serif ─────────────────────────────────────────────────────────────
  {
    name: 'Helvetica',
    package: 'helvet',
    command: '\\renewcommand{\\familydefault}{\\sfdefault}',
    category: 'sans-serif',
    webPreview: 'Helvetica, Arial, sans-serif',
  },
  {
    name: 'Avant Garde',
    package: 'avant',
    command: '\\renewcommand{\\familydefault}{\\sfdefault}',
    category: 'sans-serif',
    webPreview: '"Century Gothic", "Avant Garde", Arial, sans-serif',
  },
  {
    name: 'Source Sans Pro',
    package: 'sourcesanspro',
    command: '\\renewcommand{\\familydefault}{\\sfdefault}',
    category: 'sans-serif',
    webPreview: '"Source Sans Pro", Arial, sans-serif',
  },
  {
    name: 'Roboto',
    package: 'roboto',
    command: '\\renewcommand{\\familydefault}{\\sfdefault}',
    category: 'sans-serif',
    webPreview: 'Roboto, Arial, sans-serif',
  },
  {
    name: 'Lato',
    package: 'lato',
    command: '\\renewcommand{\\familydefault}{\\sfdefault}',
    category: 'sans-serif',
    webPreview: 'Lato, Arial, sans-serif',
  },
]

// All known font packages — used to clean up preamble when switching fonts
const KNOWN_FONT_PACKAGES = new Set(
  LATEX_FONTS.map((f) => f.package).filter(Boolean) as string[]
)

// ─── Internal helpers ─────────────────────────────────────────────────────────

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/** Split LaTeX into [preamble, rest] at \begin{document}. */
function splitAtDocument(latex: string): [string, string] {
  const idx = latex.indexOf('\\begin{document}')
  if (idx === -1) return [latex, '']
  return [latex.slice(0, idx), latex.slice(idx)]
}

// ─── Font ─────────────────────────────────────────────────────────────────────

export function extractFontFromPreamble(latex: string): string {
  const [preamble] = splitAtDocument(latex)
  for (const font of LATEX_FONTS) {
    if (!font.package) continue
    const re = new RegExp(
      `\\\\usepackage(?:\\[[^\\]]*\\])?\\{${escapeRegex(font.package)}\\}`
    )
    if (re.test(preamble)) return font.name
  }
  return 'Computer Modern'
}

export function setFontInPreamble(
  latex: string,
  fontPackage: string | null,
  fontCommand: string | null
): string {
  const [preamble, body] = splitAtDocument(latex)

  // Remove all known font package lines and \renewcommand{\familydefault}...
  const filteredLines = preamble.split('\n').filter((line) => {
    const stripped = line.replace(/%.*$/, '').trim()
    for (const pkg of KNOWN_FONT_PACKAGES) {
      if (
        new RegExp(
          `\\\\usepackage(?:\\[[^\\]]*\\])?\\{${escapeRegex(pkg)}\\}`
        ).test(stripped)
      ) {
        return false
      }
    }
    if (/\\renewcommand\{\\familydefault\}\{\\sfdefault\}/.test(stripped)) {
      return false
    }
    return true
  })

  // Insert new font package lines right after \documentclass
  if (fontPackage) {
    const newLines: string[] = [`\\usepackage{${fontPackage}}`]
    if (fontCommand) newLines.push(fontCommand)
    const docIdx = filteredLines.findIndex((l) => /\\documentclass/.test(l))
    if (docIdx !== -1) {
      filteredLines.splice(docIdx + 1, 0, ...newLines)
    } else {
      filteredLines.unshift(...newLines)
    }
  }

  return filteredLines.join('\n') + body
}

// ─── Accent color ─────────────────────────────────────────────────────────────

export function extractAccentColorFromPreamble(latex: string): string | null {
  const [preamble] = splitAtDocument(latex)
  const m = preamble.match(/\\definecolor\{accent\}\{HTML\}\{([A-Fa-f0-9]{6})\}/)
  return m?.[1]?.toUpperCase() ?? null
}

export function setAccentColorInPreamble(latex: string, hexColor: string): string {
  const upper = hexColor.toUpperCase().replace(/^#/, '')
  const newDef = `\\definecolor{accent}{HTML}{${upper}}`
  if (/\\definecolor\{accent\}\{HTML\}\{[A-Fa-f0-9]{6}\}/.test(latex)) {
    return latex.replace(/\\definecolor\{accent\}\{HTML\}\{[A-Fa-f0-9]{6}\}/g, newDef)
  }
  // Not present — add before \begin{document}
  return latex.replace(/(\\begin\{document\})/, `${newDef}\n$1`)
}

export function removeAccentColorFromPreamble(latex: string): string {
  return latex.replace(/\\definecolor\{accent\}\{HTML\}\{[A-Fa-f0-9]{6}\}\n?/g, '')
}

// ─── Font size ────────────────────────────────────────────────────────────────

export function extractFontSizeFromPreamble(
  latex: string
): '10pt' | '11pt' | '12pt' {
  const [preamble] = splitAtDocument(latex)
  const m = preamble.match(/\\documentclass\[([^\]]*)\]/)
  if (!m) return '11pt'
  const pt = m[1]
    .split(',')
    .map((s) => s.trim())
    .find((o) => /^\d+pt$/.test(o))
  if (pt === '10pt' || pt === '11pt' || pt === '12pt') return pt
  return '11pt'
}

export function setFontSizeInPreamble(
  latex: string,
  size: '10pt' | '11pt' | '12pt'
): string {
  // \documentclass[...Xpt...]{...} — replace existing pt (non-greedy to avoid eating leading digit)
  if (/\\documentclass\[[^\]]*\d+pt[^\]]*\]/.test(latex)) {
    return latex.replace(
      /(\\documentclass\[[^\]]*?)\d+pt([^\]]*?\])/,
      `$1${size}$2`
    )
  }
  // \documentclass[...]{...} without pt — prepend size option
  if (/\\documentclass\[[^\]]*\]/.test(latex)) {
    return latex.replace(/(\\documentclass\[)/, `$1${size},`)
  }
  // \documentclass{...} — add brackets
  return latex.replace(/(\\documentclass)\{/, `$1[${size}]{`)
}

// ─── Margins ─────────────────────────────────────────────────────────────────

export function extractMarginsFromPreamble(latex: string): string {
  const [preamble] = splitAtDocument(latex)
  const m = preamble.match(/\\geometry\{margin=([^,}]+)[,}]/)
  if (m) {
    const raw = m[1].trim()
    const val = parseFloat(raw)
    if (!isNaN(val)) {
      if (val <= 0.6) return '0.5in'
      if (val <= 0.875) return '0.75in'
      return '1in'
    }
    return raw
  }
  return '0.75in'
}

export function setMarginsInPreamble(latex: string, margin: string): string {
  const newGeo = `\\geometry{margin=${margin}}`
  if (/\\geometry\{[^}]*\}/.test(latex)) {
    return latex.replace(/\\geometry\{[^}]*\}/, newGeo)
  }
  // Add before \begin{document}
  return latex.replace(/(\\begin\{document\})/, `${newGeo}\n$1`)
}
