'use client'

import { useState, useCallback } from 'react'
import Header from '@/components/Header'
import LaTeXEditor from '@/components/LaTeXEditor'
import JobDescriptionInput from '@/components/JobDescriptionInput'
import PDFPreview from '@/components/PDFPreview'
import FileUpload from '@/components/FileUpload'
import LoadingSpinner from '@/components/LoadingSpinner'
import ErrorBoundary from '@/components/ErrorBoundary'
import { FileText, Briefcase, Eye } from 'lucide-react'

export default function Home() {
  const [latexContent, setLatexContent] = useState('')
  const [jobDescription, setJobDescription] = useState('')
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [activeTab, setActiveTab] = useState<'editor' | 'job' | 'preview'>('editor')

  const handleFileUpload = useCallback((content: string) => {
    setLatexContent(content)
    setActiveTab('editor')
  }, [])

  const handleLatexChange = useCallback((value: string) => {
    setLatexContent(value)
  }, [])

  const handleJobDescriptionChange = useCallback((value: string) => {
    setJobDescription(value)
  }, [])

  return (
    <ErrorBoundary>
      <div className="min-h-screen">
        <Header />
        
        <main className="container mx-auto px-4 py-8">
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
              <div className="card h-[600px] flex flex-col">
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
              <div className="card h-[600px] flex flex-col">
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
              <div className="card h-[600px] flex flex-col">
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
                    isLoading={isLoading}
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
                      className="btn-outline px-4 py-2 text-sm"
                      disabled={!latexContent || isLoading}
                    >
                      Compile PDF
                    </button>
                    <button
                      className="btn-primary px-4 py-2 text-sm"
                      disabled={!latexContent || !jobDescription || isLoading}
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