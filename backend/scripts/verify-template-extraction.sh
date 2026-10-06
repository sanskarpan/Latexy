#!/usr/bin/env bash
set -euo pipefail

engine="${LATEXY_TEMPLATE_ENGINE:-lualatex}"
templates_root="${LATEXY_TEMPLATES_ROOT:-/backend/app/data/templates}"
if [[ ! -d "$templates_root" ]]; then
  templates_root="app/data/templates"
fi

for command_name in "$engine" pdffonts pdftotext; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Required command is unavailable: $command_name" >&2
    exit 2
  fi
done

work_dir="$(mktemp -d /tmp/latexy-template-extraction.XXXXXX)"

cleanup() {
  case "$work_dir" in
    /tmp/latexy-template-extraction.*) rm -rf -- "$work_dir" ;;
    *) echo "Refusing to remove unexpected temporary path: $work_dir" >&2 ;;
  esac
}

trap cleanup EXIT

template_count=0
leading_separator_count=0

while IFS= read -r -d '' template; do
  template_count=$((template_count + 1))
  relative_path="${template#"$templates_root"/}"
  artifact_dir="$work_dir/$template_count"
  mkdir -p "$artifact_dir"

  if ! "$engine" -interaction=nonstopmode -halt-on-error \
    -output-directory="$artifact_dir" "$template" >"$artifact_dir/build.log" 2>&1; then
    echo "Template compile failed: $relative_path (engine=$engine)" >&2
    tail -n 40 "$artifact_dir/build.log" >&2
    exit 1
  fi

  pdf_path="$artifact_dir/$(basename "${template%.tex}").pdf"
  fonts_path="$artifact_dir/fonts.txt"
  text_path="$artifact_dir/extracted.txt"
  pdffonts "$pdf_path" >"$fonts_path"
  pdftotext -layout "$pdf_path" "$text_path"

  if awk 'NR > 2 && NF > 0 && $6 != "yes" { exit 1 }' "$fonts_path"; then
    :
  else
    echo "Template contains a font without a ToUnicode CMap: $relative_path" >&2
    cat "$fonts_path" >&2
    exit 1
  fi

  word_count="$(wc -w < "$text_path" | tr -d ' ')"
  if (( word_count < 25 )); then
    echo "Template extracts fewer than 25 words: $relative_path ($word_count)" >&2
    sed -n '1,40p' "$text_path" >&2
    exit 1
  fi

  if grep -Eq '^[[:space:]]*\|' "$text_path"; then
    leading_separator_count=$((leading_separator_count + 1))
    echo "Leading separator found in extracted text: $relative_path" >&2
    grep -En '^[[:space:]]*\|' "$text_path" | head -n 5 >&2
  fi

  if [[ "$relative_path" == "ats_safe/hindi_professional.tex" ]]; then
    for expected_text in "आरव शर्मा" "व्यावसायिक सारांश" "भुगतान मंच"; do
      if ! grep -Fq "$expected_text" "$text_path"; then
        echo "Devanagari text did not round-trip through PDF extraction: $expected_text" >&2
        sed -n '1,40p' "$text_path" >&2
        exit 1
      fi
    done
  fi
done < <(find "$templates_root" -type f -name '*.tex' -print0 | sort -z)

if (( template_count == 0 )); then
  echo "No template sources found under $templates_root" >&2
  exit 2
fi

if (( leading_separator_count > 0 )); then
  echo "$leading_separator_count template(s) contain an extracted line beginning with a separator" >&2
  exit 1
fi

echo "Template extraction contract passed: $template_count templates, engine=$engine, all fonts uni=yes, all outputs >=25 words"
echo "Templates with extracted lines beginning with a separator: 0"
