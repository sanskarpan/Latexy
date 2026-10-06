import assert from 'node:assert/strict'
import test from 'node:test'

import { autofillApplication } from '../autofill.js'

class BaseField {
  constructor({ name = '', type = 'text', value = '', label = '', options = [] } = {}) {
    this.name = name
    this.id = name
    this.type = type
    this._value = value
    this.labels = label ? [{ textContent: label }] : []
    this.options = options
    this.disabled = false
    this.readOnly = false
    this.events = []
  }
  get value() { return this._value }
  set value(value) { this._value = value }
  getAttribute() { return null }
  dispatchEvent(event) { this.events.push(event.type); return true }
}
class Input extends BaseField {}
class Select extends BaseField {}
class Textarea extends BaseField {}

globalThis.HTMLInputElement = Input
globalThis.HTMLSelectElement = Select
globalThis.HTMLTextAreaElement = Textarea

test('fills supported empty identity fields without overwriting or submitting', () => {
  const first = new Input({ name: 'first_name' })
  const email = new Input({ name: 'candidate_email' })
  const phone = new Input({ name: 'phone', value: 'already entered' })
  const file = new Input({ name: 'resume', type: 'file' })
  const country = new Select({
    name: 'country',
    options: [{ value: '', textContent: 'Choose' }, { value: 'IN', textContent: 'India' }],
  })
  const doc = { querySelectorAll: () => [first, email, phone, file, country] }

  const result = autofillApplication(
    { firstName: 'Jordan', email: 'jordan@example.com', phone: '555', country: 'India' },
    doc,
  )

  assert.equal(first.value, 'Jordan')
  assert.equal(email.value, 'jordan@example.com')
  assert.equal(country.value, 'IN')
  assert.equal(phone.value, 'already entered')
  assert.equal(file.value, '')
  assert.deepEqual(result, { count: 3, fields: ['firstName', 'email', 'country'] })
  assert.deepEqual(first.events, ['input', 'change'])
})
