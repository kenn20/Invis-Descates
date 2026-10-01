# Central beta: implementation and verification contract

## Scope

Central Flask API, Google web OIDC initiated from Obsidian, single-use browser-approved pairing, device development tokens, and a dedicated vector collection per account. No full website or worker is required for this beta. Google identifies accounts by verified subject; internal account IDs select vector collections. Tokens bind the account, installation and vault. Re-pairing rotates the device credential without changing its memories.

Each account's vector collection is a separate namespace in PostgreSQL. Every upload, query, generated answer and deletion is constrained by authenticated account and vault ownership before ranking. This is shared managed infrastructure, not a separate database server per user. There is no administrative data endpoint, job queue, object store or retrieval cache in this implementation. New paths must preserve the same ownership checks.

Notes stay read-only in Obsidian. Folder consent starts empty. Memory storage is separately opt-in; indexing sends at most an 8-KiB excerpt after editing stops. The command `Ask your memories` retrieves from the authenticated vault and generates an answer. A full-vault importer, chunking and attachment storage are outside this beta. Vector ranking is in-process, capped at 1,000 memories per account; validate cost and performance before expanding that cap. Keep the same embedding model for a collection's lifetime, or rebuild its vectors.

Central processing can read memories and sends approved content to the configured model provider. Hosting/database encryption and access controls do not provide end-to-end encryption. The local nudge route still uses deterministic proof logic; it is not model-generated or Model Armor screened. The hosted RAG path uses the configured embedding/generation provider directly; it does not implement the earlier Model Armor/RocketRide pipeline. Do not claim those integrations are complete.

## Stack and review order

1. `feat/central-identity` -> `main`: persistent accounts, hashed/expiring tokens, API authentication and device/vault ownership; CI baseline gates.
2. `feat/central-memory` -> `feat/central-identity`: isolated vector collections, retrieval/generation/delete APIs and server-only provider adapter.
3. `feat/google-pairing` -> `feat/central-memory`: Google OIDC, browser approval, CSRF, expiry, shared rate limits and single-use token collection.
4. `feat/obsidian-cloud` -> `feat/google-pairing`: plugin pairing, Secret Storage, hosted transport, consent-based indexing and manual memory queries.
5. `feat/central-deployment` -> `feat/obsidian-cloud`: production configuration, deployment adapter, real PostgreSQL gates and release evidence.

Each PR has its own base and incremental diff. Review and merge bottom-up. If squash-merging a lower PR, rebase the dependent branches before merging; do not merge the entire top branch as an unreviewed replacement. Keep all PRs draft until their gates pass and limitations have been reviewed. Automated CI does not replace staging/manual gates.

## Automated gate

Install Python 3.12 dependencies from `service/requirements.lock` and pytest 9.1.1. Run `npm ci` in `plugin`. Supply an isolated PostgreSQL database with schema-creation permission, then run:

```sh
TEST_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@localhost/ISOLATED_TEST_DATABASE' bash scripts/verify-central.sh
```

The gate requires PostgreSQL rather than silently skipping it. Tests create and remove random isolated schemas, covering real persistence, cross-user ownership, vector isolation and simultaneous pairing polls. Never point it at a production database. CI provisions PostgreSQL and runs the same service tests, plus plugin tests, typecheck and build.

The OIDC tests use real signed tokens and Authlib validation with substituted provider HTTP boundaries. They verify signature, issuer, audience, nonce, expiry and state; they do not prove a real Google account can sign in. Obsidian unit stubs verify configuration and credential placement, not the actual app or OS behavior.

## Candidate hosting: Vercel Python

`api/index.py`, `vercel.json` and root `requirements.txt` prepare the service for Vercel's Python runtime. No Vercel deployment or provider compatibility smoke test has been run. Confirm runtime support, function timeout (allow at least 30 seconds for embedding plus generation), concurrency and PostgreSQL connection limits in staging before selecting it for production. Persistent state lives exclusively in managed PostgreSQL; never use a serverless local SQLite file.

