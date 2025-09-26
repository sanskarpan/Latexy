'use client'

import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
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
  Crown
} from 'lucide-react'
import Link from 'next/link'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'

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

  useEffect(() => {
    // Simulate trial usage check
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

    setIsCompiling(true)
    
    // Simulate compilation
    setTimeout(() => {
      setIsCompiling(false)
      setCompilationResult({
        success: true,
        pdfUrl: '/sample-resume.pdf',
        jobId: 'demo-job-123'
      })
      
      // Update trial usage
      const newUsage = { ...trialUsage, used: trialUsage.used + 1 }
      setTrialUsage(newUsage)
      localStorage.setItem('trial_usage', JSON.stringify(newUsage))
      
      // Show signup prompt after 2nd use
      if (newUsage.used >= 2) {
        setTimeout(() => setShowSignupPrompt(true), 2000)
      }
    }, 3000)
  }

  const remainingTrials = trialUsage.total - trialUsage.used

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 dark:from-slate-900 dark:to-slate-800">
      {/* Header */}
      <div className="bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm border-b border-gray-200 dark:border-gray-700 sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center space-x-4">
              <Link href="/" className="flex items-center space-x-2 text-gray-600 hover:text-gray-900 dark:text-gray-300 dark:hover:text-white transition-colors">
                <ArrowLeft className="w-4 h-4" />
                <span>Back to Home</span>
              </Link>
            </div>
            
            <div className="flex items-center space-x-4">
              <Badge 
                variant={remainingTrials > 0 ? "success" : "destructive"}
                className="flex items-center gap-1"
              >
                <Sparkles className="w-3 h-3" />
                {remainingTrials > 0 ? `${remainingTrials} trials left` : 'Trials exhausted'}
              </Badge>
              <Button variant="outline" size="sm">
                <User className="w-4 h-4 mr-2" />
                Sign In
              </Button>
              <Button size="sm" className="bg-gradient-to-r from-blue-500 to-purple-600">
                <Crown className="w-4 h-4 mr-2" />
                Get Unlimited
              </Button>
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
          <h1 className="text-3xl md:text-4xl font-bold text-gray-900 dark:text-white mb-4">
            Try Latexy Free
          </h1>
          <p className="text-lg text-gray-600 dark:text-gray-300 max-w-2xl mx-auto">
            Experience the power of AI-driven resume optimization. No sign-up required for your first 3 tries!
          </p>
        </motion.div>

        {/* Main Editor Layout */}
        <div className="grid lg:grid-cols-3 gap-8">
          {/* LaTeX Editor */}
          <motion.div 
            className="lg:col-span-1"
            variants={fadeInUp}
            initial="initial"
            animate="animate"
          >
            <Card className="h-full">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <FileText className="w-5 h-5 text-blue-500" />
                  LaTeX Editor
                </CardTitle>
                <CardDescription>
                  Edit your resume content using LaTeX
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  <textarea
                    value={latexContent}
                    onChange={(e) => setLatexContent(e.target.value)}
                    className="w-full h-96 p-4 text-sm font-mono border border-gray-300 dark:border-gray-600 rounded-lg bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-gray-100 resize-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                    placeholder="Enter your LaTeX resume content here..."
                  />
                  <div className="flex justify-between items-center text-sm text-gray-500 dark:text-gray-400">
                    <span>{latexContent.length} characters</span>
                    <span>LaTeX format</span>
                  </div>
                </div>
              </CardContent>
            </Card>
          </motion.div>

          {/* Job Description */}
          <motion.div 
            className="lg:col-span-1"
            variants={fadeInUp}
            initial="initial"
            animate="animate"
            transition={{ delay: 0.1 }}
          >
            <Card className="h-full">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Target className="w-5 h-5 text-green-500" />
                  Job Description
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
                    className="w-full h-96 p-4 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-gray-100 resize-none focus:ring-2 focus:ring-green-500 focus:border-transparent"
                    placeholder="Paste the job description here for AI-powered optimization..."
                  />
                  <div className="flex justify-between items-center text-sm text-gray-500 dark:text-gray-400">
                    <span>{jobDescription.length} characters</span>
                    <span>Optional for basic compilation</span>
                  </div>
                </div>
              </CardContent>
            </Card>
          </motion.div>

          {/* PDF Preview */}
          <motion.div 
            className="lg:col-span-1"
            variants={fadeInUp}
            initial="initial"
            animate="animate"
            transition={{ delay: 0.2 }}
          >
            <Card className="h-full">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Download className="w-5 h-5 text-purple-500" />
                  PDF Preview
                </CardTitle>
                <CardDescription>
                  Your compiled resume will appear here
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {isCompiling ? (
                    <div className="h-96 flex items-center justify-center bg-gray-50 dark:bg-gray-800 rounded-lg border-2 border-dashed border-gray-300 dark:border-gray-600">
                      <div className="text-center">
                        <div className="w-12 h-12 border-4 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
                        <p className="text-gray-600 dark:text-gray-300 font-medium">Compiling your resume...</p>
                        <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">This may take a few seconds</p>
                      </div>
                    </div>
                  ) : compilationResult ? (
                    <div className="space-y-4">
                      <div className="h-96 bg-white rounded-lg border border-gray-300 dark:border-gray-600 flex items-center justify-center">
                        <div className="text-center">
                          <CheckCircle className="w-16 h-16 text-green-500 mx-auto mb-4" />
                          <p className="text-gray-900 dark:text-white font-medium mb-2">Resume compiled successfully!</p>
                          <p className="text-sm text-gray-600 dark:text-gray-300 mb-4">Your professional PDF is ready</p>
                          <Button className="bg-gradient-to-r from-green-500 to-blue-500 hover:from-green-600 hover:to-blue-600">
                            <Download className="w-4 h-4 mr-2" />
                            Download PDF
                          </Button>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className="h-96 flex items-center justify-center bg-gray-50 dark:bg-gray-800 rounded-lg border-2 border-dashed border-gray-300 dark:border-gray-600">
                      <div className="text-center">
                        <FileText className="w-12 h-12 text-gray-400 mx-auto mb-4" />
                        <p className="text-gray-600 dark:text-gray-300 font-medium">PDF preview will appear here</p>
                        <p className="text-sm text-gray-500 dark:text-gray-400 mt-2">Click compile to generate your resume</p>
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
          className="mt-8 flex flex-col sm:flex-row gap-4 justify-center items-center"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.3 }}
        >
          <Button 
            size="lg" 
            onClick={handleCompile}
            disabled={isCompiling || remainingTrials <= 0}
            className="bg-gradient-to-r from-blue-500 to-purple-600 hover:from-blue-600 hover:to-purple-700 shadow-lg"
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
          
          <Button variant="outline" size="lg" disabled>
            <Save className="w-5 h-5 mr-2" />
            Save (Sign Up Required)
          </Button>

          {jobDescription && (
            <Button variant="outline" size="lg" disabled>
              <Sparkles className="w-5 h-5 mr-2" />
              AI Optimize (Premium)
            </Button>
          )}
        </motion.div>

        {/* Trial Status */}
        <motion.div 
          className="mt-8 max-w-2xl mx-auto"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.4 }}
        >
          <Card className={`${remainingTrials <= 1 ? 'border-yellow-500/50 bg-yellow-500/5' : 'border-blue-500/50 bg-blue-500/5'}`}>
            <CardContent className="p-6">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  {remainingTrials > 1 ? (
                    <CheckCircle className="w-6 h-6 text-green-500" />
                  ) : remainingTrials === 1 ? (
                    <AlertCircle className="w-6 h-6 text-yellow-500" />
                  ) : (
                    <AlertCircle className="w-6 h-6 text-red-500" />
                  )}
                  <div>
                    <h3 className="font-semibold text-gray-900 dark:text-white">
                      {remainingTrials > 1 ? 'Free Trial Active' : 
                       remainingTrials === 1 ? 'Last Free Trial' : 
                       'Free Trials Exhausted'}
                    </h3>
                    <p className="text-sm text-gray-600 dark:text-gray-300">
                      {remainingTrials > 0 ? 
                        `You have ${remainingTrials} free compilation${remainingTrials > 1 ? 's' : ''} remaining` :
                        'Sign up to continue using Latexy with unlimited access'
                      }
                    </p>
                  </div>
                </div>
                {remainingTrials <= 1 && (
                  <Button className="bg-gradient-to-r from-blue-500 to-purple-600">
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
          className="mt-12 text-center"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6, delay: 0.5 }}
        >
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white mb-6">
            Unlock More with a Free Account
          </h2>
          <div className="grid md:grid-cols-3 gap-6 max-w-4xl mx-auto">
            <Card className="border-blue-500/20 bg-blue-500/5">
              <CardContent className="p-6 text-center">
                <Save className="w-8 h-8 text-blue-500 mx-auto mb-4" />
                <h3 className="font-semibold text-gray-900 dark:text-white mb-2">Save & Manage</h3>
                <p className="text-sm text-gray-600 dark:text-gray-300">
                  Save your resumes and access them anytime
                </p>
              </CardContent>
            </Card>
            <Card className="border-green-500/20 bg-green-500/5">
              <CardContent className="p-6 text-center">
                <Sparkles className="w-8 h-8 text-green-500 mx-auto mb-4" />
                <h3 className="font-semibold text-gray-900 dark:text-white mb-2">AI Optimization</h3>
                <p className="text-sm text-gray-600 dark:text-gray-300">
                  Get AI-powered resume improvements
                </p>
              </CardContent>
            </Card>
            <Card className="border-purple-500/20 bg-purple-500/5">
              <CardContent className="p-6 text-center">
                <Target className="w-8 h-8 text-purple-500 mx-auto mb-4" />
                <h3 className="font-semibold text-gray-900 dark:text-white mb-2">ATS Scoring</h3>
                <p className="text-sm text-gray-600 dark:text-gray-300">
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
            className="bg-white dark:bg-gray-800 rounded-2xl p-8 max-w-md w-full shadow-2xl"
          >
            <div className="text-center">
              <div className="w-16 h-16 bg-gradient-to-r from-blue-500 to-purple-600 rounded-full flex items-center justify-center mx-auto mb-6">
                <Crown className="w-8 h-8 text-white" />
              </div>
              <h3 className="text-2xl font-bold text-gray-900 dark:text-white mb-4">
                Ready for More?
              </h3>
              <p className="text-gray-600 dark:text-gray-300 mb-6">
                You've experienced the power of Latexy! Sign up for free to get unlimited access and advanced features.
              </p>
              <div className="space-y-3">
                <Button className="w-full bg-gradient-to-r from-blue-500 to-purple-600 hover:from-blue-600 hover:to-purple-700">
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
    </div>
  )
}
