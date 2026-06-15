export interface ParsedCommand {
  name: string
  args: Record<string, string | boolean>
  positional: string[]
  raw: string
}

export function parseSlashCommand(input: string): ParsedCommand | null {
  if (!input.startsWith('/')) return null

  const withoutSlash = input.slice(1)
  const tokens: string[] = []
  // Tokenize: handle --key="value with spaces", "quoted strings", and plain tokens
  const re = /--[\w-]+=(?:"[^"]*"|[^\s]+)|--[\w-]+|"([^"]*)"|(\S+)/g
  let match: RegExpExecArray | null

  while ((match = re.exec(withoutSlash)) !== null) {
    tokens.push(match[0])
  }

  if (tokens.length === 0) return null

  const [nameRaw, ...rest] = tokens
  if (!nameRaw) return null

  const args: Record<string, string | boolean> = {}
  const positional: string[] = []

  let i = 0
  while (i < rest.length) {
    const tok = rest[i]!
    if (tok.startsWith('--')) {
      if (tok.includes('=')) {
        const eqIdx = tok.indexOf('=')
        const key = tok.slice(2, eqIdx)
        let val = tok.slice(eqIdx + 1)
        if (val.startsWith('"') && val.endsWith('"')) val = val.slice(1, -1)
        args[key] = val
        i++
      } else {
        const key = tok.slice(2)
        const next = rest[i + 1]
        if (next && !next.startsWith('--')) {
          let val = next
          if (val.startsWith('"') && val.endsWith('"')) val = val.slice(1, -1)
          args[key] = val
          i += 2
        } else {
          args[key] = true
          i++
        }
      }
    } else {
      const val = tok.startsWith('"') && tok.endsWith('"') ? tok.slice(1, -1) : tok
      positional.push(val)
      i++
    }
  }

  return { name: nameRaw.toLowerCase(), args, positional, raw: input }
}
