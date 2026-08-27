export type ResumeAccessRole = 'owner' | 'editor' | 'commenter' | 'viewer'

const EDIT_ROLES = new Set<ResumeAccessRole>(['owner', 'editor'])

export function canEditResume(role: ResumeAccessRole): boolean {
    return EDIT_ROLES.has(role)
}
