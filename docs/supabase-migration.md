# Supabase migration

The backend supports two explicit modes:

- Local: SQLite and original files under `backend/data/` (the default).
- Cloud: PostgreSQL in the private `vetinsight` schema and original files in the private `vetinsight-records` bucket.

There is no automatic fallback from cloud storage to stale local data. The existing application accounts, password hashes, revocable sessions and administrator/member permissions remain in use. They are stored in the private application schema, not Supabase Auth. No frontend Supabase secret or public file URLs are introduced.

## Configure without exposing credentials

Run **Configure-Supabase.cmd**. The local window asks for the database password selected when creating this Supabase project and an existing `sb_secret_` server key from Project Settings → API Keys. It uses the session-pooler host and user observed in this project's Connect dialog. Password special characters are encoded automatically.

Saving writes pending settings to ignored `backend/.env.supabase`. It does not change the running app. Keep that file private. `backend/.env.local` contains active local backend settings only after verified activation. Both files are ignored, as are temporary files and `backend/backups/`. For a different project, supply the appropriate backend variables listed in `backend/.env.example` instead of using the project-specific configuration window.

## Offline migration and activation

Stop the local backend first. The migration refuses to run while its loopback port is in use and holds the port while copying so the backend cannot restart midway. Then, from `backend`:

```powershell
.\.venv\Scripts\python.exe -m app.migrate_cloud --activate
```

Or use `Migrate-Supabase.cmd --activate` from the project root. Without `--activate`, it copies and verifies data but leaves the active backend configuration unchanged; it is not a dry run.

The migration:

1. Checks database connectivity and initializes the private schema. It creates or verifies the private bucket, refusing a public bucket.
2. Takes a consistent SQLite snapshot and copies every referenced original file to a timestamped `backend/backups/` directory. Its manifest records counts and SHA-256 hashes, not plaintext passwords or secret keys.
3. Refuses to overwrite different existing cloud rows or objects. An interrupted run can reuse matching objects; differing content causes a failure.
4. Preserves case/upload/user IDs, patient fields, notes, annotations, review revisions, dataset assignments, password hashes, session-token hashes, audit records and login limits. PostgreSQL identity sequences advance beyond the imported IDs.
5. Downloads each cloud object and compares its SHA-256 with the backed-up original. It compares every database row after committing the copy.
6. Activates the exact verified settings atomically only when `--activate` was supplied and every verification passed.

Run **Start-VetInsight.cmd** after successful activation. Verify your existing account, case library, original downloads, PDF preview/text, image annotations and exports through the normal authenticated app.

If copying fails, the local SQLite database and originals remain intact. Cloud objects successfully uploaded before a failed database transaction may remain private for a retry; they are not overwritten or deleted automatically. If cloud rows differ, inspect the target before retrying rather than deleting records blindly. Do not switch back to an old SQLite backup after new cloud writes without reconciling those changes first.

## Access and file handling

The application schema is outside `public`, uses row-level security without public policies, and revokes schema/table access from PUBLIC and the Supabase `anon`/`authenticated` roles when present. The backend connects as the configured database user and enforces application sessions and roles. The server secret key remains backend-only and is sent in the `apikey` header, not treated as a JWT.

Uploaded originals retain their UUID storage names and original metadata. Cloud downloads are proxied through the existing authenticated endpoints. PDF text extraction, image validation and export materialize private objects in temporary directories that are removed after use. The existing 20 MiB upload limit and export resource limits remain in force. A remote upload is removed if its database transaction fails; a failed cleanup is logged by object ID for follow-up. Storage buckets must be provisioned and private before cloud backend startup succeeds.

For Railway, configure these same variables in the VetInsight backend service, plus the exact frontend origin and secure cookies for HTTPS. Do not host the SQLite snapshot or pending credentials as frontend assets. This migration does not deploy Railway or change your other Railway applications.

## Verification

Run the backend regression suite normally for isolated SQLite and mocked private-storage transport checks. Real PostgreSQL tests require an explicit `VETINSIGHT_TEST_DATABASE_URL`; each creates and removes a unique `vetinsight_test_*` schema, never the production schema. A skipped PostgreSQL test does not establish cloud connectivity or migration success. The migration manifest and post-cutover HTTP/browser checks establish those separately.
