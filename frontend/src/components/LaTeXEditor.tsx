'use client'

import { useImperativeHandle, useRef, forwardRef } from 'react'
import Editor from '@monaco-editor/react'

export interface LaTeXEditorRef {
  setValue: (value: string) => void
  getValue: () => string
}

interface LaTeXEditorProps {
  value: string
  onChange: (value: string) => void
  readOnly?: boolean
}

const SAMPLE_LATEX = `\\documentclass[letterpaper,11pt]{article}
\\usepackage[empty]{fullpage}
\\usepackage[hidelinks]{hyperref}
\\usepackage{enumitem}

\\begin{document}

\\begin{center}
    \\textbf{\\Large Your Name} \\\\
    \\vspace{2pt}
    (555) 123-4567 $|$ your.email@example.com $|$ linkedin.com/in/yourname
\\end{center}

\\section*{Experience}
\\textbf{Your Job Title} \\hfill \\textbf{Month Year -- Present} \\\\
\\textit{Company Name} \\\\
\\begin{itemize}[leftmargin=*,noitemsep]
    \\item Achievement or responsibility with quantifiable results
    \\item Another key accomplishment that demonstrates your value
    \\item Technical skill or project that's relevant to your target role
\\end{itemize}

\\section*{Education}
\\textbf{Your Degree} \\hfill \\textbf{Year} \\\\
\\textit{University Name}

\\section*{Skills}
\\textbf{Technical Skills:} List your relevant technical skills here \\\\
\\textbf{Languages:} Programming languages you know

\\end{document}`

const LaTeXEditor = forwardRef<LaTeXEditorRef, LaTeXEditorProps>(function LaTeXEditor({ value, onChange, readOnly = false }, ref) {
  const editorRef = useRef<any>(null)

  useImperativeHandle(ref, () => ({
    setValue(content: string) {
      const model = editorRef.current?.getModel()
      if (!model) return
      model.setValue(content)
      editorRef.current?.revealLine(model.getLineCount())
    },
    getValue() {
      return editorRef.current?.getValue() ?? ''
    },
  }))

  const handleEditorDidMount = (editor: any, monaco: any) => {
    editorRef.current = editor

    monaco.languages.register({ id: 'latex' })
    monaco.languages.setMonarchTokensProvider('latex', {
      tokenizer: {
        root: [
          [/\\[a-zA-Z@]+/, 'keyword'],
          [/\\[^a-zA-Z@]/, 'keyword'],
          [/\{/, 'delimiter.bracket'],
          [/\}/, 'delimiter.bracket'],
          [/\[/, 'delimiter.square'],
          [/\]/, 'delimiter.square'],
          [/%.*$/, 'comment'],
          [/\$\$/, 'string.math'],
          [/\$/, 'string.math'],
        ],
      },
    })

    monaco.editor.defineTheme('latexy-dark', {
      base: 'vs-dark',
      inherit: true,
      rules: [
        { token: 'keyword', foreground: 'f59e0b' },
        { token: 'comment', foreground: '71717a', fontStyle: 'italic' },
        { token: 'string.math', foreground: 'fb7185' },
        { token: 'delimiter.bracket', foreground: 'c084fc' },
        { token: 'delimiter.square', foreground: 'c084fc' },
      ],
      colors: {
        'editor.background': '#07090f',
        'editor.lineHighlightBackground': '#0f1118',
      },
    })

    monaco.editor.setTheme('latexy-dark')
  }

  return (
    <div className="flex h-full flex-col">
      {!value ? (
        <div className="flex flex-1 flex-col items-center justify-center px-6 text-center">
          <p className="text-sm uppercase tracking-[0.14em] text-zinc-500">Empty Document</p>
          <p className="mt-2 max-w-sm text-sm text-zinc-400">No LaTeX source is loaded. Insert a sample template or start writing manually.</p>
          <button onClick={() => onChange(SAMPLE_LATEX)} className="btn-ghost mt-4 px-4 py-2 text-xs">
            Insert Sample Resume
          </button>
        </div>
      ) : (
        <div className="min-h-0 flex-1">
          <Editor
            height="100%"
            defaultLanguage="latex"
            value={value}
            onChange={(nextValue) => onChange(nextValue || '')}
            onMount={handleEditorDidMount}
            options={{
              minimap: { enabled: false },
              fontSize: 13,
              lineNumbers: 'on',
              wordWrap: 'on',
              scrollBeyondLastLine: false,
              automaticLayout: true,
              tabSize: 2,
              insertSpaces: true,
              renderLineHighlight: 'line',
              cursorBlinking: 'smooth',
              cursorSmoothCaretAnimation: 'on',
              smoothScrolling: true,
              contextmenu: false,
              readOnly,
            }}
          />
        </div>
      )}

      <div className="flex items-center justify-between border-t border-white/10 bg-black/25 px-3 py-2 text-[10px] uppercase tracking-[0.12em] text-zinc-500">
        <span>{readOnly ? 'Editor locked while run is active' : 'LaTeX editor ready'}</span>
        <span>{value.length} chars</span>
      </div>
    </div>
  )
})

export default LaTeXEditor
