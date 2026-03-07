import './globals.css'
import type { Metadata } from 'next'
import { NotificationProvider } from '@/components/NotificationProvider'
import { WebSocketProvider } from '@/components/WebSocketProvider'
import { AuthSync } from '@/components/AuthSync'
import GlobalHeader from '@/components/GlobalHeader'
import MarketingFooter from '@/components/marketing/MarketingFooter'
import { Toaster } from 'sonner'

export const metadata: Metadata = {
  title: 'Latexy | Precision Resume Intelligence',
  description: 'Compile, optimize, and score LaTeX resumes with enterprise-grade speed and ATS precision.',
  keywords: 'LaTeX, ATS, resume optimization, AI, job applications',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="font-sans antialiased">
        <NotificationProvider>
          <WebSocketProvider>
            <AuthSync />
            <div className="min-h-screen enterprise-grid noise-overlay flex flex-col">
              <GlobalHeader />
              <main className="flex-1">
                {children}
              </main>
              <MarketingFooter />
            </div>
            <Toaster
              richColors
              position="top-right"
              toastOptions={{
                className: 'border border-white/10 bg-zinc-950 text-zinc-100',
              }}
            />
          </WebSocketProvider>
        </NotificationProvider>
      </body>
    </html>
  )
}
