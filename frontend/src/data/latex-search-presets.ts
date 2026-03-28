export interface LatexSearchPreset {
  label: string
  pattern: string
  isRegex: boolean
  description?: string
  isMultiline?: boolean
}

export const LATEX_SEARCH_PRESETS: LatexSearchPreset[] = [
  {
    label: 'All section headers',
    pattern: '\\\\section\\{([^}]+)\\}',
    isRegex: true,
    description: 'Find all \\section{...} commands',
  },
  {
    label: 'All \\textbf content',
    pattern: '\\\\textbf\\{([^}]+)\\}',
    isRegex: true,
    description: 'Find all bold text',
  },
  {
    label: 'All \\item bullets',
    pattern: '^\\s*\\\\item\\s+(.+)$',
    isRegex: true,
    isMultiline: false,
  },
  {
    label: 'All \\href links',
    pattern: '\\\\href\\{([^}]+)\\}\\{([^}]+)\\}',
    isRegex: true,
  },
  {
    label: 'All dates (Month Year format)',
    pattern: '(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\\.?\\s+\\d{4}',
    isRegex: true,
  },
  {
    label: 'All company names (subsection)',
    pattern: '\\\\resumeSubheading\\{([^}]+)\\}',
    isRegex: true,
  },
]
