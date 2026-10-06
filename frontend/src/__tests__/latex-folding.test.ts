import { describe, expect, it } from 'vitest'
import { buildLatexFoldingRanges } from '@/lib/latex-folding'

describe('LaTeX folding ranges', () => {
  it('folds properly nested environments', () => {
    expect(buildLatexFoldingRanges(String.raw`\begin{document}
\begin{itemize}
\item One
\end{itemize}
\end{document}`)).toEqual([
      { start: 1, end: 5 },
      { start: 2, end: 4 },
    ])
  })

  it('ignores commented tokens and command-like text inside literal environments', () => {
    expect(buildLatexFoldingRanges(String.raw`% \begin{fake}
\begin{verbatim}
\begin{fake}
\end{fake}
\end{verbatim}`)).toEqual([{ start: 2, end: 5 }])
  })

  it('does not pair a mismatched closing environment', () => {
    expect(buildLatexFoldingRanges(String.raw`\begin{one}
text
\end{two}`)).toEqual([])
  })

  it('folds section bodies until the next peer or ancestor', () => {
    expect(buildLatexFoldingRanges(String.raw`\section{One}
text
\subsection{Child}
child text
\section{Two}
last`)).toEqual([
      { start: 1, end: 4 },
      { start: 3, end: 4 },
      { start: 5, end: 6 },
    ])
  })
})
