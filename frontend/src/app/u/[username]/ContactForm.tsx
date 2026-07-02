'use client'

/**
 * Portfolio contact form.
 *
 * NOTE: There is no backend contact endpoint yet, so this form does not submit
 * anywhere. Rather than falsely tell visitors their message was "Sent!" (silent
 * data loss), the form is disabled and points visitors at a working channel.
 */
export default function ContactForm() {
  return (
    <form
      className="grid grid-cols-2 gap-4 max-w-lg"
      aria-disabled
      onSubmit={(e) => {
        // No contact endpoint exists — prevent submission entirely.
        e.preventDefault()
      }}
    >
      <div className="flex flex-col gap-1">
        <label className="text-sm text-gray-500">Name</label>
        <input
          disabled
          placeholder="Your name"
          className="rounded-lg border border-gray-300 bg-transparent px-3 py-2 text-sm outline-none focus:border-blue-500 disabled:opacity-60 disabled:cursor-not-allowed"
        />
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-sm text-gray-500">Email</label>
        <input
          disabled
          type="email"
          placeholder="your@email.com"
          className="rounded-lg border border-gray-300 bg-transparent px-3 py-2 text-sm outline-none focus:border-blue-500 disabled:opacity-60 disabled:cursor-not-allowed"
        />
      </div>
      <div className="col-span-2 flex flex-col gap-1">
        <label className="text-sm text-gray-500">Message</label>
        <textarea
          disabled
          rows={4}
          placeholder="Say hello…"
          className="rounded-lg border border-gray-300 bg-transparent px-3 py-2 text-sm outline-none focus:border-blue-500 resize-y disabled:opacity-60 disabled:cursor-not-allowed"
        />
      </div>
      <div className="col-span-2 flex items-center gap-3">
        <button
          type="submit"
          disabled
          className="rounded-lg bg-blue-600 px-5 py-2 text-sm font-semibold text-white opacity-60 cursor-not-allowed"
        >
          Send
        </button>
        <p className="text-sm text-gray-500">
          Direct messaging isn&apos;t available yet.
        </p>
      </div>
    </form>
  )
}
