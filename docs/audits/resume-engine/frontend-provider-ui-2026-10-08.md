# Semantic review provider chooser — 2026-10-08

## Implemented behavior

The managed resume's **Improve your resume** panel now offers **Review provider** and, for an explicit provider, **Review model**. Automatic retains the existing admission behavior: omit both provider override fields, prefer the user's connected OpenAI key, otherwise use the server's default provider.

Options come exclusively from authenticated `GET /resumes/engine/providers`. The response contains nonsecret default readiness and each supported provider's key availability and exact supported model IDs. It contains no API key bytes. Explicit OpenAI, Anthropic, or OpenRouter choices submit `provider` and `provider_model`; the UI never invents models or borrows the unrelated legacy job selector's model list.

Providers without an available key or supported models are disabled. A provider with one model selects that model when chosen; multiple models require a deliberate model choice before **Find suggestions** enables. Unavailable Automatic review does not prevent choosing another available provider. Key management links to `/byok`. A failed options request offers Retry, preserving the resume and target job text.

Explicit-choice copy explains that the review stops if the chosen provider becomes unavailable. Enforcing no platform fallback and rejecting missing/decrypt-failed keys or unsupported pricing before admission is the backend contract; the UI is not a security boundary.

## Account boundaries

The hook stores options and selection with the current resume/account identity and token. The first render after identity or token changes hides the previous account's options and selection before effect cleanup; the effective choice becomes Automatic and review admission stays disabled until current options load.

Options fetches carry a captured account context and abort on cleanup. Successful and failed responses check current identity and token before updating state. Admission sends the same captured context through the API client's authentication dispatch gate. The panel ignores responses after that context changes, including an account change while a review is in flight. Switching provider does not submit keys through this UI.

## Verification scope

New unit coverage includes the actual panel's Automatic omission, explicit provider/model body, and delayed admission response, as well as connected/advertised model eligibility, unavailable Automatic, missing-key/unsupported-model rejection, render-time account reset, late options response rejection, the authenticated options URL, and a dispatch-time account change.

The existing production Chromium managed-review contract now advertises a two-model Anthropic choice, checks that admission is disabled until a model is selected, and asserts the exact chosen provider/model in the admission body while preserving its candidate/decision/PDF assertions. That contract uses mocked authentication/API/stream and valid synthetic PDF bytes. It does not invoke a real paid provider.

The earlier full frontend validation (1,162 unit tests, TypeScript, lint, production Next build, and nine production Chromium contracts) covered the cancellation/identity fixes before this provider chooser. It must not be described as validation of these newly added UI bytes. Focused provider validation and the final build/browser result are recorded separately below when complete.

Initial options/client unit run: four passed; one hit Vitest's five-second test deadline while dynamically importing modules under host contention. Moving the pure test's import to module setup resolved this without changing deadlines or assertions. Rerun: **5/5 passed**, two files, **23.11 s** total (including module transform/import).

Final focused run: **8/8 passed across three files**, 15.06 seconds, including
the actual panel admission tests. Full TypeScript check and ESLint with zero
warnings passed. ESLint initially rejected a lowercase hook-test harness function;
renaming it as a component harness fixed the naming violation without suppressions.
Final production build/browser verification remains pending here; consult the
parent release audit rather than claiming the previous runtime includes the chooser.

Completed afterward: the **full 1,170-test/185-file unit suite**, complete
40-page production build and artifact validator, and **all nine production
Chromium contracts with zero retries** passed. The changed provider/model contract
was exercised against the new standalone bundle. See the dated parent audit and
its hashed frontend summaries for source/environment provenance and the separate
real guest first-task result. No live paid-provider request is claimed.
