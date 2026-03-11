'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { apiClient } from '@/lib/api-client'
import { toast } from 'sonner'
import MultiFormatUpload from '@/components/MultiFormatUpload'

const templates = [
  {
    id: 'blank',
    title: 'Standard Professional',
    description: 'Clean, minimalist design suitable for most industries and roles.',
    content: `\\documentclass[11pt,a4paper]{article}
\\usepackage[margin=0.72in]{geometry}
\\usepackage{enumitem}
\\setlist{nosep}

\\begin{document}
\\begin{center}
{\\LARGE\\textbf{Your Name}} \\\\
\\vspace{1mm}
Your Desired Role \\\\
Email: you@example.com | linkedin.com/in/yourprofile
\\end{center}

\\section*{Summary}
Briefly describe your career goals and key achievements here.

\\section*{Experience}
\\textbf{Role Title, Company Name} \\hfill 2022 - Present
\\begin{itemize}
\\item Key achievement or responsibility
\\item Another important impact you made
\\end{itemize}

\\section*{Skills}
Skill 1, Skill 2, Skill 3, Technology A, Framework B
\\end{document}`,
  },
  {
    id: 'technical',
    title: 'Engineering / CS',
    description: 'Emphasizes projects, technical depth, and measurable outcomes.',
    content: `\\documentclass[10pt,a4paper]{article}
\\usepackage[margin=0.5in]{geometry}
\\usepackage{hyperref}

\\begin{document}
\\begin{center}
    {\\huge \\textbf{Software Engineer Name}} \\\\
    \\href{mailto:email@address.com}{email@address.com} | GitHub: github.com/username | Portfolio: yoursite.com
\\end{center}

\\section*{Technical Skills}
\\textbf{Languages:} Python, Java, C++, TypeScript, SQL \\\\
\\textbf{Tools:} Docker, Kubernetes, AWS, Git, Terraform

\\section*{Experience}
\\textbf{Company Name} | Software Engineer \\hfill Jan 2023 -- Present
\\begin{itemize}
    \\item Designed and implemented microservices using Node.js and Go
    \\item Improved system throughput by 25% through database optimization
\\end{itemize}

\\section*{Projects}
\\textbf{Project Name} | \\textit{Python, React}
\\begin{itemize}
    \\item Open-source tool for data visualization with 500+ stars on GitHub
\\end{itemize}
\\end{document}`,
  },
]

export default function NewResumePage() {
  const router = useRouter()
  const [title, setTitle] = useState('')
  const [selectedTemplate, setSelectedTemplate] = useState('blank')
  const [importMode, setImportMode] = useState(false)
  const [importedContent, setImportedContent] = useState('')
  const [isCreating, setIsCreating] = useState(false)

  const handleCreate = async () => {
    if (!title.trim()) {
      toast.error('Please enter a resume title')
      return
    }

    const content = importMode ? importedContent : templates.find((template) => template.id === selectedTemplate)?.content || ''

    if (importMode && !content) {
      toast.error('Please upload a file first')
      return
    }

    setIsCreating(true)
    try {
      const created = await apiClient.createResume({
        title,
        latex_content: content,
        is_template: false,
      })
      toast.success('Resume created')
      router.push(`/workspace/${created.id}/edit`)
    } catch (error) {
      toast.error('Failed to create resume')
      setIsCreating(false)
    }
  }

  return (
    <div className="content-shell space-y-7 pb-14">
      <header className="flex items-end justify-between gap-4">
        <div>
          <p className="overline">Workspace</p>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight text-white">Create Resume</h1>
          <p className="mt-1 text-sm text-zinc-400">Start from a template or import an existing LaTeX file.</p>
        </div>
        <Link href="/workspace" className="btn-ghost px-4 py-2 text-xs">
          Back to Workspace
        </Link>
      </header>

      <section className="surface-panel edge-highlight p-6">
        <label className="mb-2 block text-xs uppercase tracking-[0.14em] text-zinc-500">Resume Title</label>
        <input
          type="text"
          placeholder="Senior Backend Engineer - Q3 2026"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          className="w-full rounded-xl border border-white/10 bg-black/40 px-4 py-3 text-base text-white outline-none transition focus:border-orange-300/50"
        />
      </section>

      <section className="grid gap-6 lg:grid-cols-2">
        <button
          onClick={() => setImportMode(false)}
          className={`surface-panel edge-highlight p-6 text-left transition ${
            !importMode ? 'border-orange-300/35 bg-orange-300/[0.05]' : 'hover:bg-white/[0.03]'
          }`}
        >
          <p className="text-xs uppercase tracking-[0.14em] text-zinc-500">Mode</p>
          <h2 className="mt-2 text-lg font-semibold text-white">Use Template</h2>
          <p className="mt-1 text-sm text-zinc-400">Use a pre-structured resume layout and start editing immediately.</p>
        </button>

        <button
          onClick={() => setImportMode(true)}
          className={`surface-panel edge-highlight p-6 text-left transition ${
            importMode ? 'border-orange-300/35 bg-orange-300/[0.05]' : 'hover:bg-white/[0.03]'
          }`}
        >
          <p className="text-xs uppercase tracking-[0.14em] text-zinc-500">Mode</p>
          <h2 className="mt-2 text-lg font-semibold text-white">Import File</h2>
          <p className="mt-1 text-sm text-zinc-400">Upload any resume format and continue from current content.</p>
        </button>
      </section>

      <section className="surface-panel edge-highlight overflow-hidden">
        {importMode ? (
          <div className="p-6">
            <MultiFormatUpload onFileUpload={setImportedContent} />
            {importedContent && (
              <p className="mt-3 text-xs uppercase tracking-[0.12em] text-emerald-300">File parsed successfully ({importedContent.length} chars)</p>
            )}
          </div>
        ) : (
          <div className="divide-y divide-white/10">
            {templates.map((template) => (
              <button
                key={template.id}
                onClick={() => setSelectedTemplate(template.id)}
                className={`w-full px-6 py-5 text-left transition hover:bg-white/[0.02] ${
                  selectedTemplate === template.id ? 'bg-white/[0.04]' : ''
                }`}
              >
                <div className="flex items-center justify-between gap-4">
                  <div>
                    <h3 className="text-base font-semibold text-white">{template.title}</h3>
                    <p className="mt-1 text-sm text-zinc-400">{template.description}</p>
                  </div>
                  <span
                    className={`rounded-full border px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.12em] ${
                      selectedTemplate === template.id
                        ? 'border-orange-300/50 bg-orange-300/15 text-orange-200'
                        : 'border-white/15 text-zinc-500'
                    }`}
                  >
                    {selectedTemplate === template.id ? 'Selected' : 'Select'}
                  </span>
                </div>
              </button>
            ))}
          </div>
        )}
      </section>

      <div className="flex justify-end">
        <button
          onClick={handleCreate}
          disabled={isCreating || !title.trim() || (importMode && !importedContent)}
          className="btn-accent px-8 py-3 text-sm font-semibold disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isCreating ? 'Creating Workspace...' : 'Create Resume'}
        </button>
      </div>
    </div>
  )
}
