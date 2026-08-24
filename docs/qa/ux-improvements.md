# Latexy — UX Audit & Improvement Backlog

> Deep UX review across all public + authenticated surfaces (Aug 2026). **126 findings** — **23 high, 62 medium, 41 low** (56 bugs, 70 improvements). Produced by a 7-surface parallel audit; each item lists type, severity, location, the problem, and a concrete fix.

| Area | Findings | High |
|---|---|---|
| Templates & Preview | 17 | 4 |
| Workspace & Resumes | 29 | 6 |
| Résumé Studio (/try) | 7 | 1 |
| Auth & Onboarding | 14 | 2 |
| Dashboard, Tracker & Cover Letters | 15 | 2 |
| Billing, BYOK, Settings & Developer | 20 | 4 |
| Global / Cross-cutting | 21 | 2 |
| Other | 3 | 2 |

## ✅ Status (verified 2026-08-24 against `main`)

Every finding — **High (P0)**, **Medium (P1)**, and **Low (P2)** — was re-checked against the current code. Each item below carries a `**Status:**` line.

| Severity | Total | ✅ Fixed | 🟡 Partial | 🔴 Open |
|---|---|---|---|---|
| High (P0) | 23 | 23 | 0 | 0 |
| Medium (P1) | 62 | 62 | 0 | 0 |
| Low (P2) | 41 | 41 | 0 | 0 |
| **All** | **126** | **126** | **0** | **0** |

Every audit finding is resolved. The seven P0/P1 items that were Partial/Open at the 2026-08-24 verification (AI-optimize diff/revert on `/try`, `/try` streaming scroll-jerk, Tracker within-column reorder, Dashboard chart tooltips, data-sourced changelog, theme toggle on the workspace fullscreen surfaces, and footer legal links) and the six remaining P2 items (clickable Recent Activity, themed GitHub/Dropbox confirm, account-synced onboarding + theme, flash-free ModeToggle, and readability of the editor micro-copy) were completed in the follow-up passes.

## 🔴 Top priority — all high-severity items

