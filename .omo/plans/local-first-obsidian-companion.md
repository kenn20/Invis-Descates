# Local-First Obsidian Companion Security Plan

## Summary

Build a desktop Obsidian plugin connected to a Python companion on `127.0.0.1`. The plugin exclusively reads the vault; the companion authenticates it, screens input through Google Model Armor, invokes RocketRide Cloud, screens the response, and returns a validated nudge.

Model Armor is a managed cloud dependency, not authentication or offline protection. Use `us-west1`, disable payload logging, and fail closed.

## Scope

In scope: local pairing, opt-in vault access, opaque identifiers, reflection nudges, local staleness reminders, Model Armor input/output screening, RocketRide generation, accessible Obsidian UI, and security-first tests.

Out of scope: public hosting, real multi-user accounts, GitHub mirroring, experience-linking retrieval, scheduler/MCP infrastructure, and write access to vault content.

## Implementation Tasks

- [ ] 1. Correct `specs/Design.md`, rotate the exposed provider credential, use `${ROCKETRIDE_OPENROUTER_APIKEY}`, ignore `.env`, and add `env.example`.
- [ ] 2. Create a typed FastAPI companion bound only to `127.0.0.1:27123`, with strict request parsing and loopback/Host protections.
- [ ] 3. Implement a 60-second pairing window that exchanges a one-time code for a 256-bit bearer token; store only its SHA-256 digest in a private local file and store the client token in Obsidian `SecretStorage`.
- [ ] 4. Build the Obsidian plugin boundary: empty-by-default folder allow-list, opaque installation/vault/note IDs, local policy enforcement, revision tracking, and stale-response rejection.
- [ ] 5. Add separate `us-west1` Model Armor input and output templates and exhaustive fail-closed verdict handling with payload logging disabled.
- [ ] 6. Integrate the existing RocketRide chat pipeline with streaming and pipeline tracing disabled, require one typed answer, and validate it before display.
- [ ] 7. Implement the accessible nudge indicator, side panel, settings, pairing, pause, and offline/error states using native Obsidian components and CSS variables.
- [ ] 8. Document the future OIDC Authorization Code with PKCE ownership model without implementing hosted identity infrastructure.

## Public Interfaces

- `GET /healthz`: unauthenticated readiness without sensitive details.
- `POST /v1/pair`: available only during the pairing window; accepts the one-time code and opaque installation/vault identifiers.
- `DELETE /v1/pairing`: authenticated revocation of the current pairing.
- `POST /v1/nudges:evaluate`: authenticated, versioned evaluation request; never accepts a filesystem path.

Evaluation requests carry `schemaVersion`, `requestId`, `installationId`, `vaultId`, `noteId`, `revision`, `createdAt`, `trigger`, a bounded excerpt, and bounded signals. Responses echo correlation fields and use an exhaustive `show`, `silent`, or `blocked` decision.

## Security Decisions

- Bind only to IPv4 loopback, require an exact loopback `Host`, emit no CORS headers, and reject browser preflights.
- Use Obsidian 1.11.4 or later so the token can live in `app.secretStorage`.
- Keep path-to-ID mappings and folder authorization inside the plugin.
- Model Armor input handling: no match forwards original content; sensitive-data-only matches forward non-empty transformed content; injection, malicious URL, hard-safety, mixed, unknown, partial, timeout, or malformed results block.
- Model Armor output uses the same fail-closed rule before anything reaches Obsidian.
- Disable Model Armor sanitize-operation payload logging, RocketRide tracing, and streaming callbacks.
- Log only correlation ID, stage, duration, and coarse verdict.
- Use Google Application Default Credentials; do not create service-account key files.

## Verification Strategy

- Security-first TDD for pairing, token rotation, loopback restrictions, payload bounds, folder traversal, opaque IDs, stale responses, and every Model Armor verdict.
- Integration tests prove blocked input never reaches RocketRide and unscreened output never reaches the plugin.
- Logging tests prove sentinel note text and credentials never appear in logs.
- End-to-end testing uses a temporary vault and live loopback service for pairing, allowed/excluded notes, invalid tokens, service restart, and upstream failure.
- Manual Obsidian QA covers keyboard access, focus behavior, light/dark themes, narrow panes, pause, token revocation, and uninterrupted offline writing.
- A credentialed smoke test exercises the real `us-west1` Model Armor templates and RocketRide pipeline before release.

## Assumptions

- The first release targets one user on desktop Obsidian.
- The plugin and companion are local, but Model Armor, RocketRide Cloud, and the configured LLM are external processors.
- Cloud-backed failures produce silence; deterministic local reminders may continue offline.
- Live cloud verification requires owner-provided ADC access and rotation of the exposed OpenRouter credential.
