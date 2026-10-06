#!/usr/bin/env bash
set -euo pipefail

# Keep public product copy from drifting back to ATS-emulation, outcome-
# prediction, or stale hard-coded catalog claims. The product may describe its
# own heuristic checks, but it must not claim to reproduce employer systems.
claim_roots=(
  frontend/src/app
  frontend/src/components
  frontend/src/lib
  frontend/public/legal
  legal
  README.md
)
forbidden='exactly what an ATS parser reads|see what an ATS reads|trackers actually read|how (a |major )?ATS (platforms? )?parse|should pass most automated screening systems|higher chances of passing initial screening|perform with Applicant Tracking Systems|optimi[sz](e|es|ed|ing) for ATS|AI-powered ATS( \(Applicant Tracking System\))? resume optimizer|ATS precision|highly ATS-compatible|ATS-ready|ATS-safe|ATS-friendly|measurable ATS performance|147 templates|[0-9]+\+? templates'

if rg --line-number --ignore-case --regexp "$forbidden" "${claim_roots[@]}"; then
  echo "Unsubstantiated or stale public marketing claim detected." >&2
  exit 1
fi

echo "Public marketing claim guard passed."
