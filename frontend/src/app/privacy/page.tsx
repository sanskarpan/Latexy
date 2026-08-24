import type { Metadata } from 'next'
import LegalDoc from '@/components/marketing/LegalDoc'

export const metadata: Metadata = {
  title: 'Privacy Policy — Latexy',
  description: 'How Latexy collects, uses, and safeguards your information.',
}

export default function PrivacyPage() {
  return <LegalDoc file="privacy-policy" />
}
