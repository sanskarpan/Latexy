# Latexy documentation map

This directory contains both current operating documentation and dated audit
evidence. A dated audit records what was true at that revision; it is not a
live backlog. When status differs, current source, green CI for the exact
revision, production probes, and the linked GitHub issue take precedence.

## Current operating documents

| Document | Purpose |
|---|---|
| [HANDOFF.md](HANDOFF.md) | Current architecture, delivery workflow, verification contract, and known external blockers |
| [local-dev.md](local-dev.md) | Supported local stacks, ports, prerequisites, and troubleshooting |
| [DATA-AND-TRAINING.md](DATA-AND-TRAINING.md) | Product data-use and model-training commitment |
| [observability/](observability/) | SLOs, telemetry, tracing, alert delivery, and incident runbooks |
| [FEATURES.md](FEATURES.md) | Feature inventory and product backlog; GitHub issue state is authoritative for completion |
| [TUI_PRD.md](TUI_PRD.md) | TUI requirements baseline plus current implementation/delivery status |
| [prd/2026-08-02-external-sources-to-resume.md](prd/2026-08-02-external-sources-to-resume.md) | External-source import specification and shipped-status reconciliation |
| [prd/2026-08-02-input-driven-optimization.md](prd/2026-08-02-input-driven-optimization.md) | Collaborative optimization specification and shipped-status reconciliation |
| [qa/issues.md](qa/issues.md) | Historical August QA register with explicit current-resolution notes |

The active senior-QA remediation tracker is GitHub issue
[#1621](https://github.com/sanskarpan/Latexy/issues/1621). Each unresolved
operational dependency has its own linked issue; credentials never belong in a
document, issue, commit, test log, or PR description.

## Historical evidence and design records

The following are intentionally preserved as point-in-time evidence. Their
findings, counts, URLs, commands, and deployment assumptions must not be quoted
as current without revalidation:

- `AUDIT-*`, `FINAL_REPORT.md`, `FIXES.md`, `ISSUES.md`, `TEST_RESULTS.md`,
  `BENCHMARKS.md`, `GAPS_ISSUES.md`, and `AUDIT_LOG.md`
- `audit-f*.md`, `mobile-responsive-audit-2026-07.md`, `audit-artifacts/`, and
  `qa/ux-improvements.md`
- dated handoffs such as `HANDOFF-2026-08-22.md`
- `superpowers/plans/`, `superpowers/specs/`, and dated design proposals
- `FEATURES-2026-07-legacy.md`, retained for feature-catalog reconciliation

Historical documents remain useful for provenance and regression ideas. A
claim becomes current only after it is reproduced against the present code or
live environment.

## Maintenance rules

1. Put changing operational guidance in an undated canonical document and link
   dated snapshots to it.
2. Mark requirements as `shipped`, `partial`, `blocked`, or `planned`, and link
   implementation evidence and the controlling issue.
3. Treat GitHub issue/PR state and exact-revision CI/deployment evidence as the
   completion record; do not copy mutable issue counts into handoffs.
4. Never store passwords, session tokens, API keys, or replacement credentials
   in tracked files. CI enforces this for documented account pairs.
5. Revalidate external provider state (npm, billing, quotas, OAuth settings)
   before changing a blocked item to shipped.
