# Subscription plan matrix - 2026-11-28

| Plan | Account fixture | Verified |
|---|---|---|
| Anonymous | incognito | Pricing shows no prices (FE-05); consent covers cards (FE-03) |
| Free | synthetic free | Billing shows Free; 10 compiles/day, 3 AI/month, no history; Free current |
| **Basic** | synthetic active basic | Billing shows **Basic ACTIVE**, renews 28/12/2026, **400 compiles/month**, **10 optimizations/month**, 30-day history, API 100/day; dashboard loads |
| Pro | synthetic pro (ATS/share/PDF journeys) | Unlimited compiles/AI, 365-day history, priority support; Optimize/ATS flows exercised |
| Team | synthetic owner + member + workspace | 5 seats, member invite/accept, 2/5 members, recruiter dashboard |
| BYOK | live paying customer + local test checkout | Backfilled live subscription/entitlement; local Dodo test checkout + webhook activation PASS |
| Admin | synthetic admin | Read-only analytics, tenant page, feature-flag enable/restore with audit rows |

## Basic plan evidence

Synthetic `basic` user, production page `/billing`, loaded state:

```text
Current subscription
Basic
ACTIVE
Renews on 28/12/2026

COMPILATIONS 400 / month
OPTIMIZATIONS 10 / month
HISTORY 30 days
ENABLED FEATURES API: 100 / day
```

Screenshots: `basic-billing-loaded.png`, `basic-dashboard.png`.

## Note

The billing "Current subscription" block still took ~18s to load; the first 9s showed **"Loading subscription state..."**. This is FE-17 / #2345, not a plan defect.
