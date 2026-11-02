# VetInsight frontend

React/TypeScript case interface for the FastAPI backend. See the [project README](../README.md) for startup, API configuration, storage and verification commands.

The frontend uses `src/api.ts` to create/list/view cases and upload documents. `VITE_API_BASE_URL` defaults to `http://localhost:8000`. Vite runs on port 5173 to match backend development CORS. No AI analysis is performed.

`DocumentViewer.tsx` previews PDFs with locally bundled PDF.js, page navigation and zoom, or displays JPG/PNG images. Embedded PDF text is fetched from the local backend and shown by page beside the PDF. Separate Download actions retain attachment delivery. `npm.cmd test` runs viewer component tests; `npm.cmd run build` and `npm.cmd run lint` verify TypeScript, packaging and lint.

The responsive Stitch-inspired shell uses hash navigation with dashboard, case list, create-case and overview screens. `CytologyWorkspace.tsx` implements image zoom/pan, manual SVG regions, editable categories and explicit annotation saves. `geometry.ts` converts pointer coordinates through the image plane's actual bounds; normalized coordinates survive resizing and zoom. Tests exercise the complete draw/edit/save/reopen sequence and coordinate invariants.
## Case dataset splits

Case overview and Cytology show a case-wide split selector: Unassigned, Training, Validation or Test. Changes save immediately through the real backend with revision checking. Current and future images inherit the case assignment; exports record it in their manifest. This organizes manually labeled data and performs no automatic cell detection or labeling. See the root README for the API contract and verification results.

