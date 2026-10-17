import type { Metadata } from 'next'
import { marketingSocialImage } from '@/lib/marketing-social-image'
import UpdatesContent from './UpdatesContent'

// This route is entirely local, public content. Avoid streaming it behind the
// root loading boundary so browsers without JavaScript receive the page itself.
export const dynamic = 'force-static'

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