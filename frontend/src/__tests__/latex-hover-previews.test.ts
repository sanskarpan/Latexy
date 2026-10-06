import { describe, expect, it } from 'vitest'
import { markdownLanguage } from '@codemirror/lang-markdown'
import { buildLatexHoverPreview, markdownCodeSpan, parseBibTeXPreviews } from '@/lib/latex-hover-previews'

function parseRenderedCodeSpan(markdown: string): string {
  const tree = markdownLanguage.parser.parse(markdown)
  const code = tree.topNode.getChild('Paragraph')?.getChild('InlineCode')
  if (!code?.firstChild || !code.lastChild) throw new Error('Expected an inline code span')
  const body = markdown.slice(code.firstChild.to, code.lastChild.from)
  return body.startsWith(' ') && body.endsWith(' ') && !/^ +$/.test(body)
    ? body.slice(1, -1)
    : body
}

describe('LaTeX hover previews', () => {
  it('renders backslash-rich and backtick-rich values as one inline code span', () => {
    for (const value of [String.raw`\frac{x}{y}`, 'value `` with `ticks`', '`edge`', '  ', String.raw` \alpha `]) {
      const markdown = markdownCodeSpan(value)
      expect(markdownLanguage.parser.parse(markdown).toString()).toContain('InlineCode(CodeMark,CodeMark)')
      expect(parseRenderedCodeSpan(markdown)).toBe(value)
    }
  })

  it('normalizes blank paragraphs and handles many backtick runs without argument overflow', () => {
    expect(parseRenderedCodeSpan(markdownCodeSpan('math\n\n![remote](https://example.test/image)')))
      .toBe('math  ![remote](https://example.test/image)')
    const manyRuns = '`x'.repeat(100_000)
    expect(markdownCodeSpan(manyRuns)).toBe('`` ' + manyRuns + ' ``')
  })

  it('finds inline and display math at the hovered offset', () => {
    const source = 'Text $x^2 + y^2$ and \\[\\frac{a}{b}\\]'
    expect(buildLatexHoverPreview(source, '', source.indexOf('x^2'))).toMatchObject({
      kind: 'math', latex: 'x^2 + y^2', displayMode: false,
    })
    expect(buildLatexHoverPreview(source, '', source.indexOf('frac'))).toMatchObject({
      kind: 'math', latex: '\\frac{a}{b}', displayMode: true,
    })
  })

  it('requires matching math environment delimiters', () => {
    const valid = '\\begin{align}a &= b\\\\ c &= d\\end{align}'
    expect(buildLatexHoverPreview(valid, '', valid.indexOf('a &'))).toMatchObject({ kind: 'math', displayMode: true })
    const malformed = '\\begin{align}a=b\\end{equation}'
    expect(buildLatexHoverPreview(malformed, '', malformed.indexOf('a=b'))).toBeNull()
  })

  it('ignores math-looking content in comments and literal environments', () => {
    const source = '% $hidden$\n\\begin{verbatim}$alsoHidden$\\end{verbatim}'
    expect(buildLatexHoverPreview(source, '', source.indexOf('hidden'))).toBeNull()
    expect(buildLatexHoverPreview(source, '', source.indexOf('alsoHidden'))).toBeNull()
  })

  it('extracts graphic filenames and options', () => {
    const source = '\\includegraphics[width=.5\\linewidth,keepaspectratio]{diagram.png}'
    expect(buildLatexHoverPreview(source, '', source.indexOf('diagram'))).toEqual({
      kind: 'graphic', start: 0, end: source.length,
      filename: 'diagram.png', options: 'width=.5\\linewidth,keepaspectratio',
    })
  })

  it('parses bounded citation metadata including braced titles', () => {
    const entries = parseBibTeXPreviews('@article{smith2024, title={{A} Reliable System}, author={Smith, Ada}, year={2024}}')
    expect(entries.get('smith2024')).toEqual({
      key: 'smith2024', type: 'article', title: '{A} Reliable System', author: 'Smith, Ada', year: '2024',
    })
  })

  it('combines saved metadata with multi-citation keys', () => {
    const source = 'Prior work \\citep[see][]{smith2024,missing}.'
    const bibliography = '@article{smith2024,title={Reliable Systems},author={Ada Smith},year=2024}'
    expect(buildLatexHoverPreview(source, bibliography, source.indexOf('smith'))).toMatchObject({
      kind: 'citation',
      citations: [
        { key: 'smith2024', title: 'Reliable Systems', author: 'Ada Smith', year: '2024' },
        { key: 'missing' },
      ],
    })
  })
})
