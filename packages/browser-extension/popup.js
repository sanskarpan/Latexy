import { assertCompanionAvailable } from './capabilities.js'
import { autofillApplication } from './autofill.js'
import { extractJobPosting } from './extraction.js'

const fields = Object.fromEntries(
  ['company', 'title', 'location', 'description', 'url'].map((id) => [id, document.getElementById(id)]),
)
const status = document.getElementById('status')
const source = document.getElementById('source')
const save = document.getElementById('save')
const autofill = document.getElementById('autofill')
const companionTools = document.getElementById('companion-tools')
const captureTools = document.getElementById('capture-tools')
let captureAllowed = false
let allowed = false
let busy = false
let captureSource = 'visible_page'

async function requireCompanion() {
  const { appOrigin = 'https://latexy.xyz' } = await chrome.storage.local.get('appOrigin')
  try {
    const { ownerId, captureAvailable } = await assertCompanionAvailable(appOrigin)
    captureAllowed = captureAvailable
    captureTools.hidden = !captureAvailable
    allowed = true
    companionTools.hidden = false
    return { appOrigin, ownerId }
  } catch (error) {
    allowed = false
    companionTools.hidden = true
    save.disabled = true
    throw error
  }
}

async function activeWebTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true })
  if (!tab?.id || !/^https?:/i.test(tab.url || '')) {
    throw new Error('Open a web job posting before using Latexy.')
  }
  return tab
}

function setStatus(message, isError = false) {
  status.textContent = message
  status.classList.toggle('error', isError)
}

async function inspectTab() {
  try {
    save.disabled = true
    await requireCompanion()
    if (!captureAllowed) { setStatus('Job capture is unavailable. You can still use permitted autofill.'); return }
    const tab = await activeWebTab()
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: extractJobPosting,
    })
    for (const [key, input] of Object.entries(fields)) input.value = result?.[key] || ''
    captureSource = result?.source === 'json_ld' ? 'json_ld' : 'visible_page'
    source.textContent = result?.source === 'json_ld' ? 'Structured posting' : 'Visible page'
    save.disabled = !(fields.company.value && fields.title.value && fields.url.value)
    setStatus(
      result?.description
        ? 'Review the captured fields before sending them to Latexy.'
        : 'No clear description was found. Review or paste it before saving.',
      !result?.description,
    )
  } catch (error) {
    setStatus(error instanceof Error ? error.message : 'Could not read this page.', true)
  }
}

for (const input of Object.values(fields)) {
  input.addEventListener('input', () => {
    save.disabled = !allowed || !captureAllowed || busy || !(fields.company.value.trim() && fields.title.value.trim() && fields.url.value.trim())
  })
}

save.addEventListener('click', async () => {
  if (busy || !allowed || !captureAllowed) return
  busy = true
  save.disabled = true
  try {
  const { appOrigin, ownerId } = await requireCompanion()
  if (!captureAllowed) throw new Error('Job capture is currently unavailable.')
  const captureId = crypto.randomUUID()
  const capture = Object.fromEntries(
    Object.entries(fields).map(([key, input]) => [key, input.value.trim()]),
  )
  capture.source = captureSource
  const key = `latexy:capture:${captureId}`
  await chrome.storage.local.set({
    [key]: { capture, ownerId, expiresAt: Date.now() + 15 * 60 * 1000 },
  })
  await chrome.tabs.create({ url: `${appOrigin}/tracker?capture_id=${encodeURIComponent(captureId)}` })
  window.close()
  } catch (error) {
    setStatus(error instanceof Error ? error.message : 'Could not verify Job Companion access.', true)
  } finally {
    busy = false
    save.disabled = !allowed || !captureAllowed || !(fields.company.value.trim() && fields.title.value.trim() && fields.url.value.trim())
  }
})

autofill.addEventListener('click', async () => {
  if (busy || !allowed) return
  busy = true
  autofill.disabled = true
  try {
    await requireCompanion()
    const { autofillProfile } = await chrome.storage.local.get('autofillProfile')
    if (!autofillProfile?.email && !autofillProfile?.firstName) {
      await chrome.runtime.openOptionsPage()
      setStatus('Add an autofill profile, then try again.')
      return
    }
    const tab = await activeWebTab()
    const [{ result }] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: autofillApplication,
      args: [autofillProfile],
    })
    setStatus(
      result?.count
        ? `Filled ${result.count} field${result.count === 1 ? '' : 's'}. Review everything before submitting.`
        : 'No empty supported fields were found on this page.',
    )
  } catch (error) {
    setStatus(error instanceof Error ? error.message : 'Autofill failed.', true)
  } finally {
    busy = false
    autofill.disabled = !allowed
  }
})

document.getElementById('options').addEventListener('click', () => chrome.runtime.openOptionsPage())

void inspectTab()