1. **[Templates & Preview] LaTeX Source view has no copy button** — The 'LaTeX Source' tab renders the full template code in a <pre> block with no way to copy it. A user who wants to grab the LaTeX (e.g. to paste into their own editor or an externa… _Fix:_ Add a 'Copy' button in the top-right of the LaTeX Source panel that writes template.latex_content to navigator.clipboard and shows a transie
2. **[Templates & Preview] Preview affordance is hover-only and invisible on touch devices** — The 'Preview' button sits in an overlay with opacity-0 that only appears on group-hover / group-focus-within. On touch devices there is no hover state, so the Preview button is eff… _Fix:_ Make the whole thumbnail area a button/clickable that calls onPreview, and/or render the Preview button always-visible (not opacity-0) at le
3. **[Templates & Preview] Cross-origin PDF is wrongly marked failed by the HEAD probe, hiding a valid PDF** — Before showing the PDF, the modal does a fetch(pdf_url, {method:'HEAD'}). If pdf_url lives on a different origin (S3/MinIO/CDN) without permissive CORS, the fetch throws and the ca… _Fix:_ Don't gate the iframe on a HEAD probe. Render the iframe optimistically and only fall back to LaTeX on a real load failure, or make the prob
4. **[Templates & Preview] Preview modal is not an accessible dialog (no role, no focus trap, no focus restore)** — The modal is a plain div with only Escape handling. It has no role="dialog", aria-modal, or aria-labelledby; focus is never moved into the modal on open, Tab is not trapped (keyboa… _Fix:_ Add role="dialog" aria-modal="true" aria-labelledby pointing at the title, move focus to the modal (or close button) on open, trap Tab withi
5. **[Workspace & Resumes] Cover-letter delete is instant with no confirmation** — Both the grid and list 'Delete' buttons call handleDelete(cl.id) directly, permanently deleting the cover letter after one click with only a toast. No confirmation dialog and no un… _Fix:_ Add a confirmation step (modal or two-step inline confirm) and/or an 'Undo' action toast. Consistency with a shared ConfirmDialog across del
6. **[Workspace & Resumes] No compile keyboard shortcut — onCompile/onSave never wired into the editor** — LaTeXEditor supports ⌘↵ compile and ⌘S save via the onCompile/onSave props, but /try passes neither. For an Overleaf-style IDE this is a glaring miss: the only way to compile is to… _Fix:_ Pass onCompile={() => runCompile('compile')} to LaTeXEditor so ⌘↵ triggers a compile from anywhere in the editor. Consider a ⌘S binding that
7. **[Workspace & Resumes] No unsaved-changes guard — editor work is silently lost on navigation** — The editor persists only on an explicit Save click (or optional auto-compile, which is NOT a save). There is no beforeunload handler and no route-change guard. If a user edits LaTe… _Fix:_ Track a dirty flag (compare editor value/title to last-saved snapshot) and (a) add a window 'beforeunload' listener that warns when dirty, (
8. **[Workspace & Resumes] List view drops most card actions (Archive, Pin, Tags, Share, Translate, Portfolio, Apply, Track are unreachable)** — Grid cards expose a MoreHorizontal overflow menu with ~13 actions including Archive (the only delete-equivalent), Pin, Edit tags, Share, Translate, Portfolio, Apply, Track applicat… _Fix:_ Reuse the same overflow (…) menu component in the list row's actions cell so grid and list expose identical actions; keep only the top 2 pri
9. **[Workspace & Resumes] Pressing Enter in the title field silently creates a BLANK resume even in Template mode** — The title <input> has onKeyDown Enter → handleCreate. In template mode handleCreate falls through to the else branch and creates a blank-content resume, then navigates away. A user… _Fix:_ In template mode, Enter in the title field should be a no-op (or focus the template search), not trigger blank creation. Only bind Enter→cre
10. **[Workspace & Resumes] Live ATS score badge shows stale score — never reflects edits or optimization output** — The editor's onChange is a no-op and `resume` state is set once on load and never updated. The quick ATS score is computed from `resume?.latex_content` (the originally loaded conte… _Fix:_ Lift editor content into state (wire onChange to a setter) and feed the current content into useQuickATSScore, or recompute the quick score 
11. **[Résumé Studio (/try)] No persistence or beforeunload guard — a page reload silently destroys all work** — latexContent lives only in React state, initialized to DEMO_RESUME_TEMPLATE. There is no localStorage persistence, no autosave, and no 'window.beforeunload' handler. An anonymous u… _Fix:_ Debounce-persist latexContent (and jobDescription) to localStorage and rehydrate on mount; add a beforeunload handler that warns when the bu
12. **[Auth & Onboarding] Onboarding 'pick a starting point' cards are dead, non-interactive** — The final onboarding step tells the user 'Pick a starting point below' and 'Pick how you want to start', then renders three prominent option Cards — 'Use a template', 'Import a res… _Fix:_ Make each card a real button/link that (a) sets a query intent and (b) closes onboarding and navigates: 'Use a template' -> /templates, 'Imp
13. **[Auth & Onboarding] Post-auth redirect is hardcoded to /workspace, deep links are lost** — Both forms do `window.location.href = '/workspace'` on success and never read a `redirect`/`callbackURL`/`next` query param. A user who hits a protected deep link (e.g. /workspace/… _Fix:_ Read a `redirect` (or `callbackURL`) search param, validate it is a same-origin relative path (must start with '/', reject '//' and absolute
14. **[Dashboard, Tracker & Cover Letters] Deleting an application has no confirmation and no undo** — The overflow-menu 'Delete' calls handleDelete(app.id) immediately, which optimistically removes the card and fires apiClient.deleteApplication with only a success toast. A single m… _Fix:_ Gate the delete behind a confirmation dialog (or at minimum an inline 'Are you sure?' in the menu), and/or make the toast an actionable 'Und
15. **[Dashboard, Tracker & Cover Letters] Kanban is unusable on touch / keyboard — no drag alternative and hover-only actions** — Two compounding issues: (1) DndContext registers only PointerSensor, so there is no KeyboardSensor — the entire status workflow (move card between columns) is impossible via keyboa… _Fix:_ Add @dnd-kit's KeyboardSensor with sortableKeyboardCoordinates and a visible status-change control (e.g. the status <select> from the edit m
16. **[Billing, BYOK, Settings & Developer] "Show" key button is a dead affordance — it never reveals the key** — Each stored key has a Show/Hide toggle. Clicking "Show" only swaps the literal string 'hidden' for a fixed run of bullet dots '•••••••••••••••••••••••••••••'. It never displays any… _Fix:_ Either remove the Show/Hide control entirely (keys are write-only by design), or have it fetch and display a safe masked preview from the ba
17. **[Billing, BYOK, Settings & Developer] One-time-shown API key has no Copy button** — After creating a developer key, the full secret is rendered in a <code> block with the warning 'Copy this key now — it will never be shown again', but there is no copy button. The … _Fix:_ Add a 'Copy' button next to the key that calls navigator.clipboard.writeText(createdKey.full_key) with a success toast/checkmark. Also add a
18. **[Billing, BYOK, Settings & Developer] Enabling 'Browser notifications' never requests notification permission** — The Desktop Notifications toggle only flips local state and calls setNotificationPref(next) into localStorage. It never calls Notification.requestPermission(). If the browser permi… _Fix:_ When toggling ON, if Notification.permission === 'default' call Notification.requestPermission() and reflect the result. If the user denies,
19. **[Billing, BYOK, Settings & Developer] Coupon is validated only against Pro but applied to any plan at checkout** — handleApplyCoupon always validates the entered coupon against a hardcoded 'pro'/'pro_annual' target, yet the resulting appliedCoupon.code is passed to createSubscription for whiche… _Fix:_ Validate the coupon against the plan the user is actually purchasing (validate at plan-select time, or re-validate against the chosen plan b
20. **[Global / Cross-cutting] No skip-to-content link — keyboard users tab through full nav on every page** — The root layout (src/app/layout.tsx) renders GlobalHeader before <main>, but <main> has no id and there is no skip link. Keyboard and screen-reader users must tab through the logo,… _Fix:_ Add a visually-hidden-until-focused anchor as the first child of <body>: <a href="#main-content" class="sr-only focus:not-sr-only ...">Skip 
21. **[Global / Cross-cutting] No themed error.tsx / global-error.tsx — runtime errors show Next's unstyled default** — Only not-found.tsx is themed. There is no app/error.tsx or app/global-error.tsx, so any client-side render error drops the user onto Next.js's default bare error page with no brand… _Fix:_ Add app/error.tsx (route-level) and app/global-error.tsx (root) mirroring not-found.tsx's token-based styling, with a 'Try again' button wir
22. **[Other] Optimize streams overwrite the live editor with no read-only lock and constant scroll-jerk** — During an optimize job, the streamingLatex effect calls editorRef.setValue(...) on every token, and LaTeXEditor.setValue() also revealLine(getLineCount()) each time — so the editor… _Fix:_ Pass readOnly={isProcessing} while a job runs so the buffer is locked and clearly labeled. Avoid revealLine on streaming updates (only revea
23. **[Other] AI optimization is destructive: no diff, no per-change accept/reject, no revert to original** — When optimize completes, the new LaTeX fully replaces the editor content and the original is gone (only Monaco undo could recover it). The 'changes applied' list (lines 466-490) is… _Fix:_ Snapshot the pre-optimize content and offer a 'Revert' button plus a diff view (original vs optimized). At minimum, surface a toast/badge po

## Full findings by area

### Templates & Preview (17)

#### 🔴 High · 🐛 Bug — LaTeX Source view has no copy button
- **Where:** `src/components/TemplatePreviewModal.tsx:244-248` · route `/templates`
- **Problem:** The 'LaTeX Source' tab renders the full template code in a <pre> block with no way to copy it. A user who wants to grab the LaTeX (e.g. to paste into their own editor or an external Overleaf) has to manually text-select from a scrollable region where the text is also broken mid-token (see break-all finding). This is the single most expected affordance for a source-code view and it's entirely missing.
- **Fix:** Add a 'Copy' button in the top-right of the LaTeX Source panel that writes template.latex_content to navigator.clipboard and shows a transient 'Copied' state / toast. Optionally add a keyboard hint.
- **Status:** ✅ Fixed

#### 🔴 High · 🐛 Bug — Preview affordance is hover-only and invisible on touch devices
- **Where:** `src/components/TemplateCard.tsx:66-75` · route `/templates`
- **Problem:** The 'Preview' button sits in an overlay with opacity-0 that only appears on group-hover / group-focus-within. On touch devices there is no hover state, so the Preview button is effectively invisible and the thumbnail itself is not tappable. Mobile users literally cannot preview a template before using it — a core flow is unreachable on phones/tablets.
- **Fix:** Make the whole thumbnail area a button/clickable that calls onPreview, and/or render the Preview button always-visible (not opacity-0) at least on coarse-pointer devices via a @media (hover: none) rule.
- **Status:** ✅ Fixed

#### 🔴 High · 🐛 Bug — Cross-origin PDF is wrongly marked failed by the HEAD probe, hiding a valid PDF
- **Where:** `src/components/TemplatePreviewModal.tsx:93-102` · route `/templates`
- **Problem:** Before showing the PDF, the modal does a fetch(pdf_url, {method:'HEAD'}). If pdf_url lives on a different origin (S3/MinIO/CDN) without permissive CORS, the fetch throws and the catch sets pdfFailed=true — even though an <iframe> (which does NOT require CORS) would have rendered the PDF perfectly. Result: templates with a valid but CORS-restricted PDF always fall back to LaTeX source and the PDF Preview tab is disabled, so users never see the rendered preview.
- **Fix:** Don't gate the iframe on a HEAD probe. Render the iframe optimistically and only fall back to LaTeX on a real load failure, or make the probe treat a network/CORS error (as opposed to a definitive 404) as inconclusive rather than failed.
- **Status:** ✅ Fixed

#### 🔴 High · ✨ Improvement — Preview modal is not an accessible dialog (no role, no focus trap, no focus restore)
- **Where:** `src/components/TemplatePreviewModal.tsx:124-132` · route `/templates`
- **Problem:** The modal is a plain div with only Escape handling. It has no role="dialog", aria-modal, or aria-labelledby; focus is never moved into the modal on open, Tab is not trapped (keyboard/screen-reader users can tab into the page behind it), and focus is not returned to the triggering card button on close. Background page scroll is also not locked. This is a significant accessibility and focus-management gap.
- **Fix:** Add role="dialog" aria-modal="true" aria-labelledby pointing at the title, move focus to the modal (or close button) on open, trap Tab within the modal, restore focus to the trigger on close, and lock body scroll while open.
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — Using a template while logged out silently bounces to /login with no context or return
- **Where:** `src/app/templates/page.tsx:89-94` · route `/templates`
- **Problem:** handleUseTemplate does router.push('/login') when there's no session, with no toast explaining why and no redirect-back parameter. The user clicks 'Use Template', gets teleported to a login screen with no explanation, and after logging in lands on the default post-login page — losing both the template they picked and their place on the Templates page.
- **Fix:** Show a toast like 'Sign in to use templates' and push to /login with a returnTo/callbackUrl that brings them back to /templates (ideally re-opening or auto-using the chosen template) after authentication.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — No way to download the PDF or the .tex file from the preview
- **Where:** `src/components/TemplatePreviewModal.tsx:255-271` · route `/templates`
- **Problem:** The preview modal only offers Cancel and 'Use This Template'. There's no Download PDF and no Download .tex option, even though both pdf_url and latex_content are available. Users who want to inspect the template offline, or grab the source without creating a workspace resume, have no path.
- **Fix:** Add Download buttons (or a small menu) in the modal footer: 'Download PDF' (anchor to pdf_url with download attr) and 'Download .tex' (Blob from latex_content). Consider an 'Open in Studio' link too.
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — Creating from one template disables the Use button on every other card
- **Where:** `src/app/templates/page.tsx:217 / src/components/TemplateCard.tsx:94-96` · route `/templates`
- **Problem:** disabled is passed as usingTemplateId !== null, so while one template is being created ALL 'Use Template' buttons across the grid go greyed/disabled. To a user this reads as the whole page breaking, not as a targeted in-flight action (which is already communicated by the 'Creating…' overlay on the active card).
- **Fix:** Only disable the button on the card that is actively creating (disabled={usingTemplateId === template.id}); leave the rest interactive, or queue subsequent clicks instead of disabling everything.
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — LaTeX source uses break-all, shredding commands mid-token
- **Where:** `src/components/TemplatePreviewModal.tsx:245` · route `/templates`
- **Problem:** The source <pre> uses whitespace-pre-wrap break-all, which breaks lines at arbitrary character boundaries — so \documentclass, \textbf, URLs, etc. get split across lines mid-word. This makes the LaTeX hard to read and, combined with the missing copy button, error-prone to hand-select. Code should preserve token boundaries.
- **Fix:** Use overflow-x-auto with whitespace-pre (horizontal scroll) or at minimum break-words instead of break-all so LaTeX commands stay intact; a monospace font would also help readability.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — Preview modal doesn't stack on mobile — fixed 208px sidebar starves the preview
- **Where:** `src/components/TemplatePreviewModal.tsx:172-202` · route `/templates`
- **Problem:** The modal body is a horizontal flex with a fixed w-52 (208px) metadata sidebar next to the preview, with no responsive breakpoint. On a narrow phone the sidebar consumes most of the width, leaving the PDF/LaTeX preview crammed into a sliver. The metadata should stack above the preview on small screens.
- **Fix:** Make the body flex-col on small screens (flex-col md:flex-row) with the metadata as a collapsible/top section, and let the preview take full width below it on mobile.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — Thumbnail and title aren't clickable to preview — only a small hover button is
- **Where:** `src/components/TemplateCard.tsx:47-90` · route `/templates`
- **Problem:** Only the tiny hover-revealed 'Preview' button opens the preview. Clicking the thumbnail image or the template name does nothing, which violates the common expectation that clicking a gallery item opens it. Combined with the hover-only button, discoverability of Preview is poor even on desktop.
- **Fix:** Make the thumbnail (and optionally the title) trigger onPreview on click, keeping the explicit Preview button as reinforcement. Add cursor-pointer and appropriate aria-label/role.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — 'Use This Template' in modal closes instantly with no in-modal feedback
- **Where:** `src/components/TemplatePreviewModal.tsx:264-269` · route `/templates`
- **Problem:** Clicking 'Use This Template' calls onUse then onClose synchronously, so the modal vanishes immediately. The creating state ('Creating…' overlay) then appears back on the grid card the user may no longer be looking at, and if they're logged out they get yanked to /login with the modal gone. There's no confirmation or spinner in the modal itself during the action.
- **Fix:** Keep the modal open and show a loading/disabled state on the button while useTemplate is in flight, then close on success (and navigate); on the logged-out path, surface the sign-in prompt before dismissing the modal.
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — Template thumbnails look selectable but every one just navigates away to /templates
- **Where:** `frontend/src/app/try/page.tsx:562-575` · route `/try`
- **Problem:** The Templates tool renders four labeled thumbnails (Minimal, Two-column, Academic, ATS-safe) styled as clickable cards inside the studio. A user reasonably expects clicking 'Minimal' to apply that template to the current editor. Instead all four are Links to /templates, yanking the user out of the studio (and discarding unsaved editor content, per the persistence bug). This is a misleading affordance.
- **Fix:** Make each thumbnail apply its template into the editor in place (editorRef.setValue) with a replace-content confirmation, or clearly relabel the section as 'Browse templates →' so it doesn't read as an in-place picker.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Disabled 'PDF Preview' tab gives no reason why it's unavailable
- **Where:** `src/components/TemplatePreviewModal.tsx:208-221` · route `/templates`
- **Problem:** When pdfFailed is true the PDF Preview tab is rendered disabled/greyed, but there's no tooltip, helper text, or label explaining that a rendered PDF isn't available for this template. The user just sees a dead, greyed tab and has to guess.
- **Fix:** Add a title/tooltip or small 'PDF unavailable' caption on the disabled tab, or hide the PDF tab entirely when no PDF exists and default cleanly to LaTeX Source.
- **Status:** ✅ Fixed

#### 🟡 Low · 🐛 Bug — Marketing category badge is arbitrarily highlighted in accent while all others are neutral
- **Where:** `src/components/TemplateCard.tsx:11-24` · route `/templates`
- **Problem:** In the card's CATEGORY_STYLES map every category resolves to the neutral surface style except 'marketing', which is given accent (bg-accent-soft / text-accent-strong / border-accent). This makes marketing template badges stand out for no semantic reason and looks like a copy/paste leftover — visually inconsistent across the grid.
- **Fix:** Make all category badges consistent (all neutral, or give every category a deliberate distinct color). Remove the special-case accent for 'marketing' unless it's intentional and applied system-wide.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Result count and empty state aren't announced to screen readers
- **Where:** `src/app/templates/page.tsx:159-161` · route `/templates`
- **Problem:** The 'N templates' count and the 'No templates found' empty state update live as the user types in search or switches category, but neither is in an aria-live region, so screen-reader users get no feedback that filtering changed the results.
- **Fix:** Wrap the count (and empty-state message) in an aria-live="polite" region so filter results are announced as the user searches/filters.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Search doesn't match category label and there's no keyboard shortcut to focus it
- **Where:** `src/app/templates/page.tsx:65-72` · route `/templates`
- **Problem:** Client-side search matches name, description, and tags but not category_label, so typing e.g. 'finance' won't match a finance-labelled template unless the word also appears in its metadata. There's also no '/' or Cmd+K shortcut to focus the search field, which is standard for a browse/gallery surface.
- **Fix:** Include t.category_label in the search predicate, and add a keyboard shortcut (e.g. '/') that focuses the search input.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Redundant/dead CATEGORY_STYLES map in the preview modal
- **Where:** `src/components/TemplatePreviewModal.tsx:14-29` · route `/templates`
- **Problem:** Every entry in the modal's CATEGORY_STYLES (plus DEFAULT_STYLE) maps to the identical ACCENT_CHIP object, so the entire lookup is dead weight and the per-category style variable never changes. It signals unfinished design intent (categories were presumably meant to be color-coded) and adds maintenance noise.
- **Fix:** Either remove the map and use ACCENT_CHIP directly, or actually implement distinct per-category colors so the abstraction earns its place (and keep it consistent with the card's badge colors).
- **Status:** ✅ Fixed


### Workspace & Resumes (29)

#### 🔴 High · 🐛 Bug — Cover-letter delete is instant with no confirmation
- **Where:** `src/app/workspace/cover-letters/page.tsx:46 (handleDelete), grid button L195, table button L254` · route `/workspace/cover-letters`
- **Problem:** Both the grid and list 'Delete' buttons call handleDelete(cl.id) directly, permanently deleting the cover letter after one click with only a toast. No confirmation dialog and no undo affordance for a destructive action.
- **Fix:** Add a confirmation step (modal or two-step inline confirm) and/or an 'Undo' action toast. Consistency with a shared ConfirmDialog across delete actions would also help.
- **Status:** ✅ Fixed

#### 🔴 High · 🐛 Bug — No compile keyboard shortcut — onCompile/onSave never wired into the editor
- **Where:** `frontend/src/app/try/page.tsx:590-601; frontend/src/components/LaTeXEditor.tsx:1316-1318` · route `/try`
- **Problem:** LaTeXEditor supports ⌘↵ compile and ⌘S save via the onCompile/onSave props, but /try passes neither. For an Overleaf-style IDE this is a glaring miss: the only way to compile is to reach for the mouse and click 'Recompile'. Power users expect ⌘↵. The status bar even conditionally advertises '⌘↵ compile' but it is suppressed here because onCompile is falsy, so the feature is simply absent.
- **Fix:** Pass onCompile={() => runCompile('compile')} to LaTeXEditor so ⌘↵ triggers a compile from anywhere in the editor. Consider a ⌘S binding that triggers compile (or persist-to-local) rather than doing nothing.
- **Status:** ✅ Fixed

#### 🔴 High · 🐛 Bug — No unsaved-changes guard — editor work is silently lost on navigation
- **Where:** `frontend/src/app/workspace/[resumeId]/edit/page.tsx (handleSave ~1378; header breadcrumb Link ~1839; no beforeunload)` · route `/workspace/[resumeId]/edit`
- **Problem:** The editor persists only on an explicit Save click (or optional auto-compile, which is NOT a save). There is no beforeunload handler and no route-change guard. If a user edits LaTeX or the title and then clicks the 'Workspace' breadcrumb, opens Cover Letter/Career links, or closes the tab, all changes are discarded with zero warning. Auto-compile can even show a freshly compiled PDF for content that was never saved, reinforcing a false sense of safety. The same gap exists on the optimize and cover-letter sub-pages.
- **Fix:** Track a dirty flag (compare editor value/title to last-saved snapshot) and (a) add a window 'beforeunload' listener that warns when dirty, (b) intercept in-app navigation (Next router events / link onClick) with a confirm modal, and (c) add lightweight debounced autosave with a visible 'Saved / Unsaved changes' status indicator in the header.
- **Status:** ✅ Fixed

#### 🔴 High · 🐛 Bug — List view drops most card actions (Archive, Pin, Tags, Share, Translate, Portfolio, Apply, Track are unreachable)
- **Where:** `frontend/src/app/workspace/page.tsx list-view actions cell (~815-857) vs grid overflow menu (~515-574)` · route `/workspace`
- **Problem:** Grid cards expose a MoreHorizontal overflow menu with ~13 actions including Archive (the only delete-equivalent), Pin, Edit tags, Share, Translate, Portfolio, Apply, Track application, References. The list/table view has NO overflow menu — its actions cell only offers Edit/Optimize/CL/Tailor/Fork/Refs/Export. A user who switches to List view therefore loses the ability to archive, pin, tag, share, translate, or track a resume entirely. Switching view mode should never remove capabilities.
- **Fix:** Reuse the same overflow (…) menu component in the list row's actions cell so grid and list expose identical actions; keep only the top 2 primary actions inline and move the rest into the shared menu for both views.
- **Status:** ✅ Fixed

#### 🔴 High · 🐛 Bug — Pressing Enter in the title field silently creates a BLANK resume even in Template mode
- **Where:** `frontend/src/app/workspace/new/page.tsx title input onKeyDown (~245) + handleCreate else-branch (~195)` · route `/workspace/new`
- **Problem:** The title <input> has onKeyDown Enter → handleCreate. In template mode handleCreate falls through to the else branch and creates a blank-content resume, then navigates away. A user who types a title and hits Enter intending to then browse templates instead gets an unexpected blank resume and is redirected to the editor, abandoning the template gallery they were about to use.
- **Fix:** In template mode, Enter in the title field should be a no-op (or focus the template search), not trigger blank creation. Only bind Enter→create in modes where a single obvious create action exists, or require an explicit 'Start from Blank' click.
- **Status:** ✅ Fixed

#### 🔴 High · 🐛 Bug — Live ATS score badge shows stale score — never reflects edits or optimization output
- **Where:** `frontend/src/app/workspace/[resumeId]/optimize/page.tsx useQuickATSScore(resume?.latex_content...) (~106) + LaTeXEditor onChange={() => {}} (~719)` · route `/workspace/[resumeId]/optimize`
- **Problem:** The editor's onChange is a no-op and `resume` state is set once on load and never updated. The quick ATS score is computed from `resume?.latex_content` (the originally loaded content). Consequently the in-editor ATS badge never changes when the user edits the LaTeX, and even after an optimization streams new content into the editor the badge keeps showing the pre-optimization score. Users see a score that contradicts the final ATS Analysis card, undermining trust.
- **Fix:** Lift editor content into state (wire onChange to a setter) and feed the current content into useQuickATSScore, or recompute the quick score from stream.streamingLatex / editorRef.current.getValue() so the badge tracks the live document.
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — 'View' navigates by resume_id, so distinct cover letters for the same resume are indistinguishable
- **Where:** `src/app/workspace/cover-letters/page.tsx:190 and L249 (href uses cl.resume_id, cl.id unused for nav)` · route `/workspace/cover-letters`
- **Problem:** Each card/row's 'View' link points to /workspace/[resumeId]/cover-letter using cl.resume_id; cl.id is never used for navigation. If a resume has multiple generated cover letters (different tones/companies), every one of them opens the same route and there is no way to open a specific historical cover letter. The library lists items that can't be individually retrieved.
- **Fix:** Include the cover-letter id in the destination (e.g. /workspace/[resumeId]/cover-letter?cl=<id> or a dedicated cover-letter detail route) so 'View' opens the exact letter that was clicked.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — Search fires an API request on every keystroke and full-screen spinners each time
- **Where:** `src/app/workspace/cover-letters/page.tsx:28-44 (effect depends on searchQuery) + setIsLoading(true) L31` · route `/workspace/cover-letters`
- **Problem:** The fetch effect depends directly on searchQuery with no debounce, so every character typed issues a listCoverLetters request. Worse, each request sets isLoading true, replacing the entire list/grid with a centered LoadingSpinner (L139-142) — the results flicker and jump on every keystroke, and rapid typing can race responses.
- **Fix:** Debounce the search (250-350ms) before fetching, and use a subtle inline 'searching' indicator (or keep prior results dimmed) instead of swapping the whole area to a full spinner on each query.
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — SyncTeX and print-preview color warnings are dead on /try — required props never passed
- **Where:** `frontend/src/app/try/page.tsx:646` · route `/try`
- **Problem:** PDFPreview is rendered as <PDFPreview pdfUrl isLoading onDownload> only. jobId, onSyncToSource, syncFromLine, latexContent, and onJumpToLine are all omitted. Consequences: (1) synctexReady never becomes true, so the marquee Overleaf feature — Ctrl+click PDF to jump to source and forward-sync — is entirely non-functional here; (2) colorWarnings needs latexContent, so the print-preview 'color-dependent elements' analysis never produces output; (3) the color-warning 'Jump to line' buttons would be no-ops even if shown. Features render toolbar buttons but silently do nothing useful.
- **Fix:** Thread jobId={stream.pdfJobId}, latexContent, onSyncToSource (→ editorRef.highlightLine), syncFromLine, and onJumpToLine into PDFPreview so SyncTeX and print-preview color analysis actually work.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — No 'Copy LaTeX source' button and no 'Copy logs' button
- **Where:** `frontend/src/app/try/page.tsx:584-588, 662-666` · route `/try`
- **Problem:** The editor tab bar (resume.tex + '⌘F to find') has no copy-source affordance, and the LogViewer/logs footer has no 'copy all' button. When a compile fails, users frequently want to copy the full error log (to paste into a search or the error explainer) or copy the whole .tex to share — both require manual select-all. For a source-centric tool this is a common missing affordance.
- **Fix:** Add a 'Copy' icon button to the editor tab bar (copies editorRef.getValue()) and a copy-to-clipboard button in the logs footer/LogViewer, each with a transient 'Copied' confirmation.
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — Fork / Create-Variant / CV→Industry use server content and drop unsaved editor edits
- **Where:** `frontend/src/app/workspace/[resumeId]/edit/page.tsx handleCreateVariant (~1711) / handleAcademicConvert (~1726)` · route `/workspace/[resumeId]/edit`
- **Problem:** handleCreateVariant calls apiClient.forkResume(resumeId) which forks the last-saved server state, not the current editor buffer. If the user has made unsaved edits and clicks 'Create Variant' (or the academic convert flow), the new variant is based on stale server content and their unsaved work is not carried over — then they are navigated away to the variant, likely losing the edits entirely.
- **Fix:** Save (or offer to save) the current editor content before forking, or pass the live editor value to the fork/convert call so the variant reflects what the user currently sees. At minimum warn when forking with unsaved changes.
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — 'Save as New Version' actually overwrites the resume — no version is created
- **Where:** `frontend/src/app/workspace/[resumeId]/optimize/page.tsx 'Save as New Version' button (~830-843)` · route `/workspace/[resumeId]/optimize`
- **Problem:** The button labeled 'Save as New Version' calls apiClient.updateResume(resumeId, { latex_content }) which overwrites the resume's content in place. No checkpoint/version is created, so the previous content is not recoverable from that action. The label promises non-destructive versioning but the behavior is a destructive overwrite.
- **Fix:** Either create an actual checkpoint (call the version/checkpoint API) so the prior version is preserved, or rename the button to 'Save to Resume (overwrite)' and add a version snapshot before overwriting.
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — 'Save to Resume' button saves the cover letter, not the resume (mislabel)
- **Where:** `frontend/src/app/workspace/[resumeId]/cover-letter/page.tsx completion 'Save to Resume' button (~639-644) → saveChanges (~248)` · route `/workspace/[resumeId]/cover-letter`
- **Problem:** In the completion panel the button reads 'Save to Resume' but its onClick is saveChanges, which calls updateCoverLetter(activeCoverLetterId, content) — it persists the cover letter document, not anything on the resume. The label implies the cover letter is being attached to / merged into the resume, which does not happen.
- **Fix:** Rename to 'Save Cover Letter' to match the actual behavior (consistent with the toast 'Cover letter saved').
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — Delete cover letter is destructive with no confirmation
- **Where:** `frontend/src/app/workspace/[resumeId]/cover-letter/page.tsx deleteCoverLetter (~294) + Delete button (~526-531)` · route `/workspace/[resumeId]/cover-letter`
- **Problem:** The 'Delete' button in the Previous Cover Letters list calls deleteCoverLetter immediately, permanently removing the cover letter (and clearing the editor/preview if it was active) with no confirmation step and no undo. A misclick destroys generated work.
- **Fix:** Add a confirmation (inline 'Delete? / Confirm' or a modal consistent with the app's design system) before deletion, and/or offer an undo toast.
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — 'Restore Original' overwrites editor content with no confirmation
- **Where:** `frontend/src/app/workspace/[resumeId]/optimize/page.tsx restoreOriginal (~256) + 'Restore Original' button (~697)` · route `/workspace/[resumeId]/optimize`
- **Problem:** restoreOriginal calls editorRef.setValue(baselineLatex) directly. If the user has typed manual edits or accepted an optimization into the editor, one click on 'Restore Original' wipes all of it with no confirmation and no undo affordance in this view.
- **Fix:** Confirm before restoring when the editor differs from baseline, and/or push the current content onto an undo stack so the restore is reversible.
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — 'Export All' ignores the active search/tag filter
- **Where:** `frontend/src/app/workspace/page.tsx handleBulkExport (~196) uses apiClient.bulkExport(format) with no filter args` · route `/workspace`
- **Problem:** When the user has narrowed the library by a tag filter or search query, the 'Export All' dropdown still exports every resume via bulkExport(format) — it does not respect the visible/filtered subset. This is surprising: the user expects to export what they are currently looking at.
- **Fix:** Either scope the export to the currently filtered resume IDs, or relabel to 'Export All Resumes' and add a separate 'Export Filtered (N)' option when a filter is active.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — No way to permanently delete a resume — only archive
- **Where:** `frontend/src/app/workspace/page.tsx — no delete anywhere; only handleArchive (~336) / handleUnarchive (~346)` · route `/workspace`
- **Problem:** The only removal action is Archive, which hides the resume; archived resumes can be Restored but never deleted. Over time users accumulate an unbounded pile of drafts, forks, and translations with no way to permanently remove any of them, and no bulk cleanup.
- **Fix:** Add a 'Delete permanently' action (with confirmation) in the archived section, and consider bulk delete/archive via multi-select on the main list.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — Toolbar and right-panel are overloaded (~20 header buttons, 17 tabs) with flat hierarchy
- **Where:** `frontend/src/app/workspace/[resumeId]/edit/page.tsx header toolbar (~1852-2184) and right-panel tab bar (~2465-2516)` · route `/workspace/[resumeId]/edit`
- **Problem:** The editor header packs ~20 buttons (Import, Export, QR, Dates, Age, Contacts, Salary, Reorder, Projects, Cover Letter, Career Path, CV→Industry, Variant, Save, Checkpoint, Share, Compiler, Settings, Collaborators, Auto, Compile, AI Optimize) into a single horizontally-scrolling strip, and the right panel exposes 17 equally-weighted tabs in another horizontal scroller. There is no grouping, overflow menu, or visual priority, so primary actions (Save/Compile/AI) compete with niche tools and are hard to find, especially on narrow screens where everything hides behind horizontal scroll.
- **Fix:** Establish hierarchy: keep Save/Compile/AI Optimize/Share as always-visible primary controls; collapse the analysis/formatting tools (QR, Dates, Age, Contacts, Salary, Reorder, Projects, CV→Industry) into a grouped 'Tools' overflow menu; group the 17 right tabs into a few categories or a searchable command palette.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — Import-file modal warns to save first but offers no Save and blocks nothing
- **Where:** `frontend/src/app/workspace/[resumeId]/edit/page.tsx Import modal (~2799-2825) copy 'Make sure to save first'` · route `/workspace/[resumeId]/edit`
- **Problem:** The import modal says 'This will replace the current editor content. Make sure to save first,' then on upload immediately overwrites the editor via setValue with no undo. It relies on the user remembering to manually save beforehand and provides no in-modal Save button or confirmation, risking loss of current content.
- **Fix:** Add a 'Save current first' button in the modal (or auto-checkpoint before replacing), and push the pre-import content onto the undo stack so the replace is reversible.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — Source↔Visual toggle can silently mutate LaTeX with only a weak warning
- **Where:** `frontend/src/app/workspace/[resumeId]/edit/page.tsx handleToggleEditorMode (~1355) source↔visual` · route `/workspace/[resumeId]/edit`
- **Problem:** Switching to Visual parses the LaTeX (flagging unrecognised blocks via wysiwygHasRaw) and switching back serializes the document model, which can reorder/reformat or rawize content the parser didn't fully understand. The only signal is a passive hasRawEntries flag; there is no upfront warning that visual editing may not round-trip complex LaTeX losslessly, so users may unknowingly alter their source.
- **Fix:** Show an explicit one-time warning when entering Visual mode on a document with unrecognised blocks, disable Visual mode (or mark it read-only for those blocks) when round-trip fidelity can't be guaranteed, and snapshot to the undo stack on every mode switch.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — No sort control for the library
- **Where:** `frontend/src/app/workspace/page.tsx filteredResumes sort (~178-183) — only pinned-first; search input (~693)` · route `/workspace`
- **Problem:** Resumes can be filtered by title text and by tag, but there is no user-facing sort. The list is ordered only pinned-first over the API's default order — users can't sort by last-updated, name, or ATS score. With a growing library and freshness/ATS data already available per card, the lack of sorting makes finding the right resume slow.
- **Fix:** Add a sort dropdown (Recently updated, Name A–Z, ATS score, Freshness) next to the grid/list toggle, defaulting to Recently updated.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — List-view table has no horizontal scroll wrapper and overflows on mobile
- **Where:** `src/app/workspace/cover-letters/page.tsx:206 (container is overflow-hidden) table L207` · route `/workspace/cover-letters`
- **Problem:** The list view renders a 5-column table inside a container with 'overflow-hidden'. On narrow viewports the Company/Role, Resume, Tone, Date, and Actions columns are compressed and clipped rather than scrollable, degrading the list view on mobile.
- **Fix:** Wrap the table in an 'overflow-x-auto' container (with a min-width on the table), or collapse to a stacked card layout below sm.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Search input lacks a label and a clear button
- **Where:** `src/app/workspace/cover-letters/page.tsx:108-117` · route `/workspace/cover-letters`
- **Problem:** The search input has only a placeholder and no aria-label/associated <label>, and there is no clear (x) control to reset the query — users must manually delete text to return to the full list. Minor a11y and convenience gap.
- **Fix:** Add an aria-label (or visually-hidden label) and a clear button that appears when searchQuery is non-empty and resets query + page.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Template selection: no per-card loading state and title field feels disconnected
- **Where:** `frontend/src/app/workspace/new/page.tsx TemplateCard grid (~475-483) disabled={isCreating}; title input at top (~240)` · route `/workspace/new`
- **Problem:** Clicking a template immediately creates+navigates, but during creation all cards are only 'disabled' with no spinner indicating which one was chosen, so on a slow network the page looks frozen. Separately, the Resume Title field sits far above the gallery and is optional for templates (falls back to template name), so users often don't realize it applies to template creation.
- **Fix:** Show a spinner/'Creating…' state on the specific clicked card, and surface the title inline (e.g., prompt for/confirm a title when a template is selected, or move a compact title field adjacent to the gallery).
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Two different 'Search' affordances are confusing
- **Where:** `frontend/src/app/workspace/page.tsx 'Search' button→ProjectSearchModal (~612) vs inline title search input (~693)` · route `/workspace`
- **Problem:** The header has a 'Search' button that opens a full-text ProjectSearchModal (⌘⇧F), while the toolbar below has an inline input placeholarded 'Search resume titles' that only filters titles. Both are called 'search' with no explanation of the difference, so users won't know which finds content vs. titles.
- **Fix:** Differentiate the labels/placeholders (e.g., button → 'Search content ⌘⇧F', input → 'Filter by title') or unify them into one search that spans titles and content.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Native confirm() dialogs break the app's visual design
- **Where:** `frontend/src/app/workspace/page.tsx archive confirm() (~569); edit page GitHub/Dropbox pull window.confirm (~1291, ~1340)` · route `/workspace`
- **Problem:** Archive-from-card and the GitHub/Dropbox 'pull will overwrite' flows use the browser-native confirm()/window.confirm(). These render as unstyled OS dialogs inconsistent with the app's custom modal system used everywhere else (fork, translate, tag edit), producing a jarring, off-brand experience for consequential actions.
- **Fix:** Replace native confirm() calls with the app's themed confirmation modal component for consistent styling and copy.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Recent Activity entries aren't clickable
- **Where:** `frontend/src/app/workspace/page.tsx Recent Activity list (~1050-1056)` · route `/workspace`
- **Problem:** The Recent Activity sidebar lists the last 5 runs (stage/status/time) but the entries are non-interactive divs. Users can't click a run to jump to its resume, logs, or result — the only navigation is the generic 'View Full History' link, so a specific recent run is a dead end.
- **Fix:** Make each activity row link to the relevant job/resume (editor logs or run history detail) so users can act on a recent run directly.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Overlapping 'Apply to a job' and 'Track application' actions are confusing
- **Where:** `frontend/src/app/workspace/page.tsx overflow menu 'Apply to a job' (~548) and 'Track application' (~551)` · route `/workspace`
- **Problem:** The card overflow menu lists both 'Apply to a job' (ApplyModal) and 'Track application' (AddApplicationModal). The labels are near-synonymous and it's unclear how they differ or when to use which, creating decision friction for a job-application workflow.
- **Fix:** Clarify the distinction in labels (e.g., 'Quick apply' vs 'Add to tracker'), add short helper text, or consolidate into a single applications action if they overlap significantly.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Saved cover letters are indistinguishable when company/role are blank
- **Where:** `frontend/src/app/workspace/[resumeId]/cover-letter/page.tsx existing list label (~519-521)` · route `/workspace/[resumeId]/cover-letter`
- **Problem:** Each saved cover letter is labeled company_name || role_title || 'Cover Letter'. Since company and role are optional at generation, multiple cover letters generated without them all display as 'Cover Letter' differentiated only by a date, making it hard to pick the right one from the history list.
- **Fix:** Fall back to a snippet of the job description or an incrementing 'Cover Letter #N', and always show the date/time; consider allowing an inline rename.
- **Status:** ✅ Fixed


### Résumé Studio (/try) (7)

#### 🔴 High · 🐛 Bug — No persistence or beforeunload guard — a page reload silently destroys all work
- **Where:** `frontend/src/app/try/page.tsx:54, 363-364` · route `/try`
- **Problem:** latexContent lives only in React state, initialized to DEMO_RESUME_TEMPLATE. There is no localStorage persistence, no autosave, and no 'window.beforeunload' handler. An anonymous user who spends 20 minutes editing a resume loses everything on an accidental refresh, tab close, or navigation — the editor silently resets to the demo template. There is also no 'autosave' indicator anywhere, so users have no signal that their work is (not) being saved.
- **Fix:** Debounce-persist latexContent (and jobDescription) to localStorage and rehydrate on mount; add a beforeunload handler that warns when the buffer differs from the last-compiled/demo content. Surface a small 'Saved locally' / 'Unsaved changes' indicator in the top bar.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — No way to cancel a running compile or optimization
- **Where:** `frontend/src/app/try/page.tsx:681-688, 619-629` · route `/try`
- **Problem:** Once a job is submitted the 'Recompile' button becomes a disabled 'Compiling…' spinner and the progress strip shows percent, but there is no Cancel/Stop control. A long or stuck optimize (or a compile that will hit the plan timeout) leaves the user waiting with no escape, and the editor is being overwritten in the meantime. A cancel job API exists in the platform but is unreachable from this UI.
- **Fix:** Add a Cancel button next to the progress strip (or turn the 'Compiling…' button into a Stop button) that calls the job-cancel endpoint and restores the editor to its pre-run snapshot.
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — Trial-exhausted users see silently disabled compile buttons with no inline reason or upgrade CTA
- **Where:** `frontend/src/app/try/page.tsx:683-688, 452-464` · route `/try`
- **Problem:** When trials are exhausted (!effectiveCanRun), the Recompile / Optimize / Trim buttons get disabled:opacity-50. Because they're disabled, their onClick (which contains the 'Trial limit reached. Upgrade to continue.' toast) never fires — so clicking a greyed button produces zero feedback. The only hint is a tiny 'trials 0' counter in the header. There is no inline explanation or upgrade prompt near the disabled action.
- **Fix:** When !effectiveCanRun, keep the button enabled but route its click to an explanatory toast/modal with an upgrade link, or render a persistent inline banner ('You've used all free compiles — log in / upgrade to continue') adjacent to the compile controls.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — Files list is decorative — entries aren't interactive and the .cls 'file' does nothing
- **Where:** `frontend/src/app/try/page.tsx:382-394` · route `/try`
- **Problem:** The Project file list renders 'resume.tex' (active) and 'latexy-resume.cls' as styled rows, but they are plain divs, not buttons. Clicking the .cls file gives no feedback and there's no way to view/open it. Presenting a two-file project tree where only an invisible one is real is confusing — users will try to click the .cls to inspect the document class and get nothing.
- **Fix:** Either make the entries real (open the .cls in a read-only view, allow switching files) or drop the fake .cls row. At minimum give rows button semantics and a cursor so their (non)interactivity is honest.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — On mobile, compiling from the Editor pane never surfaces the result; Auto toggle is hidden
- **Where:** `frontend/src/app/try/page.tsx:207, 690-698` · route `/try`
- **Problem:** runCompile only auto-switches panes when mobilePane==='tools' (→ 'pdf'). A mobile user sitting on the Editor pane who taps 'Recompile' stays on Editor and never sees the progress strip or rendered PDF unless they manually tap the 'PDF' tab — the compile appears to do nothing. Separately, the Auto-compile toggle is 'hidden … sm:flex', so mobile users can't enable auto-compile at all.
- **Fix:** Auto-switch mobilePane to 'pdf' on any compile/optimize submit (not just from 'tools'), and expose the Auto toggle on mobile (e.g. in the mobile rail) or document that it's desktop-only.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — PDF viewer lacks fit-to-width / reset zoom, a page indicator, and zoom keyboard shortcuts
- **Where:** `frontend/src/components/PDFPreview.tsx:344-367` · route `/try`
- **Problem:** Zoom is only ±15% stepper buttons; clicking the '100%' label does nothing (no reset), there's no 'fit to width' control, no ⌘+/⌘- or Ctrl+scroll zoom, and multi-page documents show no 'Page X of N' indicator while scrolling. For a preview pane users compare against a real PDF viewer, these are noticeable ergonomics gaps.
- **Fix:** Make the percentage label click reset to 100%/fit; add a 'Fit width' button; support keyboard/Ctrl-scroll zoom; and show a current-page/total-page indicator for multi-page resumes.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Three distinct import sources (GitHub / Portfolio URL / LinkedIn export) all open the same modal
- **Where:** `frontend/src/app/try/page.tsx:540-544` · route `/try`
- **Problem:** The Import panel lists GitHub ('Pull top projects'), Portfolio URL ('Scrape a page'), and LinkedIn export ('Upload archive') as three separate rows, but all three call setShowProjectsModal(true) — the identical modal. Users who click 'LinkedIn export' expecting an archive upload flow, or 'Portfolio URL' expecting a URL field, land in the same generic dialog, which reads as broken or mislabeled if the modal doesn't preselect their chosen source.
- **Fix:** Pass the chosen source into ImportProjectsModal (e.g. a defaultTab/source prop) so the modal opens on the matching sub-flow, or collapse the rows into one honest 'Import projects' entry.
- **Status:** ✅ Fixed


### Auth & Onboarding (14)

#### 🔴 High · 🐛 Bug — Onboarding 'pick a starting point' cards are dead, non-interactive
- **Where:** `src/components/onboarding/OnboardingFlow.tsx:189-203` · route `/workspace (OnboardingFlow step 4 'get-started')`
- **Problem:** The final onboarding step tells the user 'Pick a starting point below' and 'Pick how you want to start', then renders three prominent option Cards — 'Use a template', 'Import a resume', 'Write from scratch'. These are plain <div> Cards with no onClick, href, role, or hover-press affordance, so clicking any of them does nothing. The only real action is the generic 'Create my first resume' button, which calls onComplete — and onComplete (completeOnboarding in workspace) merely closes the modal and sets a localStorage flag; it does not route to templates, import, or the Studio. So all three choices, plus the CTA, land the user on the same generic workspace. This is a classic misleading affordance: the most visually salient elements of the final step are no-ops.
- **Fix:** Make each card a real button/link that (a) sets a query intent and (b) closes onboarding and navigates: 'Use a template' -> /templates, 'Import a resume' -> import modal/flow, 'Write from scratch' -> /try (LaTeX Studio). Pass the chosen destination into onComplete(dest) so the CTA and cards deep-link. If a single generic CTA is intended, remove the three cards or downgrade them to non-clickable illustrative copy so they don't read as selectable.
- **Status:** ✅ Fixed

#### 🔴 High · 🐛 Bug — Post-auth redirect is hardcoded to /workspace, deep links are lost
- **Where:** `src/components/auth/SignInForm.tsx:51; src/components/auth/SignUpForm.tsx:33` · route `/login, /signup`
- **Problem:** Both forms do `window.location.href = '/workspace'` on success and never read a `redirect`/`callbackURL`/`next` query param. A user who hits a protected deep link (e.g. /workspace/abc/edit, /billing, a shared resume URL) and is bounced to /login will, after signing in, land on the generic workspace instead of their intended destination — they must re-navigate manually. The same applies to social sign-in. There is no mechanism anywhere in the auth slice to preserve intended-destination.
- **Fix:** Read a `redirect` (or `callbackURL`) search param, validate it is a same-origin relative path (must start with '/', reject '//' and absolute URLs to prevent open redirect), and navigate there on success, defaulting to /workspace. Have the auth-guard that bounces users to /login append `?redirect=<encoded current path>`. Forward the same param through the login<->signup and forgot-password links.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — No show/hide password toggle on any password field
- **Where:** `src/components/auth/SignInForm.tsx:155-162; src/components/auth/SignUpForm.tsx:141-148; src/app/reset-password/page.tsx:102-128; src/components/ui/input.tsx` · route `/login, /signup, /reset-password`
- **Problem:** Every password input (sign in, sign up, and both new/confirm fields on reset) is a bare type=password with no reveal toggle. On sign-up and reset, where users are typing a new 8+ char password (and confirming it), the inability to see what they typed is a common cause of typos, failed confirmation, and abandoned sign-ups — especially on mobile keyboards. The shared Input component has no built-in affordance either.
- **Fix:** Add an eye/eye-off toggle button inside the password field (absolutely positioned, min 44px hit target, aria-pressed + aria-label 'Show/Hide password') that switches type between password and text. Either bake it into a PasswordInput variant of the Input component or wrap each field. Keep the toggle keyboard-reachable and outside the tab-to-submit flow disruption.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — Sign-up has no confirm-password field and no strength/requirements hint
- **Where:** `src/components/auth/SignUpForm.tsx:137-149` · route `/signup`
- **Problem:** Sign-up collects a single password with only native minLength=8 and no confirm field, while the reset-password page DOES require confirmation — an inconsistency. A user who typos their password at sign-up creates an account they cannot log into and must go through the forgot-password recovery flow to fix. The label is just 'Password' with no visible '8+ characters' hint or strength meter, so the requirement is only discovered on server error.
- **Fix:** Add helper text under the field ('At least 8 characters') and a lightweight strength indicator. Consider a confirm-password field for parity with reset, or pair it with the show/hide toggle above to reduce typo risk. Validate length client-side before submit and show an inline field error rather than relying on the server round-trip.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — Missing autoComplete attributes on sign-in and sign-up fields
- **Where:** `src/components/auth/SignInForm.tsx:133-162; src/components/auth/SignUpForm.tsx:115-148` · route `/login, /signup`
- **Problem:** The sign-in email/password inputs and sign-up name/email/password inputs have no autoComplete attributes, so password managers and browser autofill are far less reliable at saving/filling credentials (and won't distinguish current-password from new-password). Notably forgot-password (autoComplete='email') and reset-password (autoComplete='new-password') get this right, making the omission on the primary flows inconsistent.
- **Fix:** Add autoComplete: sign-in email='email', password='current-password'; sign-up name='name', email='email', password='new-password'. This is a one-line-per-field change that materially improves credential capture and fill.
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — Verify banner: 'Resend' disappears permanently after one send
- **Where:** `src/components/EmailVerifyBanner.tsx:80-97` · route `app-wide banner (EmailVerifyBanner)`
- **Problem:** Once `resent` becomes true, the message switches to 'Verification email sent' and the Resend button is removed via `!resent && (...)`. There is no timer/reset, so if the email never arrives (spam filter, typo, delivery delay) the user cannot resend again without a full page reload. The success state is terminal for the session. Additionally, an error sets `error` but the message priority is resent > error > default, which is fine, yet there is no cooldown/anti-spam messaging.
- **Fix:** Keep the Resend button available after success, ideally with a short cooldown (e.g. 'Resend again in 30s' countdown) so users can retry. Show the sent-confirmation as transient toast/inline text rather than replacing the action permanently. Reset `resent` after the cooldown.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — Verify-failed page tells users to use a banner they may have dismissed
- **Where:** `src/app/verify-email/page.tsx:104-114` · route `/verify-email (error state)`
- **Problem:** On verification failure the copy says 'You can request a new one from the banner in the app.' But EmailVerifyBanner is dismissible and its dismissal is persisted in localStorage, so a user who dismissed it earlier has no visible path to resend — the instruction points to something that may not exist for them. The page itself offers no 'resend verification email' action, only 'Back to app'.
- **Fix:** Add a direct 'Resend verification email' button on the verify-email error state (calling authClient.sendVerificationEmail for the logged-in user), so recovery does not depend on the banner. If the user is not logged in, prompt them to sign in first. Also consider un-dismissing the banner when a verification attempt fails.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Progress bar segments are 1.5px-tall clickable targets with weak affordance
- **Where:** `src/components/onboarding/OnboardingFlow.tsx:270-281` · route `/workspace (OnboardingFlow)`
- **Problem:** The segmented progress indicator is made of buttons that are only h-1.5 (6px) tall and full-width thin bars. They are the step-jump navigation (goToStep) but give no visual cue they are clickable, and future steps look inactive (bg-surface-2) yet are still clickable. The tiny hit area fails the 44px touch-target guideline and the interaction is undiscoverable.
- **Fix:** Either make the segments clearly non-interactive (pure progress) and rely on Back/Next, or if step-jumping is desired, increase the interactive hit area (padded wrapper), add visible hover/focus states, distinct styling for completed vs current vs upcoming, and aria-current on the active step.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Confirm-mismatch and length only validated on submit; no live feedback or strength
- **Where:** `src/app/reset-password/page.tsx:22-53, 102-128` · route `/reset-password`
- **Problem:** Password rules on reset are checked only in handleSubmit: length<8 and mismatch surface as a single error block after the user presses submit, and there is no live 'passwords match' indicator or strength meter. Combined with the missing show/hide toggle, a user who mistypes the confirm field only learns after submitting, and cannot see either value to reconcile them.
- **Fix:** Validate on blur/change: show an inline 'Passwords don't match' hint under the confirm field once both are non-empty, and a length/strength hint under the new-password field. Disable submit until both pass, or at minimum give real-time reassurance.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Reset-link sent state offers no 'resend' or 'wrong email' recovery
- **Where:** `src/app/forgot-password/page.tsx:53-76` · route `/forgot-password`
- **Problem:** After submitting, the success card correctly uses anti-enumeration copy but then only offers 'Back to sign in'. There is no way to resend the email, no 'didn't get it?' affordance, and no way to correct a mistyped address without navigating back and re-entering — a common need given the whole point is the user lost access.
- **Fix:** In the sent state, add a 'Resend link' action (with a short cooldown) and a 'Use a different email' link that returns to the form (optionally preserving nothing, or letting them edit). Keep the anti-enumeration copy intact.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Server error passthrough can surface vague/technical messages; error not focus-announced
- **Where:** `src/components/auth/SignInForm.tsx:47-57; src/components/auth/SignUpForm.tsx:28-40` · route `/login, /signup`
- **Problem:** Errors fall back to generic strings ('Sign in failed', 'Sign up failed', 'An unexpected error occurred') and otherwise pass result.error.message straight through, which may be terse Better Auth codes. The error region is aria-live=polite (good) but focus is not moved to it and there's no field-level association, so a screen-reader user mid-form may not reliably hear it, and a sighted user who submitted from the button may not see an error rendered above.
- **Fix:** Map common auth error codes to friendly copy (e.g. invalid credentials, email already registered, too many attempts). Associate the error with the form via aria-describedby and consider moving focus to the error summary on failure. Ensure the error is visible in-viewport after submit.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Onboarding completion is device-local only and re-triggers per browser
- **Where:** `src/components/onboarding/OnboardingFlow.tsx:343-384; src/app/workspace/page.tsx:147-150` · route `/workspace (useOnboarding)`
- **Problem:** Completion is stored solely in localStorage ('latexy_onboarding_completed'). A returning user on a new browser/device or after clearing storage will be shown the full onboarding again on /workspace, and conversely a user who completed it on one device sees no continuity. There is also no server-side 'has_onboarded' flag, so the nudge is not tied to the account. Skip and Complete are treated identically (both mark completed), which is reasonable but means a user who skipped can never intentionally re-open onboarding (resetOnboarding exists in the hook but is not wired to any UI).
- **Fix:** Persist onboarding completion on the user record (server) and hydrate from session so it is consistent across devices; keep localStorage as a fast-path cache. Expose a 'Replay onboarding / product tour' entry point (e.g. in help or settings) that calls resetOnboarding+startOnboarding, since the capability already exists but is unreachable.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Free-plan limits are hardcoded in onboarding copy and may drift from real plan
- **Where:** `src/components/onboarding/OnboardingFlow.tsx:181-186` · route `/workspace (OnboardingFlow step 4)`
- **Problem:** Step 4 states 'Your free account includes 10 compilations a day and 3 AI optimizations a month' as static text branched only on userType==='premium'. These numbers are not sourced from the actual plan/entitlements, so if plan limits change (per MEMORY, free = 3 uses) the onboarding will show numbers that contradict the real limits enforced elsewhere — an easy source of user confusion and support tickets.
- **Fix:** Drive the quota copy from the same plan/entitlements source the app uses to enforce limits, or soften to non-numeric copy ('generous free tier') if exact numbers can't be sourced reliably. At minimum reconcile the hardcoded values with the actual free-plan configuration.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Social sign-in shows 'Redirecting...' but no explanation if the OAuth popup/redirect stalls
- **Where:** `src/components/auth/SignInForm.tsx:60-77; src/components/auth/SignUpForm.tsx:42-59` · route `/login, /signup`
- **Problem:** handleSocial sets socialLoading and the button reads 'Redirecting...'; if the client returns without a url it releases and shows an error (good). But when data.url IS returned the code lets Better Auth navigate the browser — during any latency the user sees a disabled 'Redirecting...' with no timeout/fallback messaging, and both forms disable the entire form. There's no guard against a hung state where the redirect neither errors nor navigates.
- **Fix:** Keep the current release-on-error logic, but add a soft timeout (e.g. after ~8s still 'Redirecting...') that surfaces a 'Taking longer than expected — try again' affordance and re-enables the button, so a stalled OAuth handshake isn't a dead end. Ensure the same behavior on the sign-up form.
- **Status:** ✅ Fixed


### Dashboard, Tracker & Cover Letters (15)

#### 🔴 High · 🐛 Bug — Deleting an application has no confirmation and no undo
- **Where:** `src/app/tracker/page.tsx:417 (handleDelete) + ApplicationCard delete menu item ~L207` · route `/tracker`
- **Problem:** The overflow-menu 'Delete' calls handleDelete(app.id) immediately, which optimistically removes the card and fires apiClient.deleteApplication with only a success toast. A single misclick permanently destroys a tracked application (company, role, notes, ATS score, job URL) with zero confirmation and no way to recover it.
- **Fix:** Gate the delete behind a confirmation dialog (or at minimum an inline 'Are you sure?' in the menu), and/or make the toast an actionable 'Undo' toast (sonner supports action buttons) that reinserts the card and cancels the API call within a few seconds.
- **Status:** ✅ Fixed

#### 🔴 High · 🐛 Bug — Kanban is unusable on touch / keyboard — no drag alternative and hover-only actions
- **Where:** `src/app/tracker/page.tsx:312 (only PointerSensor) + ApplicationCard menu L170 (opacity-0 group-hover)` · route `/tracker`
- **Problem:** Two compounding issues: (1) DndContext registers only PointerSensor, so there is no KeyboardSensor — the entire status workflow (move card between columns) is impossible via keyboard, a serious a11y gap. (2) The Edit/Delete overflow trigger is 'opacity-0 group-hover:opacity-100', so on touch devices with no hover the menu button is invisible/unreachable, leaving edit and delete effectively inaccessible on mobile. On a horizontally-scrollable board, pointer-drag also fights with scroll on touch.
- **Fix:** Add @dnd-kit's KeyboardSensor with sortableKeyboardCoordinates and a visible status-change control (e.g. the status <select> from the edit modal exposed on the card) as a non-drag alternative. Make the overflow trigger always visible (or focus-visible) on coarse-pointer devices via a `@media (hover:none)` / `pointer-coarse` style so it is tappable.
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — Within-column card reordering is visual-only and never persisted
- **Where:** `src/app/tracker/page.tsx:392 (handleDragEnd early-returns when sourceCol===finalCol) + SortableContext L247` · route `/tracker`
- **Problem:** Columns use SortableContext with verticalListSortingStrategy, so users can reorder cards within a column, but handleDragEnd returns early when source and destination columns match and no ordering is sent to the API. Any within-column reorder silently reverts on reload, making the reordering affordance misleading.
- **Fix:** Either persist an explicit order/position field on reorder (arrayMove + PATCH), or, if ordering isn't supported by the backend, remove the sortable reorder behavior within a column so users aren't given an affordance that doesn't stick.
- **Status:** ✅ Fixed — added a **Manual** sort mode; a within-column drag now reorders, persists (localStorage), and switches the board into Manual so the order sticks.

#### 🟠 Medium · ✨ Improvement — No filters, search, or sort on the board despite unbounded card growth
- **Where:** `src/app/tracker/page.tsx (header L458-479, no filter UI)` · route `/tracker`
- **Problem:** The tracker loads all applications into 7 columns with no search box, company/date filters, or sort controls. As a job seeker accumulates dozens of applications, finding a specific company or filtering by recency/ATS becomes tedious — you must eyeball every column.
- **Fix:** Add a search input (filter by company/role) plus lightweight filters (e.g. this-week, has-offer, ATS threshold) in the header row. Filtering can be purely client-side against boardData.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — Notes entered in the edit modal are never surfaced anywhere
- **Where:** `src/app/tracker/page.tsx: EditApplicationModal notes field L653-656; ApplicationCard has no notes display` · route `/tracker`
- **Problem:** The edit modal collects a Notes textarea and persists app.notes, but nothing in the UI ever displays it — the card shows only company, role, ATS, date, and a link. Notes are effectively write-only, and there is no card detail/expand view, so a core piece of tracking data is invisible after entry.
- **Fix:** Show a notes indicator on the card (e.g. a note icon when notes exist) and reveal notes in an expandable card detail or on-hover preview. A read-only detail popover reusing the card data would also add the currently-missing 'view application' affordance.
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — On fetch error the charts show 'No data' empty states instead of an error state
- **Where:** `src/app/dashboard/page.tsx:61-68 (catch sets error, analytics stays null) + charts render EmptyChart when series empty (MetricCharts.tsx:26,123,183)` · route `/dashboard`
- **Problem:** When fetchDashboardData throws, an error banner appears at the top, but because analytics/timeseries remain null the derived series are empty and the chart cards render 'No activity data available yet.' / 'No feature usage tracked yet.' The KPI grid also collapses to nothing (kpis returns [] when analytics is null). A user with a transient API failure is told they have no data rather than that loading failed — misleading and alarming.
- **Fix:** When error is set, render error/placeholder states inside the KPI and chart cards (e.g. 'Couldn't load' with a retry) rather than the 'no data yet' empty states, or hide the chart bodies while the error banner is shown.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — Charts have no tooltips, hover, or value read-out — exact numbers are unrecoverable
- **Where:** `src/components/analytics/MetricCharts.tsx (ActivityAreaChart L58, StatusDonutChart L204) consumed by dashboard L236/L255` · route `/dashboard`
- **Problem:** The activity area chart and status donut are static SVG with no hover tooltips, data-point markers, or crosshair. A user can see the shape of activity but cannot read the value for any specific day, nor the percentage of a donut slice without doing mental math against the legend counts. This substantially limits the analytical value of the dashboard.
- **Fix:** Add hover tooltips (visx Tooltip/localPoint) showing date+value on the area chart and label+count+percent on donut slices; consider point markers on the line for discoverability.
- **Status:** ✅ Fixed — the activity chart now has a hover read-out: a guide line, point marker, and a date/value tooltip.

#### 🟠 Medium · ✨ Improvement — Charts are inaccessible to screen readers — bare SVG with no roles/labels
- **Where:** `src/components/analytics/MetricCharts.tsx: <svg> elements L59, L147, L206 (no role/aria/title/desc)` · route `/dashboard`
- **Problem:** All three charts are raw <svg> with no role='img', aria-label, <title>/<desc>, or tabular fallback. Non-visual users get nothing from Activity Trend, Feature Usage Mix, or Run Status Distribution. The range toggle buttons also lack aria-pressed state.
- **Fix:** Add role='img' + a descriptive aria-label (or <title>/<desc>) summarizing each chart, and consider an offscreen data table. Add aria-pressed to the 7D/30D/90D toggle buttons and to the grid/list toggles elsewhere.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — Changelog is hardcoded and stale — newest entry is months old
- **Where:** `src/app/updates/page.tsx:3-19 (static updates array, latest 'March 06, 2026')` · route `/updates`
- **Problem:** The updates/shipping-log page is a static array whose most recent entry is dated March 2026 while the product is actively shipping months later. A public 'Shipping log and platform progress' page that hasn't moved in months signals an abandoned/stale product to prospective users and undercuts the page's stated purpose.
- **Fix:** Source updates from a maintained data file/CMS/markdown and keep it current, or remove/hide the page until it can be maintained. At minimum backfill recent releases so the log reflects actual activity.
- **Status:** ✅ Fixed — moved to a `src/data/changelog.ts` data module (single source of truth) with a current entry.

#### 🟡 Low · ✨ Improvement — Empty board shows 7 'Drop here' columns with no first-run onboarding
- **Where:** `src/app/tracker/page.tsx: StatsBar returns null when 0 apps (L267); columns render 'Drop here' L252-256` · route `/tracker`
- **Problem:** When a user has zero applications, the stats bar is hidden and the board renders 7 dashed 'Drop here' placeholders. There is no explanatory empty state pointing them at 'Add Application' or explaining the pipeline concept — it reads as broken/empty rather than ready-to-use.
- **Fix:** Render a dedicated empty state when total applications is 0 (illustration + one-line explanation + a prominent 'Add your first application' CTA) instead of seven identical 'Drop here' columns.
- **Status:** ✅ Fixed

#### 🟡 Low · 🐛 Bug — 'Recent Runs' cards are dead ends — clicking a run does nothing
- **Where:** `src/app/dashboard/page.tsx:274-282 (job rows are plain <div>)` · route `/dashboard`
- **Problem:** Each recent run renders stage/status/timestamp in a non-interactive div. There is no way to open the job, view logs, or jump to its result from the dashboard — the primary 'what happened with my run' drill-down is missing. The 'Full history' link exists, but individual runs aren't actionable.
- **Fix:** Make each recent-run row a link/button to the job detail (or /workspace/history filtered to that job) so users can inspect logs/results, with hover affordance and keyboard focus.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Status donut fallback is computed from only the last 10 jobs but presented as overall distribution
- **Where:** `src/app/dashboard/page.tsx:93-102 (statusSeries fallback uses recentJobs) + heading 'Run Status Distribution' L254` · route `/dashboard`
- **Problem:** When timeseries.status_distribution is absent, statusSeries is derived from recentJobs, which is explicitly sliced to the 10 most recent (L60). The donut's center shows that count as total 'RUNS' and the card is titled 'Run Status Distribution', implying it reflects the selected range — but it only reflects up to 10 jobs, which can badly misrepresent success/failure ratios.
- **Fix:** Either always drive the donut from range-scoped server data, or when falling back to recentJobs label it explicitly (e.g. 'Last 10 runs') so the scope is honest.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — KPI values are unformatted and can render awkwardly (raw latency, no units guard)
- **Where:** `src/app/dashboard/page.tsx:117-119 (avg_compilation_time) and 112-114 (success_rate)` · route `/dashboard`
- **Problem:** 'Avg Compile Latency' prints `${analytics.avg_compilation_time}s` with no rounding/guard — a value like 3.4179 or 0 would render as '3.4179s' / '0s' with no context. There's no formatting layer, so backend precision leaks into the KPI and can look broken.
- **Fix:** Round/format latency (e.g. toFixed(1) + graceful handling of 0/undefined as '—'), and consider a small trend indicator vs. the prior window to give the numbers meaning.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Feature-usage bar labels can collide with their value labels on short bars
- **Where:** `src/components/analytics/MetricCharts.tsx:168-173` · route `/dashboard`
- **Problem:** The category name is drawn at x=6 inside/over the bar and the value at x=max(barWidth-6,34), right-anchored. For short bars (small values) the value is pinned to x=34 while the name also starts at x=6, so on low-count features the name and the number overlap and become unreadable; the name in accent-fg over a low-opacity accent bar can also fail contrast.
- **Fix:** Place category labels to the left of the bars (dedicated gutter) or above each bar, and position value labels outside the bar end when the bar is too short to contain them, ensuring no overlap and adequate contrast.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Card overflow menu can't be dismissed with Escape and isn't a real menu for a11y
- **Where:** `src/app/tracker/page.tsx:182-217 (portal menu; only backdrop click closes it)` · route `/tracker`
- **Problem:** The per-card Edit/Delete menu is closed only by clicking the full-screen backdrop button; there is no Escape-to-close (the keydown handler exists only in the EditApplicationModal, L586-590) and the popover lacks menu/menuitem roles and focus management. Keyboard users can't reliably open, navigate, or dismiss it.
- **Fix:** Add Escape-to-close and focus the first item on open, restore focus to the trigger on close, and apply role='menu'/role='menuitem' (or adopt a headless menu primitive) for proper keyboard and screen-reader support.
- **Status:** ✅ Fixed


### Billing, BYOK, Settings & Developer (20)

#### 🔴 High · 🐛 Bug — "Show" key button is a dead affordance — it never reveals the key
- **Where:** `frontend/src/components/byok/APIKeyManager.tsx:164-169, 192-194` · route `/byok`
- **Problem:** Each stored key has a Show/Hide toggle. Clicking "Show" only swaps the literal string 'hidden' for a fixed run of bullet dots '•••••••••••••••••••••••••••••'. It never displays any part of the actual key (not even a masked last-4). The button promises to reveal a secret and delivers placeholder dots, which reads as broken and erodes trust in the whole credential store.
- **Fix:** Either remove the Show/Hide control entirely (keys are write-only by design), or have it fetch and display a safe masked preview from the backend (e.g. 'sk-...4f9a'). If keys are intentionally never retrievable, replace the toggle with a static 'Stored securely — cannot be displayed' note.
- **Status:** ✅ Fixed

#### 🔴 High · 🐛 Bug — One-time-shown API key has no Copy button
- **Where:** `frontend/src/app/developer/page.tsx:204-214` · route `/developer`
- **Problem:** After creating a developer key, the full secret is rendered in a <code> block with the warning 'Copy this key now — it will never be shown again', but there is no copy button. The user must manually drag-select the value; on mobile or if the code block scrolls horizontally this is error-prone, and a mis-copy means the key is lost forever (they must revoke and recreate). This is the single most important copy affordance on the page and it is missing.
- **Fix:** Add a 'Copy' button next to the key that calls navigator.clipboard.writeText(createdKey.full_key) with a success toast/checkmark. Also add a 'Done'/dismiss button to hide the banner afterward.
- **Status:** ✅ Fixed

#### 🔴 High · 🐛 Bug — Enabling 'Browser notifications' never requests notification permission
- **Where:** `frontend/src/app/settings/page.tsx:681-707` · route `/settings`
- **Problem:** The Desktop Notifications toggle only flips local state and calls setNotificationPref(next) into localStorage. It never calls Notification.requestPermission(). If the browser permission is still 'default' (the common case), the user turns the switch ON, sees it as enabled, but will never receive a single desktop notification — silent failure. The page only surfaces a warning when permission is already 'denied', not when it is 'default'.
- **Fix:** When toggling ON, if Notification.permission === 'default' call Notification.requestPermission() and reflect the result. If the user denies, revert the toggle and show the blocked-permissions hint. Only persist the pref as ON once permission is 'granted'.
- **Status:** ✅ Fixed

#### 🔴 High · 🐛 Bug — Coupon is validated only against Pro but applied to any plan at checkout
- **Where:** `frontend/src/app/billing/page.tsx:147-163, 207-215` · route `/billing`
- **Problem:** handleApplyCoupon always validates the entered coupon against a hardcoded 'pro'/'pro_annual' target, yet the resulting appliedCoupon.code is passed to createSubscription for whichever plan the user later selects (basic, byok, team, student). A coupon that is valid for Pro but not for Basic will show a green 'valid' state, then either be silently ignored or rejected at the payment step — a misleading promise about the price the user will pay.
- **Fix:** Validate the coupon against the plan the user is actually purchasing (validate at plan-select time, or re-validate against the chosen plan before checkout). At minimum label the coupon result as 'Valid on Pro plans' so the scope is explicit.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — Freshly created key banner never dismisses and lingers as a secret on screen
- **Where:** `frontend/src/app/developer/page.tsx:204-214` · route `/developer`
- **Problem:** The createdKey banner has no dismiss control and stays rendered until a full page reload — even after the user scrolls away, renames/revokes other keys, or creates additional keys (it just overwrites). Leaving a plaintext API key persistently visible is both a UX annoyance and a shoulder-surfing/security risk.
- **Fix:** Add an explicit 'I've saved it — dismiss' button that clears createdKey. Optionally auto-collapse the raw value behind a reveal after the first copy, and clear it on navigation.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — Applied coupon has no effect on displayed pricing and can't be cleared
- **Where:** `frontend/src/app/billing/page.tsx:391-441, 429-439` · route `/billing`
- **Problem:** After a coupon validates successfully the PricingCard prices are unchanged — nothing shows the discounted amount the user will actually be charged, so they take it on faith through an external Razorpay tab. There is also no 'remove coupon' control; appliedCoupon persists for the rest of the session and to change it you must retype over it. Users can't confirm the discount before committing to checkout.
- **Fix:** Once a coupon is valid, show the discounted price on the applicable card(s) (e.g. strike-through original) and render a removable chip ('SAVE20 ✕') so the coupon can be cleared. Recompute effective price client-side from discountPercent.
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — Removing a team seat has no confirmation despite being destructive
- **Where:** `frontend/src/app/billing/page.tsx:316-326, 512-518` · route `/billing`
- **Problem:** handleRemoveSeat immediately revokes a teammate's seat/access on a single click with no confirm dialog, while every other destructive action in this slice (cancel subscription, disconnect integrations, revoke developer key, delete BYOK key) guards with confirm(). An accidental click silently kicks a teammate off the plan, and there is no undo.
- **Fix:** Wrap handleRemoveSeat in a confirm() (or a modal) naming the teammate: 'Remove teammate@company.com from your team? They will lose access immediately.'
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — Add-key Save button is not disabled during the save request — allows duplicate submissions
- **Where:** `frontend/src/components/byok/APIKeyManager.tsx:89-116, 253-259` · route `/byok`
- **Problem:** The 'Validate and Save' button is disabled only while `validating` is true. validateAPIKey sets validating back to false before the subsequent POST to /api/byok/api-keys runs, so during the actual save the button is fully enabled and still reads 'Validate and Save'. A user (or an impatient double-click) can fire multiple create requests, producing duplicate keys, and gets no loading feedback during the save leg.
- **Fix:** Introduce a single `saving`/`submitting` state that stays true across both validation and the POST; disable the button and show 'Saving…' for the whole operation.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — Add-key modal lacks accessibility and dismissal basics
- **Where:** `frontend/src/components/byok/APIKeyManager.tsx:206-263` · route `/byok`
- **Problem:** The provider modal is a bare div with no role="dialog"/aria-modal, no focus trap, no autofocus on the first field, no Escape-to-close, and clicking the backdrop overlay does not dismiss it. Keyboard users can tab out of the dialog into the page behind it, and there is no standard way to close it besides the Cancel button. This is a focus/keyboard trap-adjacent accessibility gap on a security-sensitive form.
- **Fix:** Add role="dialog" aria-modal="true" with a labelled heading, trap focus within the modal, autofocus the provider select, close on Escape, and close on backdrop click.
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — Connecting an integration full-page-redirects and silently discards unsaved notification toggles
- **Where:** `frontend/src/app/settings/page.tsx:196-240, 563-657` · route `/settings`
- **Problem:** handleConnectGitHub/Zotero/Mendeley/Dropbox navigate away via window.location.href to the backend OAuth flow. Notification preferences on the same page are edit-then-explicit-Save (no autosave). If a user flips a notification toggle and then clicks 'Connect GitHub' before saving, the toggle changes are lost with no warning. The two subsystems share one page but have incompatible persistence models.
- **Fix:** Either autosave notification prefs on toggle (optimistic PATCH), or warn/prompt before navigating away with unsaved pref changes. Prefer opening OAuth in a popup (as Zotero/Mendeley already postMessage back) so the settings page state is preserved.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — Notification preferences have no autosave and no unsaved-changes indication
- **Where:** `frontend/src/app/settings/page.tsx:561-657` · route `/settings`
- **Problem:** Toggling 'Job completion emails' or 'Weekly digest' mutates local state only; changes persist only after clicking 'Save preferences'. There is no dirty-state indicator, so a user who toggles and navigates away (very likely given the toggles look like instant switches) silently loses the change and believes it was applied. Toggle switches strongly imply immediate effect.
- **Fix:** Autosave on toggle with an inline 'Saved' confirmation, or show a persistent 'You have unsaved changes' bar with the Save button, and warn on navigation while dirty.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — Settings page shows no signed-out state — renders empty/default cards to logged-out users
- **Where:** `frontend/src/app/settings/page.tsx:81-131, 256-263` · route `/settings`
- **Problem:** Unlike /byok and /developer which redirect unauthenticated users to /login, /settings just stops its loaders when !sessionData and renders every integration as 'not connected' plus default notification prefs. A signed-out visitor sees Connect buttons that redirect into backend OAuth (which needs an auth token) and a Save button that will fail. There is no 'Sign in to manage settings' gate.
- **Fix:** When the session resolves to null, render a sign-in prompt (link to /login?next=/settings) in place of the cards, matching the pattern used by the developer and BYOK pages.
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — Usage chart has no empty state
- **Where:** `frontend/src/app/developer/page.tsx:283-299` · route `/developer`
- **Problem:** When usage.history is empty (a brand-new key, or a plan with no recorded activity), the 'Usage' column renders the header and 'Current plan …' line followed by a completely blank area with no bars and no message. The user can't tell whether data failed to load, is still loading, or is genuinely empty.
- **Fix:** Render an explicit empty state ('No API requests yet — your daily usage will appear here') when usage.history has no entries.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — Six plans as separate cards make head-to-head comparison hard
- **Where:** `frontend/src/app/billing/page.tsx:428-441` · route `/billing`
- **Problem:** With monthly showing free/basic/pro/byok/student/team, users get six independent cards each repeating the same feature labels, forcing them to scan back and forth to compare 'AI optimizations' or 'History retention' across tiers. There is no comparison table and no clear delineation of what each higher tier adds over the previous one.
- **Fix:** Add a compact feature-comparison table (features as rows, plans as columns) beneath or as a toggle alongside the cards, and/or annotate each card with 'Everything in X, plus…' to clarify the upgrade path.
- **Status:** ✅ Fixed

#### 🟡 Low · 🐛 Bug — OAuth success query params are never cleared, so a refresh re-fires the success toast
- **Where:** `frontend/src/app/settings/page.tsx:134-164` · route `/settings`
- **Problem:** After returning from OAuth with ?github=connected (or dropbox/zotero/mendeley), the success banner shows for 5s but the query string is left in the URL. Reloading or sharing the URL re-triggers the 'connected successfully' message even though no new connection happened, which is misleading.
- **Fix:** After handling the connected param, strip it with router.replace(pathname) / history.replaceState so a refresh doesn't replay the success state.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Monthly/Annual toggle is not exposed as a proper control to assistive tech
- **Where:** `frontend/src/app/billing/page.tsx:375-388` · route `/billing`
- **Problem:** The billing-period switch is two plain <button>s that only reflect state via background color. There is no role, aria-pressed, or grouping, so screen-reader users get no indication of which period is currently selected. The '20% off' savings is also only mentioned in body copy, not tied to the Annual button.
- **Fix:** Use a radiogroup or aria-pressed on each button (aria-pressed={billingPeriod==='annual'}), group them with an accessible label ('Billing period'), and add a 'Save 20%' badge on the Annual option.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Free plan shows 'Select Plan' but selecting it only toasts 'already available'
- **Where:** `frontend/src/app/billing/page.tsx:192-195` · route `/billing`
- **Problem:** The free plan's PricingCard renders the same 'Select Plan' CTA as paid plans, but clicking it just shows toast.info('Free plan is already available.') regardless of the user's actual tier. The label implies an action; the result is a no-op message. It's also unhelpful for a user currently on a paid plan who might want to downgrade.
- **Fix:** Relabel the free plan's button contextually — 'Current plan' (disabled) when on free, or 'Downgrade to Free' with a real flow when on a paid tier — rather than a generic 'Select Plan' that does nothing.
- **Status:** ✅ Fixed

#### 🟡 Low · 🐛 Bug — Empty-state can flash before keys finish loading
- **Where:** `frontend/src/components/byok/APIKeyManager.tsx:34-70, 130-132` · route `/byok`
- **Problem:** The single `loading` flag is cleared in fetchProviders' finally block, independent of fetchAPIKeys which runs in parallel and has no loading gate. If providers resolve before the keys request, the component leaves the loading state and renders 'No API Keys Yet' momentarily before the real keys pop in, making existing keys briefly appear deleted.
- **Fix:** Track both requests' loading state (or gate the key list on its own flag) so the empty state only shows after the keys request has actually resolved to an empty array.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Key validation failure gives no actionable reason
- **Where:** `frontend/src/components/byok/APIKeyManager.tsx:72-99` · route `/byok`
- **Problem:** validateAPIKey discards any error detail and returns only a boolean; addAPIKey then shows the generic 'Key validation failed for selected provider'. Users can't tell whether the key is malformed, revoked, lacks permissions, or hit a provider outage — leaving them to guess how to fix it.
- **Fix:** Surface the backend's validation error message/reason when available (e.g. 'Invalid API key', 'Insufficient quota') instead of a single catch-all string.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Rename button is always enabled, firing no-op saves for unchanged names
- **Where:** `frontend/src/app/developer/page.tsx:125-137, 255-261` · route `/developer`
- **Problem:** The per-key Rename button is only disabled while busy; it stays enabled when the field equals the current name or is unchanged, so clicking it issues a pointless rename request and a 'Key renamed' toast even though nothing changed. There's also no disabled state when the field is empty (handleRename returns early but the button still looks actionable).
- **Fix:** Disable Rename when the trimmed value is empty or equals key.name, so it only acts on a genuine change.
- **Status:** ✅ Fixed


### Global / Cross-cutting (21)

#### 🔴 High · 🐛 Bug — No skip-to-content link — keyboard users tab through full nav on every page
- **Where:** `src/app/layout.tsx:70-77` · route `all`
- **Problem:** The root layout (src/app/layout.tsx) renders GlobalHeader before <main>, but <main> has no id and there is no skip link. Keyboard and screen-reader users must tab through the logo, every nav item, theme toggle, install button, and account menu on every single page before reaching page content. This is a WCAG 2.4.1 (Bypass Blocks) failure.
- **Fix:** Add a visually-hidden-until-focused anchor as the first child of <body>: <a href="#main-content" class="sr-only focus:not-sr-only ...">Skip to content</a>, and give <main> id="main-content" tabindex="-1". Style it to appear on focus.
- **Status:** ✅ Fixed

#### 🔴 High · 🐛 Bug — No themed error.tsx / global-error.tsx — runtime errors show Next's unstyled default
- **Where:** `src/app/ (missing error.tsx, global-error.tsx)` · route `all`
- **Problem:** Only not-found.tsx is themed. There is no app/error.tsx or app/global-error.tsx, so any client-side render error drops the user onto Next.js's default bare error page with no branding, no theme tokens, and no recovery action beyond a raw reset. The careful design system disappears exactly when a user is already frustrated.
- **Fix:** Add app/error.tsx (route-level) and app/global-error.tsx (root) mirroring not-found.tsx's token-based styling, with a 'Try again' button wired to the reset() callback plus a 'Back home' link.
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — Active nav state is color-only and breaks on nested routes
- **Where:** `src/components/GlobalHeader.tsx:110-120` · route `all`
- **Problem:** In GlobalHeader desktop nav (line 110-118) the active item is signalled solely by text-accent-strong vs text-fg-2 — a color-only cue that fails WCAG 1.4.1 (Use of Color) and reads as weak hierarchy. It also uses strict equality `pathname === item.href`, so nested routes like /tracker/123 or /templates/foo never highlight their parent nav item, leaving the user with no 'you are here' indicator.
- **Fix:** Add a non-color active affordance (underline/indicator bar or aria-current='page' with bold weight) and match with startsWith for section roots (e.g. pathname === href || pathname.startsWith(href + '/')).
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — Mobile nav has no active-page indicator
- **Where:** `src/components/GlobalHeader.tsx:233-242` · route `all`
- **Problem:** The mobile menu maps activeNav (lines 233-242) without ever computing `active`, so on phones there is zero indication of which page the user is currently on — every item looks identical. The desktop nav at least sets an active color.
- **Fix:** Compute active in the mobile map the same way as desktop and apply an active class (color + weight + aria-current='page').
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — Header nav links, footer links, and account-menu items have no focus-visible style
- **Where:** `src/components/GlobalHeader.tsx:99,115; src/components/marketing/MarketingFooter.tsx:25-28` · route `all`
- **Problem:** There is no global :focus-visible rule in globals.css/design-tokens.css. The desktop nav Links (GlobalHeader 112-118), the account-menu links via the `menuLink` class (line 99 — only hover states), and all MarketingFooter links (25-28) define only hover transitions and no focus-visible ring/underline. Keyboard users get no visible focus indicator on the primary navigation, a WCAG 2.4.7 failure. (Buttons like the account trigger do have rings, so it's inconsistent.)
- **Fix:** Add a global :focus-visible outline in design-tokens.css (e.g. outline: 2px solid var(--focus); outline-offset: 2px) and/or append focus-visible:ring utilities to menuLink, nav Links, and footer Links.
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — Theme toggle is unreachable on fullscreen editor surfaces
- **Where:** `src/components/GlobalHeader.tsx:34,60-62; src/components/theme/ModeToggle.tsx` · route `/try, /workspace/[id]/edit, /optimize`
- **Problem:** GlobalHeader returns null for /try, /workspace/[id]/edit, /optimize, and /cover-letter (fullscreenPatterns, line 34/60). ModeToggle lives only in the header, so on exactly the pages where users spend the most time (the Studio and editors) there is no way to switch light/dark unless those pages ship their own toggle. A user who set dark mode is fine, but one who wants to change it while editing is stuck.
- **Fix:** Ensure each fullscreen editor surface renders its own ModeToggle in its local chrome, or keep a minimal persistent control (toggle + logo/back) even on fullscreen routes.
- **Status:** ✅ Fixed — a theme toggle now renders in the edit, optimize, and cover-letter headers.

#### 🟠 Medium · 🐛 Bug — Global toast auto-dismiss of 1.5s is too short to read
- **Where:** `src/app/layout.tsx:78-85` · route `all`
- **Problem:** The Sonner <Toaster> in layout.tsx sets duration={1500}. 1.5 seconds is below the readable threshold for most notifications and far too short for error messages — users routinely miss confirmations and, worse, error explanations before they can react. It also disadvantages users with cognitive or motor impairments.
- **Fix:** Raise the default to ~4000ms, and make error toasts persist until dismissed (duration: Infinity for error variants). Ensure toasts are keyboard-dismissible and announced via aria-live (Sonner handles the latter).
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — Framer-motion menu animations ignore prefers-reduced-motion
- **Where:** `src/components/GlobalHeader.tsx:162-168,224-231` · route `all`
- **Problem:** The reduced-motion block in design-tokens.css (108-117) only overrides CSS animation/transition durations. The account dropdown and mobile menu use framer-motion (JS/Web Animations API), which is not affected by that CSS. So users who requested reduced motion still get the scale/slide/height animations on the dropdown (162-168) and mobile menu (226-231).
- **Fix:** Gate framer-motion with useReducedMotion() from framer-motion (or wrap in MotionConfig reducedMotion='user') and skip/instant the initial/animate/exit transforms when the user prefers reduced motion.
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — Account dropdown does not move or trap focus / support arrow keys
- **Where:** `src/components/GlobalHeader.tsx:153-194` · route `all`
- **Problem:** The account menu has role='menu' and closes on Escape, but focus is never moved into the menu when it opens, items use no roving tabindex/arrow-key navigation, and focus is not returned to the trigger on close. Screen-reader users hear 'menu' but keyboard interaction doesn't follow the menu pattern; focus can also escape behind the fixed overlay backdrop.
- **Fix:** On open, focus the first menu item; implement Up/Down/Home/End roving focus and Tab-to-close; on close, return focus to the trigger button. Consider a headless menu primitive (Radix/Headless UI) to get this for free.
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — Mobile menu doesn't trap focus, lock scroll, or close on back navigation
- **Where:** `src/components/GlobalHeader.tsx:51-58,224-265` · route `all`
- **Problem:** The mobile menu (224-265) only closes via each link's onClick or the toggle. It doesn't trap focus (tab can move to content behind it), doesn't lock body scroll while open, has no Escape-to-close (the Escape handler at line 51-58 only covers the account menu), and won't auto-close on browser back/forward. On a small screen this is a mild focus/interaction trap.
- **Fix:** Add Escape-to-close and a route-change effect that closes the menu; trap focus within the panel and lock body scroll while open (or close it on pathname change via useEffect).
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — Footer has no legal/company links (Privacy, Terms, Contact, copyright)
- **Where:** `src/components/marketing/MarketingFooter.tsx:17-37` · route `marketing + app`
- **Problem:** MarketingFooter (17-37) lists only product nav (Platform/Resources/Updates/FAQ) plus an 'Open Studio' CTA. For a SaaS that handles accounts, payments (Razorpay), and user resume data, the absence of Privacy Policy, Terms of Service, Contact/Support, and a copyright line is a trust and (likely) compliance gap. It's also entirely hidden on all app surfaces, so authenticated users never see legal links anywhere.
- **Fix:** Add a footer row with Privacy, Terms, Security/Status, Contact, and a © line. Consider a slim legal-links strip that also renders (or is linked from account menu) on app surfaces.
- **Status:** ✅ Fixed — the footer now links Privacy (`/privacy`), Terms (`/terms`), and Contact; both legal pages were added (SSG).

#### 🟠 Medium · ✨ Improvement — Skeletons announce nothing to assistive tech during loading
- **Where:** `src/components/ui/Skeleton.tsx:3-41` · route `all (loading states)`
- **Problem:** Skeleton/CardSkeleton/ResumeCardSkeleton (src/components/ui/Skeleton.tsx) are purely visual animate-pulse divs with no role='status', aria-busy, or visually-hidden 'Loading…' text. Screen-reader users get silence during loads instead of a loading announcement, and the decorative shapes aren't marked aria-hidden.
- **Fix:** Wrap skeleton groups in a container with role='status' aria-live='polite' aria-busy='true' plus an sr-only 'Loading…' label, and mark the shape divs aria-hidden='true'.
- **Status:** ✅ Fixed

#### 🟠 Medium · 🐛 Bug — Onboarding modal lacks dialog semantics, focus trap, and Escape/backdrop close
- **Where:** `src/components/onboarding/OnboardingFlow.tsx:243-251` · route `/workspace (OnboardingFlow modal)`
- **Problem:** The modal is a fixed inset-0 overlay with no role='dialog', aria-modal='true', or aria-labelledby. There is no focus management (focus is not moved into the dialog on open, not trapped, not restored on close), no Escape-to-close handler, and clicking the backdrop overlay does not dismiss it. Keyboard and screen-reader users get a poor and potentially trapping experience for a full-screen modal that blocks the workspace.
- **Fix:** Add role='dialog' aria-modal='true' and aria-labelledby pointing at the step title. On open, move focus to the dialog/close control and trap Tab within it; restore focus to the trigger on close. Add an Escape key handler and an onClick on the overlay (with stopPropagation on the inner card) that calls onSkip. Respect that onSkip persists dismissal.
- **Status:** ✅ Fixed

#### 🟠 Medium · ✨ Improvement — Editor/PDF splitter is mouse-only: no keyboard support, no double-click reset, hard to grab
- **Where:** `frontend/src/app/try/page.tsx:786-791, 173-184` · route `/try`
- **Problem:** The resize splitter is a 1px-wide div driven purely by mousedown/mousemove. It has no role='separator', no aria-valuenow, no tabindex, and cannot be adjusted from the keyboard — a focus/operability gap for keyboard and AT users. There is also no double-click-to-reset-to-50% and the 1px hit target is very hard to grab with a mouse. Touch devices get nothing (they fall back to pane switching, which is fine, but desktop keyboard users are stuck).
- **Fix:** Give the splitter role='separator', aria-orientation='vertical', tabindex=0 and arrow-key handling to nudge the split; widen the hit area (e.g. an invisible padded grab zone) and add double-click to reset to 50%.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Theme mode is device-local only (cookie), not synced to the account
- **Where:** `src/components/theme/ThemeProvider.tsx:42-49` · route `all`
- **Problem:** ThemeProvider persists mode to the latexy-theme cookie (per-browser) only. A signed-in user who picks dark mode on their laptop starts in OS-default on their phone. For an authenticated product, theme preference is a natural account setting.
- **Fix:** On toggle, persist mode to the user profile via the API when authenticated, and hydrate from it on login so the preference follows the account across devices.
- **Status:** ✅ Fixed

#### 🟡 Low · 🐛 Bug — ModeToggle icon can flash the wrong glyph on first paint
- **Where:** `src/components/theme/ThemeProvider.tsx:34-40; src/components/theme/ModeToggle.tsx:19-20` · route `all`
- **Problem:** The pre-paint script sets data-mode correctly, but ThemeProvider initializes React state to 'light' and only reads the real mode in a post-mount effect (35-40). So on a dark-cookie load, ModeToggle first renders the Moon (light-mode) icon, then swaps to Sun after hydration — a visible icon flip. aria-label flips with it too.
- **Fix:** Read the already-applied data-mode attribute lazily in useState initializer (guarded for SSR) so the first client render matches the pre-paint mode, or render the icon from a CSS-driven approach.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Logo always routes to marketing home even when signed in
- **Where:** `src/components/GlobalHeader.tsx:104-106` · route `all`
- **Problem:** The GlobalHeader logo Link always targets '/' (line 104). For an authenticated user on the dashboard/workspace, clicking the logo drops them onto the public marketing landing page rather than their app home (dashboard), which is the conventional and expected behavior.
- **Fix:** Route the logo to '/dashboard' (or '/workspace') when isAuthenticated, and to '/' for guests.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — 404 page inherits the wrong aesthetic (compiler) for unknown paths
- **Where:** `src/app/layout.tsx:41-50; src/app/not-found.tsx` · route `404`
- **Problem:** The pre-paint script (layout.tsx 41-50) assigns data-aesthetic by matching pathname against a typeset whitelist; any unrecognized path (i.e. exactly the 404 cases) falls through to 'compiler', so the marketing-styled not-found page renders in the compiler dark-orange aesthetic instead of the typeset look its copy/design imply — an inconsistent brand moment.
- **Fix:** Have not-found.tsx force data-aesthetic='typeset' (e.g. via a small inline script or wrapper attribute), or default unknown paths to 'typeset' in the bootstrap script.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Sign Out gives no pending feedback during async cleanup
- **Where:** `src/components/GlobalHeader.tsx:86-96,185-190` · route `all`
- **Problem:** handleSignOut (GlobalHeader 86-96) awaits clearAllDrafts/clearCompileQueue then signOut then a full-page redirect, but the Sign Out button shows no loading/disabled state. On a slow device the menu just sits there after the click, inviting a second click.
- **Fix:** Add a signing-out state that disables the button and shows a spinner/'Signing out…' label until the redirect fires.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — No root loading.tsx for route-level transitions
- **Where:** `src/app/ (missing loading.tsx)` · route `all`
- **Problem:** There is no app/loading.tsx, so cross-route navigations that suspend show no global loading affordance — the previous page just hangs until the next renders. Per-page skeletons exist but there is no consistent top-level transition indicator.
- **Fix:** Add a lightweight app/loading.tsx (e.g. a top progress bar or centered spinner using tokens) for route-level Suspense fallbacks.
- **Status:** ✅ Fixed

#### 🟡 Low · ✨ Improvement — Pervasive 10-11px muted (text-fg-3) micro-copy strains readability and contrast
- **Where:** `frontend/src/app/try/page.tsx:373, 587, 719; frontend/src/components/LaTeXEditor.tsx:1792` · route `/try`
- **Problem:** Panel headers, status bar, page-count badges, the 'trials N' counter, and shortcut hints are rendered at text-[10px]/[11px] in the lowest-contrast token (text-fg-3), often uppercase with wide letter-spacing. This is below comfortable reading size and likely fails WCAG AA contrast for small text against surface backgrounds, affecting low-vision users and anyone on a high-DPI laptop.
- **Fix:** Bump the smallest interactive/labels to ~12px, reserve 10px for truly secondary decoration, and verify text-fg-3 on surface/surface-2 meets AA contrast; increase weight or darken the token where it fails.
- **Status:** ✅ Fixed


### Other (3)

#### 🔴 High · 🐛 Bug — Optimize streams overwrite the live editor with no read-only lock and constant scroll-jerk
- **Where:** `frontend/src/app/try/page.tsx:115-122, 590-601` · route `/try`
- **Problem:** During an optimize job, the streamingLatex effect calls editorRef.setValue(...) on every token, and LaTeXEditor.setValue() also revealLine(getLineCount()) each time — so the editor auto-scrolls to the bottom on every token, making it impossible to read. Worse, readOnly is never passed, so the editor stays editable while being externally overwritten: any keystroke a user makes mid-optimization is clobbered by the next token. The status bar's 'Read-only — job running' state is never shown because readOnly is always false here.
- **Fix:** Pass readOnly={isProcessing} while a job runs so the buffer is locked and clearly labeled. Avoid revealLine on streaming updates (only reveal on final completion), or append without forcing scroll if the user has scrolled up.
- **Status:** ✅ Fixed — streaming updates pass `{ reveal: false }`, so the viewport no longer jerks to the bottom on every token.

#### 🔴 High · ✨ Improvement — AI optimization is destructive: no diff, no per-change accept/reject, no revert to original
- **Where:** `frontend/src/app/try/page.tsx:116-120, 466-490` · route `/try`
- **Problem:** When optimize completes, the new LaTeX fully replaces the editor content and the original is gone (only Monaco undo could recover it). The 'changes applied' list (lines 466-490) is a read-only summary with no diff view, no way to accept/reject individual changes, and no 'Revert to original' button. This contradicts the intended 'changes review' UX — the user cannot see what actually changed line-by-line or selectively undo one edit. It also only renders inside the AI panel, so if the user is on any other tool they never see that changes were made.
- **Fix:** Snapshot the pre-optimize content and offer a 'Revert' button plus a diff view (original vs optimized). At minimum, surface a toast/badge pointing to the changes list, and let each change item highlight/jump to its edited line.
- **Status:** ✅ Fixed — `/try` now keeps the pre-optimize snapshot with **View diff** and **Revert to original** controls.

#### 🟠 Medium · 🐛 Bug — 'Clear' wipes the entire document with no confirmation
- **Where:** `frontend/src/app/try/page.tsx:364, 402-404` · route `/try`
- **Problem:** The Clear button calls clearEditor() which sets content to '' immediately. Combined with no persistence, a mis-click destroys the user's resume with only Monaco undo (which is lost on reload) as recovery. Reset (to demo template) is similarly unguarded. There is no confirmation on either destructive action.
- **Fix:** Add a confirm step (or an inline undo toast — 'Cleared · Undo') for Clear and Reset, especially since there is no persistent backup of the user's content.
- **Status:** ✅ Fixed

