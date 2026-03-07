'use client'

import { useEffect, useState } from 'react'

const phrases = ['people remember.', 'recruiters shortlist.', 'ATS systems score.', 'hiring teams trust.']

export default function HeroTypingLine() {
  const [phraseIndex, setPhraseIndex] = useState(0)
  const [typedText, setTypedText] = useState(phrases[0])
  const [isDeleting, setIsDeleting] = useState(false)

  useEffect(() => {
    const currentPhrase = phrases[phraseIndex]
    const isFinishedTyping = typedText === currentPhrase
    const isFinishedDeleting = typedText.length === 0

    let timeout = 70

    if (!isDeleting && isFinishedTyping) {
      timeout = 1300
      const timer = window.setTimeout(() => setIsDeleting(true), timeout)
      return () => window.clearTimeout(timer)
    }

    if (isDeleting && isFinishedDeleting) {
      setIsDeleting(false)
      setPhraseIndex((prev) => (prev + 1) % phrases.length)
      return
    }

    if (isDeleting) {
      timeout = 34
      const timer = window.setTimeout(() => {
        setTypedText(currentPhrase.slice(0, typedText.length - 1))
      }, timeout)
      return () => window.clearTimeout(timer)
    }

    const timer = window.setTimeout(() => {
      setTypedText(currentPhrase.slice(0, typedText.length + 1))
    }, timeout)

    return () => window.clearTimeout(timer)
  }, [typedText, isDeleting, phraseIndex])

  return (
    <span className="block min-h-[1.1em] whitespace-nowrap">
      {typedText}
      <span className="ml-1 inline-block h-[0.85em] w-[0.08em] bg-white/90 align-[-0.05em] animate-pulse" />
    </span>
  )
}
