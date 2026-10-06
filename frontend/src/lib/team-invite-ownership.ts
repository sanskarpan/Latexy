export interface TeamInviteOwner {
  token: string
  sessionToken: string
  generation: number
}

/**
 * Accept/preview responses may resolve after the URL or signed-in account has
 * changed. Only the exact token, account session, and render generation that
 * started the request may apply its result.
 */
export function isTeamInviteOwnerCurrent(
  owner: TeamInviteOwner | null,
  token: string | null,
  sessionToken: string | null,
  generation: number,
): owner is TeamInviteOwner {
  return Boolean(
    owner &&
      token &&
      sessionToken &&
      owner.token === token &&
      owner.sessionToken === sessionToken &&
      owner.generation === generation,
  )
}
