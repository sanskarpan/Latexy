import { describe, expect, it } from 'vitest'
import { isTeamInviteOwnerCurrent } from '../lib/team-invite-ownership'

describe('team invitation request ownership', () => {
  const owner = { token: 'invite-a', sessionToken: 'account-a', generation: 7 }

  it('rejects a late response after the token changes', () => {
    expect(isTeamInviteOwnerCurrent(owner, 'invite-b', 'account-a', 7)).toBe(false)
  })

  it('rejects a late response after the signed-in account changes', () => {
    expect(isTeamInviteOwnerCurrent(owner, 'invite-a', 'account-b', 7)).toBe(false)
  })

  it('accepts only the exact token, account, and generation', () => {
    expect(isTeamInviteOwnerCurrent(owner, 'invite-a', 'account-a', 7)).toBe(true)
    expect(isTeamInviteOwnerCurrent(owner, 'invite-a', 'account-a', 8)).toBe(false)
  })
})
