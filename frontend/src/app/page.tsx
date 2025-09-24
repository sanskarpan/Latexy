'use client'

import { useState, useCallback, useEffect } from 'react'
import Header from '@/components/Header'
import LaTeXEditor from '@/components/LaTeXEditor'
import JobDescriptionInput from '@/components/JobDescriptionInput'
import PDFPreview from '@/components/PDFPreview'
import FileUpload from '@/components/FileUpload'
import LoadingSpinner from '@/components/LoadingSpinner'
import ErrorBoundary from '@/components/ErrorBoundary'
import { useCompilation, usePdf, useHealthCheck, useOptimization } from '@/hooks/useApi'
import { FileText, Briefcase, Eye, AlertCircle, CheckCircle } from 'lucide-react'

export default function Home() {
  const [latexContent, setLatexContent] = useState('')
  const [jobDescription, setJobDescription] = useState('')
  const [activeTab, setActiveTab] = useState<'editor' | 'job' | 'preview'>('editor')
  
  // API hooks
  const { compile, isLoading: isCompiling, result: compilationResult } = useCompilation()
  const { pdfUrl, loadPdf, downloadPdf, clearPdf, isLoading: isPdfLoading } = usePdf()
  const { health, checkHealth, isLoading: isHealthLoading } = useHealthCheck()
  const { optimizeAndCompile, isLoading: isOptimizing, result: optimizationResult } = useOptimization()
  
  const isLoading = isCompiling || isPdfLoading || isOptimizing

  // Check backend health on mount
  useEffect(() => {
    checkHealth()
  }, [checkHealth])

  // Load PDF when compilation succeeds
  useEffect(() => {
    if (compilationResult?.success && compilationResult.job_id) {
      loadPdf(compilationResult.job_id)
      setActiveTab('preview')
    }
  }, [compilationResult, loadPdf])

  // Load PDF when optimization and compilation succeeds
  useEffect(() => {
    if (optimizationResult?.success) {
      // Check if we have a compilation result from optimize-and-compile
      const jobId = (optimizationResult as any)?.compilation?.job_id
      if (jobId) {
        loadPdf(jobId)
        setActiveTab('preview')
      }
    }
  }, [optimizationResult, loadPdf])

  const handleFileUpload = useCallback((content: string) => {
    setLatexContent(content)
    setActiveTab('editor')
    clearPdf() // Clear previous PDF when new content is loaded
  }, [clearPdf])

  const handleLatexChange = useCallback((value: string) => {
    setLatexContent(value)
    if (pdfUrl) {
      clearPdf() // Clear PDF when content changes
    }
  }, [pdfUrl, clearPdf])

  const handleJobDescriptionChange = useCallback((value: string) => {
    setJobDescription(value)
  }, [])

  const handleCompilePdf = useCallback(async () => {
    if (!latexContent.trim()) return
    
    clearPdf() // Clear previous PDF
    await compile(latexContent)
  }, [latexContent, compile, clearPdf])

  const handleOptimizeResume = useCallback(async () => {
    if (!latexContent.trim() || !jobDescription.trim()) return
    
    clearPdf() // Clear previous PDF
    const result = await optimizeAndCompile({
      latex_content: latexContent,
      job_description: jobDescription,
      optimization_level: 'balanced'
    })
    
    // Update LaTeX content with optimized version
    if (result?.optimization.success && result.optimization.optimized_latex) {
      setLatexContent(result.optimization.optimized_latex)
    }
  }, [latexContent, jobDescription, optimizeAndCompile, clearPdf])

  const handleDownloadPdf = useCallback(() => {
    if (compilationResult?.job_id) {
      const filename = `resume_${new Date().toISOString().split('T')[0]}.pdf`
      downloadPdf(compilationResult.job_id, filename)
    }
  }, [compilationResult, downloadPdf])

  return (
    <ErrorBoundary>
      <div className="min-h-screen">
        <Header />
        
        <main className="container mx-auto px-4 py-8">
          {/* Backend Status */}
          <div className="mb-6">
            <div className="flex items-center justify-between p-4 bg-secondary-50 rounded-lg">
              <div className="flex items-center gap-3">
                {isHealthLoading ? (
                  <LoadingSpinner size="sm" />
                ) : health?.latex_available ? (
                  <CheckCircle className="w-5 h-5 text-green-500" />
                ) : (
                  <AlertCircle className="w-5 h-5 text-red-500" />
                )}
                <div>
                  <p className="font-medium text-secondary-900">
                    Backend Status: {health?.status || 'Unknown'}
                  </p>
                  <p className="text-sm text-secondary-600">
                    LaTeX: {health?.latex_available ? 'Available' : 'Unavailable'} • 
                    Version: {health?.version || 'Unknown'}
                  </p>
                </div>
              </div>
              <button
                onClick={checkHealth}
                disabled={isHealthLoading}
                className="btn-outline px-3 py-1 text-xs"
              >
                Refresh
              </button>
            </div>
          </div>

          {/* Upload Section */}
          <div className="mb-8">
            <FileUpload onFileUpload={handleFileUpload} />
          </div>

          {/* Mobile Tab Navigation */}
          <div className="lg:hidden mb-6">
            <div className="flex space-x-1 bg-secondary-100 rounded-lg p-1">
              <button
                onClick={() => setActiveTab('editor')}
                className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-md text-sm font-medium transition-colors ${
                  activeTab === 'editor'
                    ? 'bg-white text-primary-700 shadow-sm'
                    : 'text-secondary-600 hover:text-secondary-900'
                }`}
              >
                <FileText size={16} />
                LaTeX
              </button>
              <button
                onClick={() => setActiveTab('job')}
                className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-md text-sm font-medium transition-colors ${
                  activeTab === 'job'
                    ? 'bg-white text-primary-700 shadow-sm'
                    : 'text-secondary-600 hover:text-secondary-900'
                }`}
              >
                <Briefcase size={16} />
                Job
              </button>
              <button
                onClick={() => setActiveTab('preview')}
                className={`flex-1 flex items-center justify-center gap-2 py-2 px-3 rounded-md text-sm font-medium transition-colors ${
                  activeTab === 'preview'
                    ? 'bg-white text-primary-700 shadow-sm'
                    : 'text-secondary-600 hover:text-secondary-900'
                }`}
              >
                <Eye size={16} />
                Preview
              </button>
            </div>
          </div>

          {/* Main Content */}
          <div className="grid grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 gap-6">
            {/* LaTeX Editor */}
            <div className={`${activeTab !== 'editor' ? 'hidden lg:block' : ''} xl:col-span-1`}>
              <div className="card h-[700px] lg:h-[800px] flex flex-col">
                <div className="card-header">
                  <h2 className="text-lg font-semibold text-secondary-900 flex items-center gap-2">
                    <FileText size={20} className="text-primary-600" />
                    LaTeX Editor
                  </h2>
                  <p className="text-sm text-secondary-500">
                    Edit your resume LaTeX source code
                  </p>
                </div>
                <div className="card-content flex-1 min-h-0">
                  <LaTeXEditor
                    value={latexContent}
                    onChange={handleLatexChange}
                  />
                </div>
              </div>
            </div>

            {/* Job Description */}
            <div className={`${activeTab !== 'job' ? 'hidden lg:block' : ''} xl:col-span-1`}>
              <div className="card h-[700px] lg:h-[800px] flex flex-col">
                <div className="card-header">
                  <h2 className="text-lg font-semibold text-secondary-900 flex items-center gap-2">
                    <Briefcase size={20} className="text-primary-600" />
                    Job Description
                  </h2>
                  <p className="text-sm text-secondary-500">
                    Paste the job description for optimization
                  </p>
                </div>
                <div className="card-content flex-1 min-h-0">
                  <JobDescriptionInput
                    value={jobDescription}
                    onChange={handleJobDescriptionChange}
                  />
                </div>
              </div>
            </div>

            {/* PDF Preview */}
            <div className={`${activeTab !== 'preview' ? 'hidden lg:block' : ''} xl:col-span-1`}>
              <div className="card h-[700px] lg:h-[800px] flex flex-col">
                <div className="card-header">
                  <h2 className="text-lg font-semibold text-secondary-900 flex items-center gap-2">
                    <Eye size={20} className="text-primary-600" />
                    PDF Preview
                  </h2>
                  <p className="text-sm text-secondary-500">
                    Preview your compiled resume
                  </p>
                </div>
                <div className="card-content flex-1 min-h-0">
                  <PDFPreview
                    pdfUrl={pdfUrl}
                    isLoading={isPdfLoading}
                    onDownload={handleDownloadPdf}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Action Bar */}
          <div className="mt-8">
            <div className="card">
              <div className="card-content">
                <div className="flex flex-col sm:flex-row gap-4 items-center justify-between">
                  <div className="flex items-center gap-4 text-sm text-secondary-600">
                    <span className="flex items-center gap-2">
                      <div className={`w-2 h-2 rounded-full ${latexContent ? 'bg-green-500' : 'bg-secondary-300'}`} />
                      LaTeX Content
                    </span>
                    <span className="flex items-center gap-2">
                      <div className={`w-2 h-2 rounded-full ${jobDescription ? 'bg-green-500' : 'bg-secondary-300'}`} />
                      Job Description
                    </span>
                  </div>
                  
                  <div className="flex gap-3">
                    <button
                      onClick={handleCompilePdf}
                      className="btn-outline px-4 py-2 text-sm"
                      disabled={!latexContent || isLoading || !health?.latex_available}
                    >
                      {isCompiling ? (
                        <div className="flex items-center gap-2">
                          <LoadingSpinner size="sm" />
                          Compiling...
                        </div>
                      ) : (
                        'Compile PDF'
                      )}
                    </button>
                    <button
                      onClick={handleOptimizeResume}
                      className="btn-primary px-4 py-2 text-sm"
                      disabled={!latexContent || !jobDescription || isLoading || !health?.latex_available}
                    >
                      {isLoading ? (
                        <div className="flex items-center gap-2">
                          <LoadingSpinner size="sm" />
                          Processing...
                        </div>
                      ) : (
                        'Optimize Resume'
                      )}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* Help Section */}
          <div className="mt-8">
            <div className="card">
              <div className="card-header">
                <h3 className="font-semibold text-secondary-900">Getting Started</h3>
              </div>
              <div className="card-content">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
                  <div className="flex items-start gap-3">
                    <div className="w-6 h-6 bg-primary-100 text-primary-700 rounded-full flex items-center justify-center text-xs font-bold">1</div>
                    <div>
                      <p className="font-medium text-secondary-900">Upload or Edit LaTeX</p>
                      <p className="text-secondary-600">Start with your resume LaTeX source code</p>
                    </div>
                  </div>
                  <div className="flex items-start gap-3">
                    <div className="w-6 h-6 bg-primary-100 text-primary-700 rounded-full flex items-center justify-center text-xs font-bold">2</div>
                    <div>
                      <p className="font-medium text-secondary-900">Add Job Description</p>
                      <p className="text-secondary-600">Paste the target job posting details</p>
                    </div>
                  </div>
                  <div className="flex items-start gap-3">
                    <div className="w-6 h-6 bg-primary-100 text-primary-700 rounded-full flex items-center justify-center text-xs font-bold">3</div>
                    <div>
                      <p className="font-medium text-secondary-900">Optimize & Download</p>
                      <p className="text-secondary-600">Get ATS-optimized resume with insights</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </main>
      </div>
    </ErrorBoundary>
  )
}