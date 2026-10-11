/** Match the server's new/updated share-link requirements. Whole-link DELETE
 * revocation is separate and remains available regardless of these grants. */
export function canChangeShare(
  can: (key: string) => boolean,
  anonymous: boolean,
  reviewComments: boolean | undefined,
  regenerateAnonymous = false,
): boolean {
  return can('f01') && (!(anonymous || regenerateAnonymous) || can('f02'))
    && (reviewComments !== true || can('f03'))
}
