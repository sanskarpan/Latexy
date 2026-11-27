# Share/review journey - 2026-11-27

**Verdict:** BLOCKED by a new P1 (FE-16 / #2344). The share API and public payload work; the browser cannot render the PDF because the artifact URL is not CORS-enabled.

## Setup

- Fresh pro test user (`interact7.pro.*@example.test`), email verified, synthetic active `pro` subscription.
- Flow: PDF import → adapt → compile via `POST /jobs/submit` (`latex_compilation`, `pdflatex`, `metadata.resume_id`) → wait for accepted artifact → `POST /resumes/{id}/share` → open `/r/{token}` anonymously.

## Evidence

- `share-review-journey.json` - compile states, artifact, share payload, timings.
- `share-review-page.png` - public page after ~10s.
- `share-review-45s.png` - public page after ~50s, showing "The review document could not be loaded."

## Timeline

| Step | Observed |
|---|---|
| PDF import | 201, 10.8s; extraction `partial`, 9 fields, 23 supported templates |
| Adapt | 200, 14.2s; resume `c26ecbc4-...`, 481 LaTeX chars |
| Compile submit | 200, 11.4s; job `4b3c08fb-...` |
| Compile states | processing 0% at 14.1s → 10% at 18.8s → 90% at 44.8s → completed 100% at 54.7s |
| Accepted artifact | 57.8s; 1 page |
| `POST /resumes/{id}/share` | 200 in 7.3s; `share_url` returned |
| `GET /share/{token}` (no auth) | 200; `pdf_url` present on R2; `accessible_text` 124 chars; `review_comments=true`; `anonymous_processing=false` |

## Failure

Public `/r/{token}` loads the title "Share Review Audit Resume", the PDF/accessible-text tabs, and the review panel. After ~50s:

- PDF canvas/iframe count: **0**.
- Review surface: **"The review document could not be loaded."**
- Console: `Access to fetch at 'https://2ca2c...r2.cloudflarestorage.com/...pdf' ... has been blocked by CORS policy`, `Failed to load resource: net::ERR_FAILED`.
- `curl -H 'Origin: https://latexy.xyz'` returns **200** with `Content-Type: application/pdf`, `Content-Length: 25008`, but **no `Access-Control-Allow-Origin`** header.
- No HTTP >= 400 and no application error: the API and storage are healthy; the browser blocks the cross-origin response.

## Root cause and fix

The share API hands the browser a presigned R2 URL; pdf.js fetches it cross-origin and requires CORS headers. Either proxy the PDF through a same-origin backend route with Range support, or add an R2 CORS policy for `https://latexy.xyz` / `https://www.latexy.xyz` exposing `Content-Length, Content-Range, Accept-Ranges, ETag`.

Tracked in **#2344** (P1). The no-accepted-artifact state remains tracked in **#2331**.

## Not completed

- Posting a public review comment through the UI: the button requires a PDF anchor, and the PDF never renders. The public comment POST path is therefore blocked by the same defect.
- Anonymous share mode: not exercised in this pass (pro user, anonymous disabled); it uses a separate redacted-artifact path.

## Cleanup

- User, synthetic subscription, resume, compilation, job finalization and session rows deleted.
- Remaining `interact7.%` users: **0**; resume rows: **0**.
- The generated R2 artifact becomes an orphan and is eligible for the existing render-artifact retention sweep (no DB reference remains).
