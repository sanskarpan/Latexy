import type { Metadata } from 'next'
import UpdatesContent from './UpdatesContent'
import { marketingSocialImage } from '@/lib/marketing-social-image'

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
