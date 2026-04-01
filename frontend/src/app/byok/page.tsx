'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useSession } from '@/lib/auth-client'
import APIKeyManager from '@/components/byok/APIKeyManager'
import ProviderSelector from '@/components/byok/ProviderSelector'

interface APIKeyInfo {
  id: string
  provider: string
  key_name: string
  is_active: boolean
}

const points = [
  {
    title: 'Provider-Level Performance',
    text: 'Connect directly to your model provider for lower latency and higher throughput.',
  },
  {
    title: 'Encrypted Secret Storage',
    text: 'Keys are encrypted at rest and only decrypted for runtime provider requests.',
  },
  {
    title: 'Operational Control',
    text: 'Rotate, revoke, and isolate provider access by your own security policy.',
  },
]

export default function BYOKPage() {
  const { data: session, isPending } = useSession()
  const router = useRouter()
  const [userApiKeys, setUserApiKeys] = useState<APIKeyInfo[]>([])

  useEffect(() => {
    if (!isPending && !session) {
      router.push('/login')
    }
  }, [session, isPending, router])

  return (
    <div className="content-shell">
      <div className="space-y-6">
        <section className="surface-panel edge-highlight p-6 sm:p-8 text-center sm:text-left">
          <h1 className="text-3xl font-bold text-white tracking-tight">API Key Management</h1>
          <p className="mt-2 mx-auto sm:mx-0 max-w-2xl text-zinc-400">
            Connect your own model provider keys for direct access and cost-efficient scaling.
          </p>
          <div className="mt-8 grid gap-4 md:grid-cols-3 text-left">
            {points.map((point) => (
              <article key={point.title} className="surface-card p-5 border border-white/5 bg-white/[0.02]">
                <h2 className="text-sm font-bold text-white uppercase tracking-wider">{point.title}</h2>
                <p className="mt-2 text-sm text-zinc-400 leading-relaxed">{point.text}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="surface-panel edge-highlight p-5 sm:p-6">
          <APIKeyManager onKeysChange={setUserApiKeys} />
        </section>

        <section className="surface-panel edge-highlight p-5 sm:p-6">
          <div className="mb-4">
            <h2 className="text-xl font-semibold text-white">Provider Capabilities</h2>
            <p className="text-sm text-zinc-400">
              Explore supported providers, models, and features. Click a provider to see details.
            </p>
          </div>
          <ProviderSelector userApiKeys={userApiKeys} />
        </section>
      </div>
    </div>
  )
}
