# VetInsight

Local React/Vite frontend and FastAPI backend for creating, listing and viewing veterinary cases and attaching records. No AI analysis or diagnoses are performed.

Latest local milestone checks: [1 November 2026 verification](milestone-verification.md).

Production hosting: [Railway deployment and persistent storage](railway-deployment.md).

Research data pilot: [P-Hem data audit, patch preparation and evaluation](../research/phem/README.md). This offline work is separate from deployed manual review; no trained cytology model is deployed.

The responsive workspace follows the supplied Stitch references: teal navigation, pale dashboard panels, a case library, create-case form, case overview, clinical record viewer and split cytology image/inspector layout. Counts, patient details, records and actions come from the real backend. The design exports' sample metrics, staff identities, model telemetry and compliance claims are not included.

## One-click startup (Windows)

For the PostgreSQL/private-object-storage integration and safe cutover workflow, see [Supabase migration](supabase-migration.md). Local mode remains active until a verified migration is explicitly activated.

Double-click **Start-VetInsight.cmd** in the project folder. It starts the backend and frontend in the background, waits for the API/database and frontend checks to pass, then opens http://localhost:5173/. Running it again reuses healthy services. A conflicting port or startup failure produces a readable error and keeps the launcher window open. Timestamped startup and service logs are saved in `logs/`.

The launcher uses the existing virtual environment, installed Node.js and frontend dependencies; it does not install packages or change saved cases/uploads. Complete the setup steps below first on a new machine. Services stay running after the launcher closes, but do not start automatically after Windows restarts; double-click the launcher again. This is startup verification, not continuous service monitoring. The launcher uses the default local ports 8000 and 5173; keep `VITE_API_BASE_URL` at its default for this workflow.

For startup checks without opening a browser:

```powershell
.\scripts\Start-VetInsight.ps1 -NoBrowser
```

## Start the backend (PowerShell)

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Use the virtual environment's Python directly; activation is unnecessary. Run from `backend` so Python can import `app.main`. API docs: http://localhost:8000/docs. Health: http://localhost:8000/health. Stop with Ctrl+C.

For a fresh setup, Python 3.11+ is required (this checkout uses installed Python 3.14):

```powershell
# run from the repository root
python -m venv backend/.venv
.\backend\.venv\Scripts\python.exe -m pip install -r backend/requirements.txt
```

If a virtual environment refers to a removed Python installation, recreate it with the installed Python as above.

Runtime dependencies are documented in `backend/requirements.txt`: FastAPI (HTTP routing/OpenAPI), Pydantic (input/output validation), Uvicorn (ASGI server), python-multipart (file form parsing), and pypdf (local embedded PDF text extraction). SQLite uses Python's standard library. `backend/requirements-dev.txt` adds HTTPX for tests. `backend/requirements-lock.txt` pins the tested runtime and test dependency versions; install it with `python -m pip install -r requirements-lock.txt` using the virtual environment's Python from `backend` to reproduce those versions.

## Start the frontend (second PowerShell terminal)

```powershell
Set-Location frontend
npm.cmd install
npm.cmd run dev
```

Open http://localhost:5173. Vite fixes port 5173 and fails if it is occupied, matching backend development CORS for `http://localhost:5173` and `http://127.0.0.1:5173`. API calls default to `http://localhost:8000`; to change this, copy `frontend/.env.example` to `frontend/.env.local`, edit `VITE_API_BASE_URL`, and restart Vite. A different frontend origin also requires updating the backend CORS list.

## API contract

| Method | Path | Behavior |
| --- | --- | --- |
| GET | `/health` | Checks SQLite; returns `status` and `database` |
| POST | `/cases` | Creates case, returns detail and HTTP 201 |
| GET | `/cases?limit=100&offset=0` | Case array, newest first; limit 1–100, offset >= 0 |
| GET | `/cases/{case_id}` | Case fields and `uploads` array |
| POST | `/cases/{case_id}/uploads` | Multipart field `file`; returns upload metadata and HTTP 201 |
| GET | `/cases/{case_id}/uploads/{upload_id}` | Downloads original file attached to that case |
| GET | `/cases/{case_id}/uploads/{upload_id}/preview` | Inline PDF/JPG/PNG with canonical Content-Type |
| GET | `/cases/{case_id}/uploads/{upload_id}/text` | PDF embedded text with page boundaries and extraction status |
| GET | `/dashboard` | Whole-database case, PDF, image and saved annotation counts; recorded species |
| GET | `/cases/{case_id}/uploads/{upload_id}/annotations` | Image dimensions, saved boxes, review status and revision |
| PUT | `/cases/{case_id}/uploads/{upload_id}/annotations` | Validates and saves the image's manual annotations with optimistic revision checking |
| GET | `/cases/{case_id}/exports/coco` | Downloads reviewed, classified saved annotations and oriented image copies as a case-scoped COCO ZIP |
| GET | `/cases/{case_id}/dataset-assignment` | Saved whole-case dataset split, revision and timestamp; new cases are Unassigned |
| PUT | `/cases/{case_id}/dataset-assignment` | Saves `unassigned`, `train`, `validation` or `test` with optimistic revision checking |

