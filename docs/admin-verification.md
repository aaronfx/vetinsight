# Administration verification — 1 November 2026

Implemented local account administration with administrator/member roles, first-admin CLI setup, cookie sessions, account creation and disabling, forced temporary-password changes, password reset/session revocation, overview counts and audit activity. Protected case routes include originals, previews, text extraction, annotations, split assignments and exports.

Verification:

- Final backend run: all 36 tests passed (67.006 seconds). Results are in `logs/admin-final-tests.log`.

- Frontend production build and lint passed. All 25 frontend tests passed, including setup/sign-in errors, member denial, required password change, admin account creation and authenticated fetch handling.
- Backend tests cover anonymous requests, forged role headers, member access restrictions, temporary passwords, disabled accounts, role changes, password resets, expired/revoked sessions, cookie flags, origin/security-header checks, last-admin protection, login throttling, pagination, audit entries, and rollback if auditing a case mutation fails. Existing case/document/annotation/split/export tests also run with authenticated clients and isolated storage.
- Chrome on an isolated temporary backend (8001) and frontend (5174) verified sign-in with the synthetic QA administrator and rendered the real Administration screen: overview counts, create-account form, self-protected role/status controls and stored audit events. Browser password resets were not performed. Password-reset and session-revocation behavior is covered by API tests.
- Restarted the live local backend with authentication enabled. `/health` returned OK, `/auth/status` reported setup required, and anonymous `/cases`, `/dashboard`, `/admin/users` and `/openapi.json` requests returned 401. Chrome showed the first-admin setup page at http://localhost:5173/.
- Before restarting, made a SQLite backup at `logs/before-admin.sqlite3` and recorded existing case/upload/annotation/dataset-assignment rows plus original upload SHA-256 hashes. The post-restart comparison was identical. The added account tables contained zero live users.

The user's first administrator remains to be created, so the user chooses the password locally without sending it through chat. No default/live QA credential was installed. No public hosting or Supabase migration was performed. Authentication still uses the local SQLite database. All members share the same case workspace; tenant/case isolation, MFA, email recovery and a tamper-proof clinical audit system are not implemented.

## Local account-creation correction

The original first-run screen offered terminal instructions without a browser form. Added a browser first-administrator form and local-only `/auth/setup` endpoint. Setup checks loopback address, local hostname, absence of forwarding headers, origin/security headers, and zero existing accounts. An exclusive SQLite transaction prevents concurrent first-admin creation. Success creates an authenticated session. Terminal setup remains available as a fallback.

Six new backend setup tests passed, covering successful setup/session creation, closed registration, remote/nonlocal/proxied denial, origin/header rejection, safe validation and concurrent setup. All 27 frontend tests, production build and lint passed. After restarting the local backend and refreshing the user's in-app browser, the username, display-name, password, confirmation and Create administrator account controls were visibly present. The live account remains uncreated for the user to choose credentials.
