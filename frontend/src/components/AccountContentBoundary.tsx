'use client'

import { Fragment, useEffect, useRef, type ReactNode } from 'react'
import { usePathname } from 'next/navigation'
import { useSession } from '@/lib/auth-client'
import { isConfirmedSessionUnauthorized } from '@/lib/session-authority'
import { AccountContentScopeProvider, type AccountContentScope } from '@/contexts/AccountContentScope'

/** Reset private page state on confirmed account changes, including A → B → A.
 * Uncertain refreshes preserve recovery while live admission fails closed.
 */
export default function AccountContentBoundary({ children }: { children: ReactNode }) {
  const { data: session, isPending, isRefetching = false, error } = useSession()
  const pathname = usePathname()
  const unauthorized = isConfirmedSessionUnauthorized(error)
  const scope = useRef({ owner: unauthorized ? 'anonymous' : session?.user?.id ?? 'anonymous', epoch: 0 })
  const owner = unauthorized ? 'anonymous' : session?.user?.id ?? ((!isPending && !isRefetching && !error) ? 'anonymous' : scope.current.owner)
  if (owner !== scope.current.owner) scope.current = { owner, epoch: scope.current.epoch + 1 }
  const route = useRef({ pathname, epoch: 0 })
  if (route.current.pathname !== pathname) route.current = { pathname, epoch: route.current.epoch + 1 }
  const ready = useRef(false)
  ready.current = Boolean(session?.user?.id && !unauthorized && !isPending && !isRefetching && !error)
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])
  const recovery = useRef<{ account: typeof scope.current; route: typeof route.current; identity: object } | null>(null)
  if (!recovery.current || recovery.current.account !== scope.current || recovery.current.route !== route.current) {
    recovery.current = { account: scope.current, route: route.current, identity: {} }
  }
  const recoveryIdentity = recovery.current.identity
  const token = session?.session?.token ?? null
  const admission = useRef({ recoveryIdentity, session, token, isPending, isRefetching, error, identity: {} })
  if (admission.current.recoveryIdentity !== recoveryIdentity || admission.current.session !== session
    || admission.current.token !== token || admission.current.isPending !== isPending
    || admission.current.isRefetching !== isRefetching || admission.current.error !== error) {
    // Retire admission during the parent render, even if a child skips the
    // uncertain snapshot. Recovery ownership remains stable for that child.
    admission.current = { recoveryIdentity, session, token, isPending, isRefetching, error, identity: {} }
  }
  const authority = useRef<{ admission: object; value: AccountContentScope } | null>(null)
  if (!authority.current || authority.current.admission !== admission.current.identity) {
    const account = scope.current; const path = route.current
    const lease = admission.current.identity
    const isCurrent = () => mounted.current && scope.current === account && route.current === path
    const isAdmissionCurrent = () => isCurrent() && admission.current.identity === lease
    authority.current = { admission: lease, value: {
      recoveryIdentity, isCurrent, isAdmissionCurrent,
      canAdmit: () => isAdmissionCurrent() && ready.current,
    } }
  }
  return <AccountContentScopeProvider value={authority.current.value}>
    <Fragment key={`${scope.current.owner}:${scope.current.epoch}`}>{children}</Fragment>
  </AccountContentScopeProvider>
}
