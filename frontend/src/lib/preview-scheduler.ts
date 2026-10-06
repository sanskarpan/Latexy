/** One admitted render and one replaceable latest edit; explicit exports stay outside. */
export class PreviewScheduler {
  private pending: { source: string; editedAt: number } | null = null
  private running: { source: string; startedAt: number; jobId: string | null } | null = null
  private timer: ReturnType<typeof setTimeout> | null = null
  private enabled = false
  private blocked = false
  private disposed = false
  private lastAttempted: string | null = null
  private lastTerminal: string | null = null
  private delay = 200

  constructor(private submit: (source: string, editedAt: number) => Promise<string | null>, private now = () => performance.now()) {}

  update(enabled: boolean, blocked: boolean) {
    this.enabled = enabled
    this.blocked = blocked
    if (!enabled) this.pending = null
    this.drain()
  }

  request(source: string, editedAt = this.now(), force = false) {
    if (!this.enabled || this.disposed || !source.trim()) return
    if (force) this.lastAttempted = null
    if (source === this.running?.source) this.pending = null
    else this.pending = { source, editedAt }
    this.drain()
  }

  complete(jobId: string) {
    this.lastTerminal = jobId
    if (this.running?.jobId !== jobId) return
    this.delay = Math.max(150, Math.min(250, 150 + (this.now() - this.running.startedAt) * .05))
    this.running = null
    this.drain()
  }

  dispose() {
    this.disposed = true
    this.pending = null
    if (this.timer) clearTimeout(this.timer)
  }

  activate() { this.disposed = false }

  private drain() {
    if (this.timer) clearTimeout(this.timer)
    this.timer = null
    if (this.disposed || !this.enabled || this.blocked || this.running || !this.pending) return
    if (this.pending.source === this.lastAttempted) { this.pending = null; return }
    const wait = Math.max(0, this.pending.editedAt + this.delay - this.now())
    this.timer = setTimeout(() => { this.timer = null; void this.start() }, wait)
  }

  private async start() {
    if (this.disposed || !this.enabled || this.blocked || this.running || !this.pending) return
    const source = this.pending.source
    const editedAt = this.pending.editedAt
    this.pending = null
    this.lastAttempted = source
    const invocation = { source, startedAt: this.now(), jobId: null as string | null }
    this.running = invocation // includes the admission/ACK window
    try {
      invocation.jobId = await this.submit(source, editedAt)
      if (!invocation.jobId && this.running === invocation) this.running = null
      else if (invocation.jobId && invocation.jobId === this.lastTerminal) this.complete(invocation.jobId)
    } catch {
      // Caller owns quota/auth/network feedback. Never automatically retry an
      // ambiguous admission or consume another quota unit for the same edit.
      if (this.running === invocation) this.running = null
    }
    this.drain()
  }
}
