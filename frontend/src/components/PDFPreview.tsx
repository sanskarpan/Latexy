'use client'

import { useState } from 'react'
import { FileText, Download, ZoomIn, ZoomOut } from 'lucide-react'
import LoadingSpinner from './LoadingSpinner'

interface PDFPreviewProps {
  pdfUrl: string | null
  isLoading: boolean
}

export default function PDFPreview({ pdfUrl, isLoading }: PDFPreviewProps) {
  const [zoom, setZoom] = useState(1)

  const handleZoomIn = () => setZoom(prev => Math.min(prev + 0.2, 3))
  const handleZoomOut = () => setZoom(prev => Math.max(prev - 0.2, 0.5))

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <LoadingSpinner />
          <p className="text-secondary-500 mt-4">Compiling PDF...</p>
        </div>
      </div>
    )
  }

  if (!pdfUrl) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center">
          <FileText className="w-12 h-12 text-secondary-300 mx-auto mb-4" />
          <p className="text-secondary-500">No PDF available</p>
          <p className="text-xs text-secondary-400 mt-2">
            Compile your LaTeX to see the preview
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      {/* Controls */}
      <div className="flex items-center justify-between p-3 border-b border-secondary-200">
        <div className="flex items-center gap-2">
          <button
            onClick={handleZoomOut}
            className="p-1 hover:bg-secondary-100 rounded"
            disabled={zoom <= 0.5}
          >
            <ZoomOut size={16} />
          </button>
          <span className="text-xs text-secondary-600 min-w-[3rem] text-center">
            {Math.round(zoom * 100)}%
          </span>
          <button
            onClick={handleZoomIn}
            className="p-1 hover:bg-secondary-100 rounded"
            disabled={zoom >= 3}
          >
            <ZoomIn size={16} />
          </button>
        </div>
        
        <button className="flex items-center gap-2 text-xs text-secondary-600 hover:text-secondary-900">
          <Download size={14} />
          Download
        </button>
      </div>

      {/* PDF Viewer */}
      <div className="flex-1 bg-secondary-50 overflow-auto">
        <div className="p-4 flex justify-center">
          <div 
            className="bg-white shadow-lg"
            style={{ 
              transform: `scale(${zoom})`,
              transformOrigin: 'top center',
              transition: 'transform 0.2s ease'
            }}
          >
            {/* PDF content will go here when we integrate with backend */}
            <div className="w-[595px] h-[842px] bg-white border border-secondary-200 flex items-center justify-center">
              <div className="text-center text-secondary-400">
                <FileText size={48} className="mx-auto mb-4" />
                <p>PDF Preview Placeholder</p>
                <p className="text-sm mt-2">Phase 3 will integrate actual PDF viewing</p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}