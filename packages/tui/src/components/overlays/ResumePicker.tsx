import React, { useState, useEffect, useCallback } from 'react'
import { Box, Text, useInput } from 'ink'
import TextInput from 'ink-text-input'
import { getApiClient } from '../../lib/api-client.js'
import { closeOverlay } from '../../stores/overlay.js'
import { writeConfig } from '../../lib/config.js'
import { addMessage } from '../../stores/messages.js'

interface Resume {
  id: string
  title: string
  type?: string
  updated_at: string
  is_pinned?: boolean
}

interface ResumeListResponse {
  resumes: Resume[]
  total: number
}

export function ResumePicker(): React.ReactElement {
  const [resumes, setResumes] = useState<Resume[]>([])
  const [filter, setFilter] = useState('')
  const [cursor, setCursor] = useState(0)
  const [loading, setLoading] = useState(true)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  useEffect(() => {
    const client = getApiClient()
    client.get<ResumeListResponse>('/resumes?limit=50')
      .then(res => {
        setResumes(res.resumes)
        setLoading(false)
      })
      .catch(err => {
        setErrorMsg(String(err))
        setLoading(false)
      })
  }, [])

  const filtered = filter
    ? resumes.filter(r => r.title.toLowerCase().includes(filter.toLowerCase()))
    : resumes

  // Reset cursor when filter narrows the list
  useEffect(() => {
    setCursor(0)
  }, [filter])

  const select = useCallback((resume: Resume) => {
    void writeConfig({ defaultResumeId: resume.id })
    addMessage({ role: 'system', content: `Selected: ${resume.title}` })
    closeOverlay()
  }, [])

  useInput((_input, key) => {
    if (key.escape) { closeOverlay(); return }
    if (key.upArrow) { setCursor(c => Math.max(0, c - 1)); return }
    if (key.downArrow) { setCursor(c => Math.min(filtered.length - 1, c + 1)); return }
    if (key.return && filtered[cursor]) { select(filtered[cursor]!); return }
  })

  const formatAge = (iso: string): string => {
    const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000)
    if (days === 0) return 'today'
    if (days === 1) return 'yesterday'
    if (days < 30) return `${days}d ago`
    return `${Math.floor(days / 30)}mo ago`
  }

  return (
    <Box flexDirection="column" borderStyle="round" borderColor="blue" padding={1} width={60}>
      <Text bold color="cyan">Select Resume</Text>
      <Box marginTop={1} gap={1}>
        <Text dimColor>Filter:</Text>
        <TextInput value={filter} onChange={setFilter} placeholder="type to filter..." />
      </Box>
      <Box marginTop={1} flexDirection="column">
        {loading && <Text color="yellow">Loading resumes…</Text>}
        {errorMsg != null && <Text color="red">Error: {errorMsg}</Text>}
        {!loading && errorMsg == null && filtered.length === 0 && (
          <Text dimColor>No resumes found</Text>
        )}
        {filtered.map((r, i) => (
          <Box key={r.id} gap={2}>
            <Text color={i === cursor ? 'cyan' : undefined}>
              {i === cursor ? '▶' : ' '} {r.title}
            </Text>
            {r.type && <Text dimColor>{r.type}</Text>}
            <Text dimColor>{formatAge(r.updated_at)}</Text>
            {r.is_pinned === true && <Text color="yellow">★</Text>}
          </Box>
        ))}
      </Box>
      <Box marginTop={1}>
        <Text dimColor>Type to filter · ↑↓ navigate · Enter select · Esc close</Text>
      </Box>
    </Box>
  )
}
