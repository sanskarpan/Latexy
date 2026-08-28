export type TemplateUseResult = boolean | void

/** A template action returning false means it did not create a document. */
export function shouldCloseTemplatePreview(result: TemplateUseResult): boolean {
  return result !== false
}
