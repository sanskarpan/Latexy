# Latency & cost architecture - Claude Opus 5.5 review

**Model:** `claude-opus-5-5` (Anthropic API), 2026-11-27.
**Role:** independent principal infrastructure architect; research only, no code/deploy.
**Input:** production measurements + the DeepSeek V4 Pro plan in `latency-advisor.md`.

---

# Latexy compile pipeline: independent architecture review

## 1. Verdict

The plan diagnoses the problem correctly. It sequences the work poorly, overstates some impacts, and misses several mechanisms that will decide success.

**Right**
- **No single fix reaches 12s.** The stage p50s sum to about 20.7s.
  - Reaching ≤12s needs roughly 8.7s removed.
  - Only pdflatex (9.16s) and finalize plus upload (6.7s) are large enough to supply it.
- **The 1.197s-compile job still spent 24.2s in finalize windows.** This proves finalize cost is independent of compile speed. Option 1 is necessary.
- **Never emit `job.completed` before the durable commit.** Pairing the warm pool with admission control is also correct.

**Wrong or overstated**
- **"Either lever alone gets ~13–15s" is wrong for finalize alone.**
  - Finalize alone gives roughly 20.7 − 4.7 = 16s.
  - CPU alone gives roughly 20.7 − 6 to 7 = about 14s, assuming pdflatex drops to 2–3s.
  - The 2–3s pdflatex figure is an estimate, not a measurement.
- **The 17.6× spread is attributed to CPU without ruling out alternatives.**
  - Modal lazily loads image layers. A cold page cache for the ~1.7GB TeX Live image (fonts, `.fmt` files, `.tfm` files) would produce the same signature.
  - Raising CPU does not fix a cold filesystem. Treat CPU as a hypothesis until cgroup throttling counters confirm it.
- **The idle-pool cost of $0.75/mo per container was likely computed at the default 0.125 core.**
  - With `cpu=1.0`, reserved idle capacity costs more.
  - Recompute it from Modal pricing before choosing `min`/`buffer` values.
- **Batching `log.line` events is a cost item, not a latency item.**
  - Publish was measured at under 1 ms.
  - The −0.5 to −1s claim has no measurement behind it.
