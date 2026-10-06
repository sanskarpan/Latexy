'use client'

interface SessionLoadErrorProps {
  area: string
}

export default function SessionLoadError({ area }: SessionLoadErrorProps) {
  return (
    <div className="content-shell py-16">
      <div
        role="alert"
        className="mx-auto max-w-lg rounded-[var(--radius-lg)] border border-err/20 bg-err/10 p-6 text-center"
      >
        <h1 className="text-lg font-semibold text-fg">{area} could not verify your session</h1>
        <p className="mt-2 text-sm text-fg-2">Check your connection and retry.</p>
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="mt-5 rounded-[var(--radius-md)] bg-accent px-4 py-2 text-sm font-semibold text-accent-fg"
        >
          Retry
        </button>
      </div>
    </div>
  )
}
