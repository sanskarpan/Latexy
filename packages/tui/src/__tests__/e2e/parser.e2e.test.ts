import { describe, it, expect } from 'vitest'
import { parseSlashCommand } from '../../commands/parser.js'
import { COMMAND_MAP, SLASH_COMMANDS } from '../../commands/registry.js'

describe('slash command registry integration', () => {
  it('registers exactly 32 commands', () => {
    expect(SLASH_COMMANDS.length).toBe(32)
  })

  it('COMMAND_MAP has an entry for every SLASH_COMMANDS item', () => {
    for (const cmd of SLASH_COMMANDS) {
      expect(COMMAND_MAP.has(cmd.name)).toBe(true)
    }
  })

  it('all commands have non-empty name, description and usage', () => {
    for (const cmd of SLASH_COMMANDS) {
      expect(cmd.name.length).toBeGreaterThan(0)
      expect(cmd.description.length).toBeGreaterThan(0)
      expect(cmd.usage.length).toBeGreaterThan(0)
    }
  })

  it('parseSlashCommand returns null for non-slash input', () => {
    expect(parseSlashCommand('hello world')).toBeNull()
    expect(parseSlashCommand('')).toBeNull()
    expect(parseSlashCommand('  ')).toBeNull()
  })

  it('parses every registered command name successfully', () => {
    for (const cmd of SLASH_COMMANDS) {
      const parsed = parseSlashCommand(`/${cmd.name}`)
      expect(parsed).not.toBeNull()
      expect(parsed?.name).toBe(cmd.name)
    }
  })

  it('parses compile with --resume-id and --compiler flags', () => {
    const parsed = parseSlashCommand('/compile --resume-id abc-123 --compiler xelatex')
    expect(parsed?.name).toBe('compile')
    expect(parsed?.args['resume-id']).toBe('abc-123')
    expect(parsed?.args['compiler']).toBe('xelatex')
  })

  it('parses optimize with quoted --jd value', () => {
    const parsed = parseSlashCommand('/optimize --jd "Senior Engineer at Google"')
    expect(parsed?.name).toBe('optimize')
    expect(parsed?.args['jd']).toBe('Senior Engineer at Google')
  })

  it('parses help with positional argument', () => {
    const parsed = parseSlashCommand('/help compile')
    expect(parsed?.name).toBe('help')
    expect(parsed?.positional[0]).toBe('compile')
  })

  it('parses boolean flags', () => {
    const parsed = parseSlashCommand('/list --archived')
    expect(parsed?.name).toBe('list')
    expect(parsed?.args['archived']).toBe(true)
  })

  it('parses --key=value syntax', () => {
    const parsed = parseSlashCommand('/ats --industry=software_engineering')
    expect(parsed?.name).toBe('ats')
    expect(parsed?.args['industry']).toBe('software_engineering')
  })

  it('preserves raw input', () => {
    const raw = '/compile --resume-id abc'
    const parsed = parseSlashCommand(raw)
    expect(parsed?.raw).toBe(raw)
  })

  it('local commands are correctly classified', () => {
    const localNames = SLASH_COMMANDS.filter(c => c.isLocal).map(c => c.name)
    expect(localNames).toContain('list')
    expect(localNames).toContain('clear')
    expect(localNames).toContain('help')
    expect(localNames).toContain('logout')
    expect(localNames).toContain('jobs')
    expect(localNames).toContain('billing')
  })

  it('api commands are correctly classified', () => {
    const apiNames = SLASH_COMMANDS.filter(c => !c.isLocal).map(c => c.name)
    expect(apiNames).toContain('compile')
    expect(apiNames).toContain('optimize')
    expect(apiNames).toContain('ats')
    expect(apiNames).toContain('health')
    expect(apiNames).toContain('cancel')
  })
})
