import { describe, expect, it } from 'vitest'
import { buildLatexOutline } from '@/lib/latex-outline'

describe('LaTeX document outline', () => {
  it('builds an ordered hierarchy with exact source lines', () => {
    expect(buildLatexOutline(String.raw`\part{One}
\chapter*{Two}
\section{Three}
\subsection{Four}
\paragraph{Five}`)).toEqual([
      { command: 'part', level: 0, label: 'One', line: 1 },
      { command: 'chapter', level: 1, label: 'Two', line: 2 },
      { command: 'section', level: 2, label: 'Three', line: 3 },
      { command: 'subsection', level: 3, label: 'Four', line: 4 },
      { command: 'paragraph', level: 5, label: 'Five', line: 5 },
    ])
  })

  it('supports optional and multiline balanced titles', () => {
    expect(buildLatexOutline(String.raw`\section[Short]{A {nested}
title}
\subparagraph{}`)).toEqual([
      { command: 'section', level: 2, label: 'A {nested} title', line: 1 },
      { command: 'subparagraph', level: 6, label: 'Untitled section', line: 3 },
    ])
  })

  it('unwraps common formatting commands in displayed titles', () => {
    expect(buildLatexOutline(String.raw`\section{An \textbf{Important} Result}`)[0].label)
      .toBe('An Important Result')
  })

  it('ignores comments and literal code environments while preserving escaped percent', () => {
    expect(buildLatexOutline(String.raw`% \section{Hidden}
\section{Visible \% result} % \subsection{Also hidden}
\begin{verbatim}
\chapter{Code only}
\end{verbatim}
\section{Last}`)).toEqual([
      { command: 'section', level: 2, label: String.raw`Visible \% result`, line: 2 },
      { command: 'section', level: 2, label: 'Last', line: 6 },
    ])
  })

  it('skips malformed commands without hiding later valid sections', () => {
    expect(buildLatexOutline(String.raw`\section missing
\section{Valid}`)).toEqual([
      { command: 'section', level: 2, label: 'Valid', line: 2 },
    ])
  })
})
