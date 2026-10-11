/** A relatable, clearly fictional starting document for the guest editor. */
export const FIRST_USE_RESUME_TEMPLATE = String.raw`\documentclass[11pt,a4paper]{article}
\usepackage[margin=0.75in]{geometry}
\usepackage[T1]{fontenc}
\usepackage{enumitem}
\usepackage{hyperref}
\pagestyle{empty}
\setlength{\parindent}{0pt}
\begin{document}
\begin{center}
{\Large \textbf{Alex Morgan}}\\
Customer Success Associate\\
alex@example.com | London | linkedin.com/in/alexmorgan
\end{center}
\section*{Profile}
Customer-focused professional who helps people get started, answers product questions, and makes everyday support feel personal. Replace this sample with your own experience.
\section*{Experience}
\textbf{Customer Success Associate, Example Company} \hfill 2023 -- Present
\begin{itemize}[leftmargin=*,noitemsep]
\item Guided new customers through onboarding and answered questions about their account.
\item Updated the welcome guide to make common tasks easier to understand.
\item Worked with colleagues to follow up on feedback and resolve customer issues.
\end{itemize}
\section*{Education}
\textbf{Bachelor of Arts, Example University} \hfill 2019 -- 2022
\section*{Skills}
Customer communication, onboarding, problem solving, teamwork, organization
\end{document}
`

/** The same fictional starting content in the engine's exact, bounded starter
 * grammar. Keep this separate from the legacy Visual projection's sample: a
 * design-only preamble change must not silently remove Resume-mode fields.
 */
export const FIRST_USE_ENGINE_RESUME_TEMPLATE = String.raw`\documentclass[11pt,a4paper]{article}
\usepackage[margin=0.72in]{geometry}
\usepackage{enumitem}
\setlist{nosep}

\begin{document}
\begin{center}
{\LARGE\textbf{Alex Morgan}} \\
\vspace{1mm}
Customer Success Associate \\
alex@example.com | London | linkedin.com/in/alexmorgan
\end{center}

\section*{Summary}
Customer-focused professional who helps people get started, answers product questions, and makes everyday support feel personal. Replace this sample with your own experience.

\section*{Experience}
\textbf{Customer Success Associate, Example Company} \hfill 2023 -- Present
\begin{itemize}
\item Guided new customers through onboarding and answered questions about their account.
\item Updated the welcome guide to make common tasks easier to understand.
\item Worked with colleagues to follow up on feedback and resolve customer issues.
\end{itemize}

\section*{Education}
\textbf{Bachelor of Arts, Example University} \hfill 2019 -- 2022

\section*{Skills}
Customer communication, onboarding, problem solving, teamwork, organization
\end{document}
`
