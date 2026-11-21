#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# analytics-privacy-guard.sh — CI guard for the analytics and replay policy.
#
# The old rule was simple: no session recording anywhere. The product now uses
# consent-based PostHog analytics and masked replay outside document surfaces.
# This guard keeps the important part of the original promise:
#
#   * no keystroke/heatmap vendors on shipped document surfaces;
#   * PostHog may only be imported through the approved wrapper;
#   * the wrapper must keep consent gating, total text masking, and the
#     `ph-no-capture` block selector;
#   * résumé editors and public document pages must keep their block markers.
#
# The distinction is deliberate: navigation analytics is defensible; capturing
# input or document content on a PII-bearing résumé page is not. (#1410)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SCAN_DIR="$REPO_ROOT/frontend"
POSTHOG_WRAPPER="$SCAN_DIR/src/lib/analytics/posthog.ts"

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

echo "🔒 Scanning shipped frontend code for prohibited capture SDKs…"

existing_targets=()
for t in "${TARGETS[@]}"; do
  [ -d "$t" ] && existing_targets+=("$t")
done

if [ ${#existing_targets[@]} -eq 0 ]; then
  echo "No frontend source directories found to scan — nothing to check." >&2
  exit 0
fi

failures=0

for pat in "${PATTERNS[@]}"; do
  if matches=$(grep -rniE "$pat" "${existing_targets[@]}" \
        --include='*.ts' --include='*.tsx' --include='*.js' \
        --include='*.jsx' --include='*.html' \
        2>/dev/null \
        | grep -viE '(/__tests__/|\.test\.|\.spec\.|no-session-recording)'); then
    echo "❌ Forbidden capture SDK signature found (/$pat/):" >&2
    echo "$matches" >&2
    failures=$((failures + 1))
  fi
done

if [ ! -f "$POSTHOG_WRAPPER" ]; then
  echo "❌ Approved PostHog wrapper is missing: ${POSTHOG_WRAPPER#$REPO_ROOT/}" >&2
  failures=$((failures + 1))
else
  # PostHog may only be imported/initialized inside the approved wrapper.
  if matches=$(grep -rniE \
        "from ['\"](posthog-js|posthog-node)|require\(['\"](posthog-js|posthog-node)|import\(['\"]posthog-js|posthog\.init\(" \
        "${existing_targets[@]}" \
        --include='*.ts' --include='*.tsx' --include='*.js' --include='*.jsx' \
        2>/dev/null \
        | grep -viE '(/__tests__/|\.test\.|\.spec\.)' \
        | grep -vF "$POSTHOG_WRAPPER"); then
    echo "❌ PostHog imported or initialized outside the approved wrapper:" >&2
    echo "$matches" >&2
    failures=$((failures + 1))
  fi

  # The wrapper must keep the privacy controls that make replay acceptable.
  required_tokens=(
    "latexy-analytics-consent"
    "disable_session_recording: true"
    "capture_pageleave: false"
    "before_send:"
    "mask_all_text: true"
    "maskTextSelector: '*'"
    "maskAllInputs: true"
    "blockSelector: '.ph-no-capture, [data-ph-no-capture]'"
    "readAnalyticsConsent() !== 'granted'"
    "startSessionRecording()"
  )
  for token in "${required_tokens[@]}"; do
    if ! grep -qF "$token" "$POSTHOG_WRAPPER"; then
      echo "❌ PostHog wrapper is missing required privacy control: $token" >&2
      failures=$((failures + 1))
    fi
  done
fi

# Document surfaces must remain explicitly excluded from replay.
DOCUMENT_SURFACES=(
  "src/app/workspace/[resumeId]/edit/page.tsx"
  "src/app/try/page.tsx"
  "src/app/r/[token]/page.tsx"
  "src/app/u/[username]/page.tsx"
)
for relative in "${DOCUMENT_SURFACES[@]}"; do
  if ! grep -qF 'ph-no-capture' "$SCAN_DIR/$relative"; then
    echo "❌ Document surface lost its replay block marker: $relative" >&2
    failures=$((failures + 1))
  fi
done

if [ "$failures" -gt 0 ]; then
  echo >&2
  echo "Analytics may not capture document input or run outside the approved," >&2
  echo "consent-gated, fully masked PostHog wrapper (see docs/POSTHOG.md)." >&2
  exit 1
fi

echo "✅ Analytics policy upheld: consent-gated wrapper, masked replay, document surfaces blocked."
