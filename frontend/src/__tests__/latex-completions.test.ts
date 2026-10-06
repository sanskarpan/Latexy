import { describe, expect, it } from 'vitest'
import {
  extractCitationKeys,
  extractLatexLabels,
  matchLatexArgumentCompletion,
} from '@/lib/latex-completions'

describe('LaTeX autocomplete parsing', () => {
  it('extracts unique labels while ignoring comments', () => {
    expect(extractLatexLabels(String.raw`
      \label{sec:intro}
      % \label{sec:hidden}
      text \label { fig:one }
      \label{sec:intro}
    `)).toEqual(['sec:intro', 'fig:one'])
  })

  it('combines inline bibitems and BibTeX entry keys without directives', () => {
    expect(extractCitationKeys(
      String.raw`\bibitem[Doe]{inline-key} Paper`,
      String.raw`
        @article{doe2024, title={Paper}}
        @BOOK ( smith-2025, title={Book} )
        @string{journal = "Journal"}
        % @article{hidden, title={Hidden}}
      `,
    )).toEqual(['inline-key', 'doe2024', 'smith-2025'])
  })

  it('matches common natbib and biblatex commands with optional arguments', () => {
    expect(matchLatexArgumentCompletion(String.raw`Text \citep[see][p. 2]{do`)).toMatchObject({
      kind: 'citation',
      partial: 'do',
    })
    expect(matchLatexArgumentCompletion(String.raw`Text \textcite{sm`)).toMatchObject({
      kind: 'citation',
      partial: 'sm',
    })
  })

  it('completes only the final key and tracks earlier multi-cite keys', () => {
    const match = matchLatexArgumentCompletion(String.raw`\cite{doe2024, sm`)
    expect(match).toMatchObject({ kind: 'citation', partial: 'sm' })
    expect(match?.alreadyUsed).toEqual(new Set(['doe2024']))
  })

  it('matches standard and cleveref-style reference commands', () => {
    for (const command of ['ref', 'eqref', 'pageref', 'autoref', 'cref', 'Cref', 'nameref']) {
      expect(matchLatexArgumentCompletion(`\\${command}{sec:`)).toMatchObject({
        kind: 'reference',
        partial: 'sec:',
      })
    }
  })

  it('does not activate outside an unfinished citation or reference argument', () => {
    expect(matchLatexArgumentCompletion(String.raw`\cite{done}`)).toBeNull()
    expect(matchLatexArgumentCompletion(String.raw`plain text`)).toBeNull()
  })
})
