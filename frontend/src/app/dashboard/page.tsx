'use client'

import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { 
  FileText, 
  Plus, 
  Download, 
  Edit, 
  Copy, 
  Trash2, 
  TrendingUp, 
  Clock, 
  Target,
  Zap,
  BarChart3,
  Calendar,
  User,
  Settings,
  Crown,
  Sparkles
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input } from '@/components/ui/input'

const fadeInUp = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
  transition: { duration: 0.5 }
}

const staggerContainer = {
  animate: {
    transition: {
      staggerChildren: 0.1
    }
  }
}

// Mock data - in production this would come from API
const userStats = {
  resumesCreated: 12,
  monthlyUsage: 8,
  monthlyLimit: 50,
  successRate: 85,
  planUsage: 40
}

const recentResumes = [
  {
    id: '1',
    title: 'Software Engineer Resume',
    lastModified: '2 hours ago',
    status: 'optimized',
    atsScore: 9.2,
    downloads: 5
  },
  {
    id: '2',
    title: 'Data Scientist Resume',
    lastModified: '1 day ago',
    status: 'draft',
    atsScore: 7.8,
    downloads: 2
  },
  {
    id: '3',
    title: 'Product Manager Resume',
    lastModified: '3 days ago',
    status: 'optimized',
    atsScore: 8.9,
    downloads: 8
  }
]

const quickActions = [
  {
    title: 'New Resume',
    description: 'Start from scratch',
    icon: Plus,
    color: 'bg-blue-500',
    href: '/editor'
  },
  {
    title: 'Browse Templates',
    description: 'Professional templates',
    icon: FileText,
    color: 'bg-green-500',
    href: '/templates'
  },
  {
    title: 'Upload .tex',
    description: 'Import existing file',
    icon: Download,
    color: 'bg-purple-500',
    href: '/upload'
  },
  {
    title: 'Upgrade Plan',
    description: 'Unlock more features',
    icon: Crown,
    color: 'bg-yellow-500',
    href: '/billing'
  }
]

const activityFeed = [
  {
    id: '1',
    action: 'Resume optimized',
    target: 'Software Engineer Resume',
    time: '2 hours ago',
    type: 'optimization'
  },
  {
    id: '2',
    action: 'PDF downloaded',
    target: 'Product Manager Resume',
    time: '1 day ago',
    type: 'download'
  },
  {
    id: '3',
    action: 'Resume created',
    target: 'Data Scientist Resume',
    time: '3 days ago',
    type: 'creation'
  }
]

