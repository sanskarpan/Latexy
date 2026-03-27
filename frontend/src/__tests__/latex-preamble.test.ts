import { describe, test, expect } from 'vitest'
import {
  extractFontFromPreamble,
  extractFontSizeFromPreamble,
  extractAccentColorFromPreamble,
  extractMarginsFromPreamble,
  setFontInPreamble,
  setFontSizeInPreamble,
  setAccentColorInPreamble,
  removeAccentColorFromPreamble,
  setMarginsInPreamble,
  LATEX_FONTS,
  getInstalledPackages,
  addPackageToPreamble,
  removePackageFromPreamble,
} from '../lib/latex-preamble'

// ─── Helpers ─────────────────────────────────────────────────────────────────

const MINIMAL = '\\documentclass[11pt]{article}\n\\begin{document}\n\\end{document}'
const WITH_TIMES =
  '\\documentclass[11pt]{article}\n\\usepackage{mathptmx}\n\\begin{document}\n\\end{document}'
const WITH_ACCENT =
  '\\documentclass[11pt]{article}\n\\definecolor{accent}{HTML}{FF6B6B}\n\\begin{document}\n\\end{document}'
const WITH_GEOMETRY =
  '\\documentclass[11pt]{article}\n\\usepackage{geometry}\n\\geometry{margin=1in}\n\\begin{document}\n\\end{document}'

// ─── extractFontSizeFromPreamble ──────────────────────────────────────────────

describe('extractFontSizeFromPreamble', () => {
  test('extracts 11pt from document class options', () => {
    expect(extractFontSizeFromPreamble('\\documentclass[11pt]{article}')).toBe('11pt')
  })

  test('extracts 10pt', () => {
    expect(extractFontSizeFromPreamble('\\documentclass[10pt,a4paper]{article}')).toBe('10pt')
  })

  test('extracts 12pt', () => {
    expect(extractFontSizeFromPreamble('\\documentclass[12pt]{article}')).toBe('12pt')
  })

  test('returns 11pt default when no pt option present', () => {
    expect(extractFontSizeFromPreamble('\\documentclass{article}')).toBe('11pt')
  })

  test('returns 11pt default when no documentclass present', () => {
    expect(extractFontSizeFromPreamble('% just a comment')).toBe('11pt')
  })

  test('ignores pt values after \\begin{document}', () => {
    const doc = '\\documentclass{article}\n\\begin{document}\n\\setlength{\\parindent}{12pt}\n\\end{document}'
    expect(extractFontSizeFromPreamble(doc)).toBe('11pt')
  })
})

// ─── setFontSizeInPreamble ────────────────────────────────────────────────────

describe('setFontSizeInPreamble', () => {
  test('replaces existing pt option', () => {
    const result = setFontSizeInPreamble('\\documentclass[11pt]{article}', '12pt')
    expect(result).toContain('[12pt]')
    expect(result).not.toContain('11pt')
  })

  test('adds pt when no options present', () => {
    const result = setFontSizeInPreamble('\\documentclass{article}', '10pt')
    expect(result).toContain('[10pt]')
  })

  test('prepends pt to existing options without pt', () => {
    const result = setFontSizeInPreamble('\\documentclass[a4paper]{article}', '11pt')
    expect(result).toContain('11pt')
    expect(result).toContain('a4paper')
  })

  test('idempotent — applying same size twice does not duplicate', () => {
    const once = setFontSizeInPreamble(MINIMAL, '11pt')
    const twice = setFontSizeInPreamble(once, '11pt')
    const occurrences = (twice.match(/11pt/g) ?? []).length
    expect(occurrences).toBe(1)
  })
})

// ─── extractAccentColorFromPreamble ──────────────────────────────────────────

describe('extractAccentColorFromPreamble', () => {
  test('extracts hex color from \\definecolor{accent}', () => {
    expect(extractAccentColorFromPreamble(WITH_ACCENT)).toBe('FF6B6B')
  })

  test('returns null when no accent color defined', () => {
    expect(extractAccentColorFromPreamble(MINIMAL)).toBeNull()
  })

  test('ignores accent definitions after \\begin{document}', () => {
    const doc = '\\documentclass{article}\n\\begin{document}\n\\definecolor{accent}{HTML}{AABBCC}\n\\end{document}'
    expect(extractAccentColorFromPreamble(doc)).toBeNull()
  })
})

// ─── setAccentColorInPreamble ─────────────────────────────────────────────────

