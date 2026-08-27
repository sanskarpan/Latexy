/**
 * Headless argv splitting.
 *
 * The .tex path used to be located with `args.find(a => !a.startsWith('-'))`,
 * which cannot tell a positional from a flag's VALUE. So the documented
 * invocation `latexy compile --compiler xelatex cv.tex` tried to compile a file
 * named "xelatex", and `--output out.pdf cv.tex` read out.pdf as the LaTeX
 * source — submitting a binary PDF as a job, and burning the quota charge.
 */
import { describe, expect, it } from 'vitest'

import { parseHeadlessArgs } from '../headless.js'

const paths = (argv: string[]): string[] => parseHeadlessArgs(argv).positional

describe('parseHeadlessArgs', () => {
  it('does not mistake a flag value for the file path', () => {
    expect(paths(['compile', '--compiler', 'xelatex', 'cv.tex']))
      .toEqual(['compile', 'cv.tex'])
    expect(paths(['compile', '--output', 'out.pdf', 'cv.tex']))
      .toEqual(['compile', 'cv.tex'])
    expect(paths(['compile', '--resume-id', 'abc-123', 'cv.tex']))
      .toEqual(['compile', 'cv.tex'])
  })

  it('reads flag values regardless of position', () => {
    for (const argv of [
      ['compile', '--compiler', 'xelatex', 'cv.tex'],
      ['compile', 'cv.tex', '--compiler', 'xelatex'],
      ['compile', '--compiler=xelatex', 'cv.tex'],
    ]) {
      expect(parseHeadlessArgs(argv).flags['--compiler'], argv.join(' ')).toBe('xelatex')
    }
  })

  it('keeps headless workflow option values out of positional command arguments', () => {
    const parsed = parseHeadlessArgs([
      '--json', 'optimize', 'resume-1', '--jd', 'job.txt', '--level', 'balanced',
      '--model', 'gpt-test', '--industry', 'technology', '--page', '2', '--limit', '25',
    ])

    expect(parsed.positional).toEqual(['optimize', 'resume-1'])
    expect(parsed.flags).toMatchObject({
      '--jd': 'job.txt',
      '--level': 'balanced',
      '--model': 'gpt-test',
      '--industry': 'technology',
      '--page': '2',
      '--limit': '25',
    })
  })

  it('a value-flag with no value does not swallow the next flag or the path', () => {
    expect(paths(['compile', 'cv.tex', '--output'])).toEqual(['compile', 'cv.tex'])
    expect(paths(['compile', '--output', '--json', 'cv.tex'])).toEqual(['compile', 'cv.tex'])
    expect(parseHeadlessArgs(['compile', '--output', '--json']).flags['--output']).toBeUndefined()
  })

  it('bare flags are not positionals', () => {
    expect(paths(['compile', '--json', 'cv.tex'])).toEqual(['compile', 'cv.tex'])
    expect(paths(['--json'])).toEqual([])
  })

  it('the subcommand is the first true positional', () => {
    // cli.tsx derives the subcommand from this, so `--compiler xelatex` must not
    // be read as a subcommand called "xelatex".
    expect(paths(['--json', 'compile', 'cv.tex'])[0]).toBe('compile')
    expect(paths(['--compiler', 'xelatex', 'compile', 'cv.tex'])[0]).toBe('compile')
  })
})
