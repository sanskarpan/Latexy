'use client'

import { FormEvent, useEffect, useMemo, useState } from 'react'
import { Loader2, Plus, Trash2 } from 'lucide-react'
import { normalizeDictionaryWord, usePersonalDictionary } from '@/hooks/useSpellCheck'
import { useRequireAuth } from '@/hooks/useRequireAuth'

export default function PersonalDictionarySettings() {
  const { session, isPending, error: sessionError } = useRequireAuth()
  const ownerId = session?.user?.id ?? null
  const dictionaryScope = useMemo(() => ({
    ownerId,
    authToken: session?.session?.token ?? null,
    confirmed: ownerId !== null || (!isPending && !sessionError),
  }), [isPending, ownerId, session?.session?.token, sessionError])
  const dictionary = usePersonalDictionary(dictionaryScope)
  const words = useMemo(
    () => [...dictionary.words].sort((a, b) => a.localeCompare(b)),
    [dictionary.words],
  )
  const ownerKey = dictionaryScope.confirmed ? dictionaryScope.ownerId ?? 'anonymous' : 'unconfirmed'
  const [entryState, setEntryState] = useState({ ownerKey, value: '' })
  const entry = entryState.ownerKey === ownerKey ? entryState.value : ''
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setError(null)
    setEntryState({ ownerKey, value: '' })
  }, [ownerKey])

  function handleAdd(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const normalized = normalizeDictionaryWord(entry)
    if (!normalized) {
      setError('Enter one word of 64 characters or fewer, without spaces.')
      return
    }
    if (words.length >= 500 && !words.includes(normalized)) {
      setError('The personal dictionary is limited to 500 words. Remove one before adding another.')
      return
    }
    setError(null)
    dictionary.addWord(normalized)
    setEntryState({ ownerKey, value: '' })
  }

  function handleRemove(word: string) {
    setError(null)
    dictionary.removeWord(word)
  }

  return (
    <div className="space-y-4">
      <p className="text-[12px] leading-relaxed text-fg-3">
        Add names and specialist terms that should not be marked as spelling mistakes. Your dictionary follows your account across devices.
      </p>

      <form onSubmit={handleAdd} className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <label htmlFor="personal-dictionary-word" className="sr-only">Word to add</label>
          <input
            id="personal-dictionary-word"
            value={entry}
            onChange={(event) => setEntryState({ ownerKey, value: event.target.value })}
            maxLength={64}
            autoComplete="off"
            placeholder="e.g. OpenAI"
            className="w-full rounded-[var(--radius-md)] border border-line bg-bg px-3 py-2 text-sm text-fg outline-none transition focus:border-accent"
          />
        </div>
        <button
          type="submit"
          className="inline-flex items-center gap-1.5 rounded-[var(--radius-md)] bg-accent px-3 py-2 text-sm font-semibold text-accent-fg transition hover:brightness-110"
        >
          <Plus size={13} />
          Add
        </button>
      </form>

      {(error || dictionary.error) && <p role="alert" className="text-[11px] text-err">{error || dictionary.error}</p>}

      {dictionary.loading ? (
        <div className="flex items-center gap-2 text-sm text-fg-3">
          <Loader2 size={13} className="animate-spin" />
          Loading dictionary…
        </div>
      ) : words.length === 0 ? (
        <p className="rounded-[var(--radius-md)] bg-surface-2 px-3 py-3 text-[11px] text-fg-3">
          No personal words yet. You can also add a flagged word from the editor&apos;s quick-fix menu.
        </p>
      ) : (
        <ul aria-label="Personal dictionary words" className="max-h-52 space-y-1 overflow-y-auto pr-1">
          {words.map((word) => (
            <li key={word} className="flex items-center justify-between gap-3 rounded-[var(--radius-md)] bg-surface-2 px-3 py-2">
              <span className="min-w-0 truncate font-mono text-[12px] text-fg">{word}</span>
              <button
                type="button"
                onClick={() => handleRemove(word)}
                aria-label={`Remove ${word} from personal dictionary`}
                className="shrink-0 rounded p-1 text-fg-3 transition hover:bg-err/10 hover:text-err"
              >
                <Trash2 size={13} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <p className="text-right text-[10px] tabular-nums text-fg-3">{words.length}/500 words</p>
    </div>
  )
}
