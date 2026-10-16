import type { Metadata } from 'next'
import LegalDoc from '@/components/marketing/LegalDoc'
import { marketingSocialImage } from '@/lib/marketing-social-image'

const title = 'Terms of Service — Latexy'
const description = 'The terms that govern your use of Latexy.'

export const metadata: Metadata = {
  title,
  description,
  alternates: { canonical: '/terms' },
  openGraph: {
    title,
    description,
    url: '/terms',
    type: 'website',
    images: [marketingSocialImage],
  },
  twitter: {
    card: 'summary_large_image',
    title,
    description,
    images: [marketingSocialImage.url],
  },
}

export default function TermsPage() {
  return <LegalDoc file="terms-of-service" />
}
