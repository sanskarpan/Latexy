#!/bin/sh

set -eu
mkdir -p /var/lib/texmf
export TEXMFVAR="/var/lib/texmf"
export TEXMFCACHE="/var/lib/texmf"
engine_fonts="$(kpsewhich -var-value=TEXMFDIST)/fonts"
for font_root in "$engine_fonts" /usr/share/fonts /usr/local/share/fonts; do
  if [ -d "$font_root" ]; then
    find "$font_root" -type d -exec touch -m -d '@1704067200' {} +
  fi
done
fc-cache --force --system-only
luaotfload-tool --update --force
probe="$(mktemp -d)"
trap 'rm -rf "$probe"' EXIT
printf '%s\n' \
  '\documentclass{article}' \
  '\usepackage{geometry}' \
  '\usepackage{fontspec}' \
  '\usepackage{luatexja-fontspec}' \
  '\setmainjfont{Noto Sans CJK JP}' \
  '\usepackage{polyglossia}' \
  '\setmainfont{Latin Modern Roman}' \
  '\setmainlanguage{english}' \
  '\setotherlanguage{arabic}' \
  '\setotherlanguage{hebrew}' \
  '\setotherlanguage{hindi}' \
  '\newfontfamily\arabicfont[Script=Arabic]{Noto Naskh Arabic}' \
  '\newfontfamily\hebrewfont[Script=Hebrew]{Noto Sans Hebrew}' \
  '\newfontfamily\hindifont[Renderer=HarfBuzz,Script=Devanagari,BoldFont={Noto Sans Devanagari Bold},ItalicFont={Noto Sans Devanagari},ItalicFeatures={FakeSlant=0.15},BoldItalicFont={Noto Sans Devanagari Bold},BoldItalicFeatures={FakeSlant=0.15}]{Noto Sans Devanagari}' \
  '\begin{document}' \
  '\textenglish{Latin email@example.com •}' \
  '日本語' \
  '\textarabic{العربية}' \
  '\texthebrew{עברית}' \
  '\texthindi{हिंदी \textenglish{email@example.com •} \textbf{बोल्ड} \textit{तिरछा} \textbf{\textit{दोनों}}}' \
  '\begin{itemize}' \
  '\item \texthindi{भुगतान मंच \textenglish{email@example.com •}}' \
  '\begin{itemize}\item \texthindi{दूसरा स्तर}\end{itemize}' \
  '\end{itemize}' \
  '\end{document}' > "$probe/font-probe.tex"
lualatex -no-shell-escape -recorder -interaction=batchmode -halt-on-error \
  -output-directory="$probe" "$probe/font-probe.tex" >"$probe/font-probe.stdout" 2>&1 &
engine_pid="$!"
(
  sleep 125
  kill "$engine_pid" 2>/dev/null || true
) &
watchdog_pid="$!"
set +e
wait "$engine_pid"
engine_rc="$?"
set -e
kill "$watchdog_pid" 2>/dev/null || true
wait "$watchdog_pid" 2>/dev/null || true
test "$engine_rc" -eq 0
test -s "$probe/font-probe.pdf"
! grep -Eq 'Missing character|Font shape .*undefined|Some font shapes were not available|Fatal error|^! ' "$probe/font-probe.log"
