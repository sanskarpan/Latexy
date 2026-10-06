#!/usr/bin/env bash
set -euo pipefail

engines=(pdflatex xelatex lualatex)
packages=(atkinson avant bookman charter courier helvet lmodern mathptmx newcent palatino)
work_dir="$(mktemp -d /tmp/latexy-font-matrix.XXXXXX)"

cleanup() {
  case "$work_dir" in
    /tmp/latexy-font-matrix.*) rm -rf -- "$work_dir" ;;
    *) echo "Refusing to remove unexpected temporary path: $work_dir" >&2 ;;
  esac
}

trap cleanup EXIT

for engine in "${engines[@]}"; do
  for package in "${packages[@]}"; do
    tex_file="$work_dir/${engine}-${package}.tex"
    {
      echo '\documentclass{article}'
      echo "\\usepackage{${package}}"
      echo '\renewcommand{\familydefault}{\sfdefault}'
      echo '\begin{document}'
      echo "Readable 0 O I l with ${package}"
      echo '\end{document}'
    } > "$tex_file"

    if ! "$engine" -interaction=nonstopmode -halt-on-error \
      -output-directory="$work_dir" "$tex_file" >"$work_dir/build.log" 2>&1; then
      echo "Font compile failed: engine=${engine} package=${package}" >&2
      tail -n 30 "$work_dir/build.log" >&2
      exit 1
    fi
  done
done

echo "Hosted font matrix passed: ${#packages[@]} packages x ${#engines[@]} engines"
