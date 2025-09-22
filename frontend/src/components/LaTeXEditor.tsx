'use client'

import { useEffect, useRef } from 'react'
import Editor from '@monaco-editor/react'
import { FileCode } from 'lucide-react'

interface LaTeXEditorProps {
  value: string
  onChange: (value: string) => void
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

export default function LaTeXEditor({ value, onChange }: LaTeXEditorProps) {
  const editorRef = useRef(null)

  const handleEditorDidMount = (editor: any, monaco: any) => {
    editorRef.current = editor

    // Configure LaTeX language support
    monaco.languages.register({ id: 'latex' })
    
    // Define LaTeX tokens
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
        ]
      }
    })

    // Define theme
    monaco.editor.defineTheme('latex-theme', {
      base: 'vs',
      inherit: true,
      rules: [
        { token: 'keyword', foreground: '0ea5e9', fontStyle: 'bold' },
        { token: 'comment', foreground: '64748b', fontStyle: 'italic' },
        { token: 'string.math', foreground: 'dc2626' },
        { token: 'delimiter.bracket', foreground: '7c3aed' },
        { token: 'delimiter.square', foreground: '7c3aed' },
      ],
      colors: {
        'editor.background': '#ffffff',
        'editor.lineHighlightBackground': '#f8fafc',
      }
    })

    monaco.editor.setTheme('latex-theme')
  }

  const handleChange = (newValue: string | undefined) => {
    onChange(newValue || '')
  }

  const insertSample = () => {
    onChange(SAMPLE_LATEX)
  }

  return (
    <div className="h-full flex flex-col">
      {!value && (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <FileCode className="w-12 h-12 text-secondary-300 mx-auto mb-4" />
            <p className="text-secondary-500 mb-4">No LaTeX content yet</p>
            <button
              onClick={insertSample}
              className="btn-primary px-4 py-2 text-sm"
            >
              Insert Sample Resume
            </button>
          </div>
        </div>
      )}
      
      {value && (
        <div className="flex-1">
          <Editor
            height="100%"
            defaultLanguage="latex"
            value={value}
            onChange={handleChange}
            onMount={handleEditorDidMount}
            options={{
              minimap: { enabled: false },
              fontSize: 14,
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
            }}
          />
        </div>
      )}
      
      {value && (
        <div className="flex items-center justify-between p-3 border-t border-secondary-200 text-xs text-secondary-500">
          <span>LaTeX Editor</span>
          <span>{value.length} characters</span>
        </div>
      )}
    </div>
  )
}