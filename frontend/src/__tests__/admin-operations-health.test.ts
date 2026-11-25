import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

const read = (path: string) => readFileSync(new URL(path, import.meta.url), 'utf8')

describe('admin worker and container health', () => {
  const component = read('../components/admin/AdminOperationsHealth.tsx')
  const operations = read('../components/admin/AdminOperations.tsx')
  const apiClient = read('../lib/api-client.ts')

  it('renders per-worker status, CPU, memory, last-seen and queue ownership', () => {
    expect(component).toContain('Worker &amp; container health')
    expect(component).toContain('AdminWorkerHealthComponent')
    expect(component).toContain('cpu_percent')
    expect(component).toContain('memory_percent')
    expect(component).toContain('memory_mb')
    expect(component).toContain('last_seen')
    expect(component).toContain('queues.length')
    expect(component).toContain('stale_after_seconds')
    expect(component).toContain('missing_metrics')
    expect(component).toContain('unowned_queues')
    expect(component).toContain('stale')
    expect(component).toContain('WorkerCard')
    expect(apiClient).toContain('AdminWorkerHealthComponent')
    expect(apiClient).toContain('AdminWorkerHealth')
    expect(operations).toContain("import AdminOperationsHealth from '@/components/admin/AdminOperationsHealth'")
    expect(operations).toContain('<AdminOperationsHealth refreshKey={refreshKey} />')
  })

  it('links to provider consoles and shows the last check time', () => {
    expect(component).toContain('Provider consoles')
    expect(component).toContain('https://modal.com/apps')
    expect(component).toContain('https://console.upstash.com')
    expect(component).toContain('https://console.neon.tech')
    expect(component).toContain('https://dash.cloudflare.com')
    expect(component).toContain('last_check_at')
    expect(component).toContain('Checked {formatAge(workers.last_check_at)}')
    expect(component).toContain('target="_blank"')
    expect(component).toContain('rel="noreferrer"')
  })

  it('never renders credentials, host identifiers or document content', () => {
    for (const forbidden of [
      'REDIS_PASSWORD',
      'CELERY_BROKER_URL',
      'MINIO_SECRET_KEY',
      'container_id',
      'hostname',
      'latex_content',
      'customer_email',
    ]) {
      expect(component).not.toContain(forbidden)
    }
  })
})
