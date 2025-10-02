'use client'

import React, { useState, useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { 
  Search, 
  FileText, 
  Zap, 
  CreditCard, 
  Shield, 
  Settings,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  MessageCircle,
  Mail,
  Book,
  Video,
  Download
} from 'lucide-react'

interface FAQItem {
  id: string
  question: string
  answer: string
  category: string
  tags: string[]
}

interface HelpCategory {
  id: string
  name: string
  icon: React.ReactNode
  description: string
  color: string
}

interface HelpCenterProps {
  isOpen: boolean
  onClose: () => void
}

const helpCategories: HelpCategory[] = [
  {
    id: 'getting-started',
    name: 'Getting Started',
    icon: <FileText className="w-5 h-5" />,
    description: 'Learn the basics of using Latexy',
    color: 'blue'
  },
  {
    id: 'optimization',
    name: 'AI Optimization',
    icon: <Zap className="w-5 h-5" />,
    description: 'How AI optimization works',
    color: 'green'
  },
  {
    id: 'billing',
    name: 'Billing & Plans',
    icon: <CreditCard className="w-5 h-5" />,
    description: 'Subscription and payment questions',
    color: 'purple'
  },
  {
    id: 'security',
    name: 'Security & Privacy',
    icon: <Shield className="w-5 h-5" />,
    description: 'Data protection and security',
    color: 'red'
  },
  {
    id: 'technical',
    name: 'Technical Support',
    icon: <Settings className="w-5 h-5" />,
    description: 'Troubleshooting and technical issues',
    color: 'orange'
  }
]

const faqData: FAQItem[] = [
  // Getting Started
  {
    id: 'what-is-latexy',
    question: 'What is Latexy and how does it work?',
    answer: 'Latexy is an AI-powered resume optimization platform that helps you create ATS-friendly resumes using LaTeX. It combines professional typesetting with artificial intelligence to optimize your resume content for specific job descriptions, ensuring better compatibility with Applicant Tracking Systems (ATS).',
    category: 'getting-started',
    tags: ['basics', 'overview', 'ats']
  },
  {
    id: 'free-trial',
    question: 'How does the free trial work?',
    answer: 'You get 3 free resume compilations without needing to register. We use device fingerprinting to track usage, and the trial resets every 24 hours to prevent abuse. After your trial, you can register for unlimited access with our subscription plans.',
    category: 'getting-started',
    tags: ['trial', 'free', 'registration']
  },
  {
    id: 'latex-knowledge',
    question: 'Do I need to know LaTeX to use Latexy?',
    answer: 'No! While LaTeX knowledge is helpful, Latexy provides templates, syntax highlighting, and AI assistance to help you create professional resumes. Our editor includes helpful hints and error detection to guide you through the process.',
    category: 'getting-started',
    tags: ['latex', 'beginner', 'templates']
  },
  
  // AI Optimization
  {
    id: 'how-ai-works',
    question: 'How does AI optimization work?',
    answer: 'Our AI analyzes your resume content and the job description you provide, then suggests improvements for better ATS compatibility. It optimizes keywords, formatting, and content structure while maintaining your professional voice and achievements.',
    category: 'optimization',
    tags: ['ai', 'optimization', 'ats', 'keywords']
  },
  {
    id: 'ats-scoring',
    question: 'What is ATS scoring and how is it calculated?',
    answer: 'ATS scoring (0-100) measures how well your resume will perform with Applicant Tracking Systems. We analyze formatting, keyword density, section organization, and readability. Higher scores indicate better ATS compatibility and higher chances of passing initial screening.',
    category: 'optimization',
    tags: ['ats', 'scoring', 'compatibility']
  },
  {
    id: 'byok-benefits',
    question: 'What are the benefits of BYOK (Bring Your Own Key)?',
    answer: 'BYOK allows you to use your own API keys from providers like OpenAI, Anthropic, or Google. This gives you access to the latest models, potentially lower costs for heavy usage, and full control over your AI optimization expenses.',
    category: 'optimization',
    tags: ['byok', 'api-keys', 'cost-savings']
  },
  
  // Billing & Plans
  {
    id: 'subscription-plans',
    question: 'What subscription plans are available?',
    answer: 'We offer: Free Trial (3 compilations), Basic (₹299/month - 50 compilations, 10 optimizations), Pro (₹599/month - unlimited), and BYOK (₹199/month - unlimited with your API keys). All paid plans include resume history and priority support.',
    category: 'billing',
    tags: ['plans', 'pricing', 'subscription']
  },
  {
    id: 'payment-methods',
    question: 'What payment methods do you accept?',
    answer: 'We accept all major credit/debit cards, UPI, net banking, and digital wallets through our secure payment partner Razorpay. All transactions are encrypted and PCI DSS compliant for your security.',
    category: 'billing',
    tags: ['payment', 'razorpay', 'security']
  },
  {
    id: 'cancel-subscription',
    question: 'How do I cancel my subscription?',
    answer: 'You can cancel anytime from your account settings. Your subscription remains active until the end of the current billing period, and you\'ll retain access to all features until then. No refunds are provided for unused time.',
    category: 'billing',
    tags: ['cancellation', 'refund', 'billing']
  },
  
  // Security & Privacy
  {
    id: 'data-security',
    question: 'How secure is my data?',
    answer: 'We use enterprise-grade security including AES-256 encryption, TLS 1.3 for data in transit, secure data centers, and regular security audits. Your resume content is processed for optimization but not stored permanently unless you save it.',
    category: 'security',
    tags: ['security', 'encryption', 'privacy']
  },
  {
    id: 'api-key-security',
    question: 'How are my API keys protected?',
    answer: 'API keys are encrypted using AES-256 encryption with separate encryption keys for each user. We never store keys in plain text, and they\'re only used to make requests on your behalf. You can delete them anytime.',
    category: 'security',
    tags: ['api-keys', 'encryption', 'byok']
  },
  {
    id: 'gdpr-compliance',
    question: 'Are you GDPR compliant?',
    answer: 'Yes, we\'re fully GDPR compliant. You have the right to access, correct, delete, or export your data. We process data only for service provision and with your consent. Contact privacy@latexy.com for data requests.',
    category: 'security',
    tags: ['gdpr', 'privacy', 'data-rights']
  },
  
  // Technical Support
  {
    id: 'compilation-errors',
    question: 'Why is my LaTeX compilation failing?',
    answer: 'Common issues include syntax errors, missing packages, or unsupported commands. Check the error logs in the compilation results, ensure proper LaTeX syntax, and try our templates as starting points. Contact support if issues persist.',
    category: 'technical',
    tags: ['latex', 'errors', 'compilation']
  },
  {
    id: 'slow-performance',
    question: 'Why is the service running slowly?',
    answer: 'Performance can be affected by high server load, complex LaTeX documents, or network issues. Try refreshing the page, using simpler templates, or contact support if problems persist. We monitor performance 24/7.',
    category: 'technical',
    tags: ['performance', 'speed', 'troubleshooting']
  },
  {
    id: 'browser-compatibility',
    question: 'Which browsers are supported?',
    answer: 'Latexy works best on modern browsers: Chrome 90+, Firefox 88+, Safari 14+, and Edge 90+. For the best experience, keep your browser updated and enable JavaScript. Mobile browsers are also supported.',
    category: 'technical',
    tags: ['browser', 'compatibility', 'requirements']
  }
]

export default function HelpCenter({ isOpen, onClose }: HelpCenterProps) {
  const [searchQuery, setSearchQuery] = useState('')
  const [selectedCategory, setSelectedCategory] = useState<string | null>(null)
  const [expandedFAQ, setExpandedFAQ] = useState<string | null>(null)

  const filteredFAQs = useMemo(() => {
    let filtered = faqData

    if (selectedCategory) {
      filtered = filtered.filter(faq => faq.category === selectedCategory)
    }

    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      filtered = filtered.filter(faq =>
        faq.question.toLowerCase().includes(query) ||
        faq.answer.toLowerCase().includes(query) ||
        faq.tags.some(tag => tag.toLowerCase().includes(query))
      )
    }

    return filtered
  }, [searchQuery, selectedCategory])

  const toggleFAQ = (faqId: string) => {
    setExpandedFAQ(expandedFAQ === faqId ? null : faqId)
  }

  const getCategoryColor = (color: string) => {
    const colors = {
      blue: 'bg-blue-50 text-blue-700 border-blue-200',
      green: 'bg-green-50 text-green-700 border-green-200',
      purple: 'bg-purple-50 text-purple-700 border-purple-200',
      red: 'bg-red-50 text-red-700 border-red-200',
      orange: 'bg-orange-50 text-orange-700 border-orange-200'
    }
    return colors[color as keyof typeof colors] || colors.blue
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <motion.div
        initial={{ opacity: 0, scale: 0.9 }}
        animate={{ opacity: 1, scale: 1 }}
        exit={{ opacity: 0, scale: 0.9 }}
        className="bg-white rounded-2xl shadow-2xl max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col"
      >
        {/* Header */}
        <div className="p-6 border-b border-secondary-200 bg-gradient-to-r from-primary-50 to-blue-50">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-2xl font-bold text-secondary-900 mb-2">
                Help Center
              </h2>
              <p className="text-secondary-600">
                Find answers to common questions and get help with Latexy
              </p>
            </div>
            <button
              onClick={onClose}
              className="text-secondary-400 hover:text-secondary-600 text-xl font-semibold"
            >
              ×
            </button>
          </div>

          {/* Search */}
          <div className="mt-4 relative">
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-secondary-400 w-5 h-5" />
            <input
              type="text"
              placeholder="Search for help..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-10 pr-4 py-3 border border-secondary-200 rounded-lg focus:ring-2 focus:ring-primary-500 focus:border-transparent"
            />
          </div>
        </div>

        <div className="flex flex-1 overflow-hidden">
          {/* Sidebar */}
          <div className="w-80 border-r border-secondary-200 bg-secondary-50 overflow-y-auto">
            <div className="p-4">
              <h3 className="font-semibold text-secondary-900 mb-3">Categories</h3>
              <div className="space-y-2">
                <button
                  onClick={() => setSelectedCategory(null)}
                  className={`w-full text-left p-3 rounded-lg transition-colors ${
                    selectedCategory === null
                      ? 'bg-primary-100 text-primary-700 border border-primary-200'
                      : 'hover:bg-secondary-100'
                  }`}
                >
                  <div className="flex items-center gap-3">
                    <Book className="w-5 h-5" />
                    <span className="font-medium">All Topics</span>
                  </div>
                </button>
                
                {helpCategories.map((category) => (
                  <button
                    key={category.id}
                    onClick={() => setSelectedCategory(category.id)}
                    className={`w-full text-left p-3 rounded-lg transition-colors border ${
                      selectedCategory === category.id
                        ? getCategoryColor(category.color)
                        : 'hover:bg-secondary-100 border-transparent'
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      {category.icon}
                      <div>
                        <div className="font-medium">{category.name}</div>
                        <div className="text-xs opacity-75">{category.description}</div>
                      </div>
                    </div>
                  </button>
                ))}
              </div>

              {/* Contact Support */}
              <div className="mt-6 p-4 bg-white rounded-lg border border-secondary-200">
                <h4 className="font-semibold text-secondary-900 mb-2">Need More Help?</h4>
                <div className="space-y-2">
                  <a
                    href="mailto:support@latexy.com"
                    className="flex items-center gap-2 text-sm text-secondary-600 hover:text-primary-600"
                  >
                    <Mail className="w-4 h-4" />
                    Email Support
                  </a>
                  <a
                    href="/contact"
                    className="flex items-center gap-2 text-sm text-secondary-600 hover:text-primary-600"
                  >
                    <MessageCircle className="w-4 h-4" />
                    Live Chat
                  </a>
                  <a
                    href="/documentation"
                    className="flex items-center gap-2 text-sm text-secondary-600 hover:text-primary-600"
                  >
                    <ExternalLink className="w-4 h-4" />
                    Documentation
                  </a>
                </div>
              </div>
            </div>
          </div>

          {/* Main Content */}
          <div className="flex-1 overflow-y-auto">
            <div className="p-6">
              {searchQuery && (
                <div className="mb-4 text-sm text-secondary-600">
                  Found {filteredFAQs.length} result{filteredFAQs.length !== 1 ? 's' : ''} for "{searchQuery}"
                </div>
              )}

              {filteredFAQs.length === 0 ? (
                <div className="text-center py-12">
                  <Search className="w-12 h-12 text-secondary-300 mx-auto mb-4" />
                  <h3 className="text-lg font-semibold text-secondary-900 mb-2">
                    No results found
                  </h3>
                  <p className="text-secondary-600 mb-4">
                    Try adjusting your search terms or browse categories
                  </p>
                  <button
                    onClick={() => {
                      setSearchQuery('')
                      setSelectedCategory(null)
                    }}
                    className="btn-outline"
                  >
                    Clear Search
                  </button>
                </div>
              ) : (
                <div className="space-y-4">
                  {filteredFAQs.map((faq) => (
                    <motion.div
                      key={faq.id}
                      initial={{ opacity: 0, y: 20 }}
                      animate={{ opacity: 1, y: 0 }}
                      className="border border-secondary-200 rounded-lg overflow-hidden"
                    >
                      <button
                        onClick={() => toggleFAQ(faq.id)}
                        className="w-full p-4 text-left hover:bg-secondary-50 transition-colors"
                      >
                        <div className="flex items-center justify-between">
                          <h3 className="font-semibold text-secondary-900 pr-4">
                            {faq.question}
                          </h3>
                          {expandedFAQ === faq.id ? (
                            <ChevronDown className="w-5 h-5 text-secondary-400 flex-shrink-0" />
                          ) : (
                            <ChevronRight className="w-5 h-5 text-secondary-400 flex-shrink-0" />
                          )}
                        </div>
                      </button>
                      
                      <AnimatePresence>
                        {expandedFAQ === faq.id && (
                          <motion.div
                            initial={{ height: 0 }}
                            animate={{ height: 'auto' }}
                            exit={{ height: 0 }}
                            className="overflow-hidden"
                          >
                            <div className="p-4 pt-0 border-t border-secondary-100">
                              <p className="text-secondary-700 leading-relaxed">
                                {faq.answer}
                              </p>
                              <div className="mt-3 flex flex-wrap gap-2">
                                {faq.tags.map((tag) => (
                                  <span
                                    key={tag}
                                    className="px-2 py-1 bg-secondary-100 text-secondary-600 text-xs rounded-full"
                                  >
                                    {tag}
                                  </span>
                                ))}
                              </div>
                            </div>
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </motion.div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-secondary-200 bg-secondary-50">
          <div className="flex items-center justify-between text-sm text-secondary-600">
            <div>
              Still need help? <a href="mailto:support@latexy.com" className="text-primary-600 hover:underline">Contact Support</a>
            </div>
            <div className="flex items-center gap-4">
              <a href="/documentation" className="hover:text-primary-600">Documentation</a>
              <a href="/tutorials" className="hover:text-primary-600">Tutorials</a>
              <a href="/status" className="hover:text-primary-600">System Status</a>
            </div>
          </div>
        </div>
      </motion.div>
    </div>
  )
}

// Hook for managing help center
export function useHelpCenter() {
  const [isHelpOpen, setIsHelpOpen] = useState(false)

  const openHelp = () => setIsHelpOpen(true)
  const closeHelp = () => setIsHelpOpen(false)

  return {
    isHelpOpen,
    openHelp,
    closeHelp
  }
}

