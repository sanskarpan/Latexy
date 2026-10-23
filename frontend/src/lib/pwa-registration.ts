type OptionalWorkbox = { register: () => unknown }

const attempted = new WeakSet<object>()

// A worker is an enhancement: unsupported APIs and browser policy denial must
// leave the online application usable. Keep the original Workbox object and
// its events intact, and attempt registration only once per actual instance.
export function registerOptionalWorker(workbox: unknown): void {
  if (!workbox || typeof workbox !== 'object' ||
      typeof (workbox as Partial<OptionalWorkbox>).register !== 'function' ||
      attempted.has(workbox)) return

  attempted.add(workbox)
  try {
    void Promise.resolve((workbox as OptionalWorkbox).register()).catch(() => undefined)
  } catch {
    // Some policy implementations throw before returning a promise.
  }
}
