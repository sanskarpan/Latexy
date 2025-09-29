import { FileText, Zap, Key } from 'lucide-react'
import Link from 'next/link'

export default function Header() {
  return (
    <header className="border-b border-secondary-200 bg-white/80 backdrop-blur-sm sticky top-0 z-50">
      <div className="container mx-auto px-4">
        <div className="flex items-center justify-between h-16">
          <div className="flex items-center gap-3">
            <Link href="/" className="flex items-center gap-3">
              <div className="w-10 h-10 bg-gradient-to-br from-primary-500 to-primary-600 rounded-xl flex items-center justify-center">
                <FileText className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-secondary-900">
                  Latexy
                </h1>
                <p className="text-xs text-secondary-500">
                  AI-powered LaTeX resume optimizer
                </p>
              </div>
            </Link>
          </div>
          
          <div className="flex items-center gap-4">
            <div className="hidden sm:flex items-center gap-2 text-sm text-secondary-600">
              <Zap className="w-4 h-4 text-green-500" />
              <span>Phase 10: Multi-Provider & BYOK Complete</span>
            </div>
            
            <Link 
              href="/byok" 
              className="flex items-center gap-2 btn-outline px-3 py-2 text-sm hover:bg-blue-50 transition-colors"
            >
              <Key className="w-4 h-4" />
              <span className="hidden sm:inline">BYOK</span>
            </Link>
            
            <button className="btn-outline px-3 py-2 text-sm">
              Help
            </button>
          </div>
        </div>
      </div>
    </header>
  )
}