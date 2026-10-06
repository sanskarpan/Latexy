export function autofillApplication(profile, doc = document) {
  const clean = (value, max = 300) =>
    typeof value === 'string' ? value.replace(/\s+/g, ' ').trim().slice(0, max) : ''
  const normalized = {
    firstName: clean(profile?.firstName),
    lastName: clean(profile?.lastName),
    fullName: clean(`${profile?.firstName || ''} ${profile?.lastName || ''}`),
    email: clean(profile?.email),
    phone: clean(profile?.phone),
    city: clean(profile?.city),
    region: clean(profile?.region),
    country: clean(profile?.country),
    linkedin: clean(profile?.linkedin),
    website: clean(profile?.website),
  }

  const rules = [
    { key: 'firstName', re: /first.?name|given.?name|fname/i },
    { key: 'lastName', re: /last.?name|family.?name|surname|lname/i },
    { key: 'fullName', re: /full.?name|candidate.?name|your.?name/i },
    { key: 'email', re: /e-?mail/i },
    { key: 'phone', re: /phone|mobile|telephone|tel\b/i },
    { key: 'city', re: /city|locality/i },
    { key: 'region', re: /state|province|region/i },
    { key: 'country', re: /country/i },
    { key: 'linkedin', re: /linkedin/i },
    { key: 'website', re: /website|portfolio|personal.?site/i },
  ]

  const describe = (field) => {
    const labels = Array.from(field.labels || []).map((label) => label.textContent || '').join(' ')
    return [
      field.name,
      field.id,
      field.type,
      field.autocomplete,
      field.placeholder,
      field.getAttribute?.('aria-label'),
      labels,
    ].filter(Boolean).join(' ')
  }

  const setValue = (field, value) => {
    const proto = field instanceof HTMLSelectElement
      ? HTMLSelectElement.prototype
      : field instanceof HTMLTextAreaElement
        ? HTMLTextAreaElement.prototype
        : HTMLInputElement.prototype
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set
    if (setter) setter.call(field, value)
    else field.value = value
    field.dispatchEvent(new Event('input', { bubbles: true }))
    field.dispatchEvent(new Event('change', { bubbles: true }))
  }

  const filled = []
  for (const field of doc.querySelectorAll('input, select, textarea')) {
    if (field.disabled || field.readOnly || field.type === 'hidden' || field.type === 'file') continue
    if (String(field.value || '').trim()) continue
    const rule = rules.find(({ re }) => re.test(describe(field)))
    if (!rule) continue
    const value = normalized[rule.key]
    if (!value) continue

    if (field instanceof HTMLSelectElement) {
      const option = Array.from(field.options).find((candidate) =>
        clean(candidate.value).toLowerCase() === value.toLowerCase() ||
        clean(candidate.textContent).toLowerCase() === value.toLowerCase()
      )
      if (!option) continue
      setValue(field, option.value)
    } else {
      setValue(field, value)
    }
    filled.push(rule.key)
  }
  return { count: filled.length, fields: [...new Set(filled)] }
}
