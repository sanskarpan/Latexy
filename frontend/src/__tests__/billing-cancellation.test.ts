import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { describe, expect, test } from 'vitest'

const MANAGER_SOURCE = readFileSync(
  fileURLToPath(new URL('../components/billing/SubscriptionManager.tsx', import.meta.url)),
  'utf8',
)
const BILLING_PAGE_SOURCE = readFileSync(
  fileURLToPath(new URL('../app/billing/page.tsx', import.meta.url)),
  'utf8',
)

describe('end-of-cycle subscription cancellation', () => {
  test('scheduled cancellation is presented as continued paid access', () => {
    expect(MANAGER_SOURCE).toContain("subscription.status === 'cancel_scheduled'")
    expect(MANAGER_SOURCE).toContain("cancellationScheduled ? 'Access until' : 'Renews on'")
    expect(MANAGER_SOURCE).toContain("'Cancellation scheduled'")
  })

  test('scheduled subscriptions cannot submit another cancel or plan change', () => {
    expect(MANAGER_SOURCE).toContain('!billingStatus?.available || cancellationScheduled')
    expect(MANAGER_SOURCE).toContain("subscription.status === 'active' && subscription.subscriptionId")
  })

  test('the Free action does not claim an immediate downgrade', () => {
    expect(BILLING_PAGE_SOURCE).toContain('Your paid access continues until then.')
    expect(BILLING_PAGE_SOURCE).toContain(
      "result.message || 'Cancellation scheduled for the end of the billing cycle.'",
    )
    expect(BILLING_PAGE_SOURCE).not.toContain("toast.success('Downgraded to the Free plan.')")
  })
})