export default function DashboardPage() {
  const [searchQuery, setSearchQuery] = useState('')
  const [filteredResumes, setFilteredResumes] = useState(recentResumes)

  useEffect(() => {
    const filtered = recentResumes.filter(resume =>
      resume.title.toLowerCase().includes(searchQuery.toLowerCase())
    )
    setFilteredResumes(filtered)
  }, [searchQuery])

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-blue-50 dark:from-slate-900 dark:to-slate-800">
      {/* Header */}
      <div className="bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm border-b border-gray-200 dark:border-gray-700 sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex justify-between items-center h-16">
            <div className="flex items-center space-x-4">
              <div className="w-8 h-8 bg-gradient-to-r from-blue-500 to-purple-600 rounded-lg flex items-center justify-center">
                <Sparkles className="w-5 h-5 text-white" />
              </div>
              <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Dashboard</h1>
            </div>
            <div className="flex items-center space-x-4">
              <Button variant="outline" size="sm">
                <Settings className="w-4 h-4 mr-2" />
                Settings
              </Button>
              <div className="w-8 h-8 bg-gradient-to-r from-green-400 to-blue-500 rounded-full flex items-center justify-center">
                <User className="w-4 h-4 text-white" />
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Welcome Section */}
        <motion.div 
          className="mb-8"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
        >
          <div className="flex flex-col md:flex-row justify-between items-start md:items-center mb-6">
            <div>
              <h2 className="text-3xl font-bold text-gray-900 dark:text-white mb-2">
                Welcome back! 👋
              </h2>
              <p className="text-gray-600 dark:text-gray-300">
                Here's what's happening with your resumes today.
              </p>
            </div>
            <Badge variant="outline" className="mt-4 md:mt-0 border-blue-500/50 text-blue-600 dark:text-blue-400">
              <Crown className="w-3 h-3 mr-1" />
              Free Plan
            </Badge>
          </div>
        </motion.div>

        {/* Stats Overview */}
        <motion.div 
          className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8"
          variants={staggerContainer}
          initial="initial"
          animate="animate"
        >
          <motion.div variants={fadeInUp}>
            <Card className="card-hover">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Resumes Created</CardTitle>
                <FileText className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{userStats.resumesCreated}</div>
                <p className="text-xs text-muted-foreground">
                  +2 from last month
                </p>
              </CardContent>
            </Card>
          </motion.div>

          <motion.div variants={fadeInUp}>
            <Card className="card-hover">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">This Month</CardTitle>
                <BarChart3 className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{userStats.monthlyUsage}/{userStats.monthlyLimit}</div>
                <p className="text-xs text-muted-foreground">
                  Compilations used
                </p>
              </CardContent>
            </Card>
          </motion.div>

          <motion.div variants={fadeInUp}>
            <Card className="card-hover">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Success Rate</CardTitle>
                <TrendingUp className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{userStats.successRate}%</div>
                <p className="text-xs text-muted-foreground">
                  Interview callbacks
                </p>
              </CardContent>
            </Card>
          </motion.div>

          <motion.div variants={fadeInUp}>
            <Card className="card-hover">
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Plan Usage</CardTitle>
                <Target className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{userStats.planUsage}/50</div>
                <p className="text-xs text-muted-foreground">
                  Monthly limit
                </p>
              </CardContent>
            </Card>
          </motion.div>
        </motion.div>

        <div className="grid lg:grid-cols-3 gap-8">
          {/* Main Content */}
          <div className="lg:col-span-2 space-y-8">
            {/* Quick Actions */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.2 }}
            >
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Zap className="w-5 h-5 text-yellow-500" />
                    Quick Actions
                  </CardTitle>
                  <CardDescription>
                    Get started with these common tasks
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    {quickActions.map((action, index) => (
                      <motion.div
                        key={action.title}
                        className="group cursor-pointer"
                        whileHover={{ scale: 1.02 }}
                        whileTap={{ scale: 0.98 }}
                      >
                        <div className="flex flex-col items-center p-4 rounded-lg border border-gray-200 dark:border-gray-700 hover:border-blue-300 dark:hover:border-blue-600 transition-colors">
                          <div className={`w-12 h-12 ${action.color} rounded-lg flex items-center justify-center mb-3 group-hover:scale-110 transition-transform`}>
                            <action.icon className="w-6 h-6 text-white" />
                          </div>
                          <h3 className="font-medium text-sm text-center text-gray-900 dark:text-white mb-1">
                            {action.title}
                          </h3>
                          <p className="text-xs text-gray-500 dark:text-gray-400 text-center">
                            {action.description}
                          </p>
                        </div>
                      </motion.div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </motion.div>

            {/* Recent Resumes */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 0.3 }}
            >
              <Card>
                <CardHeader>
                  <div className="flex justify-between items-center">
                    <div>
                      <CardTitle className="flex items-center gap-2">
                        <FileText className="w-5 h-5 text-blue-500" />
                        Recent Resumes
                      </CardTitle>
                      <CardDescription>
                        Your latest resume projects
                      </CardDescription>
                    </div>
                    <Button size="sm">
                      <Plus className="w-4 h-4 mr-2" />
                      New Resume
                    </Button>
                  </div>
                  <div className="mt-4">
                    <Input
                      placeholder="Search resumes..."
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      className="max-w-sm"
                    />
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="space-y-4">
                    {filteredResumes.map((resume, index) => (
                      <motion.div
                        key={resume.id}
                        className="flex items-center justify-between p-4 rounded-lg border border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors"
                        initial={{ opacity: 0, x: -20 }}
                        animate={{ opacity: 1, x: 0 }}
                        transition={{ duration: 0.3, delay: index * 0.1 }}
                      >
                        <div className="flex items-center space-x-4">
                          <div className="w-10 h-10 bg-gradient-to-r from-blue-500 to-purple-600 rounded-lg flex items-center justify-center">
                            <FileText className="w-5 h-5 text-white" />
                          </div>
                          <div>
                            <h3 className="font-medium text-gray-900 dark:text-white">
                              {resume.title}
                            </h3>
                            <div className="flex items-center space-x-4 text-sm text-gray-500 dark:text-gray-400">
                              <span className="flex items-center">
                                <Clock className="w-3 h-3 mr-1" />
                                {resume.lastModified}
                              </span>
                              <Badge 
                                variant={resume.status === 'optimized' ? 'success' : 'secondary'}
                                className="text-xs"
                              >
                                {resume.status}
                              </Badge>
                              <span className="flex items-center">
                                <Target className="w-3 h-3 mr-1" />
                                ATS: {resume.atsScore}/10
                              </span>
                            </div>
                          </div>
                        </div>
                        <div className="flex items-center space-x-2">
                          <Button variant="ghost" size="sm">
                            <Edit className="w-4 h-4" />
                          </Button>
                          <Button variant="ghost" size="sm">
                            <Download className="w-4 h-4" />
                          </Button>
                          <Button variant="ghost" size="sm">
                            <Copy className="w-4 h-4" />
                          </Button>
                          <Button variant="ghost" size="sm">
                            <Trash2 className="w-4 h-4" />
                          </Button>
                        </div>
                      </motion.div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </motion.div>
          </div>

          {/* Sidebar */}
          <div className="space-y-6">
            {/* Activity Feed */}
            <motion.div
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.6, delay: 0.4 }}
            >
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Calendar className="w-5 h-5 text-green-500" />
                    Recent Activity
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-4">
                    {activityFeed.map((activity, index) => (
                      <motion.div
                        key={activity.id}
                        className="flex items-start space-x-3"
                        initial={{ opacity: 0, y: 10 }}
                        animate={{ opacity: 1, y: 0 }}
                        transition={{ duration: 0.3, delay: index * 0.1 }}
                      >
                        <div className={`w-2 h-2 rounded-full mt-2 ${
                          activity.type === 'optimization' ? 'bg-blue-500' :
                          activity.type === 'download' ? 'bg-green-500' :
                          'bg-purple-500'
                        }`} />
                        <div className="flex-1 min-w-0">
                          <p className="text-sm text-gray-900 dark:text-white">
                            {activity.action}
                          </p>
                          <p className="text-sm text-gray-500 dark:text-gray-400 truncate">
                            {activity.target}
                          </p>
                          <p className="text-xs text-gray-400 dark:text-gray-500">
                            {activity.time}
                          </p>
                        </div>
                      </motion.div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            </motion.div>

            {/* Upgrade Prompt */}
            <motion.div
              initial={{ opacity: 0, x: 20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.6, delay: 0.5 }}
            >
              <Card className="bg-gradient-to-r from-blue-500/10 to-purple-600/10 border-blue-500/20">
                <CardContent className="p-6">
                  <div className="flex items-center gap-3 mb-4">
                    <div className="w-10 h-10 bg-gradient-to-r from-blue-500 to-purple-600 rounded-lg flex items-center justify-center">
                      <Crown className="w-5 h-5 text-white" />
                    </div>
                    <div>
                      <h3 className="font-semibold text-gray-900 dark:text-white">
                        Upgrade to Pro
                      </h3>
                      <p className="text-sm text-gray-600 dark:text-gray-300">
                        Unlock unlimited features
                      </p>
                    </div>
                  </div>
                  <ul className="space-y-2 mb-4 text-sm text-gray-600 dark:text-gray-300">
                    <li className="flex items-center gap-2">
                      <div className="w-1.5 h-1.5 bg-green-500 rounded-full" />
                      Unlimited compilations
                    </li>
                    <li className="flex items-center gap-2">
                      <div className="w-1.5 h-1.5 bg-green-500 rounded-full" />
                      AI optimization
                    </li>
                    <li className="flex items-center gap-2">
                      <div className="w-1.5 h-1.5 bg-green-500 rounded-full" />
                      Priority support
                    </li>
                  </ul>
                  <Button className="w-full bg-gradient-to-r from-blue-500 to-purple-600 hover:from-blue-600 hover:to-purple-700">
                    Upgrade Now
                  </Button>
                </CardContent>
              </Card>
            </motion.div>
          </div>
        </div>
      </div>
    </div>
  )
}
