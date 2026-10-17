import type { Metadata } from 'next'
import { marketingSocialImage } from '@/lib/marketing-social-image'
import UpdatesContent from './UpdatesContent'

// Keep this route request-rendered so the root layout can use the locale
// negotiated by middleware. The route-level loading boundary renders the full
// changelog for browsers that cannot run JavaScript while the page resolves.

const description = 'Read Latexy product and engineering updates, with release dates and notes on what changed.'

export const metadata: Metadata = {
  title: 'Product Updates and Release Notes | Latexy',
  description,
  alternates: { canonical: '/updates' },
  openGraph: {
    title: 'Product updates and platform progress | Latexy',
    description,
    url: '/updates',
    type: 'website',
    images: [marketingSocialImage],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'Product updates and platform progress | Latexy',
    description,
    images: [marketingSocialImage.url],
  },
}

export default function UpdatesPage() {
  return <UpdatesContent />
}

