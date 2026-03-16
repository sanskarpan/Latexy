'use client'

interface ATSScoreBadgeProps {
  score: number | null
  loading: boolean
  onClick?: () => void
}

export default function ATSScoreBadge({ score, loading, onClick }: ATSScoreBadgeProps) {
  if (loading) {
    return (
      <span className="flex items-center gap-1 text-[10px] text-zinc-500">
        <span className="h-1.5 w-1.5 animate-spin rounded-full border border-zinc-500 border-t-transparent" />
        ATS
      </span>
    )
  }

  if (score === null) {
    return (
      <span className="text-[10px] text-zinc-600">ATS —</span>
    )
  }

  const colorClass =
    score >= 80
      ? 'text-emerald-400 bg-emerald-500/10'
      : score >= 60
        ? 'text-amber-400 bg-amber-500/10'
        : 'text-rose-400 bg-rose-500/10'

  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-md px-1.5 py-0.5 text-[10px] font-medium transition-colors ${colorClass} ${onClick ? 'cursor-pointer hover:brightness-110' : 'cursor-default'}`}
      title="Live ATS score (updates 10s after last change)"
    >
      ATS {score}
    </button>
  )
}
