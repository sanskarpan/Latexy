/** A version is a compatibility contract, never inferred from existing routes. */
export const GUIDED_BUILDER_VERSION = 1

export function supportsGuidedBuilder(capabilities: unknown): boolean {
  return typeof capabilities === 'object'
    && capabilities !== null
    && 'guided_builder_version' in capabilities
    && capabilities.guided_builder_version === GUIDED_BUILDER_VERSION
}
