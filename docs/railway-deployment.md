# Railway deployment

The signed-in workspace includes a Research section at `/#research`. It displays
audited MIDOG++ results and four clearly labeled demonstration tiles with saved
model candidates. These are recorded outputs from the completed experiment.
The score slider filters the selected example, while the metrics describe the
full held-out cohort. The published model limitation remains visible at the top.
The reviewed CC0 example pixels and summary are served under `/assets/research/`.

The root Dockerfile builds React and serves its output through FastAPI. Production API requests use the same origin as the frontend. Local Vite development still uses port 5173 and backend port 8000.

Configure the existing `vetinsight` service from `aaronfx/vetinsight`, branch `main`, repository root (no Root Directory override). Railway detects the root Dockerfile and railway.json sets `/health` as the deployment health check. The server listens on Railway's `PORT` with one Uvicorn worker.

Attach a persistent Railway volume at `/data` before deploying. The image sets `VETINSIGHT_DATA_DIR=/data`, keeping the database and original uploads on that volume. Startup refuses Railway SQLite mode without a volume, or with a data directory outside its mount. Keep one replica. Do not activate Supabase variables when using this local-storage deployment.

Generate a Railway public HTTP domain targeting the injected `PORT`. The application allows that exact HTTPS origin from `RAILWAY_PUBLIC_DOMAIN`. For a custom domain, additionally set `VETINSIGHT_FRONTEND_ORIGIN` to its exact HTTPS origin. Secure HttpOnly cookies are enabled in the image. The frontend and API must share the same hostname.

No local records, account hashes, credentials or uploads are copied into the image. This starts a new empty data store. The public website serves the sign-in page and health/auth status; case records, downloads and API documentation remain authenticated. Local-only browser administrator setup remains disabled over the Internet.

## First administrator

Use a trusted terminal with the Railway CLI connected to this project and service:

```powershell
railway ssh --service vetinsight -- python -m app.manage_admin
```

Enter the username/display name and password at the prompts. Password entry is hidden. This command must execute inside the running container so it uses `/data`; running `railway run` locally is not equivalent. No default administrator password is supplied. If an account already exists, setup refuses to replace it. Then open the Railway domain and sign in. The CLI's final localhost URL is a local-development hint; use the deployment's HTTPS URL instead.

Back up the volume separately; persistence across deployments does not itself provide backups. Railway volume deployments may briefly interrupt service. No AI integration is configured.
