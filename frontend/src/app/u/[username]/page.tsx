import { notFound } from 'next/navigation'
import type { Metadata } from 'next'
import { apiClient, type PortfolioResponse } from '@/lib/api-client'
import ContactForm from './ContactForm'

interface PageProps {
  params: Promise<{ username: string }>
}

export async function generateMetadata({ params }: PageProps): Promise<Metadata> {
  const { username } = await params
  return {
    title: `${username} — Portfolio`,
    description: `Public portfolio for ${username} on Latexy`,
  }
}

async function fetchPortfolio(username: string): Promise<PortfolioResponse | null> {
  try {
    return await apiClient.getPortfolio(username)
  } catch {
    return null
  }
}

export default async function PortfolioPage({ params }: PageProps) {
  const { username } = await params
  const portfolio = await fetchPortfolio(username)

  if (!portfolio) notFound()

  const { name, tagline, theme, resumes } = portfolio

  const themeClass =
    theme === 'dark'
      ? 'bg-gray-950 text-gray-100'
      : theme === 'professional'
        ? 'bg-slate-50 text-slate-900'
        : 'bg-white text-gray-900'

  const accentClass = theme === 'dark' ? 'text-blue-400' : 'text-blue-600'

  const cardClass =
    theme === 'dark'
      ? 'bg-gray-900 border-gray-800'
      : theme === 'professional'
        ? 'bg-white border-slate-200 shadow-sm'
        : 'bg-gray-50 border-gray-200'

  const headerClass =
    theme === 'dark'
      ? 'border-gray-800 bg-gray-950/90 backdrop-blur'
      : 'border-gray-200 bg-white/90 backdrop-blur'

  return (
    <div className={`min-h-screen ${themeClass}`}>
      {/* Header */}
      <header className={`sticky top-0 z-50 border-b ${headerClass}`}>
        <div className="mx-auto max-w-5xl px-6 h-14 flex items-center justify-between">
          <span className="font-bold text-lg">{name || username}</span>
          <nav className="flex gap-6 text-sm">
            <a href="#resumes" className={`${accentClass} hover:underline`}>Resumes</a>
            <a href="#contact" className={`${accentClass} hover:underline`}>Contact</a>
          </nav>
        </div>
      </header>

      {/* Hero */}
      <section className="mx-auto max-w-5xl px-6 py-16">
        <h1 className="text-4xl font-extrabold tracking-tight sm:text-5xl">
          {name || username}
        </h1>
        {tagline && (
          <p className="mt-4 text-xl text-gray-500 max-w-xl">{tagline}</p>
        )}
      </section>

      {/* Resumes */}
      <section className="mx-auto max-w-5xl px-6 pb-12" id="resumes">
        <h2 className="text-2xl font-bold mb-6 pb-2 border-b border-current/20">
          Resumes
        </h2>
        {resumes.length === 0 ? (
          <p className="text-gray-500">No public resumes yet.</p>
        ) : (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {resumes.map((r) => (
              <div
                key={r.id}
                className={`rounded-xl border p-5 transition hover:border-blue-500 ${cardClass}`}
              >
                <p className="font-semibold">{r.title}</p>
                <p className="text-sm text-gray-500 mt-1">
                  Updated{' '}
                  {new Date(r.updated_at).toLocaleDateString('en-US', {
                    month: 'short',
                    year: 'numeric',
                  })}
                </p>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Contact */}
      <section className="mx-auto max-w-5xl px-6 pb-16" id="contact">
        <h2 className="text-2xl font-bold mb-6 pb-2 border-b border-current/20">
          Contact
        </h2>
        <ContactForm />
      </section>

      {/* Footer */}
      <footer className="text-center py-8 text-sm text-gray-500">
        Powered by{' '}
        <a
          href="https://latexy.io"
          target="_blank"
          rel="noopener noreferrer"
          className={accentClass}
        >
          Latexy
        </a>
      </footer>
    </div>
  )
}
