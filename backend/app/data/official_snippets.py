"""
Official (Latexy-curated) LaTeX snippet seed data — Feature 82.

Loaded via POST /admin/snippets/seed (admin only, idempotent upsert by title).
"""

OFFICIAL_SNIPPETS: list[dict] = [
    # ── 1. Two-column skills table ────────────────────────────────────────────
    {
        "title": "Two-Column Skills Table",
        "description": "Compact two-column layout for technical skills using tabular. Perfect for listing programming languages, frameworks, and tools side by side.",
        "content": r"""\begin{tabular}{l l}
\textbf{Languages:} & Python, JavaScript, TypeScript, Go, Rust \\
\textbf{Frameworks:} & React, FastAPI, Django, Next.js, Node.js \\
\textbf{Databases:} & PostgreSQL, Redis, MongoDB, Elasticsearch \\
\textbf{Cloud/DevOps:} & AWS, Docker, Kubernetes, Terraform, CI/CD \\
\textbf{Tools:} & Git, Linux, VS Code, Figma, Postman \\
\end{tabular}""",
        "category": "skills",
        "tags": ["tabular", "two-column", "technical", "programming"],
        "is_official": True,
    },

    # ── 2. Progress bars for skill levels ─────────────────────────────────────
    {
        "title": "Skill Level Progress Bars (TikZ)",
        "description": "Visual progress bars for skill proficiency levels using TikZ. Renders a horizontal bar for each skill showing proficiency from 0–5.",
        "content": r"""\usepackage{tikz}
% In preamble. Then in document:
\newcommand{\skillbar}[2]{%
  \begin{tikzpicture}[baseline]
    \fill[gray!20] (0,0) rectangle (3cm, 0.25cm);
    \fill[violet!60] (0,0) rectangle (#2*0.6cm, 0.25cm);
  \end{tikzpicture}
  \hspace{0.3em} #1
}

\skillbar{Python}{5}\\[2pt]
\skillbar{TypeScript}{4}\\[2pt]
\skillbar{Rust}{3}\\[2pt]
\skillbar{Kubernetes}{4}\\[2pt]
\skillbar{Machine Learning}{3}""",
        "category": "skills",
        "tags": ["tikz", "progress-bar", "visual", "proficiency"],
        "is_official": True,
    },

    # ── 3. Boxed professional summary ─────────────────────────────────────────
    {
        "title": "Boxed Professional Summary",
        "description": "Eye-catching boxed summary section with a subtle border. Uses tcolorbox for a clean, modern look that makes the summary stand out.",
        "content": r"""\usepackage{tcolorbox}
% In preamble. Then in document:
\begin{tcolorbox}[
  colback=gray!5,
  colframe=gray!40,
  boxrule=0.5pt,
  arc=3pt,
  left=6pt, right=6pt, top=4pt, bottom=4pt
]
\small
Results-driven software engineer with 5+ years of experience building
scalable distributed systems. Expertise in Python, Go, and cloud-native
architectures. Passionate about developer tooling, open-source, and
turning complex problems into elegant solutions.
\end{tcolorbox}""",
        "category": "header",
        "tags": ["tcolorbox", "summary", "boxed", "modern"],
        "is_official": True,
    },

    # ── 4. Compact header with photo placeholder ──────────────────────────────
    {
        "title": "Header with Photo Placeholder",
        "description": "Professional resume header with a circular photo placeholder on the right and contact details on the left. Uses minipage layout.",
        "content": r"""\begin{minipage}[t]{0.72\textwidth}
  \vspace{-6pt}
  {\Huge \textbf{Jane Smith}} \\[4pt]
  {\large Senior Software Engineer} \\[6pt]
  \faEnvelope\ jane@example.com \quad
  \faPhone\ +1 (555) 123-4567 \quad
  \faLinkedin\ linkedin.com/in/janesmith \\
  \faGithub\ github.com/janesmith \quad
  \faGlobe\ janesmith.dev
\end{minipage}%
\begin{minipage}[t]{0.25\textwidth}
  \raggedleft
  \vspace{-10pt}
  \begin{tikzpicture}
    \clip (0,0) circle (1.2cm);
    \fill[gray!30] (-1.5,-1.5) rectangle (1.5,1.5);
    \node at (0,0) {\small Photo};
  \end{tikzpicture}
\end{minipage}""",
        "category": "header",
        "tags": ["header", "photo", "minipage", "contact"],
        "is_official": True,
    },

    # ── 5. Publication list ────────────────────────────────────────────────────
    {
        "title": "Publication List",
        "description": "Formatted academic publication list with bibitem entries. Supports journal articles, conference papers, and preprints with DOI links.",
        "content": r"""\begin{enumerate}[leftmargin=*, label={[\arabic*]}]
  \item \textbf{Smith, J.}, Johnson, A., \& Lee, C. (2024).
    ``Scalable Graph Neural Networks for Code Analysis.''
    \textit{Proceedings of ICML 2024}, pp. 1234--1245.
    \href{https://doi.org/10.xxxx/xxxx}{\texttt{doi:10.xxxx/xxxx}}

  \item \textbf{Smith, J.} \& Williams, B. (2023).
    ``Efficient Attention Mechanisms for Long Sequences.''
    \textit{NeurIPS 2023 Workshop on Efficient ML}.
    \href{https://arxiv.org/abs/2309.xxxxx}{\texttt{arXiv:2309.xxxxx}}

  \item \textbf{Smith, J.} (2022).
    ``Runtime Verification of Distributed Protocols.''
    \textit{ACM Transactions on Software Engineering}, 28(3), 45--67.
\end{enumerate}""",
        "category": "misc",
        "tags": ["publications", "academia", "bibitem", "citations"],
        "is_official": True,
    },

    # ── 6. Awards and honors table ─────────────────────────────────────────────
    {
        "title": "Awards & Honors Table",
        "description": "Clean tabular layout for awards, honors, and scholarships with year, title, and issuing organization columns.",
        "content": r"""\begin{tabular}{@{}lll@{}}
\toprule
\textbf{Year} & \textbf{Award} & \textbf{Organization} \\
\midrule
2024 & Best Paper Award & ICML Conference \\
2023 & Graduate Excellence Fellowship & University of XYZ \\
2022 & 1st Place Hackathon & Google Developer Day \\
2021 & Dean's List (all semesters) & University of XYZ \\
2020 & National Merit Scholarship & National Merit Corp. \\
\bottomrule
\end{tabular}""",
        "category": "misc",
        "tags": ["awards", "honors", "tabular", "booktabs"],
        "is_official": True,
    },

    # ── 7. Multi-column interests / hobbies ───────────────────────────────────
    {
        "title": "Multi-Column Interests Section",
        "description": "Compact three-column layout for interests, hobbies, and activities using multicol or minipage.",
        "content": r"""\begin{multicols}{3}
\begin{itemize}[leftmargin=*, noitemsep]
  \item Open Source Development
  \item Technical Blogging
  \item Rock Climbing
  \item Chess (FIDE rated)
  \item Amateur Radio (KD9XYZ)
  \item Competitive Programming
\end{itemize}
\end{multicols}""",
        "category": "misc",
        "tags": ["interests", "hobbies", "multicol", "compact"],
        "is_official": True,
    },

    # ── 8. Color-accented section dividers ────────────────────────────────────
    {
        "title": "Color-Accented Section Rule",
        "description": "Custom section command with a colored rule underneath for a modern look. Uses xcolor and a custom \\resumesection command.",
        "content": r"""\usepackage{xcolor}
\definecolor{accent}{RGB}{100, 60, 180}

% In preamble — redefine \section for colored accent:
\renewcommand{\section}[1]{%
  {\large\bfseries #1}%
  \vspace{2pt}%
  \hrule height 1.5pt \relax%
  \vspace{4pt}%
}

% Usage: same as normal \section{Experience}""",
        "category": "misc",
        "tags": ["xcolor", "section", "accent", "divider", "custom"],
        "is_official": True,
    },

    # ── 9. Timeline experience (alternating) ──────────────────────────────────
    {
        "title": "Timeline Experience Section (TikZ)",
        "description": "Visually engaging timeline-style experience section with a vertical line and dots for each entry. Great for creative CVs.",
        "content": r"""\usepackage{tikz}
\newcommand{\timelineentry}[4]{%
  % #1=year, #2=title, #3=company, #4=description
  \begin{tikzpicture}[baseline]
    \fill[violet!70] (0,0) circle (0.12cm);
    \draw[gray!40, line width=0.6pt] (0,0.12) -- (0,1.0);
  \end{tikzpicture}%
  \hspace{0.4em}%
  \begin{minipage}[t]{0.88\linewidth}
    {\small\textcolor{gray}{#1}} \quad \textbf{#2} $\cdot$ #3 \\
    {\small #4}
  \end{minipage}\\[6pt]
}

\timelineentry{2022--Present}{Senior Engineer}{Acme Corp}{Led platform team, reduced p99 latency by 40\%.}
\timelineentry{2020--2022}{Software Engineer}{Startup Inc}{Built real-time data pipeline handling 1M events/day.}""",
        "category": "experience",
        "tags": ["tikz", "timeline", "creative", "visual"],
        "is_official": True,
    },

    # ── 10. Modern education entry with GPA ───────────────────────────────────
    {
        "title": "Education Entry with GPA Highlight",
        "description": "Clean education entry with degree, institution, GPA badge, and relevant coursework. Highlights strong GPA with colored text.",
        "content": r"""\textbf{B.S. Computer Science} \hfill \textit{2018 -- 2022} \\
\textit{University of Example} \hfill \textcolor{violet}{\textbf{GPA: 3.95 / 4.0}} \\[3pt]
\textbf{Relevant Coursework:} Algorithms \& Data Structures,
  Operating Systems, Distributed Computing, Machine Learning,
  Computer Architecture, Compilers, Cryptography \\[3pt]
\textbf{Honors:} Summa Cum Laude, Dean's List (8 semesters),
  Outstanding Senior Thesis Award""",
        "category": "education",
        "tags": ["education", "gpa", "coursework", "honors"],
        "is_official": True,
    },

    # ── 11. Volunteering / Leadership section ─────────────────────────────────
    {
        "title": "Volunteering & Leadership Entry",
        "description": "Standard entry format for volunteering and leadership roles with impact metrics. Mirrors the experience entry style.",
        "content": r"""\resumeSubheading
  {Open Source Contributor}{Jan 2023 -- Present}
  {NumPy / SciPy Project}{Remote}
  \resumeItemListStart
    \resumeItem{Merged 12 PRs fixing numerical precision bugs and improving documentation}
    \resumeItem{Reviewed 30+ community pull requests; mentored 3 first-time contributors}
    \resumeItem{Presented at SciPy Conference 2023 on sparse matrix optimizations}
  \resumeItemListEnd""",
        "category": "experience",
        "tags": ["volunteering", "open-source", "leadership", "impact"],
        "is_official": True,
    },

    # ── 12. Certifications list ───────────────────────────────────────────────
    {
        "title": "Certifications & Credentials",
        "description": "Formatted certification list with provider, credential name, and expiry date. Uses itemize with custom formatting.",
        "content": r"""\begin{itemize}[leftmargin=*, noitemsep]
  \item \textbf{AWS Solutions Architect -- Professional} \hfill \textit{Valid: 2025}
  \item \textbf{Google Professional Data Engineer} \hfill \textit{Valid: 2026}
  \item \textbf{Certified Kubernetes Administrator (CKA)} \hfill \textit{Valid: 2025}
  \item \textbf{MongoDB Certified Developer} \hfill \textit{No expiry}
  \item \textbf{Chartered Financial Analyst (CFA) Level I} \hfill \textit{Passed 2023}
\end{itemize}""",
        "category": "misc",
        "tags": ["certifications", "credentials", "AWS", "professional"],
        "is_official": True,
    },
]
