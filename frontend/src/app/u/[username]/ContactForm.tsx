'use client'

export default function ContactForm() {
  return (
    <form
      className="grid grid-cols-2 gap-4 max-w-lg"
      onSubmit={(e) => {
        e.preventDefault()
        const btn = e.currentTarget.querySelector('button') as HTMLButtonElement
        if (btn) { btn.textContent = 'Sent!'; btn.disabled = true }
        setTimeout(() => {
          if (btn) { btn.textContent = 'Send'; btn.disabled = false }
        }, 3000)
      }}
    >
      <div className="flex flex-col gap-1">
        <label className="text-sm text-gray-500">Name</label>
        <input
          required
          placeholder="Your name"
          className="rounded-lg border border-gray-300 bg-transparent px-3 py-2 text-sm outline-none focus:border-blue-500"
        />
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-sm text-gray-500">Email</label>
        <input
          required
          type="email"
          placeholder="your@email.com"
          className="rounded-lg border border-gray-300 bg-transparent px-3 py-2 text-sm outline-none focus:border-blue-500"
        />
      </div>
      <div className="col-span-2 flex flex-col gap-1">
        <label className="text-sm text-gray-500">Message</label>
        <textarea
          required
          rows={4}
          placeholder="Say hello…"
          className="rounded-lg border border-gray-300 bg-transparent px-3 py-2 text-sm outline-none focus:border-blue-500 resize-y"
        />
      </div>
      <div className="col-span-2">
        <button
          type="submit"
          className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-semibold text-white hover:bg-blue-700 transition"
        >
          Send
        </button>
      </div>
    </form>
  )
}
