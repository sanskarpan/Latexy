'use client'

interface ATSScoreBadgeProps {
  score: number | null
  loading: boolean
  onClick?: () => void
}

export default function ATSScoreBadge({ score, loading, onClick }: ATSScoreBadgeProps) {
  if (loading) {
    return (
      <span className="flex items-center gap-1 text-[10px] text-fg-3">
        <span className="h-1.5 w-1.5 animate-spin rounded-full border border-line-2 border-t-transparent" />
        ATS
      </span>
    )
  }

  if (score === null) {
    return (
      <span className="text-[10px] text-fg-3">ATS —</span>
    )
  }

  const colorClass =
    score >= 80
      ? 'text-ok bg-ok/10'
      : score >= 60
        ? 'text-warn bg-warn/10'
        : 'text-err bg-err/10'

  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-[var(--radius-md)] px-1.5 py-0.5 text-[10px] font-medium transition-colors ${colorClass} ${onClick ? 'cursor-pointer hover:brightness-110' : 'cursor-default'}`}
      title="Live ATS score (updates 10s after last change)"
    >
      ATS {score}
    </button>
  )
}
