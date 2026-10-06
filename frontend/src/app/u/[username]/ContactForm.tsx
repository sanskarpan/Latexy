'use client'

import { FormEvent, useState } from 'react'

import { apiClient } from '@/lib/api-client'

type ContactStatus =
  | { kind: 'idle' }
  | { kind: 'success'; message: string }
  | { kind: 'error'; message: string }

export default function ContactForm({ username }: { username: string }) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)
  const [status, setStatus] = useState<ContactStatus>({ kind: 'idle' })

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setSending(true)
    setStatus({ kind: 'idle' })
    try {
      await apiClient.sendPortfolioContact(username, { name, email, message })
      setName('')
      setEmail('')
      setMessage('')
      setStatus({ kind: 'success', message: 'Your message was sent.' })
    } catch (error) {
      setStatus({
        kind: 'error',
        message: error instanceof Error ? error.message : 'Unable to send your message.',
      })
    } finally {
      setSending(false)
    }
  }

  return (
    <form className="grid max-w-lg grid-cols-2 gap-4" onSubmit={handleSubmit}>
      <div className="flex flex-col gap-1">
        <label htmlFor="portfolio-contact-name" className="text-sm text-gray-500">Name</label>
        <input
          id="portfolio-contact-name"
          name="name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          required
          maxLength={100}
          autoComplete="name"
          placeholder="Your name"
          className="rounded-lg border border-gray-300 bg-transparent px-3 py-2 text-sm outline-none focus:border-blue-500"
        />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="portfolio-contact-email" className="text-sm text-gray-500">Email</label>
        <input
          id="portfolio-contact-email"
          name="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          required
          maxLength={254}
          autoComplete="email"
          type="email"
          placeholder="your@email.com"
          className="rounded-lg border border-gray-300 bg-transparent px-3 py-2 text-sm outline-none focus:border-blue-500"
        />
      </div>
      <div className="col-span-2 flex flex-col gap-1">
        <label htmlFor="portfolio-contact-message" className="text-sm text-gray-500">Message</label>
        <textarea
          id="portfolio-contact-message"
          name="message"
          value={message}
          onChange={(event) => setMessage(event.target.value)}
          required
          maxLength={5000}
          rows={4}
          placeholder="Say hello…"
          className="resize-y rounded-lg border border-gray-300 bg-transparent px-3 py-2 text-sm outline-none focus:border-blue-500"
        />
      </div>
      <div className="col-span-2 flex items-center gap-3">
        <button
          type="submit"
          disabled={sending}
          className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
        >
          {sending ? 'Sending…' : 'Send'}
        </button>
        {status.kind !== 'idle' && (
          <p role="status" className={`text-sm ${status.kind === 'success' ? 'text-green-600' : 'text-red-600'}`}>
            {status.message}
          </p>
        )}
      </div>
    </form>
  )
}
