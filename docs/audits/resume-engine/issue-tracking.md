Implement docs/RESUME_ENGINE_ARCHITECTURE.md on codex/resume-engine in the isolated managed worktree. Track all stages and integrate only verified behavior. Existing #1809 (preview scheduling) and #1810 (source/PDF navigation) are dependencies.

Acceptance:
- Durable binary artifacts and revision-scoped early preview, preserving authoritative export and tenant authorization.
- Shared versioned documents, source facts, JD context, bounded provider optimization and durable stage recovery.
- Latest-only preview scheduling and exact-PDF semantic editing with candidate acceptance guards.
- End-to-end measurements, certified fixture matrix, cancellation/security/quota regression coverage.
- Incremental commits, rebase latest main, reviewed PR with passing checks before merge.
- Report actual warm/cold/cache/load measurements; do not equate targets with observed performance.
