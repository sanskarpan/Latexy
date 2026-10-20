import { useCallback, useEffect, useRef, useState } from 'react'
import { apiClient } from '@/lib/api-client'
import type { ResumeAccessRole } from '@/lib/resume-access'

/** Own ACL refreshes by auth/document lifetime, never by PDF/preview lifetime. */
export function useCollaborationAccessRefresh({ ownerId, resumeId, token, collaborationAllowed, setRole }: {
  ownerId: string | null
  resumeId: string
  token: string | null | undefined
  collaborationAllowed: boolean
  setRole: (role: ResumeAccessRole) => void
}) {
  const scopeRef = useRef({ ownerId, resumeId, token })
  if (scopeRef.current.ownerId !== ownerId || scopeRef.current.resumeId !== resumeId || scopeRef.current.token !== token) {
    scopeRef.current = { ownerId, resumeId, token }
  }
  const [status, setStatus] = useState<{ scope: typeof scopeRef.current | null; pending: boolean }>({ scope: null, pending: false })
  const requestRef = useRef(0)
  const setRoleRef = useRef(setRole)
  setRoleRef.current = setRole
  const refresh = useCallback(async (changedResumeId: string) => {
    if (changedResumeId !== resumeId || !ownerId) return
    const scope = scopeRef.current
    if (!token || scope.ownerId !== ownerId || scope.resumeId !== resumeId || scope.token !== token) return
    const request = ++requestRef.current
    const ownsScope = () => scopeRef.current === scope && requestRef.current === request
    setStatus({ scope, pending: true })
    // AuthSync publishes the API token in an effect. Give same-commit effects
    // one turn, but never let a mismatched credential retain owner privileges.
    await Promise.resolve()
    if (!ownsScope()) return
    if (apiClient.getAuthToken() !== token) {
      setRoleRef.current('viewer')
      setStatus({ scope, pending: false })
      return
    }
    const isCurrent = () => ownsScope() && apiClient.getAuthToken() === token
    try {
      const data = await apiClient.getResume(resumeId)
      if (isCurrent()) setRoleRef.current(data.access_role ?? (data.user_id === ownerId ? 'owner' : 'viewer'))
    } catch {
      // Keep source intact; a transient error cannot establish write access.
      if (isCurrent()) setRoleRef.current('viewer')
    } finally {
      if (isCurrent()) setStatus({ scope, pending: false })
    }
  }, [ownerId, resumeId, token])

  useEffect(() => {
    const onFocus = () => { void refresh(resumeId) }
    if (!ownerId || !token) setStatus({ scope: scopeRef.current, pending: false })
    else onFocus()
    window.addEventListener('focus', onFocus)
    return () => { requestRef.current += 1; window.removeEventListener('focus', onFocus) }
  }, [ownerId, token, resumeId, collaborationAllowed, refresh])
  // A new document/auth scope is unresolved during the transition render,
  // before its effect can start. Never reuse old-scope write authorization.
  const pending = Boolean(ownerId && token) && (status.scope !== scopeRef.current || status.pending)
  return { refresh, pending }
}
