const form = document.getElementById('profile-form')
const status = document.getElementById('status')
const PROFILE_FIELDS = [
  'firstName', 'lastName', 'email', 'phone', 'city', 'region', 'country', 'linkedin', 'website',
]
const ALLOWED_ORIGINS = new Set([
  'https://latexy.xyz',
  'http://localhost:5180',
  'http://127.0.0.1:5180',
])

async function load() {
  const { autofillProfile = {}, appOrigin = 'https://latexy.xyz' } =
    await chrome.storage.local.get(['autofillProfile', 'appOrigin'])
  for (const key of PROFILE_FIELDS) form.elements[key].value = autofillProfile[key] || ''
  form.elements.appOrigin.value = ALLOWED_ORIGINS.has(appOrigin) ? appOrigin : 'https://latexy.xyz'
}

form.addEventListener('submit', async (event) => {
  event.preventDefault()
  const autofillProfile = Object.fromEntries(
    PROFILE_FIELDS.map((key) => [key, form.elements[key].value.replace(/\s+/g, ' ').trim()]),
  )
  const selectedOrigin = form.elements.appOrigin.value
  const appOrigin = ALLOWED_ORIGINS.has(selectedOrigin) ? selectedOrigin : 'https://latexy.xyz'
  await chrome.storage.local.set({ autofillProfile, appOrigin })
  status.textContent = 'Saved in this browser.'
})

document.getElementById('clear').addEventListener('click', async () => {
  await chrome.storage.local.remove('autofillProfile')
  for (const key of PROFILE_FIELDS) form.elements[key].value = ''
  status.textContent = 'Local autofill profile cleared.'
})

void load()
