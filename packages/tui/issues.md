# TUI audit — round 4

Fourth adversarial pass over `packages/tui`. Rounds 1–3 (PR #1075) found 43 defects
and closed #1065–#1072.

**27 new defects, every one reproduced with running code before being fixed.** One
was a regression introduced by a fix in this same round; it is listed as such.

Three areas were attacked hard and **could not be broken** — they are recorded at the
bottom, because a confirmed-correct is worth as much as a finding and stops it being
re-investigated a fifth time.

Ordered root-cause-first: several symptom clusters trace to one cause.

---

## Severe

### 1. Interactive sign-in could never succeed

**Where** `src/components/overlays/LoginOverlay.tsx:39`, `src/lib/api-client.ts:44`

`LoginOverlay` POSTs to Better Auth on the Next.js app. Better Auth rejects any
request it judges to have come from a browser but carrying no `Origin` — and
Node's `fetch`, which `ApiClient` uses, trips that heuristic while sending no
`Origin` of its own.

**Evidence** Same endpoint, same body, three header sets:

```
no Origin          403 {"message":"Missing or null Origin","code":"MISSING_OR_NULL_ORIGIN"}
Origin: app url    200 {"token":"wf6Uu2mSgHmPlc7xe…","user":{…}}
Origin: bogus      403 {"message":"Invalid origin","code":"INVALID_ORIGIN"}
```

`curl` with no `Origin` returns 200, which is why this was never noticed by hand —
but the TUI does not use curl. Reproduced directly through `ApiClient`.

**User impact** The first-run journey. A new user runs `npx @sanskarpan/latexy`,
types their email and password, and gets a 403 — with the reason discarded (see
#26), so the prompt just said *Forbidden*. There was no way to sign in from the
TUI at all except by setting `LATEXY_SESSION_TOKEN` out of band.

**Fix** `ApiClient` takes an optional `origin`; `LoginOverlay` declares the auth
origin. Verified end to end: a user is created, the token Better Auth issues
authenticates against FastAPI `/me`, and it survives a simulated restart via
`readConfig()`. *Production is unverified* — I could only test against the local
Next.js app, and a differently-configured `trustedOrigins` could behave otherwise.

---

### 2. Ctrl+C tore down the interface and then hung forever

**Where** `src/cli.tsx:24`, `src/components/AppShell.tsx:29`

Ink puts stdin in raw mode, so Ctrl+C arrives as the byte `0x03` and never as a
signal — the `process.on('SIGINT')` handler was unreachable from the keyboard.
`AppShell` handled it with Ink's `exit()`, which unmounts the UI but does not end
the process, and the websocket heartbeat (`ws-client.ts:184`) plus the 30s health
poll (`app.tsx:77`) kept the event loop alive indefinitely.

**Evidence** pty harness, 4 trials: UI unmounted cleanly, cursor restored, no stack
trace — and the process was still alive after 35s with the shell never returning. A
real `SIGINT` signal exited the same build in 0.62s, proving the handler worked and
only the keyboard path was broken.

**User impact** The single most-used key in any terminal program. The user has to
kill the terminal or find the pid.

**Fix** `waitUntilExit().then(() => process.exit(0))` in `cli.tsx`, plus
`wsClient.destroy()` before `exit()`. Re-verified: 0.77s idle, 0.76s with an overlay
open, 0.01–0.05s mid-job, and real SIGINT/SIGTERM still exit.

---

### 3. A dropped websocket replayed the entire job

**Where** `src/lib/ws-client.ts:150` (`subscribe`), `src/hooks/useJobStream.ts:39`

`subscriptions` was seeded with `'0'` and **never advanced**, so every reconnect
resubscribed from the start of the stream. Nothing downstream deduplicates:
`onLogLine` pushes and `onLLMToken` concatenates.

**Evidence** Against the real backend, subscribing to a finished job with
`last_event_id='0'` replayed **all 20 of its events** (13 `log.line`, plus
`job.completed`):

```
events replayed for a FINISHED job with last_event_id='0': 20
{"job.queued":1,"job.started":1,"job.progress":3,"log.line":13,
 "job.pdf_extracted":1,"job.completed":1}
```

A `ws` test server confirmed the client asks for `'0'` again after an unclean drop,
having already received `1700000000000-5`.

**User impact** A compile that blipped its connection showed every build-log line
twice; an `/optimize` showed the generated LaTeX concatenated with itself.

**Fix** Track the last `event_id` per subscription and resume from it; released
subscriptions are not resurrected by a late event. Plus a second layer: the
controller drops any `event_id` it has already applied.

---

### 4. `/cancel` could not clear the slot it was told to clear

**Where** `src/commands/dispatch.ts:110`

The single-job slot is held by `$activeJobId` until a terminal event arrives. If the
socket dropped, the worker died, or the job settled while the TUI was not listening,
that event never came — and `/cancel` never cleared `$activeJobId`.

**User impact** Permanent lockout. Every later job is refused with *"A job is already
running — /cancel it first"*, and the one command that message names could not fix
it. Restart was the only way out.

**Evidence** `probe-state`: set `$activeJobId`, dispatch `/cancel`, `$activeJobId` is
still set and `claimJobSlot()` still returns false.

**Fix** Release the slot after a successful cancel, when the job is already terminal,
and when the id cannot be looked up at all.

---

### 5. Validation errors reached the user as `[object Object]`

**Where** `src/lib/api-client.ts:95`

```ts
const msg = (data as Record<string, unknown>)['detail'] as string ?? res.statusText
```

FastAPI returns `detail` as an **array** on 422. The `as string` cast is a lie and
`??` never fires because an array is not null.

**Evidence** Real `ApiClient` against `POST /ats/quick-score {}`:
```
STATUS 422
MESSAGE>>>[object Object]<<<
renders as: Quick ATS failed: [object Object]
```

**User impact** Every malformed request across every command, with no indication of
which field was wrong. Both the `error.message` envelope and `error.details` were
discarded. `binaryError()` already handled this correctly; `request()` did not.

**Fix** Shared `errorMessage()` that handles the string form, the validation array
(rendered as `latex_content: Field required`), and the `{error:{message}}` envelope.
Both paths now use it.

---

## Moderate

### 6. Documented headless invocations could not work

**Where** `src/headless.ts:138`

The `.tex` path was located with `args.find(a => !a.startsWith('-'))`, which cannot
distinguish a positional from a **flag's value**.

**Evidence**
```
$ latexy compile --compiler xelatex probe.tex --json
Compiling xelatex…
{"success":false,"error":"Error: ENOENT: no such file or directory, open 'xelatex'"}
```
Worse, with `--output` pointing at an existing file, that file was read as LaTeX
source and submitted as a job:
```
$ latexy compile --output b.pdf probe.tex --json     # b.pdf existed
Compiling b.pdf…
Job submitted: edf844e4-…
{"success":false,"error":"Invalid LaTeX: missing \\documentclass…"}
```
A binary PDF was uploaded as a compile job — a real, quota-charged submission.

**Fix** `parseHeadlessArgs()` knows which flags take values. Verified: `--compiler
xelatex` now returns `"compiler":"xelatex"` from the server, in any argument order.

### 7. `/compile` ignored both the saved default and the picker

**Where** `src/tools/compile.ts:79`

It called `/resumes?limit=1` and compiled whichever resume sorted first, rather than
using `resolveResumeId` like every other command.

**Evidence** With `defaultResumeId` set to resume B, `/resumes?limit=1` returned
resume A — so the most-used command in the TUI silently built a different document
than the one the user selected, with nothing on screen saying which.

**Fix** Uses `resolveResumeId`. The tool card now carries the resolved `resume_id`.

### 8. The resume chosen in `/list` was written and never read

**Where** `src/tools/shared.ts:49`, `src/components/overlays/ResumePicker.tsx:62`

`ResumePicker` has always persisted `defaultResumeId`. Nothing ever read it back —
including `resolveResumeId`, whose own doc comment claimed *"explicit id → saved
default → picker"*.

**Evidence** Wrote the default, confirmed it on disk, called `resolveResumeId` — the
picker opened anyway.

**User impact** Selecting a resume in `/list` did nothing. Every subsequent command
asked again.

**Fix** The default is honoured when it still resolves; a deleted one falls back to
the picker rather than wedging every command behind a 404.

### 9. Streamed AI output could be left rendering as in-progress forever

**Where** `src/hooks/useJobStream.ts:52`

`onLLMToken` schedules a 16ms flush. If completion arrived first, `llmMsgId` was
still null, so `onComplete`'s `streaming: false` had nothing to apply to — and the
timer then **created** the message with `streaming: true`. The timer also kept the
event loop alive.

**Evidence** `probe-lifecycle`: token then immediate completion leaves exactly one
message with `streaming === true` after the job has finished.

**Fix** `flushLLM()` writes buffered text and clears the timer on complete/failed/
cancelled.

### 10. Resumes beyond the first 50 were unreachable, silently

**Where** `src/tools/shared.ts:58`, `ResumePicker.tsx:38`

Both fetched `limit=50` and neither said so when the account had more.

**Evidence** Test account with 57 resumes: the listing returned 50 and the fixture
resume was **not in the window** — so its saved default was silently discarded, and
it could not be picked from `/list` either. No message; the list simply looked
complete.

**Fix** `RESUME_PAGE = 200`, the overlay title reports `showing N of M`, and a default
outside the page is confirmed by direct fetch rather than dropped. *Partial* — see
Remaining below.

### 11. The resume picker overflowed the terminal

**Where** `ResumePicker.tsx:95` — `filtered.map(...)` with no windowing, while
`SelectOverlay` windowed to 10.

**Evidence** 43 resumes at 100x30: a **54-line live frame in a 30-row terminal**. The
title, filter field and cursor row all scrolled off. Because the frame exceeded the
terminal height Ink could not erase in place, so **one keystroke re-emitted 129 lines
/ 2 full frames** — the screen lurched on every character typed.

**Fix** Windowed, and then sized to the terminal (`useOverlaySize`), after the first
fix still overflowed at 60x20 with a hardcoded `WINDOW = 10` and `width={60}`.

### 12. Pasted commands were never submitted

**Where** `src/components/PromptInput.tsx:61`

A pasted command arrives as one chunk including its newline; `ink-text-input` treats
`\r` as an ordinary character.

**Evidence** A single write of `/health\r` inserted a literal newline, grew the box
to two lines, and ran nothing:
```
│ ❯ /health
                                                          │
```

**Fix** `handleChange` splits on **all** newlines and submits every complete line.
(The first attempt consumed only the first newline and relapsed on a two-command
paste — caught on re-verification and fixed.)

### 13. Ctrl+L leaked a literal `l` into the prompt

**Where** `AppShell.tsx:33` + `PromptInput.tsx`

`AppShell`'s `useInput` consumed Ctrl+L to clear the transcript, but `ink-text-input`
received the same keypress and appended the character.

**Evidence** Fresh session, Ctrl+L only → `│ ❯ l │`

**Fix** Handled at the `useInput` layer in `PromptInput`. **My first fix was a
no-op** — I stripped C0 control bytes in `onChange`, but Ink normalises `0x0C` into
`input='l'` + `key.ctrl` *before* `onChange` runs, so there was no control byte left
to strip. Caught on re-verification.

### 14. Typing `/` showed no command menu

**Where** `PromptInput.tsx:47` — `isSlash && value.length > 1`

The welcome banner and the hint line both say *"Type / to see available commands"*.
Typing exactly `/` showed nothing.

**Fix** Gate removed. Verified the 7-item list fits in both 30-row and 20-row
terminals.

---

## Minor

| # | Defect | Evidence | Fix |
|---|---|---|---|
| 15 | `/compile` told unauthenticated users to run `/login` — never a registered command | `SLASH_COMMANDS` has no `login`; `compile.ts:24` printed it | uses `requireAuth()` |
| 16 | Picker never drew the type label or the ★ | code read `type`/`is_pinned`; API returns `document_type`/`pinned` | renamed; type labels now render |
| 17 | Backend down → `TypeError: fetch failed` | `/health` with no backend | `describeError` names the host and the code |
| 18 | Every command took ~3s to admit the backend was down | idempotent GETs retried a refused connection twice with backoff | fast-fail on `ECONNREFUSED`/`ENOTFOUND`, incl. dual-stack `AggregateError`; 9 commands now fail in 2.3s total |
| 19 | 401 discarded the server's wording | hardcoded `'Unauthorized'` | uses the server message |
| 20 | `report()` rendered a bare heading over a blank body | all-empty rows | prints `(nothing to show)` |
| 21 | `latexy --json` printed the literal text `undefined` | `{"error":"Unknown subcommand: undefined…"}` | prints usage |
| 22 | 9 commands badged `local` in autocomplete while making REST calls | `isLocal` vs `API_HANDLERS` | reclassified; the e2e test had pinned the wrong values |
| 23 | 6 commands described as opening overlays only print static text | `/jobs` "Open job monitor overlay" renders a transcript message | descriptions and usage strings corrected |
| 24 | `/co` ranked `/share` above `/compile` | description matched "copy share link" | name matches rank first |
| 25 | `/checkpoint` hit the 20 cap with no way to delete one | server says "Delete older ones first"; no TUI command could | added `/checkpoint --delete` over the existing endpoint |
| 26 | Auth failures rendered as bare `Forbidden` | Better Auth puts its reason in a top-level `message`, which `errorMessage()` did not read | reads it; the login prompt now says what was wrong |
| 27 | Ctrl+L also leaked its letter into the overlays' filter boxes | `Ctrl+L` with the picker open → `Filter: l` | the guard is now a shared hook used by the prompt and both overlays |

Dead scaffolding removed: `MessageRole` `ats_result` and `resume_list` were produced
by zero code paths and had no branch in `MessageRow` — they would have rendered as
the literal placeholder `[ats_result]`.

---

## Regression introduced by this round's own fixes

**`/cancel` threw before reaching the server when the state body was not an object.**
My fix for #3 read `state.status` directly; a non-object response made it throw, and
the cancellation never happened. Caught by the existing `dispatch.e2e` mocks within
minutes of writing it. Fixed with optional chaining.

Measured rate this round: **1 regression per 27 fixes**, against roughly 1-in-7 in
prior rounds. Two further mistakes were caught before they shipped — the no-op Ctrl+L
fix (#12) and the single-newline paste fix (#11) — both by adversarial re-verification
rather than by me.

---

## Attacked and could not be broken

- **Concurrency.** Three `/compile` commands dispatched *simultaneously* produced
  **exactly one** job on the server, with the other two reporting "already running".
  The round-3 check-then-act fix holds.
- **`/edit` data loss.** Seven hostile editors — truncate-then-exit-3, SIGKILL after
  truncating, clean exit over an emptied buffer, latin-1 output, temp file deleted
  mid-edit, `$EDITOR` with arguments, unchanged file. **The resume survived every
  one**, and none reported "Saved".
- **API response shapes.** ~30 endpoints probed live and compared field-by-field
  against what the handlers read. Only the four defects above were mismatches;
  everything else matched, including the `by_status` tracker grouping, the
  `quotas.dimensions` nesting, `export/formats`' `key` field, the `{original_latex,
  optimized_latex}` checkpoint payload, and the float-epoch `created_at` that
  `formatAge` handles. `GET /resumes?limit=1` (no trailing slash) 307-redirects and
  Node's fetch preserves the Authorization header.
- **`/help` parity.** The rendered list was extracted from a pty and diffed against
  `registry.ts` — identical, zero drift.
- **Long transcripts.** `TranscriptView` wraps settled messages in Ink `<Static>`, so
  a 62-line `/help` in a 20-row terminal scrolls into real scrollback with the prompt
  anchored. Correct.
- **Resize.** 100x30 → 80x40 mid-session with an overlay open: reflowed once, no
  duplication.

---

## Findings that dissolved under testing — recorded so they are not re-filed

- **"`/edit` destroys the resume when the editor is killed"** — the suite failed only
  because `LATEXY_FIXTURES` was unset, so it spawned `/ed_fail.sh` at the filesystem
  root. With fixtures present all three cases pass. The suite now asserts its own
  precondition instead of failing as though the code were broken.
- **"Ctrl+C still hangs mid-job after the fix"** — pty harness artifact: the child
  had already exited (state `Z`) and the waiter broke out on `EIO` without reaping.
  Real measurement: 0.01s.
- **"Every component is unreferenced"** — a zsh globbing error in the search, not a
  finding. All 14 components are reachable.
- **"`/checkpoint` is broken"** — the 20-per-resume cap, correctly enforced and
  correctly reported, reached after repeated audit runs. The test now prunes first.
- **Two live suites appearing to break each other's resume** — both used
  `LATEXY_TEST_RESUME` and vitest runs files in parallel. Split onto separate
  resumes.

---

## Remaining, not fixed

1. **Picker filtering is client-side.** Beyond `RESUME_PAGE` (200) resumes, older
   ones are still unreachable and the filter cannot find them. The count is now
   honest about it; real pagination or server-side search is the actual fix.
2. **`activeModel` / `activeProvider` in `LatexyConfig` are never read or written.**
   `/model` lists providers but persists nothing. Intended for #1095 — left in place
   deliberately, flagged here.
3. **`/logout` reports success while `LATEXY_SESSION_TOKEN` is set.** Env overrides
   the file by design, so the user stays signed in on next start.
4. **Headless mode supports only `compile`.** 31 other commands are TTY-only.
5. **Status bar fields run together at 60 columns** (`⬡ Latexypro tui-audit4@…`).
   Cosmetic; pre-existing.
6. **A hard minimum terminal size of roughly 50x16.** The overlay now fits 100x30
   exactly and overflows 80x24 and 60x20 by only 1–3 lines — costing the status bar,
   not the list. But at **40x12 the frame is 77 lines against 12**, and that is
   *horizontal*: at 40 columns the box clamps to ~28 and every row, the footer and
   the hint wrap two or three ways. No row count can recover 65 lines; it needs a
   compact layout for narrow terminals. Documented rather than claimed fixed.
7. **Ctrl+I inserts a literal tab** — it is byte-identical to Tab, and the strip
   regex deliberately preserves `\t`. Cosmetic, pre-existing.
6. **The published npm package (1.0.2) predates PR #1075**, so a fresh
   `npx @sanskarpan/latexy` today still has all 25 phantom commands and the `/edit`
   data-loss path, plus everything above. **Nothing in this audit reaches users until
   a release is cut.**

---

## Coverage

| | |
|---|---|
| Commands routed | 32 / 32 |
| Commands exercised against a live backend | 32 |
| Endpoints probed and diffed against handler expectations | ~30 |
| Tests | **220 passing** (154 no-backend, 66 live), from 186 |
| | 215 + 5 skipped when the Next.js app is down — the sign-in suite needs both origins and skips with a reason rather than failing |
| Suite stability | 3 consecutive clean runs |
| Overlays/cards rendered in a real pty | boot, suggestions, `/help`, both overlays, error rows, transcript, status bar |
| Terminal geometries | 100x30, 80x40, 60x20, 40x12, plus live resize |
| Error codes covered | 400, 401, 404, 422, 500-retry, connection-refused, timeout, abort |
| Defects found | 27 (5 severe, 9 moderate, 13 minor) |
| Fixed | 27 |
| Regressions introduced and fixed | 1 |

### Keyboard behaviour has no automated regression test

`ink-testing-library@4` does **not deliver keystrokes** to Ink 5 in this setup. A
minimal `useInput` probe that appends every character received renders `[]` after
two writes to `stdin`, with and without `CI` set:

```
FRAME: "[]"      // expected "[ab]"
```

So the keyboard fixes (#12 paste, #13 Ctrl+L, #14 bare `/`) are verified **only in
the pty harness**, by hand, per change. That is why the Ctrl+L fix shipped wrong
twice before it was right. Either the testing library needs upgrading to something
Ink-5-compatible, or the pty harness should be committed as a test fixture. Until
then this is the least-protected area of the package.

### What this does *not* cover

- **Real LLM output.** No BYOK credits were spent, so `/optimize`, `/combined`,
  `/ats` and `/cover` were verified as far as **job submission and event streaming**.
  The token-streaming path was exercised with synthetic `llm.token` events, not a
  real model.
- **A real `$EDITOR` session.** `/edit` was driven with scripted editors. No
  interactive vim/VS Code session was tested.
- **Modal production runtime.** Everything ran against a local backend on
  `localhost:8030`. Behaviour under Modal's scheduling and cold starts is untested.
- **`npx` and global install.** Tested via `node dist/cli.js`. The published-package
  path (bin shim, shebang, engine constraint) was not re-tested.
- **Windows and non-UTF-8 terminals.**

### Honest summary

> 220 tests pass, 66 of them against a real backend, worker, Postgres and Redis
> (215 with the Next.js app stopped; the sign-in suite skips explicitly).
> All 32 commands are routed and produce substantive output; each was run against a
> live server and asserted on meaning, not just absence of garbage. Concurrency,
> `/edit` data loss and API field mapping were attacked specifically and held.
> Rendering was verified in a real pty across five terminal geometries.
> Not covered: real LLM generation, interactive editors, the Modal runtime, and the
> published package.

The claim *"all 32 commands work"* was made twice before in this project and was
wrong both times. It is not being made here.
