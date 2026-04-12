export interface LaTeXDoc {
  command: string
  signature: string
  description: string
  parameters: Array<{ name: string; required: boolean; description: string }>
  examples: Array<{ code: string; description: string }>
  packages: string[]
  seealso: string[]
  category: 'formatting' | 'sectioning' | 'math' | 'environments' | 'spacing' | 'graphics' | 'misc'
}

export const LATEX_DOCS: LaTeXDoc[] = [
  // ── FORMATTING ──────────────────────────────────────────────────────────
  {
    command: '\\textbf',
    signature: '\\textbf{text}',
    description: 'Renders text in bold weight. Works in text mode and can be nested with other font commands.',
    parameters: [{ name: 'text', required: true, description: 'The text to render in bold' }],
    examples: [
      { code: '\\textbf{Important:} Read carefully.', description: 'Bold a word or phrase' },
      { code: 'This is \\textbf{very} important.', description: 'Bold inline within a sentence' },
    ],
    packages: [],
    seealso: ['\\textit', '\\emph', '\\textsc'],
    category: 'formatting',
  },
  {
    command: '\\textit',
    signature: '\\textit{text}',
    description: 'Renders text in italic. Prefer \\emph for semantic emphasis as it toggles based on context.',
    parameters: [{ name: 'text', required: true, description: 'The text to italicize' }],
    examples: [
      { code: '\\textit{This is italic text.}', description: 'Basic italic usage' },
      { code: 'The term \\textit{in situ} is Latin.', description: 'Italic for foreign phrases' },
    ],
    packages: [],
    seealso: ['\\emph', '\\textbf', '\\textsl'],
    category: 'formatting',
  },
  {
    command: '\\texttt',
    signature: '\\texttt{text}',
    description: 'Renders text in a typewriter (monospace) font. Useful for code, filenames, or commands.',
    parameters: [{ name: 'text', required: true, description: 'The text to render in monospace' }],
    examples: [
      { code: 'Run \\texttt{make install} in the terminal.', description: 'Inline command reference' },
      { code: 'Edit the file \\texttt{config.json}.', description: 'Filename in monospace' },
    ],
    packages: [],
    seealso: ['\\verb', '\\textbf', '\\textrm'],
    category: 'formatting',
  },
  {
    command: '\\emph',
    signature: '\\emph{text}',
    description: 'Semantic emphasis. In normal text it italicizes; inside italic text it switches back to upright. Use this instead of \\textit for semantic emphasis.',
    parameters: [{ name: 'text', required: true, description: 'The text to emphasize' }],
    examples: [
      { code: 'This is \\emph{very important}.', description: 'Standard emphasis' },
      { code: '\\textit{Italics with \\emph{upright} emphasis inside.}', description: 'Toggle behavior inside italic context' },
    ],
    packages: [],
    seealso: ['\\textit', '\\textbf'],
    category: 'formatting',
  },
  {
    command: '\\textsc',
    signature: '\\textsc{text}',
    description: 'Renders text in small capitals. Uppercase letters are full size; lowercase letters appear as smaller capitals.',
    parameters: [{ name: 'text', required: true, description: 'The text to render in small caps' }],
    examples: [
      { code: '\\textsc{John Smith}', description: 'Name in small caps (common in resumes)' },
      { code: 'Published in \\textsc{Nature}.', description: 'Journal name in small caps' },
    ],
    packages: [],
    seealso: ['\\textbf', '\\textrm'],
    category: 'formatting',
  },
  {
    command: '\\textrm',
    signature: '\\textrm{text}',
    description: 'Renders text in the roman (serif) font family regardless of the current font. Useful to switch back inside a sans-serif environment.',
    parameters: [{ name: 'text', required: true, description: 'The text to render in roman font' }],
    examples: [
      { code: '\\textrm{Normal roman text}', description: 'Force roman font' },
    ],
    packages: [],
    seealso: ['\\textsf', '\\texttt'],
    category: 'formatting',
  },
  {
    command: '\\textsf',
    signature: '\\textsf{text}',
    description: 'Renders text in the sans-serif font family. Clean and modern look for headings or labels.',
    parameters: [{ name: 'text', required: true, description: 'The text to render in sans-serif' }],
    examples: [
      { code: '\\textsf{Section Header}', description: 'Sans-serif label' },
    ],
    packages: [],
    seealso: ['\\textrm', '\\texttt'],
    category: 'formatting',
  },
  {
    command: '\\underline',
    signature: '\\underline{text}',
    description: 'Underlines text. Note this does not break across lines; use the ulem package for linebreaking underlines.',
    parameters: [{ name: 'text', required: true, description: 'The text to underline' }],
    examples: [
      { code: '\\underline{Key term}', description: 'Underlined term' },
      { code: '\\underline{Important notice}', description: 'Underline for emphasis' },
    ],
    packages: [],
    seealso: ['\\textbf', '\\emph'],
    category: 'formatting',
  },
  {
    command: '\\small',
    signature: '{\\small text}',
    description: 'Switches to a smaller font size than the current normal size. Must be used inside a group or environment.',
    parameters: [],
    examples: [
      { code: '{\\small This text is smaller.}', description: 'Small text inside braces' },
      { code: '\\begin{quote}\n{\\small A footnote-like note.}\n\\end{quote}', description: 'Small text inside an environment' },
    ],
    packages: [],
    seealso: ['\\footnotesize', '\\normalsize', '\\tiny'],
    category: 'formatting',
  },
  {
    command: '\\large',
    signature: '{\\large text}',
    description: 'Switches to a font size one step larger than \\normalsize.',
    parameters: [],
    examples: [
      { code: '{\\large Larger text}', description: 'Slightly enlarged text' },
    ],
    packages: [],
    seealso: ['\\Large', '\\LARGE', '\\huge'],
    category: 'formatting',
  },
  {
    command: '\\Large',
    signature: '{\\Large text}',
    description: 'Switches to a font size two steps larger than \\normalsize.',
    parameters: [],
    examples: [
      { code: '{\\Large Section title}', description: 'Larger section heading' },
    ],
    packages: [],
    seealso: ['\\large', '\\LARGE'],
    category: 'formatting',
  },
  {
    command: '\\LARGE',
    signature: '{\\LARGE text}',
    description: 'Switches to a font size three steps larger than \\normalsize.',
    parameters: [],
    examples: [
      { code: '{\\LARGE Document Title}', description: 'Very large document title' },
    ],
    packages: [],
    seealso: ['\\Large', '\\huge'],
    category: 'formatting',
  },
  {
    command: '\\huge',
    signature: '{\\huge text}',
    description: 'Switches to a very large font size, four steps above \\normalsize.',
    parameters: [],
    examples: [
      { code: '{\\huge Cover Page Title}', description: 'Huge cover title' },
    ],
    packages: [],
    seealso: ['\\LARGE', '\\Huge'],
    category: 'formatting',
  },
  {
    command: '\\Huge',
    signature: '{\\Huge text}',
    description: 'The largest standard font size command in LaTeX, five steps above \\normalsize.',
    parameters: [],
    examples: [
      { code: '{\\Huge TITLE}', description: 'Maximum standard font size' },
    ],
    packages: [],
    seealso: ['\\huge', '\\LARGE'],
    category: 'formatting',
  },
  {
    command: '\\normalsize',
    signature: '{\\normalsize text}',
    description: 'Switches to the normal (default) font size defined by the document class.',
    parameters: [],
    examples: [
      { code: '{\\normalsize Back to normal size}', description: 'Reset to document default size' },
    ],
    packages: [],
    seealso: ['\\small', '\\large'],
    category: 'formatting',
  },
  {
    command: '\\footnotesize',
    signature: '{\\footnotesize text}',
    description: 'Font size used in footnotes — slightly smaller than \\small.',
    parameters: [],
    examples: [
      { code: '{\\footnotesize See also reference [1].}', description: 'Small note text' },
    ],
    packages: [],
    seealso: ['\\small', '\\tiny'],
    category: 'formatting',
  },
  {
    command: '\\tiny',
    signature: '{\\tiny text}',
    description: 'The smallest standard font size in LaTeX. Use sparingly.',
    parameters: [],
    examples: [
      { code: '{\\tiny Fine print goes here.}', description: 'Very small disclaimer text' },
    ],
    packages: [],
    seealso: ['\\footnotesize', '\\scriptsize'],
    category: 'formatting',
  },
  {
    command: '\\textcolor',
    signature: '\\textcolor{color}{text}',
    description: 'Renders text in the specified color. Requires the xcolor (or color) package.',
    parameters: [
      { name: 'color', required: true, description: 'Color name or specification (e.g., red, blue, orange)' },
      { name: 'text', required: true, description: 'The text to colorize' },
    ],
    examples: [
      { code: '\\textcolor{red}{Warning!}', description: 'Red warning text' },
      { code: '\\textcolor{blue}{Click here}', description: 'Blue link-like text' },
    ],
    packages: ['xcolor'],
    seealso: ['\\colorbox', '\\color'],
    category: 'formatting',
  },

  // ── SECTIONING ──────────────────────────────────────────────────────────
  {
    command: '\\part',
    signature: '\\part[short title]{title}',
    description: 'Creates a top-level part heading. Available in book and report classes.',
    parameters: [
      { name: 'short title', required: false, description: 'Short title for table of contents' },
      { name: 'title', required: true, description: 'The full part title' },
    ],
    examples: [
      { code: '\\part{Introduction}', description: 'A part heading' },
      { code: '\\part[Intro]{Introduction to the Topic}', description: 'Part with short TOC title' },
    ],
    packages: [],
    seealso: ['\\chapter', '\\section'],
    category: 'sectioning',
  },
  {
    command: '\\chapter',
    signature: '\\chapter[short title]{title}',
    description: 'Creates a chapter heading. Available in book and report document classes (not article).',
    parameters: [
      { name: 'short title', required: false, description: 'Short title for table of contents and running headers' },
      { name: 'title', required: true, description: 'The chapter title' },
    ],
    examples: [
      { code: '\\chapter{Getting Started}', description: 'A chapter heading' },
      { code: '\\chapter[Setup]{Setting Up Your Environment}', description: 'Chapter with short TOC title' },
    ],
    packages: [],
    seealso: ['\\section', '\\part'],
    category: 'sectioning',
  },
  {
    command: '\\section',
    signature: '\\section[short title]{title}',
    description: 'Creates a numbered section. One of the most common structural commands. Use \\section* for unnumbered.',
    parameters: [
      { name: 'short title', required: false, description: 'Short title for the table of contents' },
      { name: 'title', required: true, description: 'The section title' },
    ],
    examples: [
      { code: '\\section{Methods}', description: 'A standard numbered section' },
      { code: '\\section*{Abstract}', description: 'Unnumbered section (no * variant in TOC by default)' },
      { code: '\\section[Results]{Experimental Results}', description: 'Custom short TOC label' },
    ],
    packages: [],
    seealso: ['\\subsection', '\\chapter', '\\tableofcontents'],
    category: 'sectioning',
  },
  {
    command: '\\subsection',
    signature: '\\subsection[short title]{title}',
    description: 'Creates a numbered subsection, nested under \\section.',
    parameters: [
      { name: 'short title', required: false, description: 'Short title for table of contents' },
      { name: 'title', required: true, description: 'The subsection title' },
    ],
    examples: [
      { code: '\\subsection{Data Collection}', description: 'A subsection' },
      { code: '\\subsection*{Note}', description: 'Unnumbered subsection' },
    ],
    packages: [],
    seealso: ['\\section', '\\subsubsection'],
    category: 'sectioning',
  },
  {
    command: '\\subsubsection',
    signature: '\\subsubsection[short title]{title}',
    description: 'Creates a third-level heading within a subsection. In article class, this is the deepest numbered heading by default.',
    parameters: [
      { name: 'short title', required: false, description: 'Short title for table of contents' },
      { name: 'title', required: true, description: 'The subsubsection title' },
    ],
    examples: [
      { code: '\\subsubsection{Implementation Details}', description: 'A third-level heading' },
    ],
    packages: [],
    seealso: ['\\subsection', '\\paragraph'],
    category: 'sectioning',
  },
  {
    command: '\\paragraph',
    signature: '\\paragraph[short title]{title}',
    description: 'Creates a run-in heading (inline with text). No vertical spacing is added before the following text.',
    parameters: [
      { name: 'short title', required: false, description: 'Short title for TOC (if included)' },
      { name: 'title', required: true, description: 'The paragraph heading' },
    ],
    examples: [
      { code: '\\paragraph{Note.} This is a noted paragraph.', description: 'Run-in paragraph heading' },
    ],
    packages: [],
    seealso: ['\\subsubsection', '\\subparagraph'],
    category: 'sectioning',
  },
  {
    command: '\\maketitle',
    signature: '\\maketitle',
    description: 'Generates a title block using \\title, \\author, and \\date defined in the preamble.',
    parameters: [],
    examples: [
      {
        code: '\\title{My Document}\n\\author{Jane Doe}\n\\date{\\today}\n\\begin{document}\n\\maketitle',
        description: 'Standard title block',
      },
    ],
    packages: [],
    seealso: ['\\title', '\\author', '\\date'],
    category: 'sectioning',
  },
  {
    command: '\\tableofcontents',
    signature: '\\tableofcontents',
    description: 'Generates a table of contents from all sectioning commands. Requires two compilation passes.',
    parameters: [],
    examples: [
      { code: '\\tableofcontents\n\\newpage', description: 'TOC followed by a page break' },
    ],
    packages: [],
    seealso: ['\\section', '\\listoffigures'],
    category: 'sectioning',
  },

  // ── ENVIRONMENTS ─────────────────────────────────────────────────────────
  {
    command: '\\begin{itemize}',
    signature: '\\begin{itemize}\n  \\item text\n\\end{itemize}',
    description: 'An unordered (bulleted) list. Each list item begins with \\item.',
    parameters: [],
    examples: [
      {
        code: '\\begin{itemize}\n  \\item First item\n  \\item Second item\n\\end{itemize}',
        description: 'Simple bullet list',
      },
    ],
    packages: [],
    seealso: ['\\begin{enumerate}', '\\item'],
    category: 'environments',
  },
  {
    command: '\\begin{enumerate}',
    signature: '\\begin{enumerate}\n  \\item text\n\\end{enumerate}',
    description: 'An ordered (numbered) list. Each item begins with \\item. Use the enumitem package for customization.',
    parameters: [],
    examples: [
      {
        code: '\\begin{enumerate}\n  \\item Step one\n  \\item Step two\n\\end{enumerate}',
        description: 'Numbered list',
      },
    ],
    packages: [],
    seealso: ['\\begin{itemize}', '\\item'],
    category: 'environments',
  },
  {
    command: '\\begin{tabular}',
    signature: '\\begin{tabular}{cols}\n  row1 \\\\\n  row2 \\\\\n\\end{tabular}',
    description: 'Creates a table. The column spec (e.g., {lcc}) defines alignment: l=left, c=center, r=right, | for vertical lines.',
    parameters: [
      { name: 'cols', required: true, description: 'Column specification string (e.g., l c r or |l|c|r|)' },
    ],
    examples: [
      {
        code: '\\begin{tabular}{lcc}\n  Name & Age & Score \\\\\n  \\hline\n  Alice & 30 & 95 \\\\\n  Bob   & 25 & 88 \\\\\n\\end{tabular}',
        description: 'Simple table with header',
      },
    ],
    packages: [],
    seealso: ['\\hline', '\\multicolumn', '\\begin{table}'],
    category: 'environments',
  },
  {
    command: '\\begin{figure}',
    signature: '\\begin{figure}[placement]\n  \\includegraphics{file}\n  \\caption{caption}\n\\end{figure}',
    description: 'A floating figure environment. LaTeX places it automatically. Placement options: h=here, t=top, b=bottom, p=page.',
    parameters: [
      { name: 'placement', required: false, description: 'Placement specifier: h, t, b, p, or combinations like [htbp]' },
    ],
    examples: [
      {
        code: '\\begin{figure}[htbp]\n  \\centering\n  \\includegraphics[width=0.8\\linewidth]{diagram}\n  \\caption{Architecture diagram.}\n  \\label{fig:arch}\n\\end{figure}',
        description: 'Standard figure with caption and label',
      },
    ],
    packages: ['graphicx'],
    seealso: ['\\includegraphics', '\\caption', '\\label'],
    category: 'environments',
  },
  {
    command: '\\begin{equation}',
    signature: '\\begin{equation}\n  formula\n\\end{equation}',
    description: 'A displayed, numbered equation. Use \\begin{equation*} for unnumbered. Equivalent to \\[ ... \\] but auto-numbered.',
    parameters: [],
    examples: [
      {
        code: '\\begin{equation}\n  E = mc^2\n\\end{equation}',
        description: 'Einstein\'s equation, numbered',
      },
      {
        code: '\\begin{equation*}\n  \\frac{d}{dx} x^n = n x^{n-1}\n\\end{equation*}',
        description: 'Unnumbered equation',
      },
    ],
    packages: [],
    seealso: ['\\begin{align}', '\\frac', '\\sum'],
    category: 'environments',
  },
  {
    command: '\\begin{align}',
    signature: '\\begin{align}\n  lhs &= rhs \\\\\n  lhs &= rhs\n\\end{align}',
    description: 'Multi-line aligned equations from the amsmath package. Use & as the alignment anchor. Use align* for unnumbered.',
    parameters: [],
    examples: [
      {
        code: '\\begin{align}\n  f(x) &= x^2 + 2x + 1 \\\\\n       &= (x+1)^2\n\\end{align}',
        description: 'Two-line aligned derivation',
      },
    ],
    packages: ['amsmath'],
    seealso: ['\\begin{equation}', '\\frac'],
    category: 'environments',
  },
  {
    command: '\\begin{center}',
    signature: '\\begin{center}\n  content\n\\end{center}',
    description: 'Centers all content horizontally. Adds vertical space above and below. Use \\centering inside figure/table instead.',
    parameters: [],
    examples: [
      { code: '\\begin{center}\n  \\textbf{Centered Title}\n\\end{center}', description: 'Centered bold title' },
    ],
    packages: [],
    seealso: ['\\centering', '\\begin{figure}'],
    category: 'environments',
  },
  {
    command: '\\begin{minipage}',
    signature: '\\begin{minipage}[pos]{width}\n  content\n\\end{minipage}',
    description: 'Creates a miniature page within the current line. Useful for side-by-side content without the figure float mechanism.',
    parameters: [
      { name: 'pos', required: false, description: 'Vertical alignment: t (top), c (center), b (bottom)' },
      { name: 'width', required: true, description: 'Width of the minipage (e.g., 0.45\\linewidth)' },
    ],
    examples: [
      {
        code: '\\begin{minipage}{0.45\\linewidth}\n  Left column content\n\\end{minipage}\\hfill\n\\begin{minipage}{0.45\\linewidth}\n  Right column content\n\\end{minipage}',
        description: 'Two columns using minipages',
      },
    ],
    packages: [],
    seealso: ['\\hfill', '\\begin{figure}'],
    category: 'environments',
  },
  {
    command: '\\begin{verbatim}',
    signature: '\\begin{verbatim}\n  raw text\n\\end{verbatim}',
    description: 'Displays text verbatim (as-is), in monospace, without interpreting LaTeX commands. Good for code samples.',
    parameters: [],
    examples: [
      {
        code: '\\begin{verbatim}\ndef hello():\n    print("Hello, world!")\n\\end{verbatim}',
        description: 'Python code block verbatim',
      },
    ],
    packages: [],
    seealso: ['\\verb', '\\texttt'],
    category: 'environments',
  },

  // ── SPACING ──────────────────────────────────────────────────────────────
  {
    command: '\\vspace',
    signature: '\\vspace{length}',
    description: 'Inserts vertical space of the given length. Negative values reduce spacing. Use \\vspace* to force at page top/bottom.',
    parameters: [{ name: 'length', required: true, description: 'Vertical distance (e.g., 1cm, 2ex, -0.5em)' }],
    examples: [
      { code: '\\vspace{1cm}', description: '1 cm of vertical space' },
      { code: '\\vspace*{-5mm}', description: 'Reduce spacing by 5 mm (forced)' },
    ],
    packages: [],
    seealso: ['\\hspace', '\\bigskip', '\\vfill'],
    category: 'spacing',
  },
  {
    command: '\\hspace',
    signature: '\\hspace{length}',
    description: 'Inserts horizontal space. \\hspace* preserves the space even at line boundaries.',
    parameters: [{ name: 'length', required: true, description: 'Horizontal distance (e.g., 1em, 0.5cm)' }],
    examples: [
      { code: 'Name:\\hspace{2cm}Date:', description: 'Manual field spacing' },
      { code: 'Column A\\hspace*{1in}Column B', description: 'Force spacing across a line break' },
    ],
    packages: [],
    seealso: ['\\vspace', '\\hfill'],
    category: 'spacing',
  },
  {
    command: '\\newline',
    signature: '\\newline',
    description: 'Forces a line break within a paragraph without starting a new paragraph. Similar to \\\\.',
    parameters: [],
    examples: [
      { code: 'Line one\\newlineLine two', description: 'Break within a paragraph' },
    ],
    packages: [],
    seealso: ['\\newpage', '\\par'],
    category: 'spacing',
  },
  {
    command: '\\newpage',
    signature: '\\newpage',
    description: 'Ends the current page and starts a new one. Also flushes any pending floats in two-column mode.',
    parameters: [],
    examples: [
      { code: '\\chapter{Introduction}\n\\newpage\n\\chapter{Methods}', description: 'Force each chapter on a new page' },
    ],
    packages: [],
    seealso: ['\\clearpage', '\\pagebreak'],
    category: 'spacing',
  },
  {
    command: '\\clearpage',
    signature: '\\clearpage',
    description: 'Ends the current page and outputs all pending floats (figures, tables) before starting a new page.',
    parameters: [],
    examples: [
      { code: '\\clearpage', description: 'Flush all floats and start a new page' },
    ],
    packages: [],
    seealso: ['\\newpage', '\\cleardoublepage'],
    category: 'spacing',
  },
  {
    command: '\\noindent',
    signature: '\\noindent',
    description: 'Suppresses paragraph indentation for the immediately following paragraph.',
    parameters: [],
    examples: [
      { code: '\\noindent This paragraph has no indent.', description: 'No indent on the first paragraph' },
    ],
    packages: [],
    seealso: ['\\indent', '\\par'],
    category: 'spacing',
  },
  {
    command: '\\par',
    signature: '\\par',
    description: 'Explicitly ends a paragraph. Usually an empty line is preferred, but \\par is useful inside macros.',
    parameters: [],
    examples: [
      { code: 'First paragraph.\\par Second paragraph.', description: 'Explicit paragraph break' },
    ],
    packages: [],
    seealso: ['\\noindent', '\\newline'],
    category: 'spacing',
  },
  {
    command: '\\medskip',
    signature: '\\medskip',
    description: 'Inserts a medium amount of vertical space (approximately 6pt plus or minus 2pt).',
    parameters: [],
    examples: [
      { code: 'Paragraph one.\\medskip\nParagraph two.', description: 'Medium gap between paragraphs' },
    ],
    packages: [],
    seealso: ['\\bigskip', '\\smallskip', '\\vspace'],
    category: 'spacing',
  },
  {
    command: '\\bigskip',
    signature: '\\bigskip',
    description: 'Inserts a big amount of vertical space (approximately 12pt plus or minus 4pt).',
    parameters: [],
    examples: [
      { code: 'Section end.\\bigskip\nNext section starts.', description: 'Large vertical gap' },
    ],
    packages: [],
    seealso: ['\\medskip', '\\smallskip'],
    category: 'spacing',
  },
  {
    command: '\\smallskip',
    signature: '\\smallskip',
    description: 'Inserts a small amount of vertical space (approximately 3pt plus or minus 1pt).',
    parameters: [],
    examples: [
      { code: 'Item A.\\smallskip\nItem B.', description: 'Small gap between items' },
    ],
    packages: [],
    seealso: ['\\medskip', '\\bigskip'],
    category: 'spacing',
  },
  {
    command: '\\vfill',
    signature: '\\vfill',
    description: 'Inserts infinitely stretchable vertical space that fills all available vertical room. Useful for centering content on a page.',
    parameters: [],
    examples: [
      { code: '\\vfill\n\\begin{center}Centered vertically\\end{center}\n\\vfill', description: 'Vertically centered content' },
    ],
    packages: [],
    seealso: ['\\hfill', '\\vspace'],
    category: 'spacing',
  },
  {
    command: '\\hfill',
    signature: '\\hfill',
    description: 'Inserts infinitely stretchable horizontal space. Useful for pushing content to the right margin.',
    parameters: [],
    examples: [
      { code: 'Name \\hfill Date', description: 'Push date to right margin' },
      { code: '\\hfill \\textbf{Page \\thepage}', description: 'Right-align page number' },
    ],
    packages: [],
    seealso: ['\\vfill', '\\hspace'],
    category: 'spacing',
  },

  // ── MATH ────────────────────────────────────────────────────────────────
  {
    command: '\\frac',
    signature: '\\frac{numerator}{denominator}',
    description: 'Renders a fraction. Must be used in math mode. \\dfrac forces display-style fraction; \\tfrac forces text-style.',
    parameters: [
      { name: 'numerator', required: true, description: 'The top of the fraction' },
      { name: 'denominator', required: true, description: 'The bottom of the fraction' },
    ],
    examples: [
      { code: '$\\frac{1}{2}$', description: 'One half inline' },
      { code: '\\[ \\frac{x^2 + 1}{x - 3} \\]', description: 'Rational expression in display mode' },
    ],
    packages: [],
    seealso: ['\\sqrt', '\\begin{equation}'],
    category: 'math',
  },
  {
    command: '\\sqrt',
    signature: '\\sqrt[n]{expression}',
    description: 'Renders a square root (or nth root when the optional argument is provided). Must be in math mode.',
    parameters: [
      { name: 'n', required: false, description: 'Root degree (e.g., 3 for cube root)' },
      { name: 'expression', required: true, description: 'The expression under the radical' },
    ],
    examples: [
      { code: '$\\sqrt{x^2 + y^2}$', description: 'Square root' },
      { code: '$\\sqrt[3]{8} = 2$', description: 'Cube root' },
    ],
    packages: [],
    seealso: ['\\frac', '\\sum'],
    category: 'math',
  },
  {
    command: '\\sum',
    signature: '\\sum_{lower}^{upper}',
    description: 'Summation symbol. Subscript sets the lower bound; superscript sets the upper bound.',
    parameters: [
      { name: 'lower', required: false, description: 'Lower bound (subscript), e.g., i=1' },
      { name: 'upper', required: false, description: 'Upper bound (superscript), e.g., n' },
    ],
    examples: [
      { code: '$\\sum_{i=1}^{n} i = \\frac{n(n+1)}{2}$', description: 'Sum of first n integers' },
    ],
    packages: [],
    seealso: ['\\prod', '\\int', '\\lim'],
    category: 'math',
  },
  {
    command: '\\int',
    signature: '\\int_{lower}^{upper}',
    description: 'Integral symbol. Use \\iint for double integral, \\iiint for triple, \\oint for contour integral.',
    parameters: [
      { name: 'lower', required: false, description: 'Lower bound of integration' },
      { name: 'upper', required: false, description: 'Upper bound of integration' },
    ],
    examples: [
      { code: '$\\int_0^1 x^2\\,dx = \\frac{1}{3}$', description: 'Definite integral from 0 to 1' },
      { code: '$\\int_{-\\infty}^{\\infty} e^{-x^2}\\,dx = \\sqrt{\\pi}$', description: 'Gaussian integral' },
    ],
    packages: [],
    seealso: ['\\sum', '\\prod', '\\frac'],
    category: 'math',
  },
  {
    command: '\\prod',
    signature: '\\prod_{lower}^{upper}',
    description: 'Product symbol (large Pi). Analogous to \\sum but for products.',
    parameters: [
      { name: 'lower', required: false, description: 'Lower bound' },
      { name: 'upper', required: false, description: 'Upper bound' },
    ],
    examples: [
      { code: '$\\prod_{i=1}^{n} i = n!$', description: 'Product equals n factorial' },
    ],
    packages: [],
    seealso: ['\\sum', '\\int'],
    category: 'math',
  },
  {
    command: '\\lim',
    signature: '\\lim_{x \\to a}',
    description: 'Limit operator. The subscript specifies the limiting variable and value.',
    parameters: [],
    examples: [
      { code: '$\\lim_{x \\to 0} \\frac{\\sin x}{x} = 1$', description: 'Sinc limit' },
      { code: '$\\lim_{n \\to \\infty} \\left(1 + \\frac{1}{n}\\right)^n = e$', description: 'Definition of e' },
    ],
    packages: [],
    seealso: ['\\sum', '\\infty'],
    category: 'math',
  },
  {
    command: '\\infty',
    signature: '\\infty',
    description: 'Renders the infinity symbol ∞. Must be in math mode.',
    parameters: [],
    examples: [
      { code: '$x \\to \\infty$', description: 'x approaching infinity' },
    ],
    packages: [],
    seealso: ['\\lim', '\\sum'],
    category: 'math',
  },
  {
    command: '\\alpha',
    signature: '\\alpha',
    description: 'Greek lowercase letter alpha (α). Must be in math mode.',
    parameters: [],
    examples: [
      { code: '$\\alpha + \\beta = \\gamma$', description: 'Greek letters in equation' },
    ],
    packages: [],
    seealso: ['\\beta', '\\gamma', '\\theta'],
    category: 'math',
  },
  {
    command: '\\beta',
    signature: '\\beta',
    description: 'Greek lowercase letter beta (β). Must be in math mode.',
    parameters: [],
    examples: [
      { code: '$\\beta$-distribution', description: 'Beta distribution reference' },
    ],
    packages: [],
    seealso: ['\\alpha', '\\gamma'],
    category: 'math',
  },
  {
    command: '\\pi',
    signature: '\\pi',
    description: 'Greek lowercase letter pi (π), representing the mathematical constant 3.14159… Must be in math mode.',
    parameters: [],
    examples: [
      { code: '$A = \\pi r^2$', description: 'Area of a circle' },
    ],
    packages: [],
    seealso: ['\\sigma', '\\theta'],
    category: 'math',
  },
  {
    command: '\\sigma',
    signature: '\\sigma',
    description: 'Greek lowercase letter sigma (σ). Commonly used for standard deviation or summation. Must be in math mode.',
    parameters: [],
    examples: [
      { code: '$\\sigma^2$', description: 'Variance notation' },
    ],
    packages: [],
    seealso: ['\\mu', '\\pi'],
    category: 'math',
  },
  {
    command: '\\delta',
    signature: '\\delta',
    description: 'Greek lowercase letter delta (δ). Commonly used for small change or Dirac delta. Must be in math mode.',
    parameters: [],
    examples: [
      { code: '$\\delta x$', description: 'Small change in x' },
    ],
    packages: [],
    seealso: ['\\Delta', '\\epsilon'],
    category: 'math',
  },
  {
    command: '\\theta',
    signature: '\\theta',
    description: 'Greek lowercase letter theta (θ). Commonly used in trigonometry and statistics. Must be in math mode.',
    parameters: [],
    examples: [
      { code: '$\\cos(\\theta)$', description: 'Cosine of theta' },
    ],
    packages: [],
    seealso: ['\\phi', '\\pi'],
    category: 'math',
  },
  {
    command: '\\lambda',
    signature: '\\lambda',
    description: 'Greek lowercase letter lambda (λ). Used in eigenvalue problems, wavelength notation, and lambda calculus. Must be in math mode.',
    parameters: [],
    examples: [
      { code: '$A\\mathbf{v} = \\lambda\\mathbf{v}$', description: 'Eigenvalue equation' },
    ],
    packages: [],
    seealso: ['\\mu', '\\sigma'],
    category: 'math',
  },
  {
    command: '\\mu',
    signature: '\\mu',
    description: 'Greek lowercase letter mu (μ). Used for mean, magnetic permeability, and micro prefix. Must be in math mode.',
    parameters: [],
    examples: [
      { code: '$\\mu = \\frac{1}{n}\\sum_{i=1}^n x_i$', description: 'Sample mean formula' },
    ],
    packages: [],
    seealso: ['\\sigma', '\\lambda'],
    category: 'math',
  },
  {
    command: '\\gamma',
    signature: '\\gamma',
    description: 'Greek lowercase letter gamma (γ). Used in physics (Lorentz factor), statistics (gamma distribution), and more. Must be in math mode.',
    parameters: [],
    examples: [
      { code: '$\\gamma = \\frac{1}{\\sqrt{1 - v^2/c^2}}$', description: 'Lorentz factor' },
    ],
    packages: [],
    seealso: ['\\alpha', '\\beta'],
    category: 'math',
  },
  {
    command: '\\vec',
    signature: '\\vec{symbol}',
    description: 'Places a vector arrow above the symbol. Must be in math mode. For bold vectors, use \\mathbf or \\boldsymbol.',
    parameters: [{ name: 'symbol', required: true, description: 'The symbol to annotate with an arrow' }],
    examples: [
      { code: '$\\vec{v} = (v_x, v_y, v_z)$', description: 'Vector notation' },
      { code: '$\\vec{F} = m\\vec{a}$', description: 'Newton\'s second law' },
    ],
    packages: [],
    seealso: ['\\hat', '\\overline'],
    category: 'math',
  },
  {
    command: '\\hat',
    signature: '\\hat{symbol}',
    description: 'Places a hat (circumflex) accent above the symbol. Used for unit vectors, estimators, etc. Must be in math mode.',
    parameters: [{ name: 'symbol', required: true, description: 'The symbol to place a hat over' }],
    examples: [
      { code: '$\\hat{x}$', description: 'Unit vector in x direction' },
      { code: '$\\hat{\\theta}$', description: 'Estimated theta (MLE notation)' },
    ],
    packages: [],
    seealso: ['\\vec', '\\tilde', '\\bar'],
    category: 'math',
  },
  {
    command: '\\overline',
    signature: '\\overline{expression}',
    description: 'Places a horizontal line over the expression. Used for complex conjugates, set complements, etc. Must be in math mode.',
    parameters: [{ name: 'expression', required: true, description: 'The expression to overline' }],
    examples: [
      { code: '$\\overline{z}$', description: 'Complex conjugate of z' },
      { code: '$\\overline{AB}$', description: 'Line segment AB' },
    ],
    packages: [],
    seealso: ['\\underline', '\\vec', '\\hat'],
    category: 'math',
  },

  // ── GRAPHICS ────────────────────────────────────────────────────────────
  {
    command: '\\includegraphics',
    signature: '\\includegraphics[options]{filename}',
    description: 'Inserts an image file. Requires the graphicx package. Supported formats depend on the LaTeX engine (PDF: pdf, png, jpg; DVI: eps).',
    parameters: [
      { name: 'options', required: false, description: 'Key-value options: width, height, scale, angle, trim, clip' },
      { name: 'filename', required: true, description: 'Path to the image file (without extension recommended)' },
    ],
    examples: [
      { code: '\\includegraphics[width=0.8\\linewidth]{figure1}', description: 'Image scaled to 80% of line width' },
      { code: '\\includegraphics[height=5cm,keepaspectratio]{logo}', description: 'Fixed height, preserve aspect ratio' },
    ],
    packages: ['graphicx'],
    seealso: ['\\begin{figure}', '\\caption'],
    category: 'graphics',
  },
  {
    command: '\\caption',
    signature: '\\caption[short]{text}',
    description: 'Adds a caption to a figure or table float. Appears in the list of figures/tables. Must be inside a float environment.',
    parameters: [
      { name: 'short', required: false, description: 'Short caption for list of figures/tables' },
      { name: 'text', required: true, description: 'The full caption text' },
    ],
    examples: [
      { code: '\\caption{System architecture overview.}', description: 'Simple figure caption' },
      { code: '\\caption[Short]{A very long and descriptive caption.}', description: 'Caption with short form for LOF' },
    ],
    packages: [],
    seealso: ['\\label', '\\begin{figure}'],
    category: 'graphics',
  },
  {
    command: '\\label',
    signature: '\\label{key}',
    description: 'Creates a label for cross-referencing with \\ref or \\pageref. Labels must be unique in the document.',
    parameters: [{ name: 'key', required: true, description: 'A unique identifier string (e.g., fig:arch, eq:1, sec:intro)' }],
    examples: [
      { code: '\\label{fig:arch}', description: 'Label a figure' },
      { code: '\\section{Methods}\\label{sec:methods}', description: 'Label a section' },
    ],
    packages: [],
    seealso: ['\\ref', '\\pageref', '\\caption'],
    category: 'graphics',
  },
  {
    command: '\\ref',
    signature: '\\ref{key}',
    description: 'Cross-references a label, inserting its number. Requires two compilation passes to resolve. Use \\eqref for equations.',
    parameters: [{ name: 'key', required: true, description: 'The label key to reference' }],
    examples: [
      { code: 'See Figure~\\ref{fig:arch} for details.', description: 'Figure reference' },
      { code: 'As shown in Section~\\ref{sec:methods}', description: 'Section reference' },
    ],
    packages: [],
    seealso: ['\\label', '\\pageref', '\\cite'],
    category: 'graphics',
  },
  {
    command: '\\footnote',
    signature: '\\footnote[number]{text}',
    description: 'Inserts a footnote at the bottom of the page. The optional number overrides automatic numbering.',
    parameters: [
      { name: 'number', required: false, description: 'Override the footnote number' },
      { name: 'text', required: true, description: 'The footnote text' },
    ],
    examples: [
      { code: 'Interesting fact.\\footnote{This is documented in \\cite{smith2020}.}', description: 'Footnote with citation' },
    ],
    packages: [],
    seealso: ['\\label', '\\cite'],
    category: 'graphics',
  },

  // ── MISC ─────────────────────────────────────────────────────────────────
  {
    command: '\\documentclass',
    signature: '\\documentclass[options]{class}',
    description: 'Declares the document class. Must be the first command in a LaTeX file (before \\begin{document}).',
    parameters: [
      { name: 'options', required: false, description: 'Class options like 12pt, a4paper, twocolumn, draft' },
      { name: 'class', required: true, description: 'Document class: article, report, book, beamer, etc.' },
    ],
    examples: [
      { code: '\\documentclass{article}', description: 'Basic article class' },
      { code: '\\documentclass[12pt,a4paper]{report}', description: 'Report with 12pt font on A4 paper' },
    ],
    packages: [],
    seealso: ['\\usepackage', '\\begin{document}'],
    category: 'misc',
  },
  {
    command: '\\usepackage',
    signature: '\\usepackage[options]{package}',
    description: 'Loads a LaTeX package in the preamble. Must be placed before \\begin{document}.',
    parameters: [
      { name: 'options', required: false, description: 'Package-specific options' },
      { name: 'package', required: true, description: 'Package name (e.g., amsmath, graphicx, geometry)' },
    ],
    examples: [
      { code: '\\usepackage{amsmath}', description: 'Load AMS math extensions' },
      { code: '\\usepackage[margin=1in]{geometry}', description: 'Set 1-inch margins' },
      { code: '\\usepackage[utf8]{inputenc}', description: 'UTF-8 input encoding' },
    ],
    packages: [],
    seealso: ['\\documentclass', '\\newcommand'],
    category: 'misc',
  },
  {
    command: '\\newcommand',
    signature: '\\newcommand{\\cmd}[nargs]{definition}',
    description: 'Defines a new command. Errors if the command already exists (use \\renewcommand to redefine). Parameters are referenced as #1, #2, etc.',
    parameters: [
      { name: '\\cmd', required: true, description: 'The new command name (backslash included)' },
      { name: 'nargs', required: false, description: 'Number of arguments (0–9). Omit for zero arguments.' },
      { name: 'definition', required: true, description: 'The command definition, using #1, #2, etc. for parameters' },
    ],
    examples: [
      { code: '\\newcommand{\\R}{\\mathbb{R}}', description: 'Shorthand for real numbers ℝ' },
      { code: '\\newcommand{\\norm}[1]{\\left\\|#1\\right\\|}', description: 'Norm command with one argument' },
    ],
    packages: [],
    seealso: ['\\renewcommand', '\\usepackage'],
    category: 'misc',
  },
  {
    command: '\\renewcommand',
    signature: '\\renewcommand{\\cmd}[nargs]{definition}',
    description: 'Redefines an existing command. Errors if the command does not already exist (use \\newcommand for new commands).',
    parameters: [
      { name: '\\cmd', required: true, description: 'Existing command to redefine' },
      { name: 'nargs', required: false, description: 'Number of arguments' },
      { name: 'definition', required: true, description: 'New definition' },
    ],
    examples: [
      { code: '\\renewcommand{\\vec}[1]{\\mathbf{#1}}', description: 'Redefine \\vec to use bold instead of arrow' },
    ],
    packages: [],
    seealso: ['\\newcommand'],
    category: 'misc',
  },
  {
    command: '\\setlength',
    signature: '\\setlength{\\register}{length}',
    description: 'Sets a length register to the specified value. Common registers: \\parindent, \\parskip, \\textwidth.',
    parameters: [
      { name: '\\register', required: true, description: 'The length register to modify (e.g., \\parindent)' },
      { name: 'length', required: true, description: 'The new length value (e.g., 0pt, 1cm, 2em)' },
    ],
    examples: [
      { code: '\\setlength{\\parindent}{0pt}', description: 'Remove paragraph indentation' },
      { code: '\\setlength{\\parskip}{6pt}', description: 'Add 6pt space between paragraphs' },
    ],
    packages: [],
    seealso: ['\\usepackage', '\\newcommand'],
    category: 'misc',
  },
  {
    command: '\\hline',
    signature: '\\hline',
    description: 'Draws a horizontal rule across all columns in a tabular environment. Place at the start of a row.',
    parameters: [],
    examples: [
      {
        code: '\\begin{tabular}{ll}\n  \\hline\n  Name & Value \\\\\n  \\hline\n  Foo & 42 \\\\\n  \\hline\n\\end{tabular}',
        description: 'Table with horizontal rules',
      },
    ],
    packages: [],
    seealso: ['\\begin{tabular}', '\\multicolumn', '\\cline'],
    category: 'misc',
  },
  {
    command: '\\multicolumn',
    signature: '\\multicolumn{n}{align}{text}',
    description: 'Spans a table cell across n columns. The alignment argument follows the same rules as the tabular column spec.',
    parameters: [
      { name: 'n', required: true, description: 'Number of columns to span' },
      { name: 'align', required: true, description: 'Column alignment: l, c, r, possibly with | borders' },
      { name: 'text', required: true, description: 'Cell content' },
    ],
    examples: [
      { code: '\\multicolumn{3}{c}{Merged heading}', description: 'Center header spanning 3 columns' },
      { code: '\\multicolumn{2}{|c|}{Centered}', description: 'Merged with vertical borders' },
    ],
    packages: [],
    seealso: ['\\begin{tabular}', '\\hline'],
    category: 'misc',
  },
  {
    command: '\\cite',
    signature: '\\cite[note]{key}',
    description: 'Inserts a citation reference. The key refers to a BibTeX entry. Requires a \\bibliography command and BibTeX run.',
    parameters: [
      { name: 'note', required: false, description: 'Optional note appended after the citation number (e.g., "p.~42")' },
      { name: 'key', required: true, description: 'BibTeX key of the reference (comma-separated for multiple)' },
    ],
    examples: [
      { code: '\\cite{smith2020}', description: 'Single citation' },
      { code: '\\cite[p.~42]{jones2019}', description: 'Citation with page note' },
      { code: '\\cite{a2020,b2021}', description: 'Multiple citations' },
    ],
    packages: [],
    seealso: ['\\bibliography', '\\ref'],
    category: 'misc',
  },
  {
    command: '\\bibliography',
    signature: '\\bibliography{bibfile}',
    description: 'Specifies the BibTeX database file and prints the bibliography. The argument is the filename without .bib extension.',
    parameters: [{ name: 'bibfile', required: true, description: 'Name of the .bib file (without extension)' }],
    examples: [
      { code: '\\bibliographystyle{plain}\n\\bibliography{references}', description: 'Standard bibliography at end of document' },
    ],
    packages: [],
    seealso: ['\\cite', '\\bibliographystyle'],
    category: 'misc',
  },
  {
    command: '\\item',
    signature: '\\item[label] text',
    description: 'Marks an item in a list environment (itemize, enumerate, description). The optional label overrides the default bullet or number.',
    parameters: [
      { name: 'label', required: false, description: 'Custom item label overriding the default bullet/number' },
    ],
    examples: [
      { code: '\\begin{itemize}\n  \\item Regular bullet\n  \\item[--] Dash bullet\n\\end{itemize}', description: 'Items with custom label' },
      { code: '\\begin{enumerate}\n  \\item First item\n  \\item Second item\n\\end{enumerate}', description: 'Numbered items' },
    ],
    packages: [],
    seealso: ['\\begin{itemize}', '\\begin{enumerate}'],
    category: 'misc',
  },
]

export const LATEX_DOCS_MAP: Map<string, LaTeXDoc> = new Map(
  LATEX_DOCS.map(doc => [doc.command, doc])
)

// Filter each doc's seealso to only include commands that exist in the map.
// This prevents LaTeXDocPanel from landing on "Not found" for dangling refs.
for (const doc of LATEX_DOCS) {
  doc.seealso = doc.seealso.filter(cmd => LATEX_DOCS_MAP.has(cmd))
}

export const LATEX_DOCS_BY_CATEGORY = LATEX_DOCS.reduce((acc, doc) => {
  if (!acc[doc.category]) acc[doc.category] = []
  acc[doc.category].push(doc)
  return acc
}, {} as Record<LaTeXDoc['category'], LaTeXDoc[]>)
