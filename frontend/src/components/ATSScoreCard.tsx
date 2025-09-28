'use client'

import React from 'react'
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
  BarChart3
} from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

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
}

const getScoreColor = (score: number) => {
  if (score >= 80) return 'text-green-600'
  if (score >= 60) return 'text-yellow-600'
  return 'text-red-600'
}

const getScoreBgColor = (score: number) => {
  if (score >= 80) return 'bg-green-100'
  if (score >= 60) return 'bg-yellow-100'
  return 'bg-red-100'
}

const getScoreBorderColor = (score: number) => {
  if (score >= 80) return 'border-green-200'
  if (score >= 60) return 'border-yellow-200'
  return 'border-red-200'
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
}) => {
  if (isLoading) {
    return (
      <Card className={`${className}`}>
        <CardHeader>
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 bg-blue-100 rounded-full flex items-center justify-center">
              <Target className="w-6 h-6 text-blue-600 animate-pulse" />
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
              <div className="h-4 bg-gray-200 rounded w-1/4 mb-2"></div>
              <div className="h-20 bg-gray-200 rounded"></div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              {[...Array(4)].map((_, i) => (
                <div key={i} className="animate-pulse">
                  <div className="h-3 bg-gray-200 rounded w-3/4 mb-2"></div>
                  <div className="h-2 bg-gray-200 rounded"></div>
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
      <Card className={`${className} border-dashed border-2 border-gray-300`}>
        <CardContent className="flex items-center justify-center py-8">
          <div className="text-center text-gray-500">
            <Target className="w-8 h-8 mx-auto mb-2" />
            <p>No ATS score available</p>
            <p className="text-sm">Run ATS analysis to see your score</p>
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
          
          <Badge variant="outline" className={`${scoreColor} ${scoreBgColor} ${scoreBorderColor}`}>
            {scoreLabel}
          </Badge>
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
          <p className="text-lg font-semibold text-gray-900">
            {scoreLabel} ATS Compatibility
          </p>
          <p className="text-sm text-gray-600">
            Score: {score.toFixed(1)}/100
          </p>
        </div>

        {/* Category Scores */}
        {categoryScores && Object.keys(categoryScores).length > 0 && (
          <div className="space-y-3">
            <h4 className="font-medium text-gray-900 flex items-center gap-2">
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
                  <div className="w-full bg-gray-200 rounded-full h-2">
                    <motion.div
                      className={`h-2 rounded-full ${
                        categoryScore >= 80 ? 'bg-green-500' :
                        categoryScore >= 60 ? 'bg-yellow-500' :
                        'bg-red-500'
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
            <h4 className="font-medium text-green-700 flex items-center gap-2">
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
                  className="flex items-start gap-2 text-sm text-green-700"
                >
                  <CheckCircle className="w-3 h-3 mt-0.5 flex-shrink-0" />
                  <span>{strength}</span>
                </motion.div>
              ))}
              {strengths.length > 3 && (
                <p className="text-xs text-gray-500 ml-5">
                  +{strengths.length - 3} more strengths
                </p>
              )}
            </div>
          </div>
        )}

        {/* Warnings */}
        {warnings.length > 0 && (
          <div className="space-y-2">
            <h4 className="font-medium text-yellow-700 flex items-center gap-2">
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
                  className="flex items-start gap-2 text-sm text-yellow-700"
                >
                  <AlertTriangle className="w-3 h-3 mt-0.5 flex-shrink-0" />
                  <span>{warning}</span>
                </motion.div>
              ))}
              {warnings.length > 2 && (
                <p className="text-xs text-gray-500 ml-5">
                  +{warnings.length - 2} more warnings
                </p>
              )}
            </div>
          </div>
        )}

        {/* Top Recommendations */}
        {recommendations.length > 0 && (
          <div className="space-y-2">
            <h4 className="font-medium text-blue-700 flex items-center gap-2">
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
                  className="flex items-start gap-2 text-sm text-blue-700"
                >
                  <Lightbulb className="w-3 h-3 mt-0.5 flex-shrink-0" />
                  <span>{recommendation}</span>
                </motion.div>
              ))}
              {recommendations.length > 3 && (
                <p className="text-xs text-gray-500 ml-5">
                  +{recommendations.length - 3} more recommendations
                </p>
              )}
            </div>
          </div>
        )}

        {/* Action Buttons */}
        <div className="flex gap-2 pt-4 border-t border-gray-200">
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

        {/* Score Interpretation */}
        <div className="text-xs text-gray-500 bg-gray-50 p-3 rounded-lg">
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
