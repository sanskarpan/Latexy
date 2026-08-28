#!/usr/bin/env bash
# Reject documentation that publishes a usable account credential pair.
#
# Provider-token scanners do not detect ordinary email/password credentials.
# This guard deliberately reports filenames only, so a CI failure cannot copy a
# credential into logs. It scans tracked documentation rather than the whole
# worktree, avoiding generated reports and local-only audit material.
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

PATTERNS=(
  # "production test accounts: person@example.com / password"
  '(production|prod|test|qa)[ -_]*accounts?.*[[:alnum:]_.%+-]+@[[:alnum:].-]+[[:space:]`]*[/|][[:space:]`]*[^<[:space:]]'
  # "person@example.com password: value" (also catches password=value)
  '[[:alnum:]_.%+-]+@[[:alnum:].-]+.*password[[:space:]`]*[:=][[:space:]`]*[^<$[:space:]]'
  # HTTP basic-auth credentials embedded in a URL.
  'https?://[^/<[:space:]]+:[^@<[:space:]]+@[^[:space:]]+'
)

must_match='Production QA account: qa-user@example.invalid / example-password'
must_not_match='Production test-account credentials are stored in the approved secret manager.'

for pattern in "${PATTERNS[@]}"; do
  if printf '%s\n' "$must_not_match" | grep -Eiq "$pattern"; then
    echo "Credential guard self-test failed: safe guidance matched." >&2
    exit 2
  fi
done

if ! printf '%s\n' "$must_match" | grep -Eiq "${PATTERNS[0]}"; then
  echo "Credential guard self-test failed: credential fixture was missed." >&2
  exit 2
fi

offenders=()
for pattern in "${PATTERNS[@]}"; do
  while IFS= read -r file; do
    offenders+=("$file")
  done < <(git grep -Il -E "$pattern" -- docs README.md 2>/dev/null || true)
done

if ((${#offenders[@]} > 0)); then
  echo "Plaintext account credentials found in tracked documentation:" >&2
  printf '%s\n' "${offenders[@]}" | sort -u >&2
  echo "Remove the values, rotate the exposed account, and reference the approved secret manager." >&2
  exit 1
fi

echo "No plaintext account credential pairs found in tracked documentation."