- **Retry policy (#9) is an LLM-cost workstream.** It is out of scope for this latency window.

**Under-specified**
- **Option 1, "pooled async engine per worker process," hides a trap.**
  - The NullPool exists because `register_manifest` runs via `asyncio.run` per call. A pooled asyncpg engine across separate `asyncio.run` loops fails with "attached to a different loop."
  - The fix is a persistent loop per worker, or a sync pooled engine.
  - If Neon's PgBouncer pooler is used, session-level advisory locks break in transaction mode. They must become `pg_advisory_xact_lock`.
- **The pass count is unknown.** Nobody has verified whether `converge` actually needs pass 2 for a typical resume.
- **The sample sizes are too small for p95.** With n=5–6 warm runs, "p95" is effectively the max. All p95 claims are unestablished.
- **The plan text is truncated.** §3.2 cuts off mid-lifecycle, and the "§4 Phase-0" it references is missing. Phase 0 is the most important part and is not written.

## 2. Top 5 decisions, in execution order

All impact figures below are estimates to be confirmed by the metric listed.

| # | Decision | Expected impact | Effort | Risk | Proof metric |
|---|---|---|---|---|---|
| 1 | **Stage instrumentation** (see §3) | None directly; it gates everything else | 3–4 d | None | ≥95% of submit→terminal wall time attributed to named spans, n≥200 |
| 2 | **Explicit CPU/memory plus container warm-up** (`MODAL_LATEX_CPU=1.0`, `MODAL_LATEX_MEMORY=2048`, plus an enter-hook dummy compile to warm fonts/`.fmt`) | pdflatex p50 9.2 → ≤3s est.; collapses p95 spread; warm p50 to ~14s | 1–2 d | Low (idle cost rises) | pdflatex stage p50/p95, plus `cpu.stat nr_throttled` ≈ 0 |
| 3 | **Finalize stage A, no transaction restructuring:**<br>• persistent loop plus pooled connection<br>• geometry and `pdftotext` run in parallel with R2 PUTs<br>• drop redundant HEADs (see §4)<br>• no 0.5s sleep retries on the success path | 6.7 → ~2.5–3s est.; warm p50 to ~10–11s | 1–1.5 w | Medium | 90%-progress → `job.completed` p50 ≤2.5s, p95 ≤5s |
| 4 | **Warm pool plus admission control:**<br>• `min=2`, `buffer=2`, explicit `max`<br>• visible queue position or 429<br>• spawn backlog on `/jobs/health` | Removes 12.8s (p99 21.6s) acquisition for bursts within pool size; 5-concurrent p50 → ≤25s | 1 w | Low–Med | % of jobs with cold acquisition; accepted→started p95 |
| 5 | **Client-perceived path:**<br>• API-side cache short-circuit<br>• presigned URL in the terminal event, plus R2 CORS<br>• preview semantics | Removes the `/download` round trip (p50 2.14s); identical resubmits return near-instantly | 1.5–2 w | Medium (contract changes) | Client submit→first PDF paint p50 (not server time) |

**Finalize stage B** (a single transaction for arbiter, manifest and Compilation row) happens only if stage A misses 2s. It is the highest-risk change in the plan. Do not lead with it, as the plan does.

## 3. First two weeks

**Days 1–3: measure, change nothing.**
- **Per-stage spans in `latex_worker.py`.** Emit timestamps around:
  - each pdflatex pass, with the pass count recorded;
  - each R2 PUT and HEAD;
  - each DB connect (separate TCP/TLS from query time);
  - each advisory-lock wait;
  - the geometry and `pdftotext` subprocesses.
- **CPU evidence without the Modal console.** Read `/sys/fs/cgroup/cpu.stat` (`usage_usec`, `nr_throttled`, `throttled_usec`) before and after pdflatex.
- **Container cold/warm flag.** Record whether this is the container's first, second, or later task. This separates page-cache warmup from CPU starvation.
- **Cache visibility.** Log the compile-cache hit/miss and the key components.
- **Separate claim from queue.** Split Modal claim from queue wait using spawn timestamp vs `run_latex_task` entry.
- **Baseline run.** Collect n≥200 warm 1-page, n≥100 10-page, and 30 bursts of 5.

**Day 4: config-only win, ship immediately.**
- **Set `MODAL_LATEX_CPU=1.0` and `MODAL_LATEX_MEMORY=2048`.**
  - These are read at decorator evaluation, so a redeploy is required.
  - Verify the deployed function's actual resource spec.
  - It is reversible in minutes, and cost is non-binding.
- **Re-run the day 1–3 matrix.**
  - If `throttled_usec` drops but first-task-in-container times stay high, page cache is the cause. Add the warm-up compile in the container enter hook.

**Days 5–10: finalize stage A behind a flag.**
- Make geometry and `pdftotext` run in parallel with PUTs.
- Replace NullPool engines at `retention.py:51` and `latex_worker.py:1016` with a per-container connection on a persistent loop.
- Shadow-compare event streams and DB rows on 100% of jobs before cutover.

**Days 8–10, in parallel:**
- Expose the spawn backlog on `/jobs/health`.
- Set `min=2`/`buffer=2` only after recomputing idle cost at the new CPU reservation.

## 4. Correctness invariants

1. **Finalization is exactly-once.** The `JobFinalization` arbiter, `FOR UPDATE`, and the arbiter→Compilation→Resume lock order guard this.
   - It prevents duplicate terminal events (already observed once in the events audit).
   - It prevents double quota charge and a Compilation row overwritten by a second writer.
   - Any merged transaction must keep the lock order, or concurrent replay deadlocks.
2. **Artifact ownership and epoch.**
   - A superseded or stale owner must never overwrite the manifest of a live replacement job (`retention.py:140-155`).
   - Pooling or a PgBouncer migration must keep these locks transaction-scoped. Session locks leak across pooled sessions and silently become non-exclusive.
3. **Object existence before registration.**
   - The serialized HEADs exist because retention GC could delete content-addressed objects between PUT and register.
   - Removing them is safe only with an equivalent guarantee. One option is a GC grace period: never delete objects younger than N minutes or referenced by any manifest.
   - Without that guarantee, a manifest can point at a deleted PDF.
4. **Quota and refund.**
   - The system charges once at admission and refunds exactly once on failure.
   - The new paths must define behavior for cache hits, previews, and admission 429s. Today they are undefined.
   - Getting this wrong means either free compiles through double refunds or users charged for compiles that never ran.
5. **Share links.**
   - Shares must resolve through the manifest or a stable R2 key, never through presigned URLs.
   - Retention must treat share references as GC roots.
   - Otherwise shared resumes break after expiry or GC.
6. **Accepted-artifact recovery.**
   - If a worker dies after `artifact.ready` but before commit, recovery must bind the existing manifest rather than recompile or double-upload.
   - Moving extraction off the critical path must not make recovery depend on `pdf_extracted`.
   - Otherwise jobs strand in `finalizing` forever.
7. **No Modal retries for compile.**
   - The double-execution guard at `modal_app.py:458` stays.
   - Admission queueing must not reintroduce re-dispatch of the same job.

## 5. Benchmark and acceptance gates

**Scenario matrix**
- warm 1-page and warm 10-page
- cold single job (fresh deploy)
- bursts of 5 and 10
- identical-source resubmit (cache hit)
- invalid LaTeX (failure and refund)
- worker killed mid-finalize (recovery)
- concurrent same-resume submits (epoch)

**Sample sizes**
- n≥200 per warm scenario for p95 (target n≥1000 before any p99 claim).
- ≥30 bursts per concurrency level.
- Run across at least two time-of-day windows, because Modal host contention varies.

**Pass thresholds**

| Metric | Gate |
|---|---|
| Warm 1-page p50 | ≤12s |
| Warm 1-page p95 | ≤18s (proposed; product has no p95 target, so set one) |
| 5-concurrent p50 | ≤25s |
| Finalize p50 / p95 | ≤2s / ≤4s |
| 10-page p50 | No regression |
| Duplicate terminals, orphaned manifests, refund mismatches | Zero in fault-injection runs |

**Rollback triggers**
- Any duplicate terminal event or lock-order deadlock.
- Compile error rate up by more than 0.5 percentage points.
- p95 regression above 10% on any scenario.
- Stuck-`finalizing` count above zero for more than 10 minutes.

## 6. What the plan misses

- **Client-perceived latency.**
  - The client sees roughly server p50 + ~1.2s edge + 2.14s download, about 24s today. Nobody measures it.
  - A 1.19s `/health` p50 is far above IST→us-east-1 RTT. Suspect Modal web-endpoint routing or TLS setup per request, not geography. Test keep-alive and reused connections before buying multi-region.
- **R2 CORS for direct fetch.** PDF.js range requests need `Range` allowed and `Accept-Ranges`/`Content-Range`/`Content-Length` exposed. Otherwise the presigned-URL change fails in the browser.
- **Cache key correctness and placement.**
  - The key must include source hash, asset hashes, compiler flags (draft/preview), and the TeX image digest.
  - Short-circuit at the API before dispatch, not inside the


<!-- continuation -->

worker after container acquisition. A hit should cost one DB lookup and return the existing manifest, never a Modal spawn.
  - Never key on the template name or resume ID alone. A shared key across users needs a tenancy decision. Content-addressed objects are safe to share, but manifests and quota charges are per user.
- **Preamble format caching.**
  - Resume templates share a small set of preambles, and package loading often dominates a 1-page pdflatex run.
  - Dumping a custom `.fmt` per template (`mylatexformat` or `-ini` with `\dump`) and keying on the preamble hash could cut pass time by more than the CPU change.
  - Build the format at image-build time for known templates and lazily on the container for unknown ones. Measure the gain before committing.
- **Pass count and aux reuse.**
  - Run a second pass only when the `.aux` hash changes after pass 1. Resumes without cross-references rarely need it.
  - Optionally seed the `.aux` from the previous successful compile of the same resume.
- **Region co-location.**
  - The plan never states where Modal runs relative to the Neon primary and the R2 jurisdiction.
  - Each serialized Neon round trip across regions costs 60–80 ms. A TLS connect costs 3–4 RTTs. Finalize makes dozens of these.
  - Check whether Neon autosuspend is enabled. A suspended compute adds 300–800 ms to the first query, which looks exactly like "finalize variance."
  - Pin the Modal region to match Neon before tuning anything else in finalize.
- **Failure-path latency.**
  - Invalid LaTeX should fail fast: `-halt-on-error`, `-interaction=nonstopmode`, and a hard per-pass timeout.
  - Today a failure may wait through the full finalize and refund path. Nobody has measured time-to-error, yet it is the most common case for users editing source.
- **Cost per compile as a tracked metric.** Every lever here trades cost for latency. Without $/compile (Modal CPU-seconds, idle pool, R2 operations, Neon compute) on the same dashboard, the cost side of decision 4 is guessed rather than governed.

## 7. Build vs buy and architectural forks

**Fork A: Modal vs an always-on compile fleet (Fly Machines, ECS, or a small VM pool).**
- An always-on fleet removes cold acquisition entirely and gives control over CPU pinning and page cache.
- It also brings capacity planning, patching, and autoscaling work back onto the team.
- **Recommendation:** stay on Modal. Revisit only if, after decisions 2 and 4, either trigger fires:
  - cold acquisition still exceeds 5% of jobs at the chosen `min`/`buffer`, or
  - idle pool cost exceeds the cost of two dedicated 2-vCPU instances.
- Both triggers are measurable from the instrumentation in §3.

**Fork B: pdflatex vs Tectonic, LuaLaTeX, or a persistent TeX process.**
- Changing engines changes output: kerning, font fallback, and package compatibility. Users will notice resumes that reflow.
- A persistent "TeX server" that forks after the preamble is loaded is clever, but it is fragile and lightly maintained.
- **Recommendation:** keep pdflatex. Get the same benefit by caching the preamble `.fmt` (§6).
- Consider Tectonic only for a new template family. Gate it on pixel-diff tests against the existing corpus.

**Fork C: client-side WASM compile (SwiftLaTeX, busytex) for live preview.**
- It is attractive for keystroke-level preview and costs nothing server-side.
- Costs:
  - a 30–100 MB initial download;
  - a font and package subset that diverges from production;
  - two renderers to keep in agreement.
- **Recommendation:** defer. Revisit only after server preview semantics (decision 5) exist and usage data shows most compiles are iterative previews. Even then, label the output as an approximate preview. The authoritative PDF stays server-side.

**Fork D: database topology.**
- Options: keep Neon with direct pooled connections, move to Neon's PgBouncer endpoint, or move the finalize writes to a co-located Postgres.
- **Recommendation:** use direct pooled connections from the persistent loop, in the same region as Modal, with autosuspend disabled on the production branch.
- Do not use PgBouncer transaction mode until every advisory lock is audited and converted to `xact` (§4, invariant 2).
- Do not migrate databases for latency. The measured problem is connection churn and serialization, not Postgres.

**Fork E: object storage.**
- A Modal Volume avoids R2 PUT latency, but it gives up durable public serving, presigned URLs, and share links.
- **Recommendation:** keep R2. Parallelize the PUTs and remove redundant HEADs once the GC grace period is in place (§4, invariant 3).

**Fork F: multi-region or edge deployment.**
- **Recommendation:** no. The 1.19s `/health` latency is almost certainly per-request connection setup, not distance. Fix keep-alive first.
- Multi-region would break the exactly-once arbiter unless the database is also distributed. That is a rewrite, not a tuning change.

**Bottom line.**
- Buy nothing new. The 12s target is reachable with instrumentation, explicit resources, finalize stage A, region co-location, and preamble caching, all on the current stack.
- The forks above have measurable triggers. Revisit them only when a trigger fires, not because a vendor demo looked fast.