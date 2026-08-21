'use client'

import React, { useState, useEffect, useCallback } from 'react'
import { motion } from 'framer-motion'
import {
  Target,
  TrendingUp,
  TrendingDown,
  AlertTriangle,
  CheckCircle,
  Info,
  Lightbulb,
  Award,
  BarChart3,
  Building2,
  Users,
} from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { apiClient, type BenchmarkResult } from '@/lib/api-client'

const FALLBACK_PROFILES = [
  { key: 'generic', label: 'General' },
  { key: 'tech_saas', label: 'Technology / SaaS' },
  { key: 'finance_banking', label: 'Finance / Banking' },
  { key: 'healthcare', label: 'Healthcare / Clinical' },
  { key: 'consulting', label: 'Consulting / Advisory' },
  { key: 'marketing', label: 'Marketing / Growth' },
]

interface ATSScoreCardProps {
  score?: number
  categoryScores?: Record<string, number>
  recommendations?: string[]
  warnings?: string[]
  strengths?: string[]
  detailedAnalysis?: Record<string, any>
  isLoading?: boolean
  onViewRecommendations?: () => void
  onViewAnalysis?: () => void
  className?: string
  /** Industry label auto-detected from job description, e.g. "Technology / SaaS" */
  industryLabel?: string | null
  /** Industry key used for benchmarking (e.g. "tech_saas") */
  industryKey?: string | null
  /** Called with a profile key when the user overrides the detected industry */
  onIndustryOverride?: (profileKey: string) => void
}

const getScoreColor = (score: number) => {
  if (score >= 80) return 'text-ok'
  if (score >= 60) return 'text-warn'
  return 'text-err'
}

const getScoreBgColor = (score: number) => {
  if (score >= 80) return 'bg-[color-mix(in_srgb,var(--ok)_14%,transparent)]'
  if (score >= 60) return 'bg-[color-mix(in_srgb,var(--warn)_14%,transparent)]'
  return 'bg-[color-mix(in_srgb,var(--err)_14%,transparent)]'
}

const getScoreBorderColor = (score: number) => {
  if (score >= 80) return 'border-[color-mix(in_srgb,var(--ok)_40%,transparent)]'
  if (score >= 60) return 'border-[color-mix(in_srgb,var(--warn)_40%,transparent)]'
  return 'border-[color-mix(in_srgb,var(--err)_40%,transparent)]'
}

const getScoreLabel = (score: number) => {
  if (score >= 90) return 'Excellent'
  if (score >= 80) return 'Good'
  if (score >= 70) return 'Fair'
  if (score >= 60) return 'Needs Improvement'
  return 'Poor'
}

const categoryLabels: Record<string, string> = {
  formatting: 'Formatting',
  structure: 'Structure',
  content: 'Content',
  keywords: 'Keywords',
  readability: 'Readability',
}

