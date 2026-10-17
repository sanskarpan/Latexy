"""Static trust policy for the nonproduction renderer functional harness."""

# Keep this exact-name allowlist in reviewed source. The runner's acknowledgement,
# ENVIRONMENT=test, and a self-set Modal environment variable do not establish that
# an arbitrary Modal Environment is nonproduction.
TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS = frozenset({
    "billing-acceptance-20261014",
})


def is_trusted_functional_acceptance_environment(name: object) -> bool:
    """Return true only for an exact, source-reviewed nonproduction environment name."""
    return isinstance(name, str) and name in TRUSTED_FUNCTIONAL_ACCEPTANCE_ENVIRONMENTS
