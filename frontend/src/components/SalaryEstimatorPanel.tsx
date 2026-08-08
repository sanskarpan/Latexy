'use client'

import { useCallback, useEffect, useState } from 'react'
import { DollarSign, Loader2, TrendingUp, X } from 'lucide-react'
import { toast } from 'sonner'
import { apiClient, type SalaryEstimateResponse } from '@/lib/api-client'

interface SalaryEstimatorPanelProps {
  isOpen: boolean
  onClose: () => void
  getLatex: () => string
}

export default function SalaryEstimatorPanel({
  isOpen,
  onClose,
  getLatex,
}: SalaryEstimatorPanelProps) {
  const [targetRole, setTargetRole] = useState('')
  const [location, setLocation] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<SalaryEstimateResponse | null>(null)

  // Reset on open
  useEffect(() => {
    if (!isOpen) return
    setResult(null)
  }, [isOpen])

  const handleEstimate = useCallback(async () => {
    const latex = getLatex()
    if (!latex.trim()) {
      toast.error('Editor is empty')
      return
    }
    if (!targetRole.trim()) {
      toast.error('Please enter a target role')
      return
    }
    if (!location.trim()) {
      toast.error('Please enter a location')
      return
    }

    setLoading(true)
    setResult(null)
    try {
      const data = await apiClient.estimateSalary({
        resume_latex: latex,
        target_role: targetRole.trim(),
        location: location.trim(),
      })
      setResult(data)
      if (data.cached) {
        toast.success('Showing cached estimate')
      } else {
        toast.success('Salary estimate ready')
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Estimation failed')
    } finally {
      setLoading(false)
    }
  }, [getLatex, targetRole, location])

  if (!isOpen) return null

  const formatCurrency = (value: number, currency: string) => {
    try {
      return new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency,
        maximumFractionDigits: 0,
      }).format(value)
    } catch {
      return `${currency} ${value.toLocaleString()}`
    }
  }

  // Compute marker position on range bar [0..100%]
  const markerPct =
    result && result.high > result.low
      ? Math.round(((result.median - result.low) / (result.high - result.low)) * 100)
      : 50

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="salary-estimator-title"
      tabIndex={-1}
      className="fixed inset-0 z-50 flex items-center justify-center bg-[var(--overlay)]"
      onKeyDown={(e) => {
        if (e.key === 'Escape') onClose()
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="w-full max-w-lg rounded-[var(--radius-lg)] border border-line bg-surface shadow-[var(--shadow-2)]">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-[var(--radius-md)] bg-accent-soft">
              <DollarSign size={13} className="text-accent-strong" />
            </div>
            <span id="salary-estimator-title" className="text-sm font-medium text-fg">Salary Estimator</span>
          </div>
          <button
            onClick={onClose}
            className="rounded-[var(--radius-md)] p-1 text-fg-3 transition-colors hover:bg-surface-2 hover:text-fg-2"
          >
            <X size={14} />
          </button>
        </div>

        {/* Body */}
        <div className="space-y-4 p-4">
          {/* Inputs */}
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-fg-3">Target Role</label>
              <input
                type="text"
                value={targetRole}
                onChange={(e) => setTargetRole(e.target.value)}
                placeholder="e.g. Senior Software Engineer"
                maxLength={200}
                className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg placeholder:text-fg-3 focus:border-accent focus:outline-none focus:ring-0"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleEstimate()
                }}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-fg-3">Location</label>
              <input
                type="text"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                placeholder="e.g. San Francisco, CA or London, UK"
                maxLength={200}
                className="w-full rounded-[var(--radius-md)] border border-line bg-surface-2 px-3 py-2 text-sm text-fg placeholder:text-fg-3 focus:border-accent focus:outline-none focus:ring-0"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleEstimate()
                }}
              />
            </div>
          </div>

          {/* Estimate button */}
          <button
            onClick={handleEstimate}
            disabled={loading}
            className="flex w-full items-center justify-center gap-2 rounded-[var(--radius-md)] bg-accent px-4 py-2 text-sm font-medium text-accent-fg transition-colors hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {loading ? (
              <>
                <Loader2 size={14} className="animate-spin" />
                Estimating…
              </>
            ) : (
              <>
                <TrendingUp size={14} />
                Estimate Salary
              </>
            )}
          </button>

          {/* Results */}
          {result && result.median > 0 && (
            <div className="space-y-4 rounded-[var(--radius-lg)] border border-line bg-surface-2 p-4">
              {/* Range numbers */}
              <div className="flex items-end justify-between">
                <div className="text-center">
                  <div className="text-xs text-fg-3">Low</div>
                  <div className="text-base font-semibold text-fg-2">
                    {formatCurrency(result.low, result.currency)}
                  </div>
                </div>
                <div className="text-center">
                  <div className="text-xs text-fg-3">Median</div>
                  <div className="text-xl font-bold text-accent">
                    {formatCurrency(result.median, result.currency)}
                  </div>
                </div>
                <div className="text-center">
                  <div className="text-xs text-fg-3">High</div>
                  <div className="text-base font-semibold text-fg-2">
                    {formatCurrency(result.high, result.currency)}
                  </div>
                </div>
              </div>

              {/* Range bar */}
              <div className="relative h-3 rounded-full bg-surface-2">
                {/* Filled portion from low to high */}
                <div
                  className="absolute inset-y-0 left-0 rounded-full bg-accent"
                  style={{ width: '100%' }}
                />
                {/* Candidate marker at median */}
                <div
                  className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2"
                  style={{ left: `${markerPct}%` }}
                >
                  <div className="h-5 w-2 rounded-full border-2 border-accent bg-surface shadow-[var(--shadow-2)]" />
                </div>
              </div>

              {/* Percentile */}
              <p className="text-center text-xs text-fg-3">
                Estimated at{' '}
                <span className="font-semibold text-accent-strong">{result.percentile}th percentile</span>{' '}
                for <span className="text-fg-2">{targetRole}</span> in{' '}
                <span className="text-fg-2">{location}</span>
              </p>

              {/* Key skills */}
              {result.key_skills.length > 0 && (
                <div className="space-y-1.5">
                  <div className="text-xs font-medium text-fg-3">Skills contributing to estimate</div>
                  <div className="flex flex-wrap gap-1.5">
                    {result.key_skills.map((skill) => (
                      <span
                        key={skill}
                        className="rounded-full border border-accent bg-accent-soft px-2 py-0.5 text-xs text-accent-strong"
                      >
                        {skill}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Disclaimer */}
              <p className="text-[10px] leading-relaxed text-fg-3">{result.disclaimer}</p>
            </div>
          )}

          {/* Edge case: zero estimate */}
          {result && result.median === 0 && (
            <p className="rounded-[var(--radius-md)] border border-line bg-surface-2 p-3 text-center text-xs text-fg-3">
              {result.disclaimer || 'Unable to generate an estimate right now.'}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
