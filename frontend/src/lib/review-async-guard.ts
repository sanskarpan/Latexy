/** Return whether an async review operation may still mutate the current panel. */
export function reviewRequestIsCurrent(requestGeneration: number, currentGeneration: number): boolean {
  return requestGeneration === currentGeneration
}