Wasmer remains an alternative if its current Python/WSGI runtime passes the same gates. No Wasmer compatibility is claimed, and Tenki is not required. A portable entrypoint is `service.wsgi:app` for Gunicorn behind a trusted TLS proxy. Do not expose Flask's development server.

The Vercel adapter trusts exactly one forwarded scheme header, and no forwarded host or client-IP header. This is safe only when the hosting platform sanitizes that header and prevents bypassing its proxy. Verify this explicitly in staging. Pairing-start rate limiting may therefore be shared by clients behind the same platform gateway; beta limit is ten starts per minute per observed peer.

## Configuration and initial database

Use `env.example` as variable names only; never deploy its placeholders. Configure Google OAuth, model and session secrets in the hosting provider's server-side settings. Generate the session secret with `python -c 'import secrets; print(secrets.token_urlsafe(48))'` locally and store it as a secret. Do not paste secrets into chat or source control. The plugin receives no provider key or Google client secret.

Use managed PostgreSQL with encrypted storage/backups and `sslmode=verify-full`, plus the provider's CA if required. Limit the application database role to required schema/table access. Database connection pools are capped per function instance, but overall concurrency still needs a provider limit/pooler.

For a **new empty beta database**, set `DATABASE_URL` and run `python -m service.manage` once from a trusted environment. Bootstrap is explicit; app startup never creates tables. This is not a migration framework: do not use it to upgrade an existing identity/memory schema. Review schema changes before deploying over a populated database.

The Vercel upload excludes `default.pipe`, local development artifacts and the plugin. Rotate any previously exposed legacy provider credential before public use; this implementation does not rotate external credentials.

## Google setup

Create a Google web OAuth client, configure the consent screen and add beta test users. Request only `openid email profile`. Register this exact redirect URI for each environment:

```text
https://YOUR_STABLE_SERVER_DOMAIN/auth/google/callback
```

Set `PUBLIC_ORIGIN` to that same HTTPS origin. Production and staging need separate credentials or explicitly registered redirect URIs. Preview domains will be rejected unless deliberately configured as that environment's origin. Basic sign-in grants no Gmail or Drive access.

## Staging gates — pending until evidence is recorded

- Deploy the candidate adapter; confirm `/healthz` and `/readyz` return 204, and readiness fails when the database is unavailable.
- Confirm HTTP is redirected/rejected, unexpected Host is rejected and forwarded-header spoofing cannot bypass the TLS boundary.
- Complete real Google login for two beta accounts from Obsidian. Confirm the browser displays the same pairing code and no credential in the URL, and only the initiating plugin receives a token.
- Confirm pending, expired, cancelled and repeated pairing attempts behave correctly in the actual app. Verify external browser opening and Secret Storage in supported Obsidian versions.
- Store different sentinel memories in two accounts, ask questions from both, and prove no cross-account result. Attempt forged installation/vault IDs against upload, query and deletion.
- Revoke/expire a device credential and confirm all memory/nudge operations reject it. Re-pair the same account and vault; verify the old credential fails and existing memories remain accessible.
- Verify actual embedding and generation calls, timeout/failure behavior, index persistence across function restart, and chosen model/provider data-handling settings.
- Confirm forbidden folders emit no request, removal of consent cancels queued work, and changing server origin never forwards an old credential.
- Verify remote deletion after deleting a stored note, including a reconnect. Multi-device conflict handling and deletion/ingestion races remain deferred; do not claim robust full-vault synchronization.
- Inspect platform access/error logs for sentinel note text and authorization values. Configure payload redaction, encrypted backups and least-privilege provider access.

Record dates, environment, build SHA and evidence for each gate before calling the service deployable or production-ready. Branch protection settings should require both CI jobs before merging; repository administration is separate from adding workflow files.

## Current evidence

Local automated tests, including real PostgreSQL, are recorded in the final PR description. Google credentials have not been configured. No live Google login, model call, Vercel/Wasmer deployment, backup restore or actual Obsidian browser/Secret Storage check has passed. These are pending, not successful or implicitly waived.