describe('setAccentColorInPreamble', () => {
  test('inserts \\definecolor before \\begin{document} when not present', () => {
    const result = setAccentColorInPreamble(MINIMAL, 'FF6B6B')
    expect(result).toContain('\\definecolor{accent}{HTML}{FF6B6B}')
    expect(result.indexOf('\\definecolor')).toBeLessThan(result.indexOf('\\begin{document}'))
  })

  test('replaces existing accent color', () => {
    const result = setAccentColorInPreamble(WITH_ACCENT, '2563EB')
    expect(result).toContain('\\definecolor{accent}{HTML}{2563EB}')
    expect(result).not.toContain('FF6B6B')
  })

  test('normalizes lowercase hex to uppercase', () => {
    const result = setAccentColorInPreamble(MINIMAL, 'ff6b6b')
    expect(result).toContain('{FF6B6B}')
  })

  test('idempotent — applying same color twice does not duplicate \\definecolor', () => {
    const once = setAccentColorInPreamble(MINIMAL, 'FF6B6B')
    const twice = setAccentColorInPreamble(once, 'FF6B6B')
    const occurrences = (twice.match(/\\definecolor\{accent\}/g) ?? []).length
    expect(occurrences).toBe(1)
  })
})

// ─── removeAccentColorFromPreamble ───────────────────────────────────────────

describe('removeAccentColorFromPreamble', () => {
  test('removes \\definecolor{accent} line', () => {
    const result = removeAccentColorFromPreamble(WITH_ACCENT)
    expect(result).not.toContain('\\definecolor{accent}')
  })

  test('no-op when accent color not present', () => {
    const result = removeAccentColorFromPreamble(MINIMAL)
    expect(result).toBe(MINIMAL)
  })
})

// ─── extractMarginsFromPreamble ───────────────────────────────────────────────

describe('extractMarginsFromPreamble', () => {
  test('extracts margin from \\geometry{margin=1in}', () => {
    expect(extractMarginsFromPreamble(WITH_GEOMETRY)).toBe('1in')
  })

  test('returns default 0.75in when no geometry command', () => {
    expect(extractMarginsFromPreamble(MINIMAL)).toBe('0.75in')
  })

  test('normalizes 0.5in to tight preset', () => {
    const doc = '\\documentclass{article}\n\\geometry{margin=0.5in}\n\\begin{document}\n\\end{document}'
    expect(extractMarginsFromPreamble(doc)).toBe('0.5in')
  })

  test('normalizes 0.7in to 0.75in (nearest preset ≤ 0.875)', () => {
    const doc = '\\documentclass{article}\n\\geometry{margin=0.7in}\n\\begin{document}\n\\end{document}'
    expect(extractMarginsFromPreamble(doc)).toBe('0.75in')
  })
})

// ─── setMarginsInPreamble ─────────────────────────────────────────────────────

