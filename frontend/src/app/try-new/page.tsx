'use client'

import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { toast, Toaster } from 'sonner'
import { 
  FileText, 
  Download, 
  Save, 
  Zap, 
  Target, 
  Clock,
  AlertCircle,
  CheckCircle,
  Sparkles,
  ArrowLeft,
  User,
  Crown,
  Play,
  Maximize2,
  Minimize2,
  RefreshCw,
  Eye,
  Code,
  Upload,
  BarChart3,
  Lightbulb,
  Settings
} from 'lucide-react'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { generateDeviceFingerprint } from '@/lib/api-client'
import { useJobManagement } from '@/hooks/useJobManagement'
import { useATSScoring } from '@/hooks/useATSScoring'
import JobStatusTracker from '@/components/JobStatusTracker'
import ATSScoreCard from '@/components/ATSScoreCard'
import JobQueue from '@/components/JobQueue'

const fadeInUp = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.5 }
}

// Sample LaTeX resume template
const sampleLatexContent = `\\documentclass[11pt,a4paper]{article}
\\usepackage[margin=0.75in]{geometry}
\\usepackage{enumitem}
\\usepackage{titlesec}
\\usepackage{xcolor}

\\titleformat{\\section}{\\large\\bfseries\\color{blue}}{}{0em}{}[\\titlerule]
\\setlist{nosep}

\\begin{document}

\\begin{center}
{\\LARGE\\textbf{John Doe}}\\\\
\\vspace{2mm}
Software Engineer | Full Stack Developer\\\\
\\vspace{1mm}
Email: john.doe@email.com | Phone: (555) 123-4567\\\\
LinkedIn: linkedin.com/in/johndoe | GitHub: github.com/johndoe
\\end{center}

\\section{Professional Summary}
Experienced software engineer with 5+ years developing scalable web applications. 
Proficient in React, Node.js, and cloud technologies. Passionate about creating 
efficient solutions and mentoring junior developers.

\\section{Technical Skills}
\\textbf{Languages:} JavaScript, TypeScript, Python, Java\\\\
\\textbf{Frontend:} React, Next.js, Vue.js, HTML5, CSS3\\\\
\\textbf{Backend:} Node.js, Express, Django, Spring Boot\\\\
\\textbf{Databases:} PostgreSQL, MongoDB, Redis\\\\
\\textbf{Cloud:} AWS, Docker, Kubernetes

\\section{Professional Experience}

\\textbf{Senior Software Engineer} \\hfill \\textit{Jan 2022 - Present}\\\\
\\textit{Tech Solutions Inc.} \\hfill \\textit{San Francisco, CA}
\\begin{itemize}
\\item Led development of microservices architecture serving 1M+ users
\\item Improved application performance by 40\\% through optimization
\\item Mentored 3 junior developers and conducted code reviews
\\end{itemize}

\\textbf{Software Engineer} \\hfill \\textit{Jun 2020 - Dec 2021}\\\\
\\textit{StartupXYZ} \\hfill \\textit{Remote}
\\begin{itemize}
\\item Built responsive web applications using React and Node.js
\\item Implemented CI/CD pipelines reducing deployment time by 60\\%
\\item Collaborated with cross-functional teams in Agile environment
\\end{itemize}

\\section{Education}
\\textbf{Bachelor of Science in Computer Science} \\hfill \\textit{2016 - 2020}\\\\
\\textit{University of California, Berkeley} \\hfill \\textit{Berkeley, CA}

\\end{document}`

