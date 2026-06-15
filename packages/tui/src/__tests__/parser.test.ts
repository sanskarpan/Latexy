import { describe, it, expect } from 'vitest'
import { parseSlashCommand } from '../commands/parser.js'

describe('parseSlashCommand', () => {
  it('returns null for non-slash input', () => {
    expect(parseSlashCommand('hello world')).toBeNull()
  })

  it('parses simple command with no args', () => {
    const r = parseSlashCommand('/compile')
    expect(r?.name).toBe('compile')
    expect(r?.args).toEqual({})
    expect(r?.positional).toEqual([])
  })

  it('parses flag with value', () => {
    const r = parseSlashCommand('/compile --compiler xelatex')
    expect(r?.args['compiler']).toBe('xelatex')
  })

  it('parses boolean flag', () => {
    const r = parseSlashCommand('/list --archived')
    expect(r?.args['archived']).toBe(true)
  })

  it('parses positional args', () => {
    const r = parseSlashCommand('/new My Resume')
    expect(r?.positional).toEqual(['My', 'Resume'])
  })

  it('parses quoted value with spaces', () => {
    const r = parseSlashCommand('/cover --company "Google Inc" --role "SWE"')
    expect(r?.args['company']).toBe('Google Inc')
    expect(r?.args['role']).toBe('SWE')
  })

  it('parses --key=value syntax', () => {
    const r = parseSlashCommand('/ats --industry=software_engineering')
    expect(r?.args['industry']).toBe('software_engineering')
  })

  it('returns raw input', () => {
    const r = parseSlashCommand('/compile --compiler pdflatex')
    expect(r?.raw).toBe('/compile --compiler pdflatex')
  })
})
