import { createHash } from 'node:crypto'
import { FIRST_USE_ENGINE_RESUME_TEMPLATE } from '../../src/lib/first-use-resume'

const digest = (text: string) => createHash('sha256').update(text).digest('hex')

/** One editable bullet from the actual submitted source, never fabricated text. */
export function projectGuestBullet(source: string) {
  const match = /^\\item[ \t]+([^\r\n]+)/m.exec(source)
  if (!match) throw new Error('Guest fixture source has no plain bullet')
  const text = match[1]
  const start = match.index + match[0].length - text.length
  return {
    document_id: 'guest', source_mode: 'imported', content_revision: 1,
    source_sha256: digest(source), structured_version: null, template_id: null, opaque_blocks: [],
    nodes: [{ node_id: 'guest-bullet', node_revision: digest(text), section: 'Experience', kind: 'bullet',
      text, source_span: { start, end: start + text.length }, editable: true, ai_editable: false }],
  }
}

export const GUEST_ORIGINAL_BULLET = projectGuestBullet(FIRST_USE_ENGINE_RESUME_TEMPLATE).nodes[0].text

/** Model the guest patch CAS and splice only the projected span. Fail loudly if
 * the fixture's source/node identity drifts instead of returning a successful no-op.
 */
export function applyGuestBulletPatch(body: {
  latex_content: string; expected_source_sha256: string
  patches: Array<{ node_id: string; expected_node_revision: string; text: string }>
}) {
  const document = projectGuestBullet(body.latex_content)
  const node = document.nodes[0]
  const patch = body.patches[0]
  if (body.expected_source_sha256 !== document.source_sha256
    || body.patches.length !== 1 || patch?.node_id !== node.node_id
    || patch.expected_node_revision !== node.node_revision) {
    throw new Error('Guest fixture patch has stale source or node identity')
  }
  if (!patch.text || /[\r\n]/.test(patch.text)) throw new Error('Guest fixture expects one plain bullet')
  const source = body.latex_content.slice(0, node.source_span.start) + patch.text
    + body.latex_content.slice(node.source_span.end)
  return { document: projectGuestBullet(source), latex_content: source }
}
