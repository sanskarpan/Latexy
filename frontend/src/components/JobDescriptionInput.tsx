'use client'

import { Briefcase } from 'lucide-react'

interface JobDescriptionInputProps {
  value: string
  onChange: (value: string) => void
}

const SAMPLE_JOB_DESCRIPTION = `Senior Software Engineer

We are seeking a Senior Software Engineer to join our growing engineering team. The ideal candidate will have experience with modern web technologies and a passion for building scalable applications.

Key Responsibilities:
• Design and develop scalable web applications using React, Node.js, and Python
• Collaborate with cross-functional teams including product managers and designers
• Implement best practices for code quality, testing, and deployment
• Mentor junior developers and contribute to technical decision-making
• Work with cloud platforms (AWS, GCP) and containerization technologies (Docker, Kubernetes)

Required Qualifications:
• Bachelor's degree in Computer Science or related field
• 5+ years of experience in full-stack software development
• Proficiency in JavaScript, Python, and modern frameworks (React, Node.js)
• Experience with databases (PostgreSQL, MongoDB) and API development
• Knowledge of cloud platforms and DevOps practices
• Strong problem-solving skills and attention to detail
• Excellent communication and teamwork abilities

Preferred Qualifications:
• Experience with microservices architecture
• Knowledge of machine learning and data science tools
• Contributions to open-source projects
• Experience with Agile development methodologies`

export default function JobDescriptionInput({ value, onChange }: JobDescriptionInputProps) {
  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    onChange(e.target.value)
  }

  const insertSample = () => {
    onChange(SAMPLE_JOB_DESCRIPTION)
  }

  const wordCount = value.trim() ? value.trim().split(/\s+/).length : 0
  const charCount = value.length

  return (
    <div className="h-full flex flex-col">
      {!value && (
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <Briefcase className="w-12 h-12 text-secondary-300 mx-auto mb-4" />
            <p className="text-secondary-500 mb-4">No job description yet</p>
            <button
              onClick={insertSample}
              className="btn-primary px-4 py-2 text-sm"
            >
              Insert Sample Job Description
            </button>
          </div>
        </div>
      )}
      
      {value && (
        <div className="flex-1 flex flex-col">
          <textarea
            value={value}
            onChange={handleChange}
            placeholder="Paste the job description here..."
            className="flex-1 w-full p-4 border-0 resize-none focus:outline-none text-sm leading-relaxed"
            style={{ minHeight: '100%' }}
          />
        </div>
      )}
      
      {!value && (
        <textarea
          value={value}
          onChange={handleChange}
          placeholder="Paste the job description here..."
          className="flex-1 w-full p-4 border-0 resize-none focus:outline-none text-sm leading-relaxed"
          style={{ minHeight: '300px' }}
        />
      )}
      
      <div className="flex items-center justify-between p-3 border-t border-secondary-200 text-xs text-secondary-500">
        <span>Job Description</span>
        <span>{wordCount} words • {charCount} characters</span>
      </div>
    </div>
  )
}