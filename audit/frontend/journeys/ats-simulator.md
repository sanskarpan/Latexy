# ATS simulator journey - 2026-11-27

**Verdict:** PASS. The simulator runs and returns a score/checks when a profile is selected.

## Setup

- Fresh synthetic pro user (`interact8.pro.*@example.test`), email verified, active pro subscription.
- Builder resume created via API (201, 16.3s), compiled via API, accepted artifact at 56.7s (1 page).
- Browser: Playwright, 1440x1100, owner cookie; optimize page.

## Timeline

| Step | Observed |
|---|---|
| Optimize page load | "Targeted Optimization" visible at **40.1s** (still the FE-01 latency) |
| ATS quick score | `GET /ats/quick-score` 200, score 15 |
| Profiles | `GET /ats/simulate/profiles` 200 after the page settles (7 profiles) |
| Select Greenhouse | profile button "Greenhouse / Good" clicked |
| Run checks | disabled before profile, **enabled after** |
| Simulation | `POST /ats/simulate` **200 in 3.4s** |
| Result | **76/100**, 2 high issues: contact missing, no section headers; 4 recommendations |

No console errors and no HTTP >= 400 during the run.

## Correction to the earlier attempt

The earlier ATS attempt reported "Run checks stayed disabled while the pipeline showed Initializing / Completed." That was a **test-timing observation, not a product block**: the simulator requires a check profile to be selected, and the profile grid had not loaded/been clicked yet. With the profile loaded and selected, the check runs. This journey is now PASS; the only real problem is the optimize page's 40s time-to-content (FE-01).

## Evidence

- `ats-simulator-journey.json` - load time, profile/run states, `/ats/*` responses, result text.
- `ats-simulator-result.png` - score ring 76, issues and recommendations.

## Cleanup

- Resume deleted through `DELETE /resumes/{id}` (204, removes the artifact).
- Synthetic subscription, usage rows, sessions and user deleted; remaining `interact8.%` users: **0**.
