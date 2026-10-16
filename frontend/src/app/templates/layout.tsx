import type { Metadata } from 'next'
import type { ReactNode } from 'react'
import { marketingSocialImage } from '@/lib/marketing-social-image'

const description =
  'Browse professional resume, academic, and presentation templates. Preview a LaTeX layout, then use it to start building with Latexy.'

export const metadata: Metadata = {
  title: 'LaTeX Templates for Resumes and Documents | Latexy',
  description,
  alternates: { canonical: '/templates' },
  openGraph: {
    title: 'LaTeX templates, ready to use | Latexy',
    description,
    url: '/templates',
    type: 'website',
    images: [marketingSocialImage],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'LaTeX templates, ready to use | Latexy',
    description,
    images: [marketingSocialImage.url],
  },
}

export default function TemplatesLayout({ children }: { children: ReactNode }) {
  return children
}
