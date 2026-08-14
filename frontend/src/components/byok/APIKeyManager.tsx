'use client'

import React, { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

interface APIKey {
  id: string
  provider: string
  key_name: string
  is_active: boolean
  last_validated: string | null
  created_at: string
}

const initialKey = {
  provider: '',
  api_key: '',
  key_name: '',
}

interface APIKeyManagerProps {
  onKeysChange?: (keys: APIKey[]) => void
}

const APIKeyManager: React.FC<APIKeyManagerProps> = ({ onKeysChange }) => {
  const [apiKeys, setApiKeys] = useState<APIKey[]>([])
  const [providers, setProviders] = useState<Record<string, string[]>>({})
  const [loading, setLoading] = useState(true)
  // Tracked separately from `loading` (providers): fetchAPIKeys and fetchProviders
  // run in parallel and resolve independently, so gating the empty-state render
  // on this flag (rather than the providers flag) stops existing keys from
  // briefly flashing "No API Keys Yet" if providers happen to resolve first.
  const [keysLoading, setKeysLoading] = useState(true)
  const [showAddModal, setShowAddModal] = useState(false)
  const [newKey, setNewKey] = useState(initialKey)
  const [saving, setSaving] = useState(false)

  const modalRef = useRef<HTMLDivElement>(null)
  const firstFieldRef = useRef<HTMLSelectElement>(null)
  const triggerRef = useRef<HTMLElement | null>(null)

  const closeAddModal = useCallback(() => {
    setShowAddModal(false)
    setNewKey(initialKey)
  }, [])

  const fetchAPIKeys = useCallback(async () => {
    try {
      const response = await fetch('/api/byok/api-keys')
      if (!response.ok) throw new Error('Failed to fetch API keys')
      const data = await response.json()
      const keys: APIKey[] = Array.isArray(data.api_keys) ? data.api_keys : []
      setApiKeys(keys)
      onKeysChange?.(keys)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to load keys')
    } finally {
      setKeysLoading(false)
    }
  }, [onKeysChange])

  const fetchProviders = useCallback(async () => {
    try {
      const response = await fetch('/api/byok/providers')
      if (!response.ok) throw new Error('Failed to fetch providers')
      const data = await response.json()
      // Backend returns providers as an array of { name, available_models, ... }
      // Transform to Record<providerName, modelList> for the dropdown
      const providerList = Array.isArray(data.providers) ? data.providers : []
      const providerMap: Record<string, string[]> = {}
      for (const p of providerList) {
        providerMap[p.name] = p.available_models || []
      }
      setProviders(providerMap)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to load providers')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    fetchAPIKeys()
    fetchProviders()
  }, [fetchAPIKeys, fetchProviders])

  useEffect(() => {
    if (!showAddModal) return

    triggerRef.current = document.activeElement as HTMLElement | null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    // Autofocus the first field once the modal has mounted.
    const focusTimer = window.setTimeout(() => firstFieldRef.current?.focus(), 0)

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        closeAddModal()
        return
      }

      if (event.key !== 'Tab') return

      const modal = modalRef.current
      if (!modal) return
      const focusable = modal.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])'
      )
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      const active = document.activeElement

      if (event.shiftKey) {
        if (active === first || !modal.contains(active)) {
          event.preventDefault()
          last.focus()
        }
      } else if (active === last || !modal.contains(active)) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)

    return () => {
      window.clearTimeout(focusTimer)
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = previousOverflow
      triggerRef.current?.focus()
    }
  }, [showAddModal, closeAddModal])

  const validateAPIKey = async (provider: string, apiKey: string): Promise<{ valid: boolean; reason?: string }> => {
    try {
      const response = await fetch('/api/byok/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider, api_key: apiKey }),
      })
      const result = await response.json()
      if (!response.ok) {
        return { valid: false, reason: result?.detail || result?.error || 'Validation request failed' }
      }
      return { valid: Boolean(result.valid), reason: result.error || undefined }
    } catch (error) {
      return { valid: false, reason: error instanceof Error ? error.message : 'Unable to reach validation service' }
    }
  }

  const addAPIKey = async () => {
    if (saving) return
    if (!newKey.provider || !newKey.api_key) {
      toast.error('Provider and API key are required')
      return
    }

    setSaving(true)
    try {
      const { valid, reason } = await validateAPIKey(newKey.provider, newKey.api_key)
      if (!valid) {
        toast.error(reason ? `Key validation failed: ${reason}` : 'Key validation failed for selected provider')
        return
      }

      const response = await fetch('/api/byok/api-keys', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newKey),
      })

      if (!response.ok) throw new Error('Failed to add API key')
      toast.success('API key added')
      setShowAddModal(false)
      setNewKey(initialKey)
      fetchAPIKeys()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to add key')
    } finally {
      setSaving(false)
    }
  }

  const deleteAPIKey = async (keyId: string) => {
    if (!confirm('Delete this API key?')) return
    try {
      const response = await fetch(`/api/byok/api-keys/${keyId}`, { method: 'DELETE' })
      if (!response.ok) throw new Error('Failed to delete API key')
      toast.success('API key deleted')
      fetchAPIKeys()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to delete key')
    }
  }

  if (loading) {
    return <div className="rounded-[var(--radius-lg)] border border-line bg-bg p-4 text-fg-2">Loading provider configuration...</div>
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-fg">API Key Management</h2>
          <p className="text-sm text-fg-2">Encrypted BYOK credential management with provider validation.</p>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="rounded-[var(--radius-md)] bg-accent px-3 py-2 text-sm font-semibold text-accent-fg hover:brightness-110"
        >
          Add Key
        </button>
      </div>

      <div className="space-y-3">
        {keysLoading ? (
          <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-8 text-center text-fg-2">
            Loading your keys...
          </div>
        ) : apiKeys.length === 0 ? (
          <div className="rounded-[var(--radius-lg)] border border-line bg-surface p-8 text-center">
            <h3 className="text-lg font-semibold text-fg">No API Keys Yet</h3>
            <p className="mt-1 text-sm text-fg-2">Add your first provider key to enable BYOK execution.</p>
          </div>
        ) : (
          apiKeys.map((key) => (
            <article key={key.id} className="rounded-[var(--radius-lg)] border border-line bg-surface p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="font-semibold text-fg">{key.key_name || `${key.provider} key`}</p>
                  <p className="text-sm text-fg-2">Provider: {key.provider}</p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => deleteAPIKey(key.id)}
                    className="rounded-[var(--radius-md)] border border-err/30 bg-err/10 px-3 py-2 text-xs text-err hover:bg-err/20"
                  >
                    Delete
                  </button>
                </div>
              </div>

              <div className="mt-3 grid gap-2 text-xs text-fg-2 sm:grid-cols-3">
                <p>
                  Status:{' '}
                  <span className={key.is_active ? 'text-ok' : 'text-err'}>
                    {key.is_active ? 'active' : 'inactive'}
                  </span>
                </p>
                <p>Created: {new Date(key.created_at).toLocaleDateString()}</p>
                <p>
                  Models: <span className="text-accent-strong">{providers[key.provider]?.length || 0}</span>
                </p>
              </div>

              <div className="mt-2 flex items-center gap-2 rounded-[var(--radius-md)] border border-line bg-bg p-2 text-xs font-mono text-fg-3">
                <span aria-hidden="true">••••</span>
                <span className="font-sans">stored securely</span>
              </div>

              {key.last_validated && (
                <p className="mt-2 text-xs text-ok">
                  Last validated {new Date(key.last_validated).toLocaleString()}
                </p>
              )}
            </article>
          ))
        )}
      </div>

      {showAddModal && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)] p-4"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) closeAddModal()
          }}
        >
          <div
            ref={modalRef}
            role="dialog"
            aria-modal="true"
            aria-labelledby="byok-add-key-title"
            className="rounded-[var(--radius-lg)] border border-line bg-surface w-full max-w-lg p-5"
          >
            <h3 id="byok-add-key-title" className="text-lg font-semibold text-fg">Add Provider Key</h3>
            <p className="mt-1 text-sm text-fg-2">Validate and store encrypted credentials for runtime usage.</p>

            <div className="mt-4 space-y-3">
              <select
                ref={firstFieldRef}
                value={newKey.provider}
                onChange={(e) => setNewKey((prev) => ({ ...prev, provider: e.target.value }))}
                className="w-full rounded-[var(--radius-md)] border border-line-2 bg-bg px-3 py-2 text-sm text-fg outline-none focus:border-accent"
              >
                <option value="">Select provider</option>
                {Object.keys(providers).map((provider) => (
                  <option key={provider} value={provider}>
                    {provider}
                  </option>
                ))}
              </select>

              <input
                type="text"
                placeholder="Friendly key name (optional)"
                value={newKey.key_name}
                onChange={(e) => setNewKey((prev) => ({ ...prev, key_name: e.target.value }))}
                className="w-full rounded-[var(--radius-md)] border border-line-2 bg-bg px-3 py-2 text-sm text-fg outline-none placeholder:text-fg-3 focus:border-accent"
              />

              <input
                type="password"
                placeholder="Paste API key"
                value={newKey.api_key}
                onChange={(e) => setNewKey((prev) => ({ ...prev, api_key: e.target.value }))}
                className="w-full rounded-[var(--radius-md)] border border-line-2 bg-bg px-3 py-2 text-sm text-fg outline-none placeholder:text-fg-3 focus:border-accent"
              />
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={closeAddModal}
                disabled={saving}
                className="rounded-[var(--radius-md)] border border-line-2 px-3 py-2 text-sm text-fg hover:bg-surface-2 disabled:opacity-60"
              >
                Cancel
              </button>
              <button
                onClick={addAPIKey}
                disabled={saving}
                className="inline-flex items-center gap-2 rounded-[var(--radius-md)] bg-accent px-3 py-2 text-sm font-semibold text-accent-fg hover:brightness-110 disabled:opacity-60"
              >
                {saving && (
                  <span
                    aria-hidden="true"
                    className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-accent-fg/40 border-t-accent-fg"
                  />
                )}
                {saving ? 'Saving…' : 'Validate and Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default APIKeyManager
