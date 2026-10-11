'use client'

import { Fragment, useRef, type ReactNode } from 'react'
import { useSession } from '@/lib/auth-client'

/** Reset private page state on confirmed account changes, including A → B → A.
 * A transient session lookup failure is not a confirmed identity change: keep
 * offline drafts mounted while capability/auth guards independently fail closed.
 */
export default function AccountContentBoundary({ children }: { children: ReactNode }) {
  const { data: session, isPending, error } = useSession()
  const scope = useRef({ owner: session?.user?.id ?? 'anonymous', epoch: 0 })
  const owner = session?.user?.id ?? ((!isPending && !error) ? 'anonymous' : scope.current.owner)
  if (owner !== scope.current.owner) scope.current = { owner, epoch: scope.current.epoch + 1 }
  return <Fragment key={`${scope.current.owner}:${scope.current.epoch}`}>{children}</Fragment>
}
