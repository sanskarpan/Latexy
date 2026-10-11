'use client'

import dynamic from 'next/dynamic'
import type { Ref } from 'react'
import type { LaTeXEditorProps, LaTeXEditorRef } from './LaTeXEditor'

type Props = LaTeXEditorProps & { editorRef: Ref<LaTeXEditorRef> }

// An explicit prop carries the imperative handle through Next's loading boundary.
// Resume mode never downloads or initializes the source editor until selected.
const DeferredLaTeXEditor = dynamic<Props>(async () => {
  const { default: Editor } = await import('./LaTeXEditor')
  return function LoadedEditor({ editorRef, ...props }: Props) {
    return <Editor ref={editorRef} {...props} />
  }
}, { ssr: false, loading: () => <div role="status" className="p-4 text-sm text-fg-3">Loading source editor…</div> })

export default DeferredLaTeXEditor
