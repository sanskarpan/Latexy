import fs from 'node:fs'
import path from 'node:path'
import type { ReactNode } from 'react'

/**
 * Renders a legal markdown document (Privacy, Terms) as an accessible page.
 *
 * The source lives in `frontend/public/legal/<file>.md` (copied from the repo's
 * top-level `legal/`). It is read at build time (Server Component / SSG) so the
 * pages are static, crawlable, and deploy-safe — no client fetch, no flash.
 * A deliberately small markdown subset is supported (headings, lists, bold,
 * links, paragraphs), which is all the legal docs use.
 */

function renderInline(text: string, keyBase: string): ReactNode[] {
  const nodes: ReactNode[] = []
  // Split on **bold** and [text](url) while keeping the delimiters.
  const parts = text.split(/(\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g)
  parts.forEach((part, i) => {
    const key = `${keyBase}-${i}`
    const bold = part.match(/^\*\*([^*]+)\*\*$/)
    const link = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/)
    if (bold) {
      nodes.push(<strong key={key} className="font-semibold text-fg">{bold[1]}</strong>)
    } else if (link) {
      nodes.push(
        <a key={key} href={link[2]} className="text-accent-strong underline hover:text-fg">{link[1]}</a>,
      )
    } else if (part) {
      nodes.push(part)
    }
  })
  return nodes
}

function renderMarkdown(md: string): ReactNode[] {
  const lines = md.replace(/\r\n/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let list: string[] = []
  let para: string[] = []

  const flushPara = (key: string) => {
    if (para.length) {
      blocks.push(<p key={key} className="mt-4 leading-relaxed text-fg-2">{renderInline(para.join(' '), key)}</p>)
      para = []
    }
  }
  const flushList = (key: string) => {
    if (list.length) {
      blocks.push(
        <ul key={key} className="mt-3 list-disc space-y-1.5 pl-5 text-fg-2">
          {list.map((li, i) => <li key={`${key}-${i}`} className="leading-relaxed">{renderInline(li, `${key}-${i}`)}</li>)}
        </ul>,
      )
      list = []
    }
  }

  lines.forEach((raw, i) => {
    const line = raw.trimEnd()
    const key = `b-${i}`
    if (/^#{1,6}\s/.test(line)) {
      flushPara(key); flushList(key)
      const level = line.match(/^(#{1,6})/)![1].length
      const text = line.replace(/^#{1,6}\s+/, '')
      if (level === 1) blocks.push(<h1 key={key} className="font-display text-3xl font-semibold text-fg">{text}</h1>)
      else if (level === 2) blocks.push(<h2 key={key} className="mt-10 font-display text-xl font-semibold text-fg">{renderInline(text, key)}</h2>)
      else blocks.push(<h3 key={key} className="mt-6 font-ui text-base font-semibold text-fg">{renderInline(text, key)}</h3>)
    } else if (/^[-*]\s/.test(line)) {
      flushPara(key)
      list.push(line.replace(/^[-*]\s+/, ''))
    } else if (line.trim() === '') {
      flushPara(key); flushList(key)
    } else {
      flushList(key)
      para.push(line)
    }
  })
  flushPara('b-end'); flushList('b-end')
  return blocks
}

export default function LegalDoc({ file }: { file: 'privacy-policy' | 'terms-of-service' }) {
  const md = fs.readFileSync(path.join(process.cwd(), 'public', 'legal', `${file}.md`), 'utf8')
  return (
    <div className="bg-bg text-fg">
      <article className="mx-auto max-w-3xl px-5 py-16 sm:px-8">
        {renderMarkdown(md)}
      </article>
    </div>
  )
}
