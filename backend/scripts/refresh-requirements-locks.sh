#!/usr/bin/env sh
# Regenerate the hash-verified Python locks from the human-edited inputs.
#
# Keep these flags in sync with the "Verify generated Python locks are fresh"
# step in .github/workflows/ci.yml. The --universal resolution keeps one lock
# valid for Linux, macOS, and Windows, and --custom-compile-command keeps the
# generated header stable across runs.
#
#   sh backend/scripts/refresh-requirements-locks.sh
set -eu
# dash has no pipefail; enable it when the shell provides it.
if (set -o pipefail) 2>/dev/null; then
  set -o pipefail
fi

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
backend_dir=$(CDPATH= cd "$script_dir/.." && pwd)

if ! command -v uv >/dev/null 2>&1; then
  echo "error: uv is required (https://docs.astral.sh/uv/)" >&2
  exit 1
fi

cd "$backend_dir"

uv pip compile --universal --python-version 3.12 --generate-hashes \
  --custom-compile-command 'uv pip compile --universal --python-version 3.12 --generate-hashes requirements.txt -o requirements.lock' \
  requirements.txt -o requirements.lock

uv pip compile --universal --python-version 3.12 --generate-hashes \
  --custom-compile-command 'uv pip compile --universal --python-version 3.12 --generate-hashes requirements-dev.txt -o requirements-dev.lock' \
  requirements-dev.txt -o requirements-dev.lock
