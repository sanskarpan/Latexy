#!/bin/bash

echo "🔍 Checking LaTeX installation..."

# Check if pdflatex is installed
if command -v pdflatex &> /dev/null; then
    echo "✅ pdflatex found"
    pdflatex_version=$(pdflatex --version | head -n 1)
    echo "   Version: $pdflatex_version"
else
    echo "❌ pdflatex not found"
    echo "   Please install TeXLive or MiKTeX"
    exit 1
fi

# Check if essential packages are available
echo ""
echo "🔍 Checking essential LaTeX packages..."

# Create a test LaTeX file
test_file="/tmp/latex_test.tex"
cat > "$test_file" << 'EOF'
\documentclass{article}
\usepackage[empty]{fullpage}
\usepackage{enumitem}
\usepackage[hidelinks]{hyperref}
\begin{document}
\textbf{LaTeX Test}
\begin{itemize}
\item Test item
\end{itemize}
\end{document}
EOF

# Try to compile the test file
echo "🧪 Testing LaTeX compilation..."
cd /tmp
if pdflatex -interaction=nonstopmode latex_test.tex > /dev/null 2>&1; then
    echo "✅ LaTeX compilation test successful"
    rm -f latex_test.*
else
    echo "❌ LaTeX compilation test failed"
    echo "   Check LaTeX installation and packages"
    rm -f latex_test.*
    exit 1
fi

echo ""
echo "✅ LaTeX installation is working correctly!"