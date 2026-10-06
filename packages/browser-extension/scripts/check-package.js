import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'

const root = resolve(import.meta.dirname, '..')
const manifest = JSON.parse(await readFile(resolve(root, 'manifest.json'), 'utf8'))
if (manifest.manifest_version !== 3) throw new Error('Extension must use Manifest V3')
if (manifest.host_permissions.includes('<all_urls>')) throw new Error('Broad host permission is forbidden')
if (!manifest.permissions.includes('activeTab')) throw new Error('Explicit active-tab access is required')

const referenced = [
  manifest.action.default_popup,
  manifest.options_page,
  ...manifest.content_scripts.flatMap((entry) => entry.js),
]
await Promise.all(referenced.map((file) => readFile(resolve(root, file))))
console.log(`Extension package valid: ${referenced.length} referenced files, least-privilege host scope`)
