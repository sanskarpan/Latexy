'use client'

import { useCallback, useState } from 'react'
import { Upload, File, X, CheckCircle } from 'lucide-react'

interface FileUploadProps {
  onFileUpload: (content: string) => void
}

export default function FileUpload({ onFileUpload }: FileUploadProps) {
  const [isDragOver, setIsDragOver] = useState(false)
  const [uploadedFile, setUploadedFile] = useState<string | null>(null)
  const [isUploading, setIsUploading] = useState(false)

  const handleFileRead = useCallback(async (file: File) => {
    setIsUploading(true)
    try {
      const content = await file.text()
      onFileUpload(content)
      setUploadedFile(file.name)
    } catch (error) {
      console.error('Error reading file:', error)
      alert('Error reading file. Please try again.')
    } finally {
      setIsUploading(false)
    }
  }, [onFileUpload])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)

    const files = Array.from(e.dataTransfer.files)
    const texFile = files.find(file => file.name.endsWith('.tex'))

    if (texFile) {
      handleFileRead(texFile)
    } else {
      alert('Please upload a .tex file')
    }
  }, [handleFileRead])

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file && file.name.endsWith('.tex')) {
      handleFileRead(file)
    } else {
      alert('Please select a .tex file')
    }
    // Reset input
    e.target.value = ''
  }, [handleFileRead])

  const clearFile = useCallback(() => {
    setUploadedFile(null)
    onFileUpload('')
  }, [onFileUpload])

  return (
    <div className="w-full">
      {uploadedFile ? (
        <div className="card">
          <div className="card-content">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <CheckCircle className="w-5 h-5 text-green-500" />
                <div>
                  <p className="font-medium text-secondary-900">{uploadedFile}</p>
                  <p className="text-sm text-secondary-500">LaTeX file uploaded successfully</p>
                </div>
              </div>
              <button
                onClick={clearFile}
                className="p-2 hover:bg-secondary-100 rounded-lg transition-colors"
              >
                <X size={16} className="text-secondary-400" />
              </button>
            </div>
          </div>
        </div>
      ) : (
        <div
          className={`border-2 border-dashed rounded-xl p-8 transition-colors ${
            isDragOver
              ? 'border-primary-400 bg-primary-50'
              : 'border-secondary-300 hover:border-secondary-400'
          }`}
          onDrop={handleDrop}
          onDragOver={(e) => {
            e.preventDefault()
            setIsDragOver(true)
          }}
          onDragLeave={() => setIsDragOver(false)}
        >
          <div className="text-center">
            <div className="mx-auto w-12 h-12 bg-secondary-100 rounded-full flex items-center justify-center mb-4">
              {isUploading ? (
                <div className="animate-spin w-6 h-6 border-2 border-primary-600 border-t-transparent rounded-full" />
              ) : (
                <Upload className="w-6 h-6 text-secondary-400" />
              )}
            </div>
            
            <h3 className="text-lg font-medium text-secondary-900 mb-2">
              {isUploading ? 'Processing file...' : 'Upload LaTeX Resume'}
            </h3>
            
            <p className="text-secondary-500 mb-4">
              Drop your .tex file here or click to browse
            </p>
            
            <div className="flex items-center justify-center gap-4">
              <label className="btn-primary px-4 py-2 text-sm cursor-pointer">
                <input
                  type="file"
                  accept=".tex"
                  onChange={handleFileSelect}
                  className="hidden"
                  disabled={isUploading}
                />
                <File size={16} className="inline mr-2" />
                Choose File
              </label>
              
              <span className="text-xs text-secondary-400">
                or drag and drop
              </span>
            </div>
            
            <p className="text-xs text-secondary-400 mt-3">
              Supported format: .tex (up to 10MB)
            </p>
          </div>
        </div>
      )}
    </div>
  )
}