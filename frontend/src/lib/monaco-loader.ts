import { loader } from '@monaco-editor/react'

// Keep the editor functional without a runtime dependency on jsDelivr. The
// matching pinned Monaco distribution is copied into public/ by predev and
// prebuild, so workers and language modules resolve from the same origin.
loader.config({ paths: { vs: '/monaco/vs' } })
