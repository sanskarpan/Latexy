import React, { useState, useEffect, useCallback } from 'react'
import { Box, Text, useInput } from 'ink'
import TextInput from 'ink-text-input'
import { useOverlaySize } from '../../lib/overlay-size.js'
import { useCtrlKeyGuard } from '../../lib/ctrl-key-guard.js'
import { getApiClient } from '../../lib/api-client.js'
import { closeOverlay } from '../../stores/overlay.js'
import { writeConfig } from '../../lib/config.js'
import { addMessage } from '../../stores/messages.js'
import { RESUME_PAGE } from '../../tools/shared.js'

interface Resume {
  id: string
  title: string
  updated_at: string
  // The API names these `document_type` and `pinned`. Reading `type`/`is_pinned`
  // meant the type label and the ★ were never drawn for any resume, pinned or
  // not — `undefined === true` is simply always false.
  document_type?: string
  pinned?: boolean
}

interface ResumeListResponse {
  resumes: Resume[]
  total: number
}

interface ResumePickerProps {
  /** Show archived resumes instead of active ones (/list --archived). */
  archived?: boolean
  /** Restrict to a document type, e.g. resume | academic_cv (/list --type). */
  documentType?: string
}

export function ResumePicker({ archived, documentType }: ResumePickerProps): React.ReactElement {
  const [resumes, setResumes] = useState<Resume[]>([])
  const [total, setTotal] = useState(0)
  const [filter, setFilter] = useState('')
  const [cursor, setCursor] = useState(0)
  const [loading, setLoading] = useState(true)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)

  useEffect(() => {
    const client = getApiClient()
    const params = new URLSearchParams({ limit: String(RESUME_PAGE) })
    if (archived === true) params.set('archived', 'true')
    if (documentType != null) params.set('document_type', documentType)
    client.get<ResumeListResponse>(`/resumes/?${params.toString()}`)
      .then(res => {
        setResumes(res.resumes)
        setTotal(res.total ?? res.resumes.length)
        setLoading(false)
      })
      .catch(err => {
        setErrorMsg(String(err))
        setLoading(false)
      })
  }, [archived, documentType])

  // Ctrl+L clears the transcript underneath; without this its letter lands in
  // this overlay's filter box instead.
  useCtrlKeyGuard(setFilter)

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

  // Every row was rendered. SelectOverlay windows to 10 for exactly this reason:
  // a user with 40 resumes had the list push the prompt off the top of the screen.
  const { rows: WINDOW, width: boxWidth } = useOverlaySize()
  const start = Math.max(0, Math.min(cursor - Math.floor(WINDOW / 2), filtered.length - WINDOW))
  const visible = filtered.slice(start, start + WINDOW)

  const formatAge = (iso: string): string => {
    const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000)
    if (days === 0) return 'today'
    if (days === 1) return 'yesterday'
    if (days < 30) return `${days}d ago`
    return `${Math.floor(days / 30)}mo ago`
  }

  return (
    <Box flexDirection="column" borderStyle="round" borderColor="blue" padding={1} width={boxWidth}>
      <Text bold color="cyan">
        {archived === true ? 'Archived Resumes' : 'Select Resume'}
        {/* Showing a page of a longer list without saying so reads as "this is
            everything you have". */}
        {total > resumes.length ? ` — showing ${resumes.length} of ${total}` : ''}
      </Text>
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
        {visible.map(r => {
          const i = filtered.indexOf(r)
          return (
            <Box key={r.id} gap={2}>
              <Text color={i === cursor ? 'cyan' : undefined}>
                {i === cursor ? '▶' : ' '} {r.title}
              </Text>
              {r.document_type != null && <Text dimColor>{r.document_type}</Text>}
              <Text dimColor>{formatAge(r.updated_at)}</Text>
              {r.pinned === true && <Text color="yellow">★</Text>}
            </Box>
          )
        })}
        {filtered.length > WINDOW && (
          <Text dimColor>{`  … ${filtered.length - WINDOW} more (type to filter)`}</Text>
        )}
      </Box>
      <Box marginTop={1}>
        <Text dimColor>Type to filter · ↑↓ navigate · Enter select · Esc close</Text>
      </Box>
    </Box>
  )
}
