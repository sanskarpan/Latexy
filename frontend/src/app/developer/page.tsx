'use client'

import { useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { Check, Copy, KeyRound, Trash2, X } from 'lucide-react'
import { useSession } from '@/lib/auth-client'
import {
  apiClient,
  type DeveloperKey,
  type DeveloperKeyCreateResponse,
  type DeveloperUsageResponse,
} from '@/lib/api-client'

type ExampleTab = 'curl' | 'python' | 'node'

const reveal = 'motion-safe:animate-[fade-in-up_.7s_cubic-bezier(.2,.7,.2,1)_both]'

const primaryBtn =
  'inline-flex items-center justify-center rounded-[var(--radius-md)] bg-accent px-5 py-2.5 font-ui text-sm font-semibold uppercase tracking-[0.06em] text-accent-fg transition duration-150 hover:brightness-110 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg disabled:opacity-50 motion-reduce:transition-none'

const ghostBtn =
  'inline-flex items-center justify-center rounded-[var(--radius-md)] border border-line-2 px-4 py-2.5 font-ui text-sm font-semibold uppercase tracking-[0.06em] text-fg transition duration-150 hover:border-accent hover:text-accent-strong focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg disabled:opacity-50 motion-reduce:transition-none'

const fieldInput =
  'w-full rounded-[var(--radius-md)] border border-line-2 bg-surface px-3 py-2.5 font-body text-sm text-fg outline-none transition duration-150 placeholder:text-fg-3 focus-visible:border-accent focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none'

const label = 'font-ui text-[0.62rem] uppercase tracking-[0.16em] text-fg-3'

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
  const [copiedCreatedKey, setCopiedCreatedKey] = useState(false)

  useEffect(() => {
    if (!isPending && !session) {
      router.push(`/login?redirect=${encodeURIComponent(window.location.pathname)}`)
    }
  }, [isPending, router, session])

  // Note: the Bearer token is published to apiClient by <AuthSync /> in the root
  // layout — it is the single source of truth. Mirroring it from here would race
  // AuthSync (child effects run first) and could publish a null token.

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
    setCopiedCreatedKey(false)
    setCreateName('')
    toast.success('Developer API key created')
    await load()
  }

  const handleCopyCreatedKey = async () => {
    if (!createdKey) return
    try {
      await navigator.clipboard.writeText(createdKey.full_key)
      setCopiedCreatedKey(true)
      toast.success('API key copied to clipboard')
    } catch {
      toast.error('Could not copy — select the key and copy manually')
    }
  }

  const handleDismissCreatedKey = () => {
    setCreatedKey(null)
    setCopiedCreatedKey(false)
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
      <div className="mx-auto max-w-6xl px-5 py-16 sm:px-8">
        <div className="border border-line bg-surface p-6 font-ui text-sm text-fg-3 sm:p-8">
          Loading developer portal…
        </div>
      </div>
    )
  }

  return (
    <div className="bg-bg text-fg">
      {/* ── hero ── */}
      <section className={`mx-auto max-w-6xl px-5 py-14 sm:px-8 lg:py-20 ${reveal}`}>
        <span className={label}>The API</span>
        <h1 className="mt-5 max-w-[18ch] text-balance font-display text-[clamp(2.4rem,6vw,4.4rem)] font-semibold leading-[0.98] tracking-[-0.025em] text-fg">
          Compile, optimize, and score — <span className="text-accent">from your own stack.</span>
        </h1>
        <p className="mt-6 max-w-[52ch] font-body text-lg text-fg-2">
          Create stable API keys for compile, optimize, and ATS workflows. Keys are shown only once and
          are rate-limited by your current plan.
        </p>
      </section>

      {/* ── API keys ── */}
      <section className="mx-auto max-w-6xl px-5 pb-14 sm:px-8">
        <div className="mb-6 flex items-baseline gap-3 border-b border-line pb-4">
          <h2 className="font-display text-[clamp(1.5rem,3vw,2.1rem)] font-semibold text-fg">API keys</h2>
          <span className="ml-auto font-ui text-xs text-fg-3">Maximum 5 active keys per account</span>
        </div>

        {/* create */}
        <div className="mb-6 flex flex-col gap-3 sm:flex-row">
          <label htmlFor="new-key-name" className="sr-only">
            New key name
          </label>
          <input
            id="new-key-name"
            value={createName}
            onChange={(event) => setCreateName(event.target.value)}
            placeholder="Production integration"
            className={fieldInput}
          />
          <button
            onClick={handleCreateKey}
            disabled={busyKeyId === 'new' || !createName.trim()}
            className={`${primaryBtn} shrink-0`}
          >
            {busyKeyId === 'new' ? 'Creating…' : 'Create key'}
          </button>
        </div>

        {createdKey && (
          <div className="mb-6 rounded-[var(--radius-md)] border border-accent bg-accent-soft p-4">
            <div className="flex items-start justify-between gap-3">
              <p className="flex items-center gap-2 font-ui text-xs uppercase tracking-[0.14em] text-accent-strong">
                <KeyRound className="h-4 w-4" aria-hidden="true" />
                Copy this key now — it will never be shown again
              </p>
              <button
                onClick={handleDismissCreatedKey}
                className="shrink-0 rounded-[var(--radius-sm)] p-1 text-accent-strong transition duration-150 hover:bg-accent-soft focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none"
                aria-label="Dismiss API key banner"
              >
                <X className="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
            <div className="mt-3 flex flex-col gap-3 sm:flex-row sm:items-stretch">
              <code className="min-w-0 flex-1 overflow-x-auto rounded-[var(--radius-sm)] bg-code-bg p-3 font-ui text-sm text-code-fg">
                {createdKey.full_key}
              </code>
              <button
                onClick={handleCopyCreatedKey}
                className={`${ghostBtn} shrink-0`}
              >
                {copiedCreatedKey ? (
                  <>
                    <Check className="mr-2 h-4 w-4" aria-hidden="true" />
                    Copied
                  </>
                ) : (
                  <>
                    <Copy className="mr-2 h-4 w-4" aria-hidden="true" />
                    Copy
                  </>
                )}
              </button>
            </div>
            <div className="mt-3 flex justify-end">
              <button onClick={handleDismissCreatedKey} className={`${ghostBtn} shrink-0`}>
                I&apos;ve saved it — dismiss
              </button>
            </div>
          </div>
        )}

        {loading ? (
          <div className="border border-line bg-surface p-4 font-ui text-sm text-fg-3">Loading keys…</div>
        ) : keys.length === 0 ? (
          <div className="border border-line bg-surface p-4 font-ui text-sm text-fg-3">
            No developer API keys yet.
          </div>
        ) : (
          <div className="overflow-hidden rounded-[var(--radius-lg)] border border-line">
            {keys.map((key, i) => (
              <div key={key.id} className={`bg-surface p-5 ${i > 0 ? 'border-t border-line' : ''}`}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="font-ui text-sm font-semibold text-fg">{key.key_prefix}</p>
                    <p className="mt-1 font-ui text-xs text-fg-3">
                      {key.request_count} requests · last used{' '}
                      {key.last_used_at ? new Date(key.last_used_at).toLocaleString() : 'never'}
                    </p>
                  </div>
                  <button
                    onClick={() => handleRevoke(key.id)}
                    disabled={busyKeyId === key.id}
                    className="inline-flex items-center gap-2 rounded-[var(--radius-md)] border border-line-2 px-3 py-2 font-ui text-sm font-semibold uppercase tracking-[0.06em] text-err transition duration-150 hover:border-err focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg disabled:opacity-50 motion-reduce:transition-none"
                  >
                    <Trash2 className="h-4 w-4" aria-hidden="true" />
                    Revoke
                  </button>
                </div>
                <div className="mt-4 flex flex-col gap-3 sm:flex-row">
                  <label htmlFor={`rename-${key.id}`} className="sr-only">
                    Rename key
                  </label>
                  <input
                    id={`rename-${key.id}`}
                    value={renaming[key.id] ?? ''}
                    onChange={(event) =>
                      setRenaming((current) => ({ ...current, [key.id]: event.target.value }))
                    }
                    className={fieldInput}
                  />
                  <button
                    onClick={() => handleRename(key.id)}
                    disabled={
                      busyKeyId === key.id ||
                      !renaming[key.id]?.trim() ||
                      renaming[key.id]?.trim() === key.name
                    }
                    className={`${ghostBtn} shrink-0`}
                  >
                    Rename
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* ── usage + docs ── */}
      <section className="mx-auto max-w-6xl px-5 pb-20 sm:px-8">
        <div className="grid gap-8 xl:grid-cols-[1.2fr_1fr]">
          {/* usage */}
          <div className="min-w-0">
            <div className="mb-6 flex items-baseline gap-3 border-b border-line pb-4">
              <h2 className="font-display text-[clamp(1.5rem,3vw,2.1rem)] font-semibold text-fg">Usage</h2>
            </div>
            <p className="mb-5 font-ui text-xs text-fg-3">
              {usage
                ? `Current plan: ${usage.plan_id} · ${usage.daily_limit} requests/day`
                : 'Rate limit history'}
            </p>

            {!usage?.history?.length ? (
              <div className="rounded-[var(--radius-md)] border border-line bg-surface p-5 font-ui text-sm text-fg-3">
                No API requests yet — your daily usage will appear here.
              </div>
            ) : (
              <div className="space-y-4">
                {usage.history.map((point) => {
                  const max = Math.max(...usage.history.map((entry) => entry.count), 1)
                  const width = `${Math.max((point.count / max) * 100, point.count > 0 ? 6 : 0)}%`
                  return (
                    <div key={point.date}>
                      <div className="mb-1.5 flex items-center justify-between font-ui text-xs text-fg-2">
                        <span>{point.date}</span>
                        <span className="text-fg">{point.count}</span>
                      </div>
                      <div className="h-2 rounded-[var(--radius-pill)] bg-surface-2">
                        <div className="h-2 rounded-[var(--radius-pill)] bg-accent" style={{ width }} />
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* docs */}
          <div className="min-w-0">
            <div className="mb-6 flex items-baseline gap-3 border-b border-line pb-4">
              <h2 className="font-display text-[clamp(1.5rem,3vw,2.1rem)] font-semibold text-fg">
                Documentation
              </h2>
            </div>

            <div
              role="tablist"
              aria-label="Code examples"
              className="inline-flex gap-1 rounded-[var(--radius-md)] border border-line bg-surface p-1"
            >
              {(['curl', 'python', 'node'] as ExampleTab[]).map((tab) => (
                <button
                  key={tab}
                  role="tab"
                  aria-selected={activeTab === tab}
                  onClick={() => setActiveTab(tab)}
                  className={`rounded-[var(--radius-sm)] px-4 py-2 font-ui text-xs uppercase tracking-[0.06em] transition duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-bg motion-reduce:transition-none ${
                    activeTab === tab
                      ? 'bg-accent text-accent-fg'
                      : 'text-fg-3 hover:text-fg'
                  }`}
                >
                  {tab}
                </button>
              ))}
            </div>

            <pre className="mt-4 max-w-full overflow-x-auto rounded-[var(--radius-md)] border border-line bg-code-bg p-4 font-ui text-xs leading-relaxed text-code-fg">
              {codeExamples[activeTab]}
            </pre>

            <div className="mt-5 space-y-2 border-t border-line pt-4 font-body text-sm text-fg-2">
              <p className="break-words">
                <span className={label}>Endpoints</span>{' '}
                <code className="font-ui text-xs text-code-fg">POST /api/v1/compile</code>,{' '}
                <code className="font-ui text-xs text-code-fg">POST /api/v1/optimize</code>,{' '}
                <code className="font-ui text-xs text-code-fg">POST /api/v1/ats/score</code>,{' '}
                <code className="font-ui text-xs text-code-fg">GET /api/v1/jobs/{'{job_id}'}</code>.
              </p>
              <p className="break-words">
                <span className={label}>Interactive docs</span>{' '}
                <span className="text-accent-strong">
                  {(process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8030')}/docs
                </span>
              </p>
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}
