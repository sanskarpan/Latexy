const ALLOWED_ORIGINS = new Set(['https://latexy.xyz', 'http://localhost:5180', 'http://127.0.0.1:5180'])

export async function assertCompanionAvailable(appOrigin, fetcher = fetch) {
  if (!ALLOWED_ORIGINS.has(appOrigin)) throw new Error('Select a supported Latexy address in extension settings.')
  const response = await fetcher(`${appOrigin}/api/extension/entitlements`, {
    credentials: 'include', cache: 'no-store', signal: AbortSignal.timeout(8000),
  })
  if (!response.ok) throw new Error('Open Latexy and sign in to check Job Companion access, then try again.')
  const data = await response.json()
  if (data?.available !== true) throw new Error('Job Companion is currently unavailable for your plan.')
}
