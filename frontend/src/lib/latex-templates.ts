/**
 * Shared LaTeX resume templates used across the app.
 * BLANK_RESUME_TEMPLATE — generic placeholder shown when editor is empty.
 * DEMO_RESUME_TEMPLATE  — filled demo shown on the /try page.
 */

export const BLANK_RESUME_TEMPLATE = `\\documentclass[11pt,a4paper]{article}
\\usepackage[margin=0.72in]{geometry}
\\usepackage{enumitem}
\\setlist{nosep}

\\begin{document}
\\begin{center}
{\\LARGE\\textbf{Your Name}} \\\\
\\vspace{1mm}
Your Desired Role \\\\
Email: you@example.com | linkedin.com/in/yourprofile
\\end{center}

\\section{Summary}
Briefly describe your career goals and key achievements here.

\\section{Experience}
\\textbf{Role Title, Company Name} \\hfill 2022 – Present
\\begin{itemize}
  \\item Key achievement or responsibility
  \\item Another important impact you made
\\end{itemize}

\\section{Skills}
Skill 1, Skill 2, Skill 3, Technology A, Framework B
\\end{document}`

export const DEMO_RESUME_TEMPLATE = `\\documentclass[11pt,a4paper]{article}
\\usepackage[margin=0.72in]{geometry}
\\usepackage{enumitem}
\\setlist{nosep}

\\begin{document}
\\begin{center}
{\\LARGE\\textbf{Alex Morgan}} \\\\
\\vspace{1mm}
Senior Software Engineer \\\\
Email: alex@example.com | linkedin.com/in/alexmorgan
\\end{center}

\\section*{Summary}
Product-focused engineer with 6+ years building resilient SaaS systems, developer tooling,
and observability-first workflows.

\\section*{Experience}
\\textbf{Staff Engineer, Northbeam Labs} \\hfill 2022 - Present
\\begin{itemize}
\\item Led migration to event-driven backend reducing deployment risk by 35\\%
\\item Built internal design system used across 6 product surfaces
\\item Mentored 4 engineers and introduced measurable review standards
\\end{itemize}

\\section*{Skills}
TypeScript, Next.js, Python, PostgreSQL, Redis, Kubernetes, AWS
\\end{document}`
