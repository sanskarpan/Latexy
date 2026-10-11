# Explicit semantic review providers — October 8, 2026

Managed resume optimization now accepts an explicit OpenAI, Anthropic or
OpenRouter provider and an exactly operator-priced model. Selection resolves
the authenticated owner's readable key before consuming quota or dispatching.
Missing keys, decryption failures, unsupported models and model-only overrides
fail admission. Explicit selections never fall back to the platform credential
or its endpoint. Automatic retains the previous behavior.

`GET /resumes/engine/providers` advertises only this owner's key availability,
configured priced model IDs and nonsecret Automatic readiness. It performs no
provider request. Availability indicates an active stored key; the admission
step additionally requires successful decryption. No schema, SDK or automatic
pricing changes are included.

Anthropic uses native Messages SSE through the existing HTTPX dependency at a
fixed endpoint. Redirects and automatic retries are disabled. Framing bytes are
bounded; duplicate/nonfinite JSON, invalid event ordering, missing usage,
truncation and refusal are rejected. Cumulative output usage is counted once.
The request sends no prompt-cache controls, and positive or malformed cache
token categories fail closed because their rates are not in the two-rate price
contract. Deadline and cancellation watchdogs close blocked headers or silent
bodies. OpenRouter retains the bounded OpenAI-compatible stream path.

Endpoint/protocol identity joins provider/model, credential scope and private
context in durable admission and paid-stage replay. Provider/model changes cannot
reuse a previous candidate's context or an ambiguous paid stage. Credentials are
not written into provider-choice metadata. Existing ownership, fact checks,
request/token/cost limits, partial results and candidate acceptance stay in force.

Protocol reference: [Anthropic streaming](https://platform.claude.com/docs/en/build-with-claude/streaming)
and [prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching).
Fixtures use synthetic HTTPX/OpenAI-compatible responses; no paid calls were made.

The initial combined real PostgreSQL/Redis run passed 137 cases and failed one
new fixture that supplied a non-UUID outsider user ID. The fixture now persists
a distinct valid user and checks that this account cannot see another owner's
provider key availability. The prior watchdog failure did not recur in this
combined run. Final rerun results are recorded in the release audit and hashed
JUnit summary rather than treating the fixture failure as a passing test.

Final rerun: **138 passed, zero failures/skips**, 341.26 seconds, with real
isolated PostgreSQL/Redis and infrastructure preflight enabled. It includes
semantic provider, durable ledger, quota and worker-preparation regressions.
Frozen backend tree: `afca6ba3fe9e1c607874928a56b09d32a8599864`.
Ruff on all changed backend modules/tests and Modal entrypoint passed.
