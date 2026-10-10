Implement bounded per-document auxiliary state, serialized across worker processes, invalidated by engine/preamble/assets/settings dependencies with TTL/cleanup. Certify simple resume one-pass templates and handle cross-reference/bibliography convergence conservatively.

Acceptance: process ownership/cancellation fences survive retries, hostile auxiliary files cannot escape sandbox, simultaneous revisions serialize, ordinary/heavy fixtures use correct pass policies, benchmarks report actual TeX and end-to-end spans.
