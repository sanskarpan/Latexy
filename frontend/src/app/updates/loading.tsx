import UpdatesContent from './UpdatesContent'

// The changelog is already local, complete content. Keep its server fallback
// useful for no-JavaScript browsers while the route resolves.
export default function Loading() {
  return <UpdatesContent staticFallback />
}
