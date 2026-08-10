export interface SlashCommand {
  name: string
  description: string
  usage: string
  isLocal: boolean
  /**
   * Whether dispatch() actually routes this command.
   *
   * The registry doubles as the autocomplete menu and as /help, so an entry with
   * no handler is not a harmless placeholder — it is advertised to the user,
   * labelled `api`, and then answered with "Unknown command". Keep this in step
   * with the handler maps in dispatch.ts; the audit test enforces it.
   */
  implemented: boolean
}

export const SLASH_COMMANDS: SlashCommand[] = [
  { name: 'compile', description: 'Compile selected resume to PDF', usage: '/compile [resume-id] [--compiler pdflatex|xelatex|lualatex]', isLocal: false , implemented: true },
  { name: 'optimize', description: 'AI-optimize resume for a job', usage: '/optimize [resume-id] [--jd url|file] [--level conservative|balanced|aggressive]', isLocal: false , implemented: true },
  { name: 'combined', description: 'Optimize + compile in one job', usage: '/combined [resume-id] [--jd url|file]', isLocal: false , implemented: true },
  { name: 'ats', description: 'Run ATS deep analysis', usage: '/ats [resume-id] [--jd url|file] [--industry software_engineering]', isLocal: false , implemented: true },
  { name: 'quick-ats', description: 'Fast rule-based ATS (no LLM)', usage: '/quick-ats [resume-id]', isLocal: false , implemented: true },
  { name: 'list', description: 'Open resume picker', usage: '/list [--archived] [--type resume|academic_cv]', isLocal: false , implemented: true },
  { name: 'workbench', description: 'Open the Miller-columns workbench', usage: '/workbench', isLocal: true , implemented: true },
  { name: 'new', description: 'Create new resume', usage: '/new [title]', isLocal: false , implemented: true },
  { name: 'edit', description: 'Open resume in $EDITOR', usage: '/edit [resume-id]', isLocal: false , implemented: true },
  { name: 'fork', description: 'Fork resume into a variant', usage: '/fork [resume-id] [new-title]', isLocal: false , implemented: true },
  { name: 'pdf', description: 'Download and open last PDF', usage: '/pdf [job-id]', isLocal: false , implemented: true },
  { name: 'log', description: 'View full pdflatex log', usage: '/log [job-id]', isLocal: false , implemented: true },
  { name: 'cancel', description: 'Cancel running job', usage: '/cancel [job-id]', isLocal: false , implemented: true },
  { name: 'jobs', description: 'List recent jobs and their status', usage: '/jobs', isLocal: false , implemented: true },
  { name: 'byok', description: 'List your API keys and supported providers', usage: '/byok', isLocal: false , implemented: true },
  { name: 'analytics', description: 'View personal analytics', usage: '/analytics [--period 7d|30d|90d]', isLocal: false , implemented: true },
  { name: 'billing', description: 'View subscription and billing', usage: '/billing', isLocal: false , implemented: true },
  { name: 'tracker', description: 'List tracked job applications', usage: '/tracker [--status <stage>]', isLocal: false , implemented: true },
  { name: 'cover', description: 'Generate cover letter', usage: '/cover [resume-id] --jd <url|file|text> [--company "..."] [--role "..."] [--tone formal|conversational|enthusiastic]', isLocal: false , implemented: true },
  { name: 'interview', description: 'Generate interview questions', usage: '/interview [resume-id] --jd url|file', isLocal: false , implemented: true },
  { name: 'health', description: 'Show backend health status', usage: '/health', isLocal: false , implemented: true },
  { name: 'history', description: 'Show optimization history', usage: '/history [resume-id]', isLocal: false , implemented: true },
  { name: 'checkpoint', description: 'Create named checkpoint', usage: '/checkpoint [resume-id] [label] | /checkpoint --delete', isLocal: false , implemented: true },
  { name: 'restore', description: 'Restore to a checkpoint', usage: '/restore [resume-id]', isLocal: false , implemented: true },
  { name: 'diff', description: 'Show diff with parent variant', usage: '/diff [resume-id]', isLocal: false , implemented: true },
  { name: 'export', description: 'Export resume to another format', usage: '/export [resume-id] --format tex|md|txt|html|json|yaml|xml|docx', isLocal: false , implemented: true },
  { name: 'share', description: 'Generate and copy share link', usage: '/share [resume-id] [--revoke]', isLocal: false , implemented: true },
  { name: 'snippets', description: 'Search the snippet marketplace', usage: '/snippets [query]', isLocal: false , implemented: true },
  { name: 'settings', description: 'Show or change notification settings', usage: '/settings [--set <key>=<true|false>]', isLocal: false , implemented: true },
  { name: 'help', description: 'Show help', usage: '/help [command]', isLocal: true , implemented: true },
  { name: 'model', description: 'List LLM providers and their models', usage: '/model', isLocal: false , implemented: true },
  { name: 'clear', description: 'Clear transcript', usage: '/clear', isLocal: true , implemented: true },
  { name: 'logout', description: 'Clear session and exit', usage: '/logout', isLocal: true , implemented: true },
]

export const COMMAND_MAP = new Map(SLASH_COMMANDS.map(c => [c.name, c]))

/** Commands the user can actually run. Autocomplete and /help use this. */
export const IMPLEMENTED_COMMANDS: SlashCommand[] = SLASH_COMMANDS.filter(c => c.implemented)
