/** Run an async request only while its caller-owned generation is current. */
export async function runLatestRequest<T>(
  request: () => Promise<T>,
  isCurrent: () => boolean,
  onSuccess: (result: T) => void,
  onError: (error: unknown) => void,
  onSettled: () => void,
): Promise<void> {
  try {
    const result = await request()
    if (isCurrent()) onSuccess(result)
  } catch (error: unknown) {
    if (isCurrent()) onError(error)
  } finally {
    if (isCurrent()) onSettled()
  }
}
