import React, { useCallback, useEffect, useState } from 'react'
import { Box, Text, useInput } from 'ink'
import TextInput from 'ink-text-input'

import { settlePick, type PickerItem } from '../../lib/pick.js'
import { theme } from '../../lib/theme.js'

interface SelectOverlayProps {
  title: string
  /** Resolved once when the overlay mounts. */
  load: () => Promise<PickerItem[]>
  emptyMessage?: string
}

/**
 * Generic "choose one of these" overlay.
 *
 * ResumePicker could only persist a default selection — it had no way to answer
 * a caller asking "which one did you mean?". Commands that act on a resume need
 * that, so this settles a pending pick (see lib/pick.ts) instead of writing
 * config, and every list-driven command can share one implementation.
 */
export function SelectOverlay({ title, load, emptyMessage }: SelectOverlayProps): React.ReactElement {
  const [items, setItems] = useState<PickerItem[]>([])
  const [filter, setFilter] = useState('')
  const [cursor, setCursor] = useState(0)
  const [loading, setLoading] = useState(true)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  useEffect(() => {
    let alive = true
    load()
      .then(list => {
        if (!alive) return
        setItems(list)
        setLoading(false)
      })
      .catch(err => {
        if (!alive) return
        setErrorMsg(err instanceof Error ? err.message : String(err))
        setLoading(false)
      })
    return () => { alive = false }
  }, [load])

  const needle = filter.toLowerCase()
  const filtered = needle
    ? items.filter(i => `${i.label} ${i.detail ?? ''}`.toLowerCase().includes(needle))
    : items

  useEffect(() => { setCursor(0) }, [filter])

  const choose = useCallback((item: PickerItem) => { settlePick(item.id) }, [])

  useInput((_input, key) => {
    // Esc resolves null rather than leaving the caller's await hanging forever.
    if (key.escape) { settlePick(null); return }
    if (key.upArrow) { setCursor(c => Math.max(0, c - 1)); return }
    if (key.downArrow) { setCursor(c => Math.min(filtered.length - 1, c + 1)); return }
    if (key.return && filtered[cursor]) { choose(filtered[cursor]!) }
  })

  // Long lists would push the prompt off screen; show a window around the cursor.
  const WINDOW = 10
  const start = Math.max(0, Math.min(cursor - Math.floor(WINDOW / 2), filtered.length - WINDOW))
  const visible = filtered.slice(Math.max(0, start), Math.max(0, start) + WINDOW)

  return (
    <Box flexDirection="column" borderStyle="round" borderColor={theme.brand} padding={1} width={72}>
      <Text bold color={theme.accent}>{title}</Text>
      <Box marginTop={1} gap={1}>
        <Text dimColor>Filter:</Text>
        <TextInput value={filter} onChange={setFilter} placeholder="type to filter..." />
      </Box>
      <Box marginTop={1} flexDirection="column">
        {loading && <Text color={theme.warning}>Loading…</Text>}
        {errorMsg != null && <Text color={theme.error}>Error: {errorMsg}</Text>}
        {!loading && errorMsg == null && filtered.length === 0 && (
          <Text dimColor>{emptyMessage ?? 'Nothing to show'}</Text>
        )}
        {visible.map(item => {
          const idx = filtered.indexOf(item)
          const active = idx === cursor
          return (
            <Box key={item.id} gap={2}>
              <Text color={active ? theme.accent : undefined}>
                {active ? '▶' : ' '} {item.label}
              </Text>
              {item.detail != null && <Text dimColor>{item.detail}</Text>}
            </Box>
          )
        })}
        {filtered.length > WINDOW && (
          <Text dimColor>{`  … ${filtered.length - WINDOW} more (filter to narrow)`}</Text>
        )}
      </Box>
      <Box marginTop={1}>
        <Text dimColor>Type to filter · ↑↓ navigate · Enter select · Esc cancel</Text>
      </Box>
    </Box>
  )
}
