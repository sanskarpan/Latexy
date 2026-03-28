# Latexy — Confirmed Code Gaps

Each gap below was verified by reading the actual source files, not by assumption.
All six have the infrastructure built but the wiring missing.

---

## GAP-001 · ResumeJobMatch caching never implemented

**Severity:** High
**Area:** Backend — `backend/app/api/ats_routes.py`

### What exists
`ResumeJobMatch` ORM model (`backend/app/database/models.py:177`) with columns
`jd_hash`, `similarity_score`, `matched_keywords`, `missing_keywords`, `semantic_gaps`.
Composite index `idx_rjm_resume_jd` on `(resume_id, jd_hash)` exists.
DB table is created and present in production.

### What is missing
`POST /ats/semantic-match` (`ats_routes.py:621`) calls
`embedding_service.semantic_keyword_match()` on every request without ever:
- computing a `jd_hash`
- querying `resume_job_matches` for a cached result
- writing results back to the table after computation

Every semantic match call recomputes cosine similarity from scratch, even for
identical resume+JD combinations.

### Fix
```python
import hashlib
jd_hash = hashlib.sha256(request.job_description.encode()).hexdigest()

# cache lookup
cached = await db.execute(
    select(ResumeJobMatch)
    .where(ResumeJobMatch.resume_id == resume_id, ResumeJobMatch.jd_hash == jd_hash)
)
row = cached.scalar_one_or_none()
if row:
    # return cached result
    ...

# cache write after computation
db.add(ResumeJobMatch(user_id=user_id, resume_id=resume_id, jd_hash=jd_hash, ...))
await db.commit()
```

---

## GAP-002 · Rate limiting middleware built but never registered

**Severity:** High
**Area:** Backend — `backend/app/middleware/rate_limiting.py`, `backend/app/main.py`

### What exists
`RateLimitMiddleware` and `APIKeyRateLimitMiddleware` are fully implemented
(`rate_limiting.py:1–217`), using Redis Lua scripts for atomic sliding-window
rate limiting. Both classes are complete and correct.

### What is missing
`main.py:74–92` registers only CORS middleware. Neither class is passed to
`app.add_middleware()`. The running application has **no rate limiting at any
endpoint**, including high-cost routes like `/jobs/submit` and `/compile`.

### Fix
```python
# main.py — after CORS setup
from .middleware.rate_limiting import RateLimitMiddleware, APIKeyRateLimitMiddleware
app.add_middleware(RateLimitMiddleware, calls_per_minute=60, calls_per_hour=1000)
app.add_middleware(APIKeyRateLimitMiddleware)
```
Thresholds should be tuned per-route (compile/optimize are more expensive than health).

---

## GAP-003 · Duplicate encryption implementations — encryption_service vs api_key_service

**Severity:** Medium
**Area:** Backend — `backend/app/services/encryption_service.py`, `backend/app/services/api_key_service.py`

### What exists
**`encryption_service.py`** — full-featured `EncryptionService` class:
- PBKDF2HMAC key derivation with fixed salt
- Provider-scoped `encrypt_api_key(key, provider)` / `decrypt_api_key(...)` with prefix verification
- `is_encrypted()`, `generate_key()` helpers
- Module-level singleton + helper functions
- 10+ unit tests in `test_byok_encryption.py`

**`api_key_service.py`** — internal `APIKeyEncryption` class:
- Direct Fernet key (no KDF)
- Only `encrypt()` / `decrypt()`, no provider scoping
- Strict: raises `ValueError` if `API_KEY_ENCRYPTION_KEY` not set
- Used in production by `api_key_service` for all BYOK key storage

### What is missing
The two implementations share no code. `api_key_service.py` does not import
`encryption_service`. Any code that calls `encryption_service` and any code that
calls `APIKeyEncryption` use **different key derivation strategies and incompatible
ciphertext**. Data encrypted by one cannot be decrypted by the other.

### Fix
Option A (preferred): Make `api_key_service.APIKeyEncryption` a thin wrapper around
`encryption_service.EncryptionService`, removing the duplicate Fernet logic.