export const ATSScoreCard: React.FC<ATSScoreCardProps> = ({
  score,
  categoryScores,
  recommendations = [],
  warnings = [],
  strengths = [],
  detailedAnalysis,
  isLoading = false,
  onViewRecommendations,
  onViewAnalysis,
  className = '',
  industryLabel,
  industryKey,
  onIndustryOverride,
}) => {
  const [industryProfiles, setIndustryProfiles] = useState(FALLBACK_PROFILES)
  const [benchmark, setBenchmark] = useState<BenchmarkResult | null>(null)
  const [benchmarkLoading, setBenchmarkLoading] = useState(false)
  const [benchmarkFetched, setBenchmarkFetched] = useState(false)

  useEffect(() => {
    if (!onIndustryOverride) return
    apiClient.getIndustryProfiles()
      .then((res) => { if (res.profiles?.length) setIndustryProfiles(res.profiles) })
      .catch(() => { /* keep fallback */ })
  }, [onIndustryOverride])

  // Lazy-load benchmark once we have a score (not on every compile)
  useEffect(() => {
    if (score === undefined || benchmarkFetched || benchmarkLoading) return
    setBenchmarkLoading(true)
    setBenchmarkFetched(true)
    apiClient.getBenchmark(score, industryKey || undefined)
      .then((res) => setBenchmark(res))
      .catch(() => { /* benchmark unavailable — don't show */ })
      .finally(() => setBenchmarkLoading(false))
  }, [score, industryKey, benchmarkFetched, benchmarkLoading])

  if (isLoading) {
    return (
      <Card className={`${className}`}>
        <CardHeader>
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 bg-accent-soft rounded-full flex items-center justify-center">
              <Target className="w-6 h-6 text-accent-strong animate-pulse" />
            </div>
            <div>
              <CardTitle>ATS Score</CardTitle>
              <CardDescription>Analyzing your resume...</CardDescription>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="animate-pulse">
              <div className="h-4 bg-surface-2 rounded-[var(--radius-md)] w-1/4 mb-2"></div>
              <div className="h-20 bg-surface-2 rounded-[var(--radius-md)]"></div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="animate-pulse">
                  <div className="h-3 bg-surface-2 rounded-[var(--radius-md)] w-3/4 mb-2"></div>
                  <div className="h-2 bg-surface-2 rounded-[var(--radius-md)]"></div>
                </div>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>
    )
  }

  if (score === undefined) {
    return (
      <Card className={`${className} border-dashed border-2 border-line`}>
        <CardContent className="flex items-center justify-center py-8">
          <div className="text-center text-fg-3">
            <Target className="w-8 h-8 mx-auto mb-2" />
            <p>No ATS score yet</p>
            <p className="text-sm">Add a job description and optimize to see your ATS score</p>
          </div>
        </CardContent>
      </Card>
    )
  }

  const scoreColor = getScoreColor(score)
  const scoreBgColor = getScoreBgColor(score)
  const scoreBorderColor = getScoreBorderColor(score)
  const scoreLabel = getScoreLabel(score)

  return (
    <Card className={`${className} ${scoreBorderColor} border-2`}>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className={`w-12 h-12 ${scoreBgColor} rounded-full flex items-center justify-center`}>
              <Target className={`w-6 h-6 ${scoreColor}`} />
            </div>
            <div>
              <CardTitle>ATS Score</CardTitle>
              <CardDescription>Resume compatibility analysis</CardDescription>
            </div>
          </div>

          <div className="flex flex-col items-end gap-1.5">
            <Badge variant="outline" className={`${scoreColor} ${scoreBgColor} ${scoreBorderColor}`}>
              {scoreLabel}
            </Badge>
            {industryLabel && (
              <div className="flex items-center gap-1.5">
                <Building2 className="w-3 h-3 text-accent" />
                <span className="text-xs font-medium text-accent-strong bg-accent-soft border border-accent rounded-full px-2 py-0.5">
                  Calibrated for: {industryLabel}
                </span>
              </div>
            )}
            {onIndustryOverride && (
              <select
                className="text-xs border border-line rounded-[var(--radius-md)] px-1.5 py-0.5 text-fg-2 bg-surface cursor-pointer"
                defaultValue=""
                onChange={(e) => e.target.value && onIndustryOverride(e.target.value)}
                title="Override industry calibration"
              >
                <option value="" disabled>Change industry...</option>
                {industryProfiles.map((p) => (
                  <option key={p.key} value={p.key}>{p.label}</option>
                ))}
              </select>
            )}
          </div>
        </div>
      </CardHeader>

      <CardContent className="space-y-6">
        {/* Main Score Display */}
        <div className="text-center">
          <motion.div
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
            transition={{ duration: 0.5, type: "spring" }}
            className={`inline-flex items-center justify-center w-24 h-24 ${scoreBgColor} rounded-full mb-4`}
          >
            <span className={`text-3xl font-bold ${scoreColor}`}>
              {Math.round(score)}
            </span>
          </motion.div>
          <p className="text-lg font-semibold text-fg">
            {scoreLabel} ATS Compatibility
          </p>
          <p className="text-sm text-fg-2">
            Score: {score.toFixed(1)}/100
          </p>
        </div>

        {/* Category Scores */}
        {categoryScores && Object.keys(categoryScores).length > 0 && (
          <div className="space-y-3">
            <h4 className="font-medium text-fg flex items-center gap-2">
              <BarChart3 className="w-4 h-4" />
              Category Breakdown
            </h4>
            <div className="space-y-2">
              {Object.entries(categoryScores).map(([category, categoryScore]) => (
                <div key={category} className="space-y-1">
                  <div className="flex justify-between text-sm">
                    <span className="font-medium">
                      {categoryLabels[category] || category}
                    </span>
                    <span className={getScoreColor(categoryScore)}>
                      {Math.round(categoryScore)}%
                    </span>
                  </div>
                  <div className="w-full bg-surface-2 rounded-full h-2">
                    <motion.div
                      className={`h-2 rounded-full ${
                        categoryScore >= 80 ? 'bg-ok' :
                        categoryScore >= 60 ? 'bg-warn' :
                        'bg-err'
                      }`}
                      initial={{ width: 0 }}
                      animate={{ width: `${categoryScore}%` }}
                      transition={{ duration: 0.8, delay: 0.2 }}
                    />
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Strengths */}
        {strengths.length > 0 && (
          <div className="space-y-2">
            <h4 className="font-medium text-ok flex items-center gap-2">
              <CheckCircle className="w-4 h-4" />
              Strengths ({strengths.length})
            </h4>
            <div className="space-y-1">
              {strengths.slice(0, 3).map((strength, index) => (
                <motion.div
                  key={index}
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: index * 0.1 }}
                  className="flex items-start gap-2 text-sm text-ok"
                >
                  <CheckCircle className="w-3 h-3 mt-0.5 flex-shrink-0" />
                  <span>{strength}</span>
                </motion.div>
              ))}
              {strengths.length > 3 && (
                <p className="text-xs text-fg-3 ml-5">
                  +{strengths.length - 3} more strengths
                </p>
              )}
            </div>
          </div>
        )}

        {/* Warnings */}
        {warnings.length > 0 && (
          <div className="space-y-2">
            <h4 className="font-medium text-warn flex items-center gap-2">
              <AlertTriangle className="w-4 h-4" />
              Warnings ({warnings.length})
            </h4>
            <div className="space-y-1">
              {warnings.slice(0, 2).map((warning, index) => (
                <motion.div
                  key={index}
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: index * 0.1 }}
                  className="flex items-start gap-2 text-sm text-warn"
                >
                  <AlertTriangle className="w-3 h-3 mt-0.5 flex-shrink-0" />
                  <span>{warning}</span>
                </motion.div>
              ))}
              {warnings.length > 2 && (
                <p className="text-xs text-fg-3 ml-5">
                  +{warnings.length - 2} more warnings
                </p>
              )}
            </div>
          </div>
        )}

        {/* Top Recommendations */}
        {recommendations.length > 0 && (
          <div className="space-y-2">
            <h4 className="font-medium text-accent-strong flex items-center gap-2">
              <Lightbulb className="w-4 h-4" />
              Top Recommendations ({recommendations.length})
            </h4>
            <div className="space-y-1">
              {recommendations.slice(0, 3).map((recommendation, index) => (
                <motion.div
                  key={index}
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: index * 0.1 }}
                  className="flex items-start gap-2 text-sm text-accent-strong"
                >
                  <Lightbulb className="w-3 h-3 mt-0.5 flex-shrink-0" />
                  <span>{recommendation}</span>
                </motion.div>
              ))}
              {recommendations.length > 3 && (
                <p className="text-xs text-fg-3 ml-5">
                  +{recommendations.length - 3} more recommendations
                </p>
              )}
            </div>
          </div>
        )}

        {/* Action Buttons */}
        <div className="flex gap-2 pt-4 border-t border-line">
          {onViewRecommendations && recommendations.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={onViewRecommendations}
              className="flex items-center gap-2"
            >
              <Lightbulb className="w-4 h-4" />
              View All Recommendations
            </Button>
          )}

          {onViewAnalysis && detailedAnalysis && (
            <Button
              variant="outline"
              size="sm"
              onClick={onViewAnalysis}
              className="flex items-center gap-2"
            >
              <Info className="w-4 h-4" />
              Detailed Analysis
            </Button>
          )}
        </div>

        {/* Benchmark Row */}
        {(benchmarkLoading || benchmark) && (
          <div className="space-y-2 pt-2 border-t border-line">
            <h4 className="font-medium text-fg flex items-center gap-2 text-sm">
              <Users className="w-4 h-4 text-accent" />
              Community Benchmark
            </h4>
            {benchmarkLoading && (
              <div className="h-4 bg-surface-2 rounded-[var(--radius-md)] animate-pulse w-3/4" />
            )}
            {benchmark && !benchmarkLoading && (
              benchmark.sufficient_data && benchmark.percentile !== null ? (
                <div className="space-y-2">
                  <p className="text-sm text-fg-2">
                    Your resume scores in the{' '}
                    <span className="font-semibold text-accent-strong">
                      top {Math.round(100 - benchmark.percentile)}%
                    </span>{' '}
                    of{' '}
                    <span className="font-medium">{benchmark.industry}</span>{' '}
                    resumes on Latexy
                    {benchmark.sample_size > 0 && (
                      <span className="text-fg-3"> ({benchmark.sample_size.toLocaleString()} resumes)</span>
                    )}
                  </p>

                  {/* Mini distribution bar */}
                  {benchmark.cohort_p25 !== null && benchmark.cohort_p75 !== null && (
                    <div className="relative h-3 rounded-full bg-surface-2 overflow-visible">
                      {/* IQR band (p25–p75) */}
                      <div
                        className="absolute h-full rounded-full bg-accent-soft"
                        style={{
                          left: `${benchmark.cohort_p25}%`,
                          width: `${(benchmark.cohort_p75 ?? 100) - (benchmark.cohort_p25 ?? 0)}%`,
                        }}
                      />
                      {/* Median marker */}
                      {benchmark.cohort_median !== null && (
                        <div
                          className="absolute top-0 h-full w-0.5 bg-accent"
                          style={{ left: `${benchmark.cohort_median}%` }}
                          title={`Median: ${benchmark.cohort_median.toFixed(1)}`}
                        />
                      )}
                      {/* User's score marker */}
                      <div
                        className="absolute -top-0.5 h-4 w-1.5 rounded-sm bg-accent-strong shadow-sm"
                        style={{ left: `calc(${score}% - 3px)` }}
                        title={`Your score: ${score?.toFixed(1)}`}
                      />
                    </div>
                  )}

                  <div className="flex justify-between text-xs text-fg-3 mt-0.5 px-0.5">
                    <span>0</span>
                    {benchmark.cohort_p25 !== null && (
                      <span style={{ position: 'absolute', left: `${benchmark.cohort_p25}%`, transform: 'translateX(-50%)' }}
                        className="hidden sm:block">
                        p25
                      </span>
                    )}
                    {benchmark.cohort_median !== null && (
                      <span>Median: {benchmark.cohort_median.toFixed(0)}</span>
                    )}
                    <span>100</span>
                  </div>
                </div>
              ) : (
                <p className="text-xs text-fg-3">
                  {benchmark.message || `Benchmarking available once more ${benchmark.industry} users join`}
                </p>
              )
            )}
          </div>
        )}

        {/* Score Interpretation */}
        <div className="text-xs text-fg-3 bg-surface-2 p-3 rounded-[var(--radius-md)]">
          <div className="flex items-start gap-2">
            <Info className="w-3 h-3 mt-0.5 flex-shrink-0" />
            <div>
              <p className="font-medium mb-1">Score Interpretation:</p>
              <p>
                {score >= 80 && "Excellent! Your resume is highly ATS-compatible and should pass most automated screening systems."}
                {score >= 60 && score < 80 && "Good compatibility with room for improvement. Consider addressing the recommendations to boost your score."}
                {score < 60 && "Your resume may face challenges with ATS systems. Focus on the recommendations to improve compatibility."}
              </p>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

export default ATSScoreCard
