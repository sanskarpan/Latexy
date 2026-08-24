#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# no-session-recording.sh — CI guard for the "no session recording" principle.
#
# Part D of docs/FEATURES.md commits Latexy to NOT running session-recording or
# heatmap SDKs on document-editing surfaces. LiveCareer and peers load Microsoft
# Clarity, Inspectlet and Qualaroo — keystroke-level capture on pages where users
# type their name, address, phone number and employment history. We refuse that.
#
# The distinction, for whoever revisits this: product analytics on *navigation*
# is defensible; capturing *input* on a PII-bearing document is not. This guard
# fails the build if a known session-recording / heatmap SDK is introduced, so a
# future analytics decision cannot quietly reintroduce one. (#1410)
#
# It matches SDK-specific tokens (load URLs, init globals), NOT bare vendor words,
# so ordinary identifiers like `bullet_clarity` do not trip it.
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SCAN_DIR="$REPO_ROOT/frontend"

# Directories that hold shipped client code. Tests may legitimately reference a
# vendor name (e.g. to assert it is absent), so they are excluded from the scan.
TARGETS=(
  "$SCAN_DIR/src"
  "$SCAN_DIR/public"
)

# SDK-specific signatures. Each entry is an extended-regex fragment matched
# case-insensitively. Keep these tight enough to avoid English-word collisions.
PATTERNS=(
  'clarity\.ms'                 # Microsoft Clarity tag host
  'clarity\(["'\''](set|identify|consent|event|start)' # Clarity JS API
  'static\.hotjar\.com'         # Hotjar loader
  '_hjSettings'                 # Hotjar bootstrap global
  '\bhj\(["'\'']'               # Hotjar command queue call
  'fullstory\.com'              # FullStory loader
  "window\\['_fs_"              # FullStory global
  '\bFS\.(identify|event|setUserVars)\b' # FullStory JS API
  'inspectlet'                  # Inspectlet
  '__insp\b'                    # Inspectlet global
  'cdn\.logrocket'              # LogRocket loader
  '\bLogRocket\.(init|identify)\b' # LogRocket JS API
  'qualaroo'                    # Qualaroo
  'smartlook'                   # Smartlook
  'mouseflow'                   # Mouseflow
  '_mfq\b'                      # Mouseflow queue global
)

echo "🔒 Scanning shipped frontend code for session-recording / heatmap SDKs…"

existing_targets=()
for t in "${TARGETS[@]}"; do
  [ -d "$t" ] && existing_targets+=("$t")
done

if [ ${#existing_targets[@]} -eq 0 ]; then
  echo "No frontend source directories found to scan — nothing to check." >&2
  exit 0
fi

hits=0
for pat in "${PATTERNS[@]}"; do
  # --include limits to shipped source; exclude test files (they may name a vendor
  # precisely to prove its absence).
  if matches=$(grep -rniE "$pat" "${existing_targets[@]}" \
        --include='*.ts' --include='*.tsx' --include='*.js' \
        --include='*.jsx' --include='*.html' \
        2>/dev/null \
        | grep -viE '(/__tests__/|\.test\.|\.spec\.|no-session-recording)'); then
    echo "❌ Forbidden session-recording SDK signature found (/$pat/):" >&2
    echo "$matches" >&2
    hits=$((hits + 1))
  fi
done

if [ "$hits" -gt 0 ]; then
  echo >&2
  echo "Session recording captures user input on PII-bearing document pages and is" >&2
  echo "prohibited (see docs/FEATURES.md Part D, issue #1410). Remove the SDK." >&2
  exit 1
fi

echo "✅ No session-recording / heatmap SDKs found. Principle upheld."
