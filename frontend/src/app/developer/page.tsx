'use client'

import { useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { useSession } from '@/lib/auth-client'
import {
  apiClient,
  type DeveloperKey,
  type DeveloperKeyCreateResponse,
  type DeveloperUsageResponse,
} from '@/lib/api-client'

type ExampleTab = 'curl' | 'python' | 'node'

export default function DeveloperPage() {
  const { data: session, isPending } = useSession()
  const sessionToken = session?.session?.token ?? null
  const router = useRouter()

  const [loading, setLoading] = useState(true)
  const [keys, setKeys] = useState<DeveloperKey[]>([])
  const [usage, setUsage] = useState<DeveloperUsageResponse | null>(null)
  const [createName, setCreateName] = useState('')
  const [createdKey, setCreatedKey] = useState<DeveloperKeyCreateResponse | null>(null)
  const [activeTab, setActiveTab] = useState<ExampleTab>('curl')
  const [busyKeyId, setBusyKeyId] = useState<string | null>(null)
  const [renaming, setRenaming] = useState<Record<string, string>>({})

  useEffect(() => {
    if (!isPending && !session) {
      router.push('/login?next=/developer')
    }
  }, [isPending, router, session])

  useEffect(() => {
    apiClient.setAuthToken(sessionToken)
  }, [sessionToken])

  const load = async () => {
    if (!sessionToken) return
    setLoading(true)
    const [keysResult, usageResult] = await Promise.all([
      apiClient.getDeveloperKeys(),
      apiClient.getDeveloperUsage(),
    ])
    if (keysResult.success && keysResult.data) {
      setKeys(keysResult.data)
      setRenaming(Object.fromEntries(keysResult.data.map((key) => [key.id, key.name])))
    } else {
      toast.error(keysResult.error || 'Failed to load developer keys')
    }
    if (usageResult.success && usageResult.data) {
      setUsage(usageResult.data)
    } else {
      toast.error(usageResult.error || 'Failed to load developer usage')
    }
    setLoading(false)
  }

  useEffect(() => {
    if (sessionToken) {
      load()
    }
  }, [sessionToken]) // eslint-disable-line react-hooks/exhaustive-deps

  const exampleKey = 'YOUR_LATEXY_API_KEY'

  const codeExamples = useMemo(() => ({
    curl: `curl -X POST "${process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8030'}/api/v1/compile" \\
  -H "Authorization: Bearer ${exampleKey}" \\
  -H "Content-Type: application/json" \\
  -d '{"latex_content":"\\\\documentclass{article}\\\\begin{document}Hello, Latexy!\\\\end{document}","compiler":"pdflatex"}'`,
    python: `import requests

resp = requests.post(
    "${process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8030'}/api/v1/ats/score",
    headers={"Authorization": "Bearer ${exampleKey}"},
    json={
        "latex_content": r"\\\\documentclass{article}\\\\begin{document}Python engineer\\\\end{document}",
        "job_description": "FastAPI developer with PostgreSQL experience",
    },
    timeout=30,
)
print(resp.json())`,
    node: `const response = await fetch("${process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8030'}/api/v1/jobs/<job_id>", {
  headers: {
    Authorization: "Bearer ${exampleKey}",
  },
});

const payload = await response.json();
console.log(payload);`,
  }), [exampleKey])

  const handleCreateKey = async () => {
    if (!createName.trim()) return
    setBusyKeyId('new')
    const result = await apiClient.createDeveloperKey(createName.trim())
    setBusyKeyId(null)
    if (!result.success || !result.data) {
      toast.error(result.error || 'Failed to create API key')
      return
    }
    setCreatedKey(result.data)
    setCreateName('')
    toast.success('Developer API key created')
    await load()
  }

  const handleRename = async (keyId: string) => {
    const nextName = renaming[keyId]?.trim()
    if (!nextName) return
    setBusyKeyId(keyId)
    const result = await apiClient.renameDeveloperKey(keyId, nextName)
    setBusyKeyId(null)
    if (!result.success) {
      toast.error(result.error || 'Failed to rename key')
      return
    }
    toast.success('Key renamed')
    await load()
  }

  const handleRevoke = async (keyId: string) => {
    if (!confirm('Revoke this developer API key?')) return
    setBusyKeyId(keyId)
    const result = await apiClient.revokeDeveloperKey(keyId)
    setBusyKeyId(null)
    if (!result.success) {
      toast.error(result.error || 'Failed to revoke key')
      return
    }
    toast.success('Key revoked')
    await load()
  }

  if (isPending || !session) {
    return (
      <div className="content-shell">
        <div className="surface-panel edge-highlight p-6 sm:p-8 text-slate-300">
          Loading developer portal...
        </div>
      </div>
    )
  }

  return (
    <div className="content-shell">
      <div className="space-y-6">
        <section className="surface-panel edge-highlight p-6 sm:p-8">
          <h1 className="text-3xl font-bold text-white tracking-tight">Developer API</h1>
          <p className="mt-2 max-w-2xl text-zinc-400">
            Create stable API keys for compile, optimize, and ATS workflows. Keys are shown only once and are rate-limited by your current plan.
          </p>
        </section>

        <section className="surface-panel edge-highlight p-5 sm:p-6">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-white">API keys</h2>
              <p className="mt-1 text-sm text-slate-400">Maximum 5 active keys per account.</p>
            </div>
          </div>

          <div className="mb-5 flex flex-col gap-3 sm:flex-row">
            <input
              value={createName}
              onChange={(event) => setCreateName(event.target.value)}
              placeholder="Production integration"
              className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none placeholder:text-slate-500"
            />
            <button
              onClick={handleCreateKey}
              disabled={busyKeyId === 'new' || !createName.trim()}
              className="rounded-lg bg-orange-300 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-orange-200 disabled:opacity-60"
            >
              {busyKeyId === 'new' ? 'Creating...' : 'Create key'}
            </button>
          </div>

          {createdKey && (
            <div className="mb-5 rounded-xl border border-amber-300/30 bg-amber-300/10 p-4">
              <p className="text-sm font-semibold text-amber-100">Copy this key now. It will never be shown again.</p>
              <code className="mt-3 block overflow-x-auto rounded-lg bg-black/50 p-3 text-sm text-white">{createdKey.full_key}</code>
            </div>
          )}

          {loading ? (
            <div className="rounded-xl border border-white/10 bg-slate-950/60 p-4 text-slate-300">Loading keys...</div>
          ) : (
            <div className="space-y-3">
              {keys.length === 0 ? (
                <div className="rounded-xl border border-white/10 bg-slate-950/60 p-4 text-sm text-slate-400">
                  No developer API keys yet.
                </div>
              ) : (
                keys.map((key) => (
                  <div key={key.id} className="rounded-xl border border-white/10 bg-slate-950/60 p-4">
                    <div className="flex flex-wrap items-start justify-between gap-3">
                      <div>
                        <p className="text-sm font-semibold text-white">{key.key_prefix}</p>
                        <p className="mt-1 text-xs text-slate-400">
                          {key.request_count} requests • last used {key.last_used_at ? new Date(key.last_used_at).toLocaleString() : 'never'}
                        </p>
                      </div>
                      <button
                        onClick={() => handleRevoke(key.id)}
                        disabled={busyKeyId === key.id}
                        className="rounded-lg border border-rose-300/30 bg-rose-300/10 px-3 py-2 text-sm text-rose-100 hover:bg-rose-300/20 disabled:opacity-60"
                      >
                        Revoke
                      </button>
                    </div>
                    <div className="mt-3 flex flex-col gap-3 sm:flex-row">
                      <input
                        value={renaming[key.id] ?? ''}
                        onChange={(event) => setRenaming((current) => ({ ...current, [key.id]: event.target.value }))}
                        className="w-full rounded-lg border border-white/10 bg-black/40 px-3 py-2 text-sm text-white outline-none"
                      />
                      <button
                        onClick={() => handleRename(key.id)}
                        disabled={busyKeyId === key.id}
                        className="rounded-lg border border-white/15 px-4 py-2 text-sm text-slate-100 hover:bg-white/10 disabled:opacity-60"
                      >
                        Rename
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}
        </section>

        <section className="grid gap-6 xl:grid-cols-[1.2fr_1fr]">
          <div className="surface-panel edge-highlight p-5 sm:p-6">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <div>
                <h2 className="text-lg font-semibold text-white">Usage</h2>
                <p className="mt-1 text-sm text-slate-400">
                  {usage ? `Current plan: ${usage.plan_id} • ${usage.daily_limit} requests/day` : 'Rate limit history'}
                </p>
              </div>
            </div>

            <div className="space-y-3">
              {(usage?.history || []).map((point) => {
                const max = Math.max(...(usage?.history.map((entry) => entry.count) || [1]), 1)
                const width = `${Math.max((point.count / max) * 100, point.count > 0 ? 6 : 0)}%`
                return (
                  <div key={point.date}>
                    <div className="mb-1 flex items-center justify-between text-sm text-slate-300">
                      <span>{point.date}</span>
                      <span>{point.count}</span>
                    </div>
                    <div className="h-2 rounded-full bg-white/10">
                      <div className="h-2 rounded-full bg-orange-300" style={{ width }} />
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          <div className="surface-panel edge-highlight p-5 sm:p-6">
            <h2 className="text-lg font-semibold text-white">Documentation</h2>
            <div className="mt-4 inline-flex rounded-xl border border-white/10 bg-slate-950/70 p-1">
              {(['curl', 'python', 'node'] as ExampleTab[]).map((tab) => (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  className={`rounded-lg px-4 py-2 text-sm capitalize ${activeTab === tab ? 'bg-orange-300 text-slate-950' : 'text-slate-300'}`}
                >
                  {tab}
                </button>
              ))}
            </div>
            <pre className="mt-4 overflow-x-auto rounded-xl border border-white/10 bg-black/50 p-4 text-xs text-slate-200">
              {codeExamples[activeTab]}
            </pre>
            <div className="mt-4 space-y-2 text-sm text-slate-300">
              <p>Available endpoints: `POST /api/v1/compile`, `POST /api/v1/optimize`, `POST /api/v1/ats/score`, `GET /api/v1/jobs/{'{job_id}'}`.</p>
              <p>Interactive backend docs: {(process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8030')}/docs</p>
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
