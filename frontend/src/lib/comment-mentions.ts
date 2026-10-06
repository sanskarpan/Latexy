const MENTION_ESCAPE_RE = /[.*+?^${}()|[\]\\]/g

/** Match a complete @mention token, not a prefix of a longer name/word. */
export function containsMentionToken(content: string, displayName: string): boolean {
  const escapedName = displayName.replace(MENTION_ESCAPE_RE, '\\$&')
  return new RegExp(`(?:^|[^\\p{L}\\p{N}_])@${escapedName}(?![\\p{L}\\p{N}_])`, 'u').test(content)
}
