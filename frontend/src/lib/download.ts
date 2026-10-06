/** Start a browser download and release its Blob URL after navigation consumes it. */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()

  // Revoking synchronously can cancel the download before Firefox consumes the
  // object URL. A short delay also keeps the URL lifetime bounded.
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
