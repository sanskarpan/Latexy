#!/usr/bin/env bash
set -euo pipefail

template="${LATEXY_INDIC_TEMPLATE:-/backend/app/data/templates/ats_safe/hindi_professional.tex}"
if [[ ! -f "$template" ]]; then
  template="app/data/templates/ats_safe/hindi_professional.tex"
fi

for command_name in lualatex pdftotext pdffonts; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Required command is unavailable: $command_name" >&2
    exit 2
  fi
done

work_dir="$(mktemp -d /tmp/latexy-indic-tagging.XXXXXX)"
cleanup() {
  case "$work_dir" in
    /tmp/latexy-indic-tagging.*) rm -rf -- "$work_dir" ;;
    *) echo "Refusing to remove unexpected temporary path: $work_dir" >&2 ;;
  esac
}
trap cleanup EXIT

{
  echo '\DocumentMetadata{lang=hi-IN,tagging=on}'
  cat "$template"
} > "$work_dir/tagged.tex"

if ! lualatex -interaction=nonstopmode -halt-on-error \
  -output-directory="$work_dir" "$work_dir/tagged.tex" > "$work_dir/build.log" 2>&1; then
  echo "The installed TeX Live cannot compile tagged Devanagari output." >&2
  tail -n 60 "$work_dir/build.log" >&2
  exit 3
fi

pdffonts "$work_dir/tagged.pdf" > "$work_dir/fonts.txt"
pdftotext -layout "$work_dir/tagged.pdf" "$work_dir/extracted.txt"

if ! awk 'NR > 2 && NF > 0 && $6 != "yes" { exit 1 }' "$work_dir/fonts.txt"; then
  echo "Tagged Devanagari PDF contains a font without a ToUnicode CMap." >&2
  exit 1
fi

for expected_text in "आरव शर्मा" "व्यावसायिक सारांश" "भुगतान मंच"; do
  if ! grep -Fq "$expected_text" "$work_dir/extracted.txt"; then
    echo "Tagged Devanagari extraction mismatch: $expected_text" >&2
    exit 1
  fi
done

echo "Tagged Devanagari compile and extraction contract passed."