Case JSON: `{"patient_name":"Luna","species":"Dog","notes":"Check-up"}`. Patient name and species are required, trimmed, non-blank strings, limited to 120 and 80 characters respectively. Notes default to empty and are limited to 10,000 characters. Unknown fields are rejected. Responses include integer IDs and UTC creation timestamps. Upload metadata includes filename, content type, byte size and relative download URL.

Errors use JSON `detail`: 400 for invalid/empty filenames or empty files, 404 for missing records/files, 413 for files over 20 MiB, 415 for unsupported extensions or mismatched file signatures, 422 for invalid input, and 503 for unavailable storage. The frontend displays backend validation messages and connection failures.

Uploads accept `.pdf`, `.jpg`, `.jpeg`, `.png` (case insensitive), checking the extension against the file header. This is basic format identification, not full document decoding or malware scanning. Browser-supplied MIME types are not trusted. Storage filenames use UUIDs; original filenames are metadata. Explicit downloads use attachment delivery. Size enforcement occurs while copying the parsed multipart file to permanent storage; a production reverse proxy should also enforce request-body limits.

## Document viewer and local text extraction

Each document has separate **View** and **Download** actions. View opens a panel inside the app. PDF.js renders PDF pages on a canvas with Previous/Next page navigation and 50–200% zoom; the worker is bundled locally. JPG/PNG files use a local image viewer with zoom. Loading, missing-file, unsupported or damaged preview, and text extraction failures are displayed separately. Downloads retain the original bytes and filenames.

Preview delivery uses a supported-format allowlist, canonical Content-Type, `Content-Disposition: inline`, `X-Content-Type-Options: nosniff`, private/no-store caching, and a sandbox Content Security Policy. The original endpoint continues to send `Content-Disposition: attachment`. Both endpoints resolve records through their case and upload IDs and check storage path containment. The canvas viewer does not execute document scripts or expose embedded attachment/link actions.

Upload metadata adds `preview_url` and `text_url`. The PDF text endpoint returns `status`, `page_count`, and `pages`: each page has its original one-based `page_number`, plain `text`, and `status`. Overall status is `extracted`, `partial` (some pages lack text), or `ocr_required` (all pages lack text). Pages without embedded text show **OCR required**, including scanned PDFs; no OCR is run. This is local document text extraction, not AI clinical-field extraction. Case names, species and notes are never populated or overwritten from a document. Text is displayed as plain text, never HTML.

Text extraction rejects encrypted, zero-page, malformed or unsupported PDFs with a clear 422 error. Non-PDF extraction returns 415. Extraction limits are 500 pages, 10 MiB decoded page content and 2 million total text characters (413); these guard ordinary oversized documents, not a full resource-isolation sandbox. Existing upload validation, SQLite schema and persistent files are preserved.

## Dashboard, cases and manual cytology

The sidebar links Dashboard, Cases, Clinical records and Cytology workspace. Clinical records and cytology require selecting a case; hash routes preserve case links through refresh/back navigation. The dashboard shows actual database totals, including saved manual regions needing review. Cases can be filtered by patient name or case ID (number, `#1`, or `CASE-0001`) and recorded species. Pagination returns 20 cases per frontend page; `/cases` keeps its array response and original default limit of 100, with optional `search` and `species` filters. Summary responses add `upload_count` and `image_count`.

Create-case accepts manual patient/species/notes and optional attachments. If an attachment fails after the case is created, the case remains saved and the overview displays the error so uploads can be retried. Existing PDFs retain preview, local text extraction and explicit Download. Images in the overview link to annotation workspaces for that exact case and upload.

In Cytology, choose an attached JPG/PNG. Drag with **Draw box** to mark a region; **Pan image** drags the view, and **Select box** or the region list opens its inspector. Zoom is 50–500% of fit, not optical magnification. **Fit image** recenters the view. Remove and redraw a box to change its geometry. Category suggestions include **Unclassified** and **Needs Review**, and custom category text is supported. Category/observation edits reset that annotation to Needs Review. Annotation and image review statuses are **Needs Review**, **In Progress** and **Reviewed**; an image can be marked Reviewed after all its boxes are Reviewed. These are manual workflow states, not clinical sign-off or immutable records.