Option B: Keep both but document which is authoritative and for what purpose,
add explicit guards preventing cross-use (e.g., an `@encrypt_with` decorator or
context markers).

---

## GAP-004 · OnboardingFlow component built but never triggered

**Severity:** Medium
**Area:** Frontend — `frontend/src/components/onboarding/OnboardingFlow.tsx`

### What exists
`OnboardingFlow.tsx` is fully implemented with 4 steps:
- Welcome
- How It Works
- Key Features
- Get Started

Supports user types `'new' | 'trial_converted' | 'premium'` and manages
completion state in localStorage (`latexy_onboarding_completed`).
Exports a `useOnboarding()` hook with `startOnboarding()` / `completeOnboarding()`.

### What is missing
Zero imports of `OnboardingFlow` anywhere in the app. No call to
`startOnboarding()` after signup. New users land on the dashboard with no
guidance, no context, and no call to action.

### Fix
Wire `useOnboarding()` into `app/dashboard/page.tsx` or `app/layout.tsx`:
```tsx
const { shouldShow, startOnboarding } = useOnboarding()
useEffect(() => {
  if (session?.user && isNewUser) startOnboarding('new')
}, [session])
// render <OnboardingFlow /> when shouldShow is true
```
Detection of `isNewUser` can use `user.createdAt` within the last 5 minutes, or
a `onboarding_shown` flag in the users table.

---

## GAP-005 · ProviderSelector not wired into BYOK page

**Severity:** Medium
**Area:** Frontend — `frontend/src/components/byok/ProviderSelector.tsx`, `frontend/src/app/byok/page.tsx`

### What exists
`ProviderSelector.tsx` is fully implemented: fetches `/api/byok/providers` and
`/api/byok/capabilities/{provider}`, displays provider cards with model dropdowns,
context window, feature badges, and "Your Key / Default" status indicators.

### What is missing
The BYOK page (`app/byok/page.tsx`) uses only `APIKeyManager`, which has a plain
`<select>` dropdown for provider selection (lines 200–211). `ProviderSelector` is
never imported anywhere. Users adding BYOK keys cannot see provider capabilities,
model options, or context limits before committing.

### Fix
Import `ProviderSelector` in `byok/page.tsx` and render it in a second section
below `APIKeyManager`:
```tsx
import ProviderSelector from '@/components/byok/ProviderSelector'
// in JSX: after APIKeyManager
<ProviderSelector userApiKeys={userApiKeys} />
```
Alternatively, move it to the optimization flow pages where users actually
select a provider at job-submission time.

---

## GAP-006 · JobQueue component built but not shown anywhere

**Severity:** Low
**Area:** Frontend — `frontend/src/components/JobQueue.tsx`

### What exists
`JobQueue.tsx` (465 lines) is fully implemented: job list with status/type
filters, search, progress bars, cancel/retry actions, system health indicator.
Uses `useJobManagement()` and `useJobStatus()` hooks which are wired to real API.

### What is missing
No page imports `JobQueue`. The admin page at `/admin` only shows the feature
flags panel. There is no queue visibility anywhere in the UI — not for admins
and not for users who want to see their job history with actions.

### Fix
Add `JobQueue` to the admin page (`app/admin/page.tsx`) below the feature flags
panel for operator visibility of the system queue. For user-facing use, add a
"Jobs" tab or section to `/dashboard`.

---

## What was confirmed NOT a gap

| Item | Reason |
|------|--------|
| `FileUpload.tsx` | Superseded by `MultiFormatUpload.tsx` which handles all formats. Deleted. |
| `marketing/SiteHeader.tsx` | Orphaned legacy; all marketing pages use `GlobalHeader` from root layout. Deleted. |
| `marketing/MarketingFrame.tsx` | Same as above. Deleted. |
| `showSuccessToast` / `showErrorToast` | Zero call sites; 154 direct `toast.*` calls across 24 files confirm sonner is the established pattern. Deleted. |
| `interview_prep_worker` / `converter_worker` | Were missing from Celery registration — **fixed** (not a gap anymore). |