export default function TryNewPage() {
  const [latexContent, setLatexContent] = useState(sampleLatexContent)
  const [jobDescription, setJobDescription] = useState('')
  const [selectedIndustry, setSelectedIndustry] = useState('technology')
  const [trialUsage, setTrialUsage] = useState({ used: 0, total: 3 })
  const [showSignupPrompt, setShowSignupPrompt] = useState(false)
  const [deviceFingerprint, setDeviceFingerprint] = useState<string>('')
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [activeTab, setActiveTab] = useState<'editor' | 'preview' | 'jobs' | 'ats'>('editor')
  const [currentJobId, setCurrentJobId] = useState<string | null>(null)

  // Job management
  const {
    compileLatex,
    optimizeAndCompile,
    scoreResume,
    isSubmitting,
    submissionError,
  } = useJobManagement()

  // ATS scoring
  const {
    scoreResume: scoreResumeATS,
    scoringResult,
    isScoringLoading,
    supportedIndustries,
    recommendations,
  } = useATSScoring({
    defaultIndustry: selectedIndustry,
    userPlan: 'free',
    deviceFingerprint,
  })

  useEffect(() => {
    // Generate device fingerprint
    const fingerprint = generateDeviceFingerprint()
    setDeviceFingerprint(fingerprint)
    
    // Load trial status (simplified for demo)
    const usage = localStorage.getItem('trial_usage')
    if (usage) {
      setTrialUsage(JSON.parse(usage))
    }
  }, [])

  const handleCompile = async () => {
    if (trialUsage.used >= trialUsage.total) {
      setShowSignupPrompt(true)
      return
    }

    if (!latexContent.trim()) {
      toast.error('Please enter LaTeX content to compile')
      return
    }

    try {
      const jobId = await compileLatex(latexContent, deviceFingerprint, 'free')
      if (jobId) {
        setCurrentJobId(jobId)
        setActiveTab('jobs')
        
        // Update trial usage
        const newUsage = { ...trialUsage, used: trialUsage.used + 1 }
        setTrialUsage(newUsage)
        localStorage.setItem('trial_usage', JSON.stringify(newUsage))
        
        toast.success('Compilation job submitted!')
      }
    } catch (error) {
      console.error('Compilation error:', error)
    }
  }

  const handleOptimizeAndCompile = async () => {
    if (trialUsage.used >= trialUsage.total) {
      setShowSignupPrompt(true)
      return
    }

    if (!latexContent.trim() || !jobDescription.trim()) {
      toast.error('Please provide both LaTeX content and job description')
      return
    }

    try {
      const jobId = await optimizeAndCompile(
        latexContent, 
        jobDescription, 
        'balanced', 
        deviceFingerprint, 
        'free'
      )
      if (jobId) {
        setCurrentJobId(jobId)
        setActiveTab('jobs')
        
        // Update trial usage
        const newUsage = { ...trialUsage, used: trialUsage.used + 1 }
        setTrialUsage(newUsage)
        localStorage.setItem('trial_usage', JSON.stringify(newUsage))
        
        toast.success('Optimization & compilation job submitted!')
      }
    } catch (error) {
      console.error('Optimization error:', error)
    }
  }

  const handleATSScore = async () => {
    if (!latexContent.trim()) {
      toast.error('Please enter LaTeX content to score')
      return
    }

    try {
      const jobId = await scoreResumeATS({
        latex_content: latexContent,
        job_description: jobDescription || undefined,
        industry: selectedIndustry,
        async_processing: true,
      })
      
      if (jobId) {
        setCurrentJobId(jobId)
        setActiveTab('ats')
        toast.success('ATS scoring job submitted!')
      }
    } catch (error) {
      console.error('ATS scoring error:', error)
    }
  }

  const remainingTrials = trialUsage.total - trialUsage.used

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <div className="bg-white border-b border-gray-200 sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center space-x-4">
              <Link href="/" className="flex items-center space-x-2 text-gray-600 hover:text-gray-900 transition-colors">
                <ArrowLeft className="w-4 h-4" />
                <span>Back to Home</span>
              </Link>
              <div className="hidden md:block h-6 w-px bg-gray-300" />
              <div className="hidden md:flex items-center space-x-2">
                <div className="w-6 h-6 bg-blue-600 rounded flex items-center justify-center">
                  <FileText className="w-4 h-4 text-white" />
                </div>
                <span className="font-semibold text-gray-900">Try Latexy (Enhanced)</span>
              </div>
            </div>
            
            <div className="flex items-center space-x-4">
              <Badge 
                variant={remainingTrials > 0 ? "default" : "destructive"}
                className={`flex items-center gap-1 ${
                  remainingTrials > 0 
                    ? 'bg-green-100 text-green-700 border-green-200' 
                    : 'bg-red-100 text-red-700 border-red-200'
                }`}
              >
                <Sparkles className="w-3 h-3" />
                {remainingTrials > 0 ? `${remainingTrials} trials left` : 'Trials exhausted'}
              </Badge>
              <Button variant="outline" size="sm">
                <User className="w-4 h-4 mr-2" />
                Sign In
              </Button>
              <Link href="/billing">
                <Button size="sm" className="bg-blue-600 hover:bg-blue-700">
                  <Crown className="w-4 h-4 mr-2" />
                  Get Unlimited
                </Button>
              </Link>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <motion.div 
          className="text-center mb-8"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
        >
          <h1 className="text-3xl md:text-4xl font-bold text-gray-900 mb-4">
            Enhanced Latexy Experience
          </h1>
          <p className="text-lg text-gray-600 max-w-2xl mx-auto">
            Experience real-time job processing, ATS scoring, and advanced features with our new async system!
          </p>
        </motion.div>

        {/* Tab Navigation */}
        <div className="flex justify-center mb-8">
          <div className="flex bg-white rounded-lg border border-gray-200 p-1">
            {[
              { id: 'editor', label: 'Editor', icon: Code },
              { id: 'jobs', label: 'Jobs', icon: Clock },
              { id: 'ats', label: 'ATS Score', icon: Target },
              { id: 'preview', label: 'Preview', icon: Eye },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id as any)}
                className={`flex items-center gap-2 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
                  activeTab === tab.id
                    ? 'bg-blue-600 text-white'
                    : 'text-gray-600 hover:text-gray-900'
                }`}
              >
                <tab.icon className="w-4 h-4" />
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {/* Tab Content */}
        <div className="grid lg:grid-cols-2 gap-8">
          {/* Left Column - Always show editor */}
          <motion.div 
            className="space-y-6"
            variants={fadeInUp}
            initial="initial"
            animate="animate"
          >
            {/* LaTeX Editor */}
            <Card className="bg-white border-gray-200">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Code className="w-5 h-5 text-blue-600" />
                    <CardTitle>LaTeX Editor</CardTitle>
                  </div>
                  <div className="flex items-center space-x-2">
                    <Button variant="ghost" size="sm">
                      <Upload className="w-4 h-4" />
                    </Button>
                    <Button 
                      variant="ghost" 
                      size="sm"
                      onClick={() => setIsFullscreen(!isFullscreen)}
                    >
                      {isFullscreen ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
                    </Button>
                  </div>
                </div>
                <CardDescription>
                  Edit your resume content using LaTeX
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  <textarea
                    value={latexContent}
                    onChange={(e) => setLatexContent(e.target.value)}
                    className={`w-full p-4 text-sm font-mono border border-gray-300 rounded-lg bg-white text-gray-900 resize-none focus:ring-2 focus:ring-blue-500 focus:border-transparent ${
                      isFullscreen ? 'h-96' : 'h-64'
                    }`}
                    placeholder="Enter your LaTeX resume content here..."
                  />
                  <div className="flex justify-between items-center text-sm text-gray-500">
                    <span>{latexContent.length} characters</span>
                    <span>LaTeX format</span>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Job Description & Industry */}
            <Card className="bg-white border-gray-200">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Target className="w-5 h-5 text-green-600" />
                  Job Description & Industry
                </CardTitle>
                <CardDescription>
                  Provide context for AI optimization and ATS scoring
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Industry
                    </label>
                    <select
                      value={selectedIndustry}
                      onChange={(e) => setSelectedIndustry(e.target.value)}
                      className="w-full p-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    >
                      {supportedIndustries.map((industry) => (
                        <option key={industry} value={industry}>
                          {industry.charAt(0).toUpperCase() + industry.slice(1)}
                        </option>
                      ))}
                    </select>
                  </div>
                  
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Job Description (Optional)
                    </label>
                    <textarea
                      value={jobDescription}
                      onChange={(e) => setJobDescription(e.target.value)}
                      className="w-full h-32 p-4 text-sm border border-gray-300 rounded-lg bg-white text-gray-900 resize-none focus:ring-2 focus:ring-green-500 focus:border-transparent"
                      placeholder="Paste the job description here for AI-powered optimization..."
                    />
                  </div>
                  
                  <div className="flex justify-between items-center text-sm text-gray-500">
                    <span>{jobDescription.length} characters</span>
                    <Badge variant="outline" className="text-xs">
                      Premium Feature
                    </Badge>
                  </div>
                </div>
              </CardContent>
            </Card>

            {/* Action Buttons */}
            <div className="flex flex-col gap-3">
              <Button 
                size="lg" 
                onClick={handleCompile}
                disabled={isSubmitting || remainingTrials <= 0}
                className="bg-blue-600 hover:bg-blue-700 w-full"
              >
                {isSubmitting ? (
                  <>
                    <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin mr-2" />
                    Submitting...
                  </>
                ) : (
                  <>
                    <Zap className="w-5 h-5 mr-2" />
                    Compile PDF (Async)
                  </>
                )}
              </Button>
              
              <Button 
                size="lg" 
                onClick={handleOptimizeAndCompile}
                disabled={isSubmitting || remainingTrials <= 0 || !jobDescription.trim()}
                className="bg-purple-600 hover:bg-purple-700 w-full"
              >
                <Sparkles className="w-5 h-5 mr-2" />
                Optimize & Compile (Premium)
              </Button>

              <Button 
                size="lg" 
                onClick={handleATSScore}
                disabled={isScoringLoading}
                className="bg-green-600 hover:bg-green-700 w-full"
              >
                <Target className="w-5 h-5 mr-2" />
                ATS Score Analysis
              </Button>
            </div>
          </motion.div>

          {/* Right Column - Tab-based content */}
          <motion.div 
            className="space-y-6"
            variants={fadeInUp}
            initial="initial"
            animate="animate"
            transition={{ delay: 0.1 }}
          >
            {activeTab === 'jobs' && (
              <div className="space-y-6">
                {currentJobId && (
                  <JobStatusTracker
                    jobId={currentJobId}
                    title="Current Job"
                    showActions={true}
                    showProgress={true}
                    showMetadata={true}
                    onComplete={(result) => {
                      toast.success('Job completed successfully!')
                      console.log('Job result:', result)
                    }}
                    onError={(error) => {
                      toast.error(`Job failed: ${error}`)
                    }}
                  />
                )}
                
                <JobQueue
                  maxJobs={20}
                  showFilters={true}
                  showSearch={true}
                  onJobClick={(jobId) => {
                    setCurrentJobId(jobId)
                    toast.info(`Switched to job ${jobId.substring(0, 8)}`)
                  }}
                  onJobComplete={(jobId, result) => {
                    toast.success(`Job ${jobId.substring(0, 8)} completed!`)
                  }}
                />
              </div>
            )}

            {activeTab === 'ats' && (
              <div className="space-y-6">
                <ATSScoreCard
                  score={scoringResult?.ats_score}
                  categoryScores={scoringResult?.category_scores}
                  recommendations={scoringResult?.recommendations}
                  warnings={scoringResult?.warnings}
                  strengths={scoringResult?.strengths}
                  detailedAnalysis={scoringResult?.detailed_analysis}
                  isLoading={isScoringLoading}
                  onViewRecommendations={() => {
                    toast.info('Recommendations panel would open here')
                  }}
                  onViewAnalysis={() => {
                    toast.info('Detailed analysis would open here')
                  }}
                />

                {recommendations && (
                  <Card>
                    <CardHeader>
                      <CardTitle className="flex items-center gap-2">
                        <Lightbulb className="w-5 h-5 text-yellow-600" />
                        Improvement Recommendations
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-4">
                        {recommendations.priority_improvements.slice(0, 3).map((improvement, index) => (
                          <div key={index} className="p-3 bg-yellow-50 border border-yellow-200 rounded-lg">
                            <div className="flex items-center justify-between mb-2">
                              <h4 className="font-medium text-yellow-800">
                                {improvement.category}
                              </h4>
                              <Badge variant="outline" className={`text-xs ${
                                improvement.priority === 'high' ? 'border-red-300 text-red-700' :
                                improvement.priority === 'medium' ? 'border-yellow-300 text-yellow-700' :
                                'border-blue-300 text-blue-700'
                              }`}>
                                {improvement.priority} priority
                              </Badge>
                            </div>
                            <p className="text-sm text-yellow-700">
                              Current score: {improvement.current_score}% 
                              (potential +{improvement.potential_improvement} points)
                            </p>
                            <ul className="mt-2 space-y-1">
                              {improvement.recommended_actions.slice(0, 2).map((action, actionIndex) => (
                                <li key={actionIndex} className="text-sm text-yellow-700 flex items-start gap-2">
                                  <span className="w-1 h-1 bg-yellow-600 rounded-full mt-2 flex-shrink-0"></span>
                                  {action}
                                </li>
                              ))}
                            </ul>
                          </div>
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                )}
              </div>
            )}

            {activeTab === 'preview' && (
              <Card className="bg-white border-gray-200">
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Eye className="w-5 h-5 text-blue-600" />
                      <CardTitle>PDF Preview</CardTitle>
                    </div>
                  </div>
                  <CardDescription>
                    Your compiled resume will appear here
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="h-96 flex items-center justify-center bg-gray-50 rounded-lg border-2 border-dashed border-gray-300">
                    <div className="text-center">
                      <FileText className="w-12 h-12 text-gray-400 mx-auto mb-4" />
                      <p className="text-gray-600 font-medium">PDF preview will appear here</p>
                      <p className="text-sm text-gray-500 mt-2">Submit a compilation job to see results</p>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )}
          </motion.div>
        </div>

        {/* Trial Status */}
        <motion.div 
          className="max-w-2xl mx-auto mt-8"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.4 }}
        >
          <Card className={`${
            remainingTrials <= 1 
              ? 'border-yellow-200 bg-yellow-50' 
              : 'border-blue-200 bg-blue-50'
          }`}>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  {remainingTrials > 1 ? (
                    <CheckCircle className="w-6 h-6 text-green-600" />
                  ) : remainingTrials === 1 ? (
                    <AlertCircle className="w-6 h-6 text-yellow-600" />
                  ) : (
                    <AlertCircle className="w-6 h-6 text-red-600" />
                  )}
                  <div>
                    <h3 className="font-semibold text-gray-900">
                      {remainingTrials > 1 ? 'Free Trial Active' : 
                       remainingTrials === 1 ? 'Last Free Trial' : 
                       'Free Trials Exhausted'}
                    </h3>
                    <p className="text-sm text-gray-600">
                      {remainingTrials > 0 ? 
                        `You have ${remainingTrials} free compilation${remainingTrials > 1 ? 's' : ''} remaining` :
                        'Sign up to continue using Latexy with unlimited access'
                      }
                    </p>
                  </div>
                </div>
                {remainingTrials <= 1 && (
                  <Button className="bg-blue-600 hover:bg-blue-700">
                    <Crown className="w-4 h-4 mr-2" />
                    Sign Up Free
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>
        </motion.div>
      </div>

      {/* Signup Prompt Modal */}
      {showSignupPrompt && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            className="bg-white rounded-2xl p-8 max-w-md w-full shadow-2xl"
          >
            <div className="text-center">
              <div className="w-16 h-16 bg-blue-600 rounded-full flex items-center justify-center mx-auto mb-6">
                <Crown className="w-8 h-8 text-white" />
              </div>
              <h3 className="text-2xl font-bold text-gray-900 mb-4">
                Ready for More?
              </h3>
              <p className="text-gray-600 mb-6">
                You've experienced the power of our new async system! Sign up for free to get unlimited access and advanced features.
              </p>
              <div className="space-y-3">
                <Button className="w-full bg-blue-600 hover:bg-blue-700">
                  <User className="w-4 h-4 mr-2" />
                  Sign Up Free
                </Button>
                <Button 
                  variant="outline" 
                  className="w-full"
                  onClick={() => setShowSignupPrompt(false)}
                >
                  Continue Trial
                </Button>
              </div>
            </div>
          </motion.div>
        </div>
      )}

      {/* Toast Notifications */}
      <Toaster position="top-right" richColors />
    </div>
  )
}
