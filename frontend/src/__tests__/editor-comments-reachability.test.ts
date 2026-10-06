import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'
import { containsMentionToken } from '@/lib/comment-mentions'

const editorPath = path.join(
  process.cwd(),
  'src/app/workspace/[resumeId]/edit/page.tsx',
)
const source = fs.readFileSync(editorPath, 'utf8')
const commentsSource = fs.readFileSync(
  path.join(process.cwd(), 'src/components/CommentsPanel.tsx'),
  'utf8',
)

describe('editor comments reachability', () => {
  it('loads the comments panel from the editor bundle', () => {
    expect(source).toContain("dynamic(() => import('@/components/CommentsPanel'))")
  })

  it('offers comments in the right-panel menu and renders the selected panel', () => {
    expect(source).toContain("{ id: 'comments', label: 'Comments', icon: MessageSquare }")
    expect(source).toContain("rightTab === 'comments'")
    expect(source).toContain("<CommentsPanel")
    expect(source).toContain("highlightCommentId={searchParams.get('comment_id') ?? undefined}")
    expect(source).toContain("canComment={collabRole !== 'viewer'}")
  })

  it('uses complete mention-token boundaries and does not load picker data for viewers', () => {
    expect(containsMentionToken('@Ann, please review', 'Ann')).toBe(true)
    expect(containsMentionToken('@Anna please review', 'Ann')).toBe(false)
    expect(containsMentionToken('x@Ann please review', 'Ann')).toBe(false)
    expect(containsMentionToken('Please ping @Ann.', 'Ann')).toBe(true)
    expect(commentsSource).toContain('if (canComment) void loadParticipants()')
    expect(commentsSource).toContain('canComment && editDrafts[comment.id] !== undefined')
  })
})