**Save annotations** explicitly persists the current boxes and review states in SQLite. The UI distinguishes unsaved changes, shows saved revision/time, and warns before discarding unsaved work when changing cases, images or pages. A stale revision returns 409 and retains the local edits; **Reload saved** can reload the current server version after confirming discard. The dashboard counts saved annotations, not uncommitted drafts.

Coordinates are normalized to the displayed original image: `x`, `y`, `width`, `height` in [0,1], not CSS pixels. The backend validates finite coordinates, positive dimensions, in-image bounds, unique UUIDs, categories and review statuses (up to 1,000 boxes/image). It validates image metadata with Pillow and accounts for EXIF orientation. Zoom, pan and ResizeObserver-driven fitting change the image plane; the SVG overlay uses the same plane, keeping regions attached to the image. Pixel coordinate readouts derive from original image dimensions. No scale bars, microscope calibration, WSI tiles, AI boxes, confidence scores or diagnoses are generated.

Annotations use the additive `annotation_sets` table keyed by upload ID, alongside existing cases/uploads. No existing case or upload rows are rewritten by this feature. CORS permits PUT from the existing development origins. An optional `VETINSIGHT_FRONTEND_ORIGIN` adds one exact origin for a separate local frontend; the default remains port 5173.

## Reviewed annotation export

In the Cytology workspace, **Download case COCO ZIP** exports saved data for the selected case. Save or reload unsaved edits first. The button displays preparation and backend errors; requesting a download does not confirm that the browser saved it to disk.

Only images saved as **Reviewed**, with at least one box, are included. Every box must be **Reviewed** with a category other than **Unclassified** or **Needs Review** (case insensitive). If any box is incomplete, the whole image is excluded to avoid dropping individual labels from an otherwise exported image. Empty images are excluded because an empty annotation set does not establish a negative training example. Review status does not establish exhaustive labeling or clinical validity. If no images qualify, the endpoint returns 422 with instructions. Missing eligible files return 404; malformed images return 422. Excluded images and reasons are listed in the manifest.

The ZIP contains:

