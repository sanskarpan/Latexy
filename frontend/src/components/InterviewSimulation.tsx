'use client'

import { useState } from 'react'
import { BrainCircuit, CheckCircle2, Loader2, RotateCcw } from 'lucide-react'
import {
  apiClient,
  type InterviewQuestion,
  type InterviewSimulationFeedback,
  type InterviewSimulationMode,
} from '@/lib/api-client'

interface InterviewSimulationProps {
  prepId: string
  questions: InterviewQuestion[]
}

type Phase = 'setup' | 'answering' | 'feedback' | 'complete'

export default function InterviewSimulation({ prepId, questions }: InterviewSimulationProps) {
  const [mode, setMode] = useState<InterviewSimulationMode>('coach')
  const [phase, setPhase] = useState<Phase>('setup')
  const [currentIndex, setCurrentIndex] = useState(0)
  const [currentAnswer, setCurrentAnswer] = useState('')
  const [answers, setAnswers] = useState<Record<number, string>>({})
  const [feedback, setFeedback] = useState<InterviewSimulationFeedback[]>([])
  const [overallFeedback, setOverallFeedback] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const start = () => {
    setCurrentIndex(0)
    setCurrentAnswer('')
    setAnswers({})
    setFeedback([])
    setOverallFeedback('')
    setError(null)
    setPhase('answering')
  }

  const evaluate = async (submitted: Record<number, string>) => {
    const indexes = Object.keys(submitted).map(Number).sort((a, b) => a - b)
    return apiClient.evaluateInterviewSimulation(prepId, {
      mode,
      answers: indexes.map(questionIndex => ({
        question_index: questionIndex,
        answer: submitted[questionIndex],
      })),
    })
  }

  const submitAnswer = async () => {
    const answer = currentAnswer.trim()
    if (answer.length < 20 || loading) return
    const submitted = { ...answers, [currentIndex]: answer }
    setAnswers(submitted)
    setLoading(true)
    setError(null)
    try {
      if (mode === 'coach') {
        const result = await evaluate({ [currentIndex]: answer })
        setFeedback(current => [...current, ...result.feedback])
        setOverallFeedback(result.overall_feedback)
        setPhase('feedback')
      } else if (currentIndex === questions.length - 1) {
        const result = await evaluate(submitted)
        setFeedback(result.feedback)
        setOverallFeedback(result.overall_feedback)
        setPhase('complete')
      } else {
        setCurrentIndex(index => index + 1)
        setCurrentAnswer('')
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Practice feedback could not be generated')
    } finally {
      setLoading(false)
    }
  }

  const continueAfterFeedback = () => {
    if (currentIndex === questions.length - 1) {
      setPhase('complete')
    } else {
      setCurrentIndex(index => index + 1)
      setCurrentAnswer('')
      setPhase('answering')
    }
  }

  const currentFeedback = feedback.find(item => item.question_index === currentIndex)
  const averageScore = feedback.length
    ? Math.round(feedback.reduce((sum, item) => sum + item.score, 0) / feedback.length)
    : 0

  if (phase === 'setup') {
    return (
      <div className="border-b border-line bg-surface px-3 py-3 space-y-2.5">
        <div className="flex items-center gap-2">
          <BrainCircuit size={13} className="text-accent-strong" />
          <p className="text-[11px] font-semibold text-fg">Text interview simulation</p>
        </div>
        <div className="grid grid-cols-2 gap-2">
          {([
            ['coach', 'Coach mode', 'Feedback after every answer'],
            ['mock', 'Mock mode', 'Feedback after the full session'],
          ] as const).map(([value, label, description]) => (
            <button
              key={value}
              type="button"
              aria-pressed={mode === value}
              onClick={() => setMode(value)}
              className={`rounded-[var(--radius-md)] border px-2.5 py-2 text-left transition ${
                mode === value ? 'border-accent bg-accent-soft' : 'border-line bg-surface-2'
              }`}
            >
              <span className="block text-[10px] font-semibold text-fg">{label}</span>
              <span className="mt-0.5 block text-[9px] leading-snug text-fg-3">{description}</span>
            </button>
          ))}
        </div>
        <p className="text-[9px] leading-snug text-fg-3">
          Text only. Answers are evaluated transiently and are not saved; no microphone, camera, or hiring prediction is used.
        </p>
        <button
          type="button"
          onClick={start}
          className="w-full rounded-[var(--radius-md)] bg-accent-soft py-1.5 text-[10px] font-semibold text-accent-strong ring-1 ring-accent"
        >
          Start {mode === 'coach' ? 'Coach' : 'Mock'} session ({questions.length} questions)
        </button>
      </div>
    )
  }

  if (phase === 'complete') {
    return (
      <div className="max-h-96 overflow-y-auto border-b border-line bg-surface px-3 py-3 space-y-2.5">
        <div className="flex items-center justify-between">
          <p className="text-[11px] font-semibold text-fg">Session feedback</p>
          <span className="rounded bg-accent-soft px-2 py-0.5 text-[10px] font-semibold text-accent-strong">
            Practice score {averageScore}/100
          </span>
        </div>
        <p className="text-[10px] leading-relaxed text-fg-2">{overallFeedback}</p>
        {feedback.map(item => <FeedbackCard key={item.question_index} feedback={item} />)}
        <button
          type="button"
          onClick={() => setPhase('setup')}
          className="flex w-full items-center justify-center gap-1.5 rounded-[var(--radius-md)] border border-line py-1.5 text-[10px] text-fg-2 hover:bg-surface-2"
        >
          <RotateCcw size={10} /> Start another session
        </button>
      </div>
    )
  }

  const question = questions[currentIndex]
  return (
    <div className="border-b border-line bg-surface px-3 py-3 space-y-2.5">
      <div className="flex items-center justify-between text-[10px] text-fg-3">
        <span>{mode === 'coach' ? 'Coach' : 'Mock'} mode</span>
        <span>Question {currentIndex + 1} of {questions.length}</span>
      </div>
      <p className="text-[12px] font-semibold leading-relaxed text-fg">{question.question}</p>
      {phase === 'answering' ? (
        <>
          <textarea
            aria-label={`Answer to question ${currentIndex + 1}`}
            value={currentAnswer}
            onChange={event => setCurrentAnswer(event.target.value)}
            maxLength={1200}
            rows={5}
            placeholder="Type the answer you would give in the interview…"
            className="w-full resize-y rounded-[var(--radius-md)] border border-line bg-bg px-2.5 py-2 text-[11px] text-fg outline-none focus:border-line-2"
          />
          <div className="flex items-center justify-between text-[9px] text-fg-3">
            <span>Minimum 20 characters</span><span>{currentAnswer.length}/1200</span>
          </div>
          {error && <p role="alert" className="text-[10px] text-err">{error}</p>}
          <button
            type="button"
            onClick={() => { void submitAnswer() }}
            disabled={currentAnswer.trim().length < 20 || loading}
            className="flex w-full items-center justify-center gap-1.5 rounded-[var(--radius-md)] bg-accent-soft py-1.5 text-[10px] font-semibold text-accent-strong ring-1 ring-accent disabled:opacity-40"
          >
            {loading && <Loader2 size={10} className="animate-spin" />}
            {loading ? 'Evaluating…' : currentIndex === questions.length - 1 ? 'Finish session' : 'Submit answer'}
          </button>
        </>
      ) : currentFeedback ? (
        <>
          <FeedbackCard feedback={currentFeedback} />
          <button
            type="button"
            onClick={continueAfterFeedback}
            className="w-full rounded-[var(--radius-md)] bg-accent-soft py-1.5 text-[10px] font-semibold text-accent-strong ring-1 ring-accent"
          >
            {currentIndex === questions.length - 1 ? 'View session summary' : 'Continue to next question'}
          </button>
        </>
      ) : null}
    </div>
  )
}

function FeedbackCard({ feedback }: { feedback: InterviewSimulationFeedback }) {
  return (
    <div className="rounded-[var(--radius-md)] border border-line bg-bg p-2.5 space-y-1.5">
      <div className="flex items-center gap-1.5">
        <CheckCircle2 size={11} className="text-ok" />
        <span className="text-[10px] font-semibold text-fg">Answer feedback</span>
        <span className="ml-auto text-[10px] font-semibold text-accent-strong">{feedback.score}/100</span>
      </div>
      <p className="text-[9px] font-semibold uppercase tracking-wide text-ok">Strengths</p>
      {feedback.strengths.map(item => <p key={item} className="text-[10px] text-fg-2">• {item}</p>)}
      <p className="text-[9px] font-semibold uppercase tracking-wide text-warn">Improve</p>
      {feedback.improvements.map(item => <p key={item} className="text-[10px] text-fg-2">• {item}</p>)}
      <p className="text-[9px] font-semibold uppercase tracking-wide text-fg-3">Suggested outline</p>
      {feedback.suggested_outline.map(item => <p key={item} className="text-[10px] text-fg-2">• {item}</p>)}
    </div>
  )
}
