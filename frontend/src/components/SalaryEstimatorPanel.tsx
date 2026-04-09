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
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onKeyDown={(e) => {
        if (e.key === 'Escape') onClose()
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="w-full max-w-lg rounded-xl border border-white/[0.08] bg-[#0d0d0d] shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-white/[0.06] px-4 py-3">
          <div className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-lg bg-emerald-500/15">
              <DollarSign size={13} className="text-emerald-300" />
            </div>
            <span id="salary-estimator-title" className="text-sm font-medium text-white/90">Salary Estimator</span>
          </div>
          <button
            onClick={onClose}
            className="rounded-md p-1 text-white/40 transition-colors hover:bg-white/[0.06] hover:text-white/70"
          >
            <X size={14} />
          </button>
        </div>

        {/* Body */}
        <div className="space-y-4 p-4">
          {/* Inputs */}
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-white/50">Target Role</label>
              <input
                type="text"
                value={targetRole}
                onChange={(e) => setTargetRole(e.target.value)}
                placeholder="e.g. Senior Software Engineer"
                maxLength={200}
                className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-sm text-white/90 placeholder:text-white/25 focus:border-emerald-500/40 focus:outline-none focus:ring-0"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') handleEstimate()
                }}
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-white/50">Location</label>
              <input
                type="text"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                placeholder="e.g. San Francisco, CA or London, UK"
                maxLength={200}
                className="w-full rounded-lg border border-white/[0.08] bg-white/[0.04] px-3 py-2 text-sm text-white/90 placeholder:text-white/25 focus:border-emerald-500/40 focus:outline-none focus:ring-0"
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
            className="flex w-full items-center justify-center gap-2 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-emerald-500 disabled:cursor-not-allowed disabled:opacity-50"
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
            <div className="space-y-4 rounded-xl border border-white/[0.06] bg-white/[0.03] p-4">
              {/* Range numbers */}
              <div className="flex items-end justify-between">
                <div className="text-center">
                  <div className="text-xs text-white/40">Low</div>
                  <div className="text-base font-semibold text-white/70">
                    {formatCurrency(result.low, result.currency)}
                  </div>
                </div>
                <div className="text-center">
                  <div className="text-xs text-white/40">Median</div>
                  <div className="text-xl font-bold text-emerald-400">
                    {formatCurrency(result.median, result.currency)}
                  </div>
                </div>
                <div className="text-center">
                  <div className="text-xs text-white/40">High</div>
                  <div className="text-base font-semibold text-white/70">
                    {formatCurrency(result.high, result.currency)}
                  </div>
                </div>
              </div>

              {/* Range bar */}
              <div className="relative h-3 rounded-full bg-white/[0.06]">
                {/* Filled portion from low to high */}
                <div
                  className="absolute inset-y-0 left-0 rounded-full bg-gradient-to-r from-emerald-900/60 via-emerald-500/70 to-emerald-900/60"
                  style={{ width: '100%' }}
                />
                {/* Candidate marker at median */}
                <div
                  className="absolute top-1/2 -translate-x-1/2 -translate-y-1/2"
                  style={{ left: `${markerPct}%` }}
                >
                  <div className="h-5 w-2 rounded-full border-2 border-emerald-400 bg-[#0d0d0d] shadow-lg shadow-emerald-500/30" />
                </div>
              </div>

              {/* Percentile */}
              <p className="text-center text-xs text-white/50">
                Estimated at{' '}
                <span className="font-semibold text-emerald-400">{result.percentile}th percentile</span>{' '}
                for <span className="text-white/70">{targetRole}</span> in{' '}
                <span className="text-white/70">{location}</span>
              </p>

              {/* Key skills */}
              {result.key_skills.length > 0 && (
                <div className="space-y-1.5">
                  <div className="text-xs font-medium text-white/40">Skills contributing to estimate</div>
                  <div className="flex flex-wrap gap-1.5">
                    {result.key_skills.map((skill) => (
                      <span
                        key={skill}
                        className="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-300"
                      >
                        {skill}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Disclaimer */}
              <p className="text-[10px] leading-relaxed text-white/25">{result.disclaimer}</p>
            </div>
          )}

          {/* Edge case: zero estimate */}
          {result && result.median === 0 && (
            <p className="rounded-lg border border-white/[0.06] bg-white/[0.03] p-3 text-center text-xs text-white/40">
              {result.disclaimer || 'Unable to generate an estimate right now.'}
            </p>
          )}
        </div>
      </div>
    </div>
  )
}
