import { describe, expect, it } from 'vitest'
import { buildLatexHoverPreview, parseBibTeXPreviews } from '@/lib/latex-hover-previews'

describe('LaTeX hover previews', () => {
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
