'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { motion } from 'framer-motion'
import { 
  Plus, 
  FileText, 
  History, 
  Settings, 
  ChevronRight, 
  Search,
  LayoutGrid,
  List as ListIcon,
  MoreVertical,
  Clock,
  CheckCircle2,
  AlertCircle
} from 'lucide-react'
import { apiClient, ResumeResponse, JobStateResponse } from '@/lib/api-client'
import { useSession } from '@/lib/auth-client'
import { Toaster, toast } from 'sonner'
import LoadingSpinner from '@/components/LoadingSpinner'

export default function WorkspacePage() {
  const { data: session, isPending: sessionLoading } = useSession()
  const [resumes, setResumes] = useState<ResumeResponse[]>([])
  const [jobs, setJobs] = useState<JobStateResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [searchQuery, setSearchQuery] = useState('')
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('grid')

  useEffect(() => {
    if (session) {
      fetchData()
    }
  }, [session])

  async function fetchData() {
    setLoading(true)
    try {
      const [resumesData, jobsData] = await Promise.all([
        apiClient.listResumes(),
        apiClient.listJobs()
      ])
      setResumes(resumesData)
      setJobs(jobsData.jobs || [])
    } catch (err) {
      console.error('Failed to fetch workspace data:', err)
      toast.error('Failed to load workspace data')
    } finally {
      setLoading(false)
    }
  }

  const filteredResumes = resumes.filter(r => 
    r.title.toLowerCase().includes(searchQuery.toLowerCase())
  )

  if (sessionLoading) return (
    <div className="flex h-screen items-center justify-center">
      <LoadingSpinner />
    </div>
  )

  if (!session) {
    return (
      <div className="flex h-[80vh] flex-col items-center justify-center space-y-4 text-center">
        <h1 className="text-2xl font-bold text-white">Access Denied</h1>
        <p className="text-zinc-400">Please sign in to access your workspace.</p>
        <Link href="/login" className="btn-primary">Sign In</Link>
      </div>
    )
  }

  return (
    <div className="content-shell">
      <Toaster richColors position="top-right" />
      <div className="space-y-6">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold text-white tracking-tight">Workspace</h1>
            <p className="text-sm text-zinc-500 mt-1">Manage your professional documents and optimizations</p>
          </div>
          <Link 
            href="/workspace/new" 
            className="flex items-center gap-2 rounded-lg bg-orange-300 px-5 py-2.5 text-sm font-bold text-slate-950 transition hover:bg-orange-200"
          >
            <Plus size={18} strokeWidth={2.5} />
            <span>New Resume</span>
          </Link>
        </div>

        <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
          {/* Main Content: Resumes */}
          <section className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="relative flex-1 min-w-[240px]">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-zinc-500" size={18} />
                <input 
                  type="text"
                  placeholder="Search resumes..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full rounded-lg border border-white/10 bg-white/5 py-2 pl-10 pr-4 text-sm text-white outline-none focus:border-orange-300/50"
                />
              </div>
              <div className="flex items-center rounded-lg border border-white/10 bg-white/5 p-1">
                <button 
                  onClick={() => setViewMode('grid')}
                  className={`rounded-md p-1.5 transition ${viewMode === 'grid' ? 'bg-white/10 text-orange-200' : 'text-zinc-500 hover:text-zinc-300'}`}
                >
                  <LayoutGrid size={18} />
                </button>
                <button 
                  onClick={() => setViewMode('list')}
                  className={`rounded-md p-1.5 transition ${viewMode === 'list' ? 'bg-white/10 text-orange-200' : 'text-zinc-500 hover:text-zinc-300'}`}
                >
                  <ListIcon size={18} />
                </button>
              </div>
            </div>

            {loading ? (
              <div className="flex h-64 items-center justify-center rounded-xl border border-dashed border-white/10">
                <LoadingSpinner />
              </div>
            ) : filteredResumes.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-20 text-center rounded-xl border border-dashed border-white/10">
                <div className="mb-4 rounded-full bg-white/5 p-4 text-zinc-500">
                  <FileText size={32} />
                </div>
                <h3 className="text-lg font-medium text-white">No resumes found</h3>
                <p className="mt-1 text-sm text-zinc-400">
                  {searchQuery ? `No results for "${searchQuery}"` : "You haven't created any resumes yet."}
                </p>
                {!searchQuery && (
                  <Link href="/workspace/new" className="mt-4 text-sm font-semibold text-orange-200 hover:text-orange-100">
                    Create your first resume
                  </Link>
                )}
              </div>
            ) : viewMode === 'grid' ? (
              <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
                {filteredResumes.map((resume) => (
                  <ResumeCard key={resume.id} resume={resume} />
                ))}
              </div>
            ) : (
              <div className="rounded-xl border border-white/10 bg-white/5 overflow-hidden">
                <table className="w-full text-left text-sm">
                  <thead>
                    <tr className="border-b border-white/10 bg-white/5 text-zinc-400">
                      <th className="px-4 py-3 font-medium">Title</th>
                      <th className="px-4 py-3 font-medium text-right">Updated</th>
                      <th className="px-4 py-3 font-medium text-right">Actions</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {filteredResumes.map((resume) => (
                      <tr key={resume.id} className="group hover:bg-white/[0.02]">
                        <td className="px-4 py-3">
                          <Link href={`/workspace/${resume.id}/edit`} className="font-medium text-white hover:text-orange-200 transition">
                            {resume.title}
                          </Link>
                        </td>
                        <td className="px-4 py-3 text-right text-zinc-400">
                          {new Date(resume.updated_at).toLocaleDateString()}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <div className="flex justify-end gap-2">
                            <Link href={`/workspace/${resume.id}/edit`} className="rounded-md p-1.5 text-zinc-400 hover:bg-white/10 hover:text-white">
                              <Settings size={16} />
                            </Link>
                            <Link href={`/workspace/${resume.id}/optimize`} className="rounded-md p-1.5 text-zinc-400 hover:bg-white/10 hover:text-white">
                              <ChevronRight size={16} />
                            </Link>
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* Sidebar: Recent Activity */}
          <aside className="space-y-6">
            <div className="surface-panel edge-highlight p-5">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-lg font-semibold text-white">Recent Activity</h2>
                <History size={18} className="text-zinc-500" />
              </div>
              
              <div className="space-y-4">
                {jobs.length === 0 ? (
                  <p className="py-4 text-center text-sm text-zinc-500">No recent activity</p>
                ) : (
                  jobs.slice(0, 5).map((job, idx) => (
                    <div key={idx} className="group relative flex gap-3 border-l-2 border-white/10 pb-4 pl-4 last:pb-0">
                      <div className="absolute -left-[9px] top-0 flex h-4 w-4 items-center justify-center rounded-full bg-slate-900 ring-2 ring-slate-900">
                        {job.status === 'completed' ? (
                          <CheckCircle2 size={12} className="text-emerald-400" />
                        ) : job.status === 'failed' ? (
                          <AlertCircle size={12} className="text-rose-400" />
                        ) : (
                          <Clock size={12} className="text-orange-300 animate-pulse" />
                        )}
                      </div>
                      <div className="space-y-1">
                        <p className="text-sm font-medium text-white line-clamp-1 group-hover:text-orange-200 transition">
                          {job.stage || 'Optimization Run'}
                        </p>
                        <p className="text-xs text-zinc-500">
                          {new Date(job.last_updated * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                        </p>
                      </div>
                    </div>
                  ))
                )}
              </div>
              
              {jobs.length > 0 && (
                <Link href="/workspace/history" className="mt-4 block text-center text-xs font-semibold text-orange-200 hover:text-orange-100">
                  View Full History
                </Link>
              )}
            </div>

            <div className="surface-panel edge-highlight p-5">
              <h3 className="text-sm font-semibold text-white">Pro Tip</h3>
              <p className="mt-2 text-xs leading-relaxed text-zinc-400">
                Optimizing for specific keywords can increase your ATS score by up to 40%. Try the "Targeted Optimization" flow.
              </p>
            </div>
          </aside>
        </div>
      </div>
    </div>
  )
}

function ResumeCard({ resume }: { resume: ResumeResponse }) {
  return (
    <motion.div 
      whileHover={{ y: -4 }}
      className="surface-card group edge-highlight flex flex-col p-5"
    >
      <div className="mb-4 flex items-start justify-between">
        <div className="rounded-lg bg-orange-300/10 p-3 text-orange-200 ring-1 ring-orange-300/20">
          <FileText size={24} />
        </div>
        <button className="rounded-md p-1 text-zinc-500 hover:bg-white/5 hover:text-zinc-300">
          <MoreVertical size={18} />
        </button>
      </div>
      
      <div className="flex-1">
        <h3 className="text-lg font-semibold text-white group-hover:text-orange-200 transition line-clamp-1">
          {resume.title}
        </h3>
        <p className="mt-1 text-xs text-zinc-500">
          Modified {new Date(resume.updated_at).toLocaleDateString()}
        </p>
      </div>

      <div className="mt-6 flex items-center justify-between gap-3">
        <Link 
          href={`/workspace/${resume.id}/edit`}
          className="flex-1 rounded-lg border border-white/10 bg-white/5 py-2 text-center text-xs font-semibold text-white transition hover:bg-white/10"
        >
          Edit
        </Link>
        <Link 
          href={`/workspace/${resume.id}/optimize`}
          className="flex-1 rounded-lg bg-orange-300/10 py-2 text-center text-xs font-semibold text-orange-200 transition hover:bg-orange-300/20"
        >
          Optimize
        </Link>
      </div>
    </motion.div>
  )
}
