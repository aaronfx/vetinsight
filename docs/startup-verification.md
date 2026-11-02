# Startup and workflow verification — 24 October 2026

The Windows launcher was checked against this checkout:

- Cold start: stopped the identified local backend/frontend processes, ran the launcher, and confirmed both services became ready.
- Repeated launch: both healthy services were reused without starting duplicates.
- Port conflict: temporarily placed a local HTTP fixture on port 8000. Startup exited with code 1 and a clear port-conflict message; the fixture stayed running. Removed the fixture and restored the backend with the launcher.
- Health verification: backend `/health`, `/cases`, `/dashboard` and the frontend responded successfully. Health checks use IPv4 loopback to avoid a slow `localhost` resolution/fallback observed on this machine.
- Failure details and service output were written to timestamped files in `logs/`.
- The `.cmd` wrapper was executed. Windows denied shell browser opening in the agent session; the launcher now reports this separately from service readiness and provides the URL. Automatic browser opening outside this session remains unverified.

Chrome checks:

- Live dashboard and existing case opened.
- Existing sample PDF rendered with page controls and extracted embedded text.
- Annotation changes were tested separately using `backend/tests/preview_server.py` on port 8001 and a QA frontend on port 5174. This uses temporary storage and a visibly labeled geometry image.
- Drew a box, entered category `Geometry circle`, marked the annotation and image Reviewed, and saved. After browser reload, the category, review state and saved revision 1 returned.
- Clicked COCO export. The page reported that the export was prepared and its download requested. Browser download-event tracking timed out, so browser filesystem saving is not confirmed.
- Independently fetched and inspected the resulting ZIP over HTTP: one image, one matching category and box, `annotations.json`, `manifest.json`, and `README.txt` were present.

The live case records and annotations were not edited for these checks. No model training or inference was performed. Startup checks do not provide automatic restart after crashes or Windows reboot.