- `annotations.json`: [COCO detection format](https://cocodataset.org/#format-data), with images, categories and boxes in original-image pixels as `[x, y, width, height]`; area is the box area and `iscrowd` is zero. No segmentation masks or model scores are generated.
- `images/`: RGB PNG copies with EXIF orientation baked into pixels and embedded metadata stripped; transparent pixels are composited on white. Filenames use numeric case/upload IDs. Original uploads remain unchanged and can still be downloaded normally.
- `manifest.json`: case/upload IDs, saved revisions and timestamps, exact original normalized boxes, UUIDs, categories, review states, reviewer observations, source/export SHA-256 hashes and skipped-image reasons.
- `README.txt`: export policy, coordinate conventions and merge/split guidance.

Case names, species, clinical notes and original upload filenames are omitted. Image pixels and reviewer observations can still contain identifying information; this is not an anonymization guarantee. Category IDs are assigned from sorted category names within each archive. When merging case exports, remap IDs by name. The manifest records the saved case assignment but does not train a model or establish image-use permission.

Exports read saved upload metadata and annotations in one SQLite snapshot and use temporary files, cleaned after response delivery or failure. Limits are 200 eligible images, 100 million total decoded pixels and a 256 MiB ZIP. Exceeding a limit returns 413. Export uses the existing Pillow dependency; no new dependencies are required.

Export verification on 2026-10-06: 18 backend tests and 15 frontend tests passed, together with production build and lint. Export tests verify normalized-to-pixel conversion, category mapping, exclusion policy, case isolation, orientation-correct image pixels, transparency handling, resource limits, original download bytes, unchanged saved cases/annotations, missing-file errors and temporary-file cleanup. Frontend tests cover the case-specific download request, loading, disabling export during unsaved edits and backend errors. In Chrome, an isolated synthetic fixture's saved review produced the export-requested state; ZIP contents were verified directly through HTTP. Browser download-event tracking was unavailable, so browser filesystem saving was not confirmed. [Export QA screenshot](annotation-export-qa.png). Live clinical data was not modified. Real clinical cytology data and model training remain unverified.

## Case dataset splits

Case overview and the Cytology workspace include **Dataset split**. Choose **Unassigned**, **Training**, **Validation** or **Test**. Changes save immediately; the control displays loading/saving/errors and the confirmed saved revision. Cytology disables changes while annotation edits are unsaved. A failed save retains the previous confirmed split. Conflicting changes return 409 and require **Reload saved split** before retrying.

The additive `dataset_assignments` SQLite table stores one assignment per case. Existing cases default to Unassigned without rewriting clinical fields, uploads or boxes. Every current and future image in that case inherits the assignment; per-image split overrides are not supported. PUT body: `{"split":"train","revision":0}`. Allowed split values are lowercase API values shown above, revision must be a nonnegative integer, and unknown fields are rejected. Saving the existing split with the current revision is a no-op. A change increments the revision, including when resetting to Unassigned.

COCO manifests include `split` (null for Unassigned), a `dataset_assignment` object with the saved case ID, split, revision and timestamp, and each included image's inherited split. Uploads, annotations and assignment are read in the same database snapshot. Export remains case-scoped, including when Unassigned; no combined dataset, folder partitioning or randomized allocation is created. Category IDs remain local to each ZIP. When combining exports, remap categories by name and select one assignment revision per case. Previously downloaded ZIPs are immutable snapshots; regenerate them after reassignment rather than mixing old and new splits.

Training is for fitting a model; validation is for development choices; test is for final evaluation. Case grouping prevents images within one case being assigned independently. It does not detect repeated patients, related specimens or duplicate images stored in different cases; those require additional grouping before training. Synthetic images are interface fixtures and should not establish clinical model accuracy. This update performs no cell detection, automatic labeling or model training.

Verified on 2026-10-07: 21 backend tests, 18 frontend tests, production build and lint passed. Tests cover default assignments, strict input validation, case isolation, reassignment/reset, stale-revision conflicts, unchanged case/upload/annotation data, image inheritance, manifest revisions and application restart. The real Uvicorn HTTP test additionally verifies the split across two separate server processes. Frontend tests cover save/reopen, failed saves, explicit conflict reload, loading retry and disabled controls during unsaved annotation edits. Live health and both live cases' default assignments returned 200; no existing case assignments were changed for testing. Fresh Chrome visual verification was blocked by browser-control timeouts, so it is not claimed.

## Persistence and verification

The default database is `backend/data/vetinsight.sqlite3`; file bytes are under `backend/data/uploads/`. Both survive backend restarts and are ignored by Git. Paths are anchored to the backend directory regardless of the working directory. Set `VETINSIGHT_DATA_DIR` before starting to use another storage directory. Back up both database and uploads together while the backend is stopped.

```powershell
Set-Location backend
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m pip check
Set-Location '..\frontend'
npm.cmd test
npm.cmd run build
npm.cmd run lint
```

Tests use isolated temporary storage and cover health, create/list/detail, PDF/JPG/PNG uploads, exact downloaded bytes, application and Uvicorn process restart persistence, case ownership, validation, upload cleanup, safe filenames and CORS. Format fixtures test header identification, not full PDF/image validity. To check manually: create a case, upload a record, stop and restart the backend, then refresh the frontend and download the record.

Verified on 2026-10-06 with Python 3.14.3: 13 backend tests, 13 frontend tests, `pip check`, frontend production build and lint passed. Tests cover the original record/upload/preview flow plus annotation validation, custom categories, review states, revision conflicts, exact coordinates through application and Uvicorn process restarts, case ownership and unchanged clinical fields. Frontend tests exercise pointer drawing, zoom, pan, resizing, save/reopen, failed saves and explicit reload, together with the document viewer. PDF rendering is mocked in component tests; real rendering was checked in Chrome with the uploaded Cooper PDF.

Browser QA checked the live dashboard, existing case overview and preserved Cooper PDF preview/text. The original PDF's SHA-256 and existing case notes remained unchanged. Cytology was checked against isolated temporary storage using a visibly labeled geometry fixture, because the live case has no cytology image. A box was drawn by browser drag, edited, saved and recovered on page reload; normalized coordinates were exactly unchanged after 100% → 125% zoom and resizing to a 390px viewport. The responsive case form also created a fictional QA case through the real API. The isolated test backend was separate from the user's running backend; no QA cases/images were added to live storage. Physical microscope images, touch hardware and clinical interpretation have not been validated. Screenshots: [live dashboard](dashboard-live.png), [cytology QA](cytology-workspace-qa.png).

The existing fictional `VetInsight_Sample_Clinical_Record (1).pdf` was verified through the live API and browser: one page, 1,771 extracted characters containing Cooper, inline preview rendered beside page text, and zoom changed from 100% to 125% and back. Preview and download returned HTTP 200 with bytes identical to the stored original (SHA-256 `47eee1f05d9ef710ce9b88f79baa1ad518295e0210ec0dc133b6ac919cb1b181`). Case details remained unchanged. The browser download-event tracker timed out, so file saving through the browser was not confirmed; the download response and bytes were verified directly over HTTP. Screenshot: [Cooper preview](cooper-preview.png). Starlette currently emits a deprecation warning for its HTTPX TestClient integration; tests pass with the pinned versions.

## Administration and sign-in

The application now requires sign-in for case records, attachments, annotations, exports and dashboard data. Administrators also have an **Administration** page with account totals, account creation, role/status editing, temporary-password resets and paginated audit activity. Members share access to all workspace cases; there is no per-clinic or per-case ownership isolation.

To create the first administrator, use **Start-VetInsight.cmd** and open http://localhost:5173/. The first-run page has username, display name, password and password-confirmation fields. Choose a password of at least 12 characters and select **Create administrator account**. A successful setup signs you in. Browser setup is restricted to direct loopback requests with a local hostname and no forwarding headers, and closes as soon as the first account exists. Simultaneous setup submissions cannot create two initial administrators. There are no default credentials or public signup endpoints.

As an alternative, double-click **Setup-Admin.cmd** from the project folder and enter credentials in the terminal (password entry is hidden). Terminal setup also refuses to run after any account exists. From PowerShell in `backend`, the equivalent command is:

```powershell
.\.venv\Scripts\python.exe -m app.manage_admin
```

Administrators create additional accounts with temporary passwords. The user must replace the temporary password before accessing the workspace. Disabling an account, changing its role or resetting its password revokes its sessions. The backend prevents disabling or demoting the last active administrator. **Your account** supports changing your own password and signs out other sessions. Email invitations, email password recovery, MFA, per-case permissions and backups/restoration UI are not implemented. Optional Supabase database/storage integration is documented in [Supabase migration](supabase-migration.md); local SQLite/file storage remains the default.

Passwords use salted PBKDF2-HMAC-SHA256 with 600,000 iterations. Random session tokens are stored as SHA-256 hashes in SQLite; browser cookies are HttpOnly, SameSite=Lax and expire after eight hours. Logout revokes the current session. Login throttling persists in SQLite: 10 attempts per normalized username and 50 per source address per 15-minute window. Requests forwarded through a proxy may share an address and quota; proxy-aware rate limiting needs deployment-specific configuration.

Writes require the `X-VetInsight-Request: 1` header. Browser origins are checked against the exact CORS allowlist, and credentialed requests are supported. `/health`, `/auth/status` and `/auth/login` are public. `/auth/setup` is unauthenticated but restricted to local first-run setup as described above. API documentation requires an administrator session. Login/logout, account updates and successful case writes are recorded without passwords or clinical notes. Case mutation audit entries commit with the data change. This is an application audit log, not a tamper-proof clinical record.

For future HTTPS hosting, set `VETINSIGHT_SECURE_COOKIES=1` and `VETINSIGHT_FRONTEND_ORIGIN` to the exact frontend origin. Use a same-site deployment (or proxy `/api` through the frontend origin) so cookie authentication works; unrelated frontend/backend domains require a separately designed cross-site cookie configuration. Credentials are never placed in frontend local storage or download URLs. The current storage remains local SQLite/files, and startup still binds to loopback.

New endpoints: `GET /auth/status`, local-only `POST /auth/setup`, `POST /auth/login`, `GET /auth/me`, `POST /auth/logout`, `POST /auth/password`, `GET /admin/overview`, `GET /admin/users`, `POST /admin/users`, `PUT /admin/users/{id}`, `POST /admin/users/{id}/password` and `GET /admin/audit`.
# Offline research backup

The [MIDOG canine histology experiment](../research/midog/README.md) is separate
from the deployed case workspace and P-Hem cytology research. Its verified
annotation audit and tested importer are available locally. An eleven-case CC0
MIDOG++ experiment completed paired baseline and higher-resolution training
with validation checkpoint selection and three reserved test cases. Test AP50
was 0.000398 for the baseline and 0.094443 for the revised configuration.
Both models missed all 138 test mitoses at score 0.5. Grouping uses source cases,
and patient independence remains unverified. See the [measured results](../research/midog/RESULTS.md)
and [Windows reproduction commands](../research/midog/EXPERIMENT.md).
The [first three-case pilot](../research/midog/PILOT.md) remains documented.
