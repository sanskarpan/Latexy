export interface EscapedPublicationEntry {
  latex_entry: string
}

/** Wrap backend-escaped publication entries in a complete LaTeX section. */
export function buildPublicationSection(publications: EscapedPublicationEntry[]): string {
  const items = publications.map(publication => `  \\item ${publication.latex_entry}`)
  return `\\section{Publications}\n\\begin{enumerate}\n${items.join('\n')}\n\\end{enumerate}`
}
