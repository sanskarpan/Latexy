#!/usr/bin/env bash
set -euo pipefail

# Keep public product copy from drifting back to ATS-emulation, outcome-
# prediction, or stale hard-coded catalog claims. The product may describe its
# own heuristic checks, but it must not claim to reproduce employer systems.
claim_roots=(frontend/src/app frontend/src/components frontend/src/lib README.md)
forbidden='exactly what an ATS parser reads|see what an ATS reads|should pass most automated screening systems|highly ATS-compatible|ATS-safe|ATS-friendly|measurable ATS performance|147 templates|[0-9]+\+? templates'

if rg --line-number --ignore-case --regexp "$forbidden" "${claim_roots[@]}"; then
  echo "Unsubstantiated or stale public marketing claim detected." >&2
  exit 1
fi

echo "Public marketing claim guard passed."
