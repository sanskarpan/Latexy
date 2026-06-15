import { atom } from 'nanostores'

export type MessageRole =
  | 'user'
  | 'assistant'
  | 'tool_use'
  | 'log_stream'
  | 'compile_result'
  | 'ats_result'
  | 'resume_list'
  | 'system'
  | 'error'

export interface Message {
  id: string
  role: MessageRole
  content: string
  timestamp: string
  streaming?: boolean
  toolName?: string
  toolArgs?: Record<string, unknown>
  toolState?: 'running' | 'success' | 'error' | 'cancelled'
  toolResult?: unknown
  durationMs?: number
  jobId?: string
  resultData?: unknown
}

export const $messages = atom<Message[]>([])
export const $activeJobId = atom<string | null>(null)

let _idCounter = 0
export function nextId(): string {
  return `msg-${Date.now()}-${_idCounter++}`
}

export function addMessage(msg: Omit<Message, 'id' | 'timestamp'>): string {
  const id = nextId()
  const full: Message = { id, timestamp: new Date().toISOString(), ...msg }
  $messages.set([...$messages.get(), full])
  return id
}

export function updateMessage(id: string, patch: Partial<Message>): void {
  $messages.set($messages.get().map(m => m.id === id ? { ...m, ...patch } : m))
}

export function clearMessages(): void {
  $messages.set([])
}
