import UpdatesContent from './UpdatesContent'

// Render complete local release notes while the route resolves, including without JavaScript.
export default function Loading() {
  return <UpdatesContent staticFallback />
}
