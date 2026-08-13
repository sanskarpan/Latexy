import './globals.css'
import type { Metadata, Viewport } from 'next'
import { fontVariables } from './fonts'
import { NotificationProvider } from '@/components/NotificationProvider'
import { WebSocketProvider } from '@/components/WebSocketProvider'
import { AuthSync } from '@/components/AuthSync'
import GlobalHeader from '@/components/GlobalHeader'
import EmailVerifyBanner from '@/components/EmailVerifyBanner'
import MarketingFooter from '@/components/marketing/MarketingFooter'
import TenantThemeSync from '@/components/TenantThemeSync'
import WebVitalsReporter from '@/components/WebVitalsReporter'
import { ThemeProvider } from '@/components/theme/ThemeProvider'
import AestheticController from '@/components/theme/AestheticController'
import { Toaster } from 'sonner'
import { FeatureFlagsProvider } from '@/contexts/FeatureFlagsContext'
import { EntitlementsProvider } from '@/contexts/EntitlementsContext'

export const metadata: Metadata = {
  title: 'Latexy | Precision Resume Intelligence',
  description: 'Compile, optimize, and score LaTeX resumes with enterprise-grade speed and ATS precision.',
  keywords: 'LaTeX, ATS, resume optimization, AI, job applications',
  manifest: '/manifest.json',
  appleWebApp: {
    capable: true,
    statusBarStyle: 'black-translucent',
    title: 'Latexy',
  },
}

export const viewport: Viewport = {
  // Mode-aware browser chrome (Typeset grounds — the default marketing surface).
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#FBFAF6' },
    { media: '(prefers-color-scheme: dark)', color: '#141310' },
  ],
}

// Runs before first paint so the theme is set with no flash. Reads the dedicated
// theme cookie (distinct from the auth cookie), else the OS preference. Aesthetic
// defaults to 'typeset'; route-group layouts override it per surface.
const THEME_BOOTSTRAP = `(function(){try{
var r=document.documentElement;
var m=document.cookie.match(/(?:^|; )latexy-theme=(light|dark)/);
var mode=m?m[1]:(window.matchMedia&&window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
r.setAttribute('data-mode',mode);
var p=location.pathname;
var TS=['/','/platform','/pricing','/templates','/resources','/faq','/updates','/developer','/login','/signup','/forgot-password','/reset-password','/verify-email'];
var aes=(TS.indexOf(p)>=0||p.indexOf('/u/')===0||p.indexOf('/r/')===0)?'typeset':'compiler';
r.setAttribute('data-aesthetic',aes);
}catch(e){}})();`

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en" data-aesthetic="typeset" className={fontVariables} suppressHydrationWarning>
      <body className="font-sans antialiased">
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[var(--z-toast)] focus:rounded-[var(--radius-md)] focus:bg-accent focus:px-4 focus:py-2 focus:font-ui focus:text-sm focus:font-semibold focus:text-accent-fg focus:shadow-[var(--shadow-2)] focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-bg"
        >
          Skip to content
        </a>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
        <ThemeProvider>
        <AestheticController />
        <FeatureFlagsProvider>
        <EntitlementsProvider>
        <NotificationProvider>
          <WebSocketProvider>
            <AuthSync />
            <TenantThemeSync />
            <WebVitalsReporter />
            <div className="min-h-screen flex flex-col">
              <EmailVerifyBanner />
              <GlobalHeader />
              <main id="main-content" tabIndex={-1} className="flex-1 focus:outline-none">
                {children}
              </main>
              <MarketingFooter />
            </div>
            <Toaster
              richColors
              closeButton
              position="bottom-right"
              duration={4000}
              toastOptions={{
                className: 'border border-line bg-surface text-fg',
              }}
            />
          </WebSocketProvider>
        </NotificationProvider>
        </EntitlementsProvider>
        </FeatureFlagsProvider>
        </ThemeProvider>
      </body>
    </html>
  )
}
