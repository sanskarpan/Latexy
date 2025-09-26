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
  Upload
} from 'lucide-react'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'
import { apiClient, generateDeviceFingerprint, showSuccessToast, showErrorToast } from '@/lib/api-client'

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

export default function TryPage() {
  const [latexContent, setLatexContent] = useState(sampleLatexContent)
  const [jobDescription, setJobDescription] = useState('')
  const [isCompiling, setIsCompiling] = useState(false)
  const [compilationResult, setCompilationResult] = useState<any>(null)
  const [trialUsage, setTrialUsage] = useState({ used: 0, total: 3 })
  const [showSignupPrompt, setShowSignupPrompt] = useState(false)
  const [deviceFingerprint, setDeviceFingerprint] = useState<string>('')
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [activeTab, setActiveTab] = useState<'editor' | 'preview'>('editor')

  useEffect(() => {
    // Generate device fingerprint
    const fingerprint = generateDeviceFingerprint()
    setDeviceFingerprint(fingerprint)
    
    // Load trial status from API
    loadTrialStatus(fingerprint)
  }, [])

  const loadTrialStatus = async (fingerprint: string) => {
    try {
      const response = await apiClient.getTrialStatus(fingerprint)
      if (response.success && response.data) {
        setTrialUsage({
          used: response.data.usage_count,
          total: 3
        })
      }
    } catch (error) {
      console.error('Failed to load trial status:', error)
      // Fallback to localStorage
      const usage = localStorage.getItem('trial_usage')
      if (usage) {
        setTrialUsage(JSON.parse(usage))
      }
    }
  }

  const handleCompile = async () => {
    if (trialUsage.used >= trialUsage.total) {
      setShowSignupPrompt(true)
      return
    }

    if (!latexContent.trim()) {
      showErrorToast('Please enter LaTeX content to compile')
      return
    }

    setIsCompiling(true)
    
    try {
      // Track usage
      await apiClient.trackUsage(deviceFingerprint, 'compile')
      
      // Compile LaTeX
      const response = await apiClient.compileLatex({
        latex_content: latexContent,
        device_fingerprint: deviceFingerprint
      })

      if (response.success && response.data) {
        setCompilationResult({
          success: true,
          pdfUrl: `/jobs/${response.data.job_id}/download`,
          jobId: response.data.job_id
        })
        
        showSuccessToast('Resume compiled successfully!')
        
        // Update trial usage
        const newUsage = { ...trialUsage, used: trialUsage.used + 1 }
        setTrialUsage(newUsage)
        localStorage.setItem('trial_usage', JSON.stringify(newUsage))
        
        // Show signup prompt after 2nd use
        if (newUsage.used >= 2) {
          setTimeout(() => setShowSignupPrompt(true), 2000)
        }
      } else {
        throw new Error(response.error || 'Compilation failed')
      }
    } catch (error) {
      console.error('Compilation error:', error)
      showErrorToast(error instanceof Error ? error.message : 'Compilation failed')
      setCompilationResult({
        success: false,
        error: error instanceof Error ? error.message : 'Compilation failed'
      })
    } finally {
      setIsCompiling(false)
    }
  }

  const handleDownload = async () => {
    if (!compilationResult?.jobId) return
    
    try {
      const response = await apiClient.downloadPdf(compilationResult.jobId)
      if (response.success && response.data) {
        const url = URL.createObjectURL(response.data)
        const a = document.createElement('a')
        a.href = url
        a.download = 'resume.pdf'
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
        
        showSuccessToast('PDF downloaded successfully!')
      } else {
        throw new Error(response.error || 'Download failed')
      }
    } catch (error) {
      console.error('Download error:', error)
      showErrorToast(error instanceof Error ? error.message : 'Download failed')
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
                <span className="font-semibold text-gray-900">Try Latexy</span>
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
        {/* Trial Header */}
        <motion.div 
          className="text-center mb-8"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
        >
          <h1 className="text-3xl md:text-4xl font-bold text-gray-900 mb-4">
            Try Latexy Free
          </h1>
          <p className="text-lg text-gray-600 max-w-2xl mx-auto">
            Experience the power of AI-driven resume optimization. No sign-up required for your first 3 tries!
          </p>
        </motion.div>

        {/* Main Editor Layout */}
        <div className="grid lg:grid-cols-2 gap-8 mb-8">
          {/* LaTeX Editor */}
          <motion.div 
            className="space-y-6"
            variants={fadeInUp}
            initial="initial"
            animate="animate"
          >
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

            {/* Job Description */}
            <Card className="bg-white border-gray-200">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Target className="w-5 h-5 text-green-600" />
                  Job Description (Optional)
                </CardTitle>
                <CardDescription>
                  Paste the job description for AI optimization
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  <textarea
                    value={jobDescription}
                    onChange={(e) => setJobDescription(e.target.value)}
                    className="w-full h-32 p-4 text-sm border border-gray-300 rounded-lg bg-white text-gray-900 resize-none focus:ring-2 focus:ring-green-500 focus:border-transparent"
                    placeholder="Paste the job description here for AI-powered optimization..."
                  />
                  <div className="flex justify-between items-center text-sm text-gray-500">
                    <span>{jobDescription.length} characters</span>
                    <Badge variant="outline" className="text-xs">
                      Premium Feature
                    </Badge>
                  </div>
                </div>
              </CardContent>
            </Card>
          </motion.div>

          {/* PDF Preview */}
          <motion.div 
            className="space-y-6"
            variants={fadeInUp}
            initial="initial"
            animate="animate"
            transition={{ delay: 0.1 }}
          >
            <Card className="bg-white border-gray-200">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Eye className="w-5 h-5 text-blue-600" />
                    <CardTitle>PDF Preview</CardTitle>
                  </div>
                  <div className="flex items-center space-x-2">
                    {compilationResult && (
                      <Button 
                        size="sm" 
                        onClick={handleDownload}
                        className="bg-green-600 hover:bg-green-700"
                      >
                        <Download className="w-4 h-4 mr-2" />
                        Download
                      </Button>
                    )}
                  </div>
                </div>
                <CardDescription>
                  Your compiled resume will appear here
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {isCompiling ? (
                    <div className="h-96 flex items-center justify-center bg-gray-50 rounded-lg border-2 border-dashed border-gray-300">
                      <div className="text-center">
                        <div className="w-12 h-12 border-4 border-blue-600 border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
                        <p className="text-gray-700 font-medium">Compiling your resume...</p>
                        <p className="text-sm text-gray-500 mt-2">This may take a few seconds</p>
                      </div>
                    </div>
                  ) : compilationResult?.success ? (
                    <div className="space-y-4">
                      <div className="h-96 bg-white rounded-lg border border-gray-300 flex items-center justify-center">
                        <div className="text-center">
                          <CheckCircle className="w-16 h-16 text-green-600 mx-auto mb-4" />
                          <p className="text-gray-900 font-medium mb-2">Resume compiled successfully!</p>
                          <p className="text-sm text-gray-600 mb-4">Your professional PDF is ready</p>
                          <Button 
                            onClick={handleDownload}
                            className="bg-green-600 hover:bg-green-700"
                          >
                            <Download className="w-4 h-4 mr-2" />
                            Download PDF
                          </Button>
                        </div>
                      </div>
                    </div>
                  ) : compilationResult?.error ? (
                    <div className="h-96 flex items-center justify-center bg-red-50 rounded-lg border-2 border-dashed border-red-300">
                      <div className="text-center">
                        <AlertCircle className="w-12 h-12 text-red-500 mx-auto mb-4" />
                        <p className="text-red-700 font-medium mb-2">Compilation failed</p>
                        <p className="text-sm text-red-600 mb-4">{compilationResult.error}</p>
                        <Button 
                          variant="outline" 
                          onClick={() => setCompilationResult(null)}
                          className="border-red-300 text-red-700 hover:bg-red-50"
                        >
                          <RefreshCw className="w-4 h-4 mr-2" />
                          Try Again
                        </Button>
                      </div>
                    </div>
                  ) : (
                    <div className="h-96 flex items-center justify-center bg-gray-50 rounded-lg border-2 border-dashed border-gray-300">
                      <div className="text-center">
                        <FileText className="w-12 h-12 text-gray-400 mx-auto mb-4" />
                        <p className="text-gray-600 font-medium">PDF preview will appear here</p>
                        <p className="text-sm text-gray-500 mt-2">Click compile to generate your resume</p>
                      </div>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          </motion.div>
        </div>

        {/* Action Bar */}
        <motion.div 
          className="flex flex-col sm:flex-row gap-4 justify-center items-center mb-8"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.3 }}
        >
          <Button 
            size="lg" 
            onClick={handleCompile}
            disabled={isCompiling || remainingTrials <= 0}
            className="bg-blue-600 hover:bg-blue-700 px-8 py-3 text-lg"
          >
            {isCompiling ? (
              <>
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin mr-2" />
                Compiling...
              </>
            ) : (
              <>
                <Zap className="w-5 h-5 mr-2" />
                Compile PDF
              </>
            )}
          </Button>
          
          <Button variant="outline" size="lg" disabled className="px-8 py-3 text-lg">
            <Save className="w-5 h-5 mr-2" />
            Save (Sign Up Required)
          </Button>

          {jobDescription && (
            <Button variant="outline" size="lg" disabled className="px-8 py-3 text-lg">
              <Sparkles className="w-5 h-5 mr-2" />
              AI Optimize (Premium)
            </Button>
          )}
        </motion.div>

        {/* Trial Status */}
        <motion.div 
          className="max-w-2xl mx-auto mb-8"
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

        {/* Features Teaser */}
        <motion.div 
          className="text-center"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.5 }}
        >
          <h2 className="text-2xl font-bold text-gray-900 mb-6">
            Unlock More with a Free Account
          </h2>
          <div className="grid md:grid-cols-3 gap-6 max-w-4xl mx-auto">
            <Card className="border-blue-200 bg-blue-50">
              <CardContent className="p-6 text-center">
                <Save className="w-8 h-8 text-blue-600 mx-auto mb-4" />
                <h3 className="font-semibold text-gray-900 mb-2">Save & Manage</h3>
                <p className="text-sm text-gray-600">
                  Save your resumes and access them anytime
                </p>
              </CardContent>
            </Card>
            <Card className="border-green-200 bg-green-50">
              <CardContent className="p-6 text-center">
                <Sparkles className="w-8 h-8 text-green-600 mx-auto mb-4" />
                <h3 className="font-semibold text-gray-900 mb-2">AI Optimization</h3>
                <p className="text-sm text-gray-600">
                  Get AI-powered resume improvements
                </p>
              </CardContent>
            </Card>
            <Card className="border-orange-200 bg-orange-50">
              <CardContent className="p-6 text-center">
                <Target className="w-8 h-8 text-orange-600 mx-auto mb-4" />
                <h3 className="font-semibold text-gray-900 mb-2">ATS Scoring</h3>
                <p className="text-sm text-gray-600">
                  Real-time ATS compatibility analysis
                </p>
              </CardContent>
            </Card>
          </div>
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
                You've experienced the power of Latexy! Sign up for free to get unlimited access and advanced features.
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