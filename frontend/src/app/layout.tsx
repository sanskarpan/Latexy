import './globals.css'
import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import { NotificationProvider } from '@/components/NotificationProvider'

const inter = Inter({ subsets: ['latin'] })

export const metadata: Metadata = {
  title: 'ATS Resume Optimizer',
  description: 'Optimize your LaTeX resume for ATS systems with AI-powered suggestions',
  keywords: 'resume, ATS, LaTeX, optimization, job application',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body className={inter.className}>
        <NotificationProvider>
          <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50">
            {children}
          </div>
        </NotificationProvider>
      </body>
    </html>
  )
}