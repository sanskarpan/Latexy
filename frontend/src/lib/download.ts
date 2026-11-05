/** Start a browser download and release its Blob URL after navigation consumes it. */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()

  // Revoking synchronously can cancel the download before Firefox consumes the
  // object URL. A short delay also keeps the URL lifetime bounded.
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export type JobTerminalStatus = 'completed' | 'failed' | 'cancelled' | 'timeout' | 'inactive'

/** Bounded poll for a job terminal state. Never throws: transport errors count as retries. */
export async function pollJobCompletion(
  getJobState: (jobId: string) => Promise<{ status?: string } | null>,
  jobId: string,
  options?: { intervalMs?: number; maxWaitMs?: number; isActive?: () => boolean; wait?: (ms: number) => Promise<void> },
): Promise<JobTerminalStatus> {
  const intervalMs = options?.intervalMs ?? 3000
  const maxWaitMs = options?.maxWaitMs ?? 180000
  const isActive = options?.isActive ?? (() => true)
  const wait = options?.wait ?? ((ms: number) => new Promise<void>((resolve) => { setTimeout(resolve, ms) }))
  const deadline = Date.now() + maxWaitMs
  for (;;) {
    if (!isActive()) return 'inactive'
    await wait(intervalMs)
    if (!isActive()) return 'inactive'
    let status: string | undefined
    try {
      status = (await getJobState(jobId))?.status ?? undefined
    } catch {
      status = undefined
    }
    if (status === 'completed' || status === 'failed' || status === 'cancelled') return status
    if (Date.now() >= deadline) return 'timeout'
  }
}
