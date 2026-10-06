import type * as Monaco from 'monaco-editor'

type IStandaloneCodeEditor = Monaco.editor.IStandaloneCodeEditor

export class MacroScriptStaleDocumentError extends Error {
  constructor() {
    super('The document changed while the script was running; nothing was applied.')
    this.name = 'MacroScriptStaleDocumentError'
  }
}

export interface MacroScriptResult {
  document: string
  operation_count: number
}

const MAX_DOCUMENT_BYTES = 500_000

function validDocument(value: unknown): value is string {
  if (typeof value !== 'string' || /[\uD800-\uDFFF]/.test(value)) return false
  try {
    return new TextEncoder().encode(value).byteLength <= MAX_DOCUMENT_BYTES
  } catch {
    return false
  }
}

function validateResult(value: unknown): MacroScriptResult {
  if (!value || typeof value !== 'object') throw new Error('Macro server returned an invalid result.')
  const result = value as Record<string, unknown>
  const operationCount = result.operation_count
  if (!validDocument(result.document) || typeof operationCount !== 'number' || !Number.isInteger(operationCount) || operationCount < 0 || operationCount > 128) {
    throw new Error('Macro server returned an invalid result.')
  }
  return { document: result.document, operation_count: operationCount }
}

/** Apply a server-validated script as one undoable, stale-safe edit. */
export async function applyMacroScript(
  editor: IStandaloneCodeEditor,
  execute: (document: string) => Promise<MacroScriptResult>,
): Promise<MacroScriptResult> {
  const capturedModel = editor.getModel()
  if (!capturedModel) throw new Error('Editor model unavailable')
  const beforeVersion = capturedModel.getAlternativeVersionId()
  const result = validateResult(await execute(capturedModel.getValue()))
  if (editor.getModel() !== capturedModel || capturedModel.getAlternativeVersionId() !== beforeVersion) {
    throw new MacroScriptStaleDocumentError()
  }
  editor.pushUndoStop()
  try {
    const applied = editor.executeEdits('macro-script', [{ range: capturedModel.getFullModelRange(), text: result.document }])
    if (!applied) throw new Error('Macro result could not be applied.')
    return result
  } finally {
    editor.pushUndoStop()
  }
}
