'use client'

import React, { useEffect, useState } from 'react'
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

const APIKeyManager: React.FC = () => {
  const [apiKeys, setApiKeys] = useState<APIKey[]>([])
  const [providers, setProviders] = useState<Record<string, string[]>>({})
  const [loading, setLoading] = useState(true)
  const [showAddModal, setShowAddModal] = useState(false)
  const [newKey, setNewKey] = useState(initialKey)
  const [validating, setValidating] = useState(false)
  const [showKey, setShowKey] = useState<Record<string, boolean>>({})

  useEffect(() => {
    fetchAPIKeys()
    fetchProviders()
  }, [])

  const fetchAPIKeys = async () => {
    try {
      const response = await fetch('/api/byok/api-keys')
      if (!response.ok) throw new Error('Failed to fetch API keys')
      const data = await response.json()
      setApiKeys(data.api_keys || [])
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to load keys')
    }
  }

  const fetchProviders = async () => {
    try {
      const response = await fetch('/api/byok/providers')
      if (!response.ok) throw new Error('Failed to fetch providers')
      const data = await response.json()
      setProviders(data.providers || {})
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Unable to load providers')
    } finally {
      setLoading(false)
    }
  }

  const validateAPIKey = async (provider: string, apiKey: string) => {
    setValidating(true)
    try {
      const response = await fetch('/api/byok/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider, api_key: apiKey }),
      })
      const result = await response.json()
      return result.success
    } catch {
      return false
    } finally {
      setValidating(false)
    }
  }

  const addAPIKey = async () => {
    if (!newKey.provider || !newKey.api_key) {
      toast.error('Provider and API key are required')
      return
    }

    const isValid = await validateAPIKey(newKey.provider, newKey.api_key)
    if (!isValid) {
      toast.error('Key validation failed for selected provider')
      return
    }

    try {
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
    return <div className="rounded-xl border border-white/10 bg-slate-950/60 p-4 text-slate-300">Loading provider configuration...</div>
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-white">API Key Management</h2>
          <p className="text-sm text-slate-400">Encrypted BYOK credential management with provider validation.</p>
        </div>
        <button
          onClick={() => setShowAddModal(true)}
          className="rounded-lg bg-orange-300 px-3 py-2 text-sm font-semibold text-slate-950 hover:bg-orange-200"
        >
          Add Key
        </button>
      </div>

      <div className="space-y-3">
        {apiKeys.length === 0 ? (
          <div className="surface-card p-8 text-center">
            <h3 className="text-lg font-semibold text-white">No API Keys Yet</h3>
            <p className="mt-1 text-sm text-slate-400">Add your first provider key to enable BYOK execution.</p>
          </div>
        ) : (
          apiKeys.map((key) => (
            <article key={key.id} className="surface-card p-4">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="font-semibold text-white">{key.key_name || `${key.provider} key`}</p>
                  <p className="text-sm text-slate-400">Provider: {key.provider}</p>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setShowKey((prev) => ({ ...prev, [key.id]: !prev[key.id] }))}
                    className="rounded-lg border border-white/10 px-3 py-2 text-xs text-slate-300 hover:bg-white/10"
                  >
                    {showKey[key.id] ? 'Hide' : 'Show'}
                  </button>
                  <button
                    onClick={() => deleteAPIKey(key.id)}
                    className="rounded-lg border border-rose-300/30 bg-rose-300/10 px-3 py-2 text-xs text-rose-200 hover:bg-rose-300/20"
                  >
                    Delete
                  </button>
                </div>
              </div>

              <div className="mt-3 grid gap-2 text-xs text-slate-300 sm:grid-cols-3">
                <p>
                  Status:{' '}
                  <span className={key.is_active ? 'text-emerald-300' : 'text-rose-300'}>
                    {key.is_active ? 'active' : 'inactive'}
                  </span>
                </p>
                <p>Created: {new Date(key.created_at).toLocaleDateString()}</p>
                <p>
                  Models: <span className="text-orange-200">{providers[key.provider]?.length || 0}</span>
                </p>
              </div>

              <div className="mt-2 rounded-lg border border-white/10 bg-slate-950/65 p-2 text-xs font-mono text-slate-400">
                {showKey[key.id] ? '•••••••••••••••••••••••••••••' : 'hidden'}
              </div>

              {key.last_validated && (
                <p className="mt-2 text-xs text-emerald-300">
                  Last validated {new Date(key.last_validated).toLocaleString()}
                </p>
              )}
            </article>
          ))
        )}
      </div>

      {showAddModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/65 p-4">
          <div className="surface-panel edge-highlight w-full max-w-lg p-5">
            <h3 className="text-lg font-semibold text-white">Add Provider Key</h3>
            <p className="mt-1 text-sm text-slate-400">Validate and store encrypted credentials for runtime usage.</p>

            <div className="mt-4 space-y-3">
              <select
                value={newKey.provider}
                onChange={(e) => setNewKey((prev) => ({ ...prev, provider: e.target.value }))}
                className="w-full rounded-lg border border-white/15 bg-slate-950/70 px-3 py-2 text-sm text-slate-100 outline-none focus:border-orange-300/50"
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
                className="w-full rounded-lg border border-white/15 bg-slate-950/70 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-500 focus:border-orange-300/50"
              />

              <input
                type="password"
                placeholder="Paste API key"
                value={newKey.api_key}
                onChange={(e) => setNewKey((prev) => ({ ...prev, api_key: e.target.value }))}
                className="w-full rounded-lg border border-white/15 bg-slate-950/70 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-500 focus:border-orange-300/50"
              />
            </div>

            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={() => {
                  setShowAddModal(false)
                  setNewKey(initialKey)
                }}
                className="rounded-lg border border-white/15 px-3 py-2 text-sm text-slate-200 hover:bg-white/10"
              >
                Cancel
              </button>
              <button
                onClick={addAPIKey}
                disabled={validating}
                className="rounded-lg bg-orange-300 px-3 py-2 text-sm font-semibold text-slate-950 hover:bg-orange-200 disabled:opacity-60"
              >
                {validating ? 'Validating...' : 'Validate and Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default APIKeyManager
