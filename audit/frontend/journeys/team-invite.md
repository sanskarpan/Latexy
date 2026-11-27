# Team workspace invite journey - 2026-11-27

**Verdict:** PASS with a P2 UI-state defect (FE-18 / #2347).

## Setup

- Fresh synthetic team: owner + member (`interact9.*@example.test`), both verified.
- Synthetic active team subscription, tenant, workspace (`39b352af-...`), owner membership.
- Owner invited the member through `/workspaces/{workspaceId}` → "Invite by email" → Enter.

## Evidence

- `team-invite-journey.json` - owner/member text before and after, console/HTTP.
- `team-workspace-owner.png` - immediately after invite (still 1/5).
- `team-workspace-owner-loaded.png` - owner after reload (2/5, member Editor).
- `team-workspace-member-loaded.png` - member's view of the shared workspace.

## Result

| Step | Observed |
|---|---|
| Owner workspace | 1/5 members, invite form present |
| Invite by email + Enter | API succeeds; member is created |
| Owner page after 4s | **Still 1/5**, no member row, no visible toast |
| Member `/workspaces` | "Interaction9 Workspace", **2/5 members** |
| Member opens workspace | 2/5, owner + member rows, Editor role |
| Owner after reload | 2/5, member row present |

No console errors and no HTTP >= 400 in the successful path.

## Defect

The owner's page does not apply the invite response; the member list/count are stale until a reload. The submit button is an icon-only Plus with no accessible name, and the email field has only a placeholder. Tracked in **#2347**.

## Cleanup

- Workspace members, workspace, tenant member, tenant, subscription, sessions and both users deleted.
- Remaining `interact9.%` users: **0**.