describe('setMarginsInPreamble', () => {
  test('replaces existing \\geometry{...}', () => {
    const result = setMarginsInPreamble(WITH_GEOMETRY, '0.5in')
    expect(result).toContain('\\geometry{margin=0.5in}')
    expect(result).not.toContain('margin=1in')
  })

  test('adds \\geometry before \\begin{document} when not present', () => {
    const result = setMarginsInPreamble(MINIMAL, '0.75in')
    expect(result).toContain('\\geometry{margin=0.75in}')
    expect(result.indexOf('\\geometry')).toBeLessThan(result.indexOf('\\begin{document}'))
  })

  test('idempotent — applying same margin twice does not duplicate', () => {
    const once = setMarginsInPreamble(MINIMAL, '0.75in')
    const twice = setMarginsInPreamble(once, '0.75in')
    const occurrences = (twice.match(/\\geometry\{margin=/g) ?? []).length
    expect(occurrences).toBe(1)
  })
})

// ─── extractFontFromPreamble ─────────────────────────────────────────────────

describe('extractFontFromPreamble', () => {
  test('returns Computer Modern when no font package present', () => {
    expect(extractFontFromPreamble(MINIMAL)).toBe('Computer Modern')
  })

  test('detects Times New Roman (mathptmx)', () => {
    expect(extractFontFromPreamble(WITH_TIMES)).toBe('Times New Roman')
  })

  test('detects Palatino', () => {
    const doc = '\\documentclass{article}\n\\usepackage{palatino}\n\\begin{document}\n\\end{document}'
    expect(extractFontFromPreamble(doc)).toBe('Palatino')
  })

  test('detects Helvetica (helvet)', () => {
    const doc = '\\documentclass{article}\n\\usepackage{helvet}\n\\begin{document}\n\\end{document}'
    expect(extractFontFromPreamble(doc)).toBe('Helvetica')
  })
})

// ─── setFontInPreamble ────────────────────────────────────────────────────────

describe('setFontInPreamble', () => {
  test('removes old font package and adds new one', () => {
    const result = setFontInPreamble(WITH_TIMES, 'palatino', null)
    expect(result).toContain('\\usepackage{palatino}')
    expect(result).not.toContain('mathptmx')
  })

  test('sets Computer Modern (null package) by removing existing font packages', () => {
    const result = setFontInPreamble(WITH_TIMES, null, null)
    expect(result).not.toContain('mathptmx')
    expect(result).not.toContain('\\usepackage{palatino}')
  })

  test('adds \\renewcommand for sans-serif fonts', () => {
    const result = setFontInPreamble(MINIMAL, 'helvet', '\\renewcommand{\\familydefault}{\\sfdefault}')
    expect(result).toContain('\\usepackage{helvet}')
    expect(result).toContain('\\renewcommand{\\familydefault}{\\sfdefault}')
  })

  test('removes \\renewcommand when switching to serif font', () => {
    const sansLatex =
      '\\documentclass[11pt]{article}\n\\usepackage{helvet}\n\\renewcommand{\\familydefault}{\\sfdefault}\n\\begin{document}\n\\end{document}'
    const result = setFontInPreamble(sansLatex, 'palatino', null)
    expect(result).not.toContain('\\renewcommand{\\familydefault}{\\sfdefault}')
    expect(result).toContain('\\usepackage{palatino}')
  })

  test('inserts new package after \\documentclass line', () => {
    const result = setFontInPreamble(MINIMAL, 'lmodern', null)
    const docIdx = result.indexOf('\\documentclass')
    const pkgIdx = result.indexOf('\\usepackage{lmodern}')
    expect(pkgIdx).toBeGreaterThan(docIdx)
  })

  test('all LATEX_FONTS with a package can be roundtripped', () => {
    for (const font of LATEX_FONTS) {
      if (!font.package) continue
      const result = setFontInPreamble(MINIMAL, font.package, font.command)
      expect(result).toContain(`\\usepackage{${font.package}}`)
    }
  })
})

// ─── getInstalledPackages ─────────────────────────────────────────────────────

const WITH_THREE_PACKAGES =
  '\\documentclass[11pt]{article}\n\\usepackage{amsmath}\n\\usepackage{geometry}\n\\usepackage[T1]{fontenc}\n\\begin{document}\n\\end{document}'

const WITH_MULTI_PACKAGE =
  '\\documentclass{article}\n\\usepackage{amsmath,amssymb,amsthm}\n\\begin{document}\n\\end{document}'

describe('getInstalledPackages', () => {
  test('returns empty array when no usepackage in preamble', () => {
    expect(getInstalledPackages(MINIMAL)).toEqual([])
  })

  test('returns package names from preamble', () => {
    const pkgs = getInstalledPackages(WITH_THREE_PACKAGES)
    expect(pkgs).toContain('amsmath')
    expect(pkgs).toContain('geometry')
    expect(pkgs).toContain('fontenc')
    expect(pkgs.length).toBe(3)
  })

  test('handles optional arguments — \\usepackage[T1]{fontenc}', () => {
    const pkgs = getInstalledPackages(WITH_THREE_PACKAGES)
    expect(pkgs).toContain('fontenc')
  })

  test('splits comma-separated packages — \\usepackage{a,b,c}', () => {
    const pkgs = getInstalledPackages(WITH_MULTI_PACKAGE)
    expect(pkgs).toContain('amsmath')
    expect(pkgs).toContain('amssymb')
    expect(pkgs).toContain('amsthm')
    expect(pkgs.length).toBe(3)
  })

  test('ignores commented \\usepackage lines (% \\usepackage{foo})', () => {
    const doc =
      '\\documentclass{article}\n% \\usepackage{geometry}\n\\begin{document}\n\\end{document}'
    expect(getInstalledPackages(doc)).toEqual([])
  })

  test('ignores inline comment containing usepackage', () => {
    const doc =
      '\\documentclass{article}\n\\usepackage{amsmath} % \\usepackage{geometry}\n\\begin{document}\n\\end{document}'
    const pkgs = getInstalledPackages(doc)
    expect(pkgs).toContain('amsmath')
    expect(pkgs).not.toContain('geometry')
  })

  test('ignores usepackage calls in document body', () => {
    const doc =
      '\\documentclass{article}\n\\usepackage{geometry}\n\\begin{document}\n\\usepackage{amsmath}\n\\end{document}'
    const pkgs = getInstalledPackages(doc)
    expect(pkgs).toContain('geometry')
    expect(pkgs).not.toContain('amsmath')
  })
})

// ─── addPackageToPreamble ─────────────────────────────────────────────────────

describe('addPackageToPreamble', () => {
  test('adds \\usepackage{amsmath} after existing packages', () => {
    const result = addPackageToPreamble(WITH_GEOMETRY, 'amsmath')
    expect(result).toContain('\\usepackage{amsmath}')
    // Should appear after \usepackage{geometry}
    const geoIdx = result.indexOf('\\usepackage{geometry}')
    const mathIdx = result.indexOf('\\usepackage{amsmath}')
    expect(mathIdx).toBeGreaterThan(geoIdx)
  })

  test('inserts before \\begin{document} when no existing packages', () => {
    const result = addPackageToPreamble(MINIMAL, 'amsmath')
    expect(result).toContain('\\usepackage{amsmath}')
    const pkgIdx = result.indexOf('\\usepackage{amsmath}')
    const docIdx = result.indexOf('\\begin{document}')
    expect(pkgIdx).toBeLessThan(docIdx)
  })

  test('idempotent — adding already-present package returns unchanged latex', () => {
    const once = addPackageToPreamble(MINIMAL, 'amsmath')
    const twice = addPackageToPreamble(once, 'amsmath')
    const occurrences = (twice.match(/\\usepackage\{amsmath\}/g) ?? []).length
    expect(occurrences).toBe(1)
  })

  test('adds package with options when provided', () => {
    const result = addPackageToPreamble(MINIMAL, 'hyperref', 'colorlinks=true')
    expect(result).toContain('\\usepackage[colorlinks=true]{hyperref}')
  })

  test('new package appears before \\begin{document}', () => {
    const result = addPackageToPreamble(MINIMAL, 'xcolor')
    const pkgIdx = result.indexOf('\\usepackage{xcolor}')
    const docIdx = result.indexOf('\\begin{document}')
    expect(pkgIdx).toBeLessThan(docIdx)
    expect(pkgIdx).toBeGreaterThan(-1)
  })
})

// ─── removePackageFromPreamble ────────────────────────────────────────────────

describe('removePackageFromPreamble', () => {
  test('removes \\usepackage{geometry} line', () => {
    const result = removePackageFromPreamble(WITH_GEOMETRY, 'geometry')
    expect(result).not.toContain('\\usepackage{geometry}')
  })

  test('no-op when package not present', () => {
    const result = removePackageFromPreamble(MINIMAL, 'amsmath')
    expect(result).toBe(MINIMAL)
  })

  test('removes package with optional arguments', () => {
    const doc =
      '\\documentclass{article}\n\\usepackage[T1]{fontenc}\n\\begin{document}\n\\end{document}'
    const result = removePackageFromPreamble(doc, 'fontenc')
    expect(result).not.toContain('fontenc')
  })

  test('after remove, getInstalledPackages no longer lists the package', () => {
    const result = removePackageFromPreamble(WITH_THREE_PACKAGES, 'geometry')
    expect(getInstalledPackages(result)).not.toContain('geometry')
  })

  test('add then remove is a no-op (round-trip)', () => {
    const added = addPackageToPreamble(MINIMAL, 'amsmath')
    const removed = removePackageFromPreamble(added, 'amsmath')
    expect(getInstalledPackages(removed)).not.toContain('amsmath')
  })

  test('does not remove usepackage-like text in document body', () => {
    const doc =
      '\\documentclass{article}\n\\usepackage{geometry}\n\\begin{document}\n\\texttt{\\\\usepackage{geometry}}\n\\end{document}'
    const result = removePackageFromPreamble(doc, 'geometry')
    // Package removed from preamble
    expect(getInstalledPackages(result)).not.toContain('geometry')
    // Body text preserved unchanged
    expect(result).toContain('\\texttt{\\\\usepackage{geometry}}')
  })
})
