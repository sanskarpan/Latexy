import type { Metadata } from 'next'
import LegalDoc from '@/components/marketing/LegalDoc'
import { marketingSocialImage } from '@/lib/marketing-social-image'

const title = 'Privacy Policy — Latexy'
const description = 'How Latexy collects, uses, and safeguards your information.'

export const metadata: Metadata = {
  title,
  description,
  alternates: { canonical: '/privacy' },
  openGraph: {
    title,
    description,
    url: '/privacy',
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

export default function PrivacyPage() {
  return <LegalDoc file="privacy-policy" />
}
