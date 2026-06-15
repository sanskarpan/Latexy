export interface SlashCommand {
  name: string
  description: string
  usage: string
  isLocal: boolean
}

export const SLASH_COMMANDS: SlashCommand[] = [
  { name: 'compile', description: 'Compile selected resume to PDF', usage: '/compile [resume-id] [--compiler pdflatex|xelatex|lualatex]', isLocal: false },
  { name: 'optimize', description: 'AI-optimize resume for a job', usage: '/optimize [resume-id] [--jd url|file] [--level conservative|balanced|aggressive]', isLocal: false },
  { name: 'combined', description: 'Optimize + compile in one job', usage: '/combined [resume-id] [--jd url|file]', isLocal: false },
  { name: 'ats', description: 'Run ATS deep analysis', usage: '/ats [resume-id] [--jd url|file] [--industry software_engineering]', isLocal: false },
  { name: 'quick-ats', description: 'Fast rule-based ATS (no LLM)', usage: '/quick-ats [resume-id]', isLocal: false },
  { name: 'list', description: 'Open resume picker', usage: '/list [--archived] [--type resume|academic_cv]', isLocal: true },
  { name: 'new', description: 'Create new resume', usage: '/new [title]', isLocal: false },
  { name: 'edit', description: 'Open resume in $EDITOR', usage: '/edit [resume-id]', isLocal: false },
  { name: 'fork', description: 'Fork resume into a variant', usage: '/fork [resume-id] [new-title]', isLocal: false },
  { name: 'pdf', description: 'Download and open last PDF', usage: '/pdf [job-id]', isLocal: false },
  { name: 'log', description: 'View full pdflatex log', usage: '/log [job-id]', isLocal: false },
  { name: 'cancel', description: 'Cancel running job', usage: '/cancel [job-id]', isLocal: false },
  { name: 'jobs', description: 'Open job monitor overlay', usage: '/jobs', isLocal: true },
  { name: 'byok', description: 'Manage BYOK API keys', usage: '/byok', isLocal: true },
  { name: 'analytics', description: 'View personal analytics', usage: '/analytics [--period 7d|30d|90d]', isLocal: false },
  { name: 'billing', description: 'View subscription and billing', usage: '/billing', isLocal: true },
  { name: 'tracker', description: 'Open job application tracker', usage: '/tracker', isLocal: true },
  { name: 'cover', description: 'Generate cover letter', usage: '/cover [resume-id] --company "..." --role "..."', isLocal: false },
  { name: 'interview', description: 'Generate interview questions', usage: '/interview [resume-id] --jd url|file', isLocal: false },
  { name: 'health', description: 'Show backend health status', usage: '/health', isLocal: false },
  { name: 'history', description: 'Show optimization history', usage: '/history [resume-id]', isLocal: false },
  { name: 'checkpoint', description: 'Create named checkpoint', usage: '/checkpoint [resume-id] [label]', isLocal: false },
  { name: 'restore', description: 'Restore to a checkpoint', usage: '/restore [resume-id]', isLocal: true },
  { name: 'diff', description: 'Show diff with parent variant', usage: '/diff [resume-id]', isLocal: false },
  { name: 'export', description: 'Export resume to another format', usage: '/export [resume-id] --format docx|markdown|html', isLocal: false },
  { name: 'share', description: 'Generate and copy share link', usage: '/share [resume-id]', isLocal: false },
  { name: 'snippets', description: 'Browse snippet marketplace', usage: '/snippets', isLocal: true },
  { name: 'settings', description: 'Open notification settings', usage: '/settings', isLocal: true },
  { name: 'help', description: 'Show help', usage: '/help [command]', isLocal: true },
  { name: 'model', description: 'Open model picker for agent mode', usage: '/model', isLocal: true },
  { name: 'clear', description: 'Clear transcript', usage: '/clear', isLocal: true },
  { name: 'logout', description: 'Clear session and exit', usage: '/logout', isLocal: true },
]

export const COMMAND_MAP = new Map(SLASH_COMMANDS.map(c => [c.name, c]))
