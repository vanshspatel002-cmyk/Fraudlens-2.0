# FraudLens 2.0 deployment configuration

FraudLens 2.0 is split into two deployed services:

- Frontend: React + TanStack Start + Vite, deployed to Vercel.
- Backend: Python FastAPI (`src/api.py`), deployed to Railway with SQLite on a persistent volume.

There are no Cloudflare Workers, D1, or R2 resources in this deployment path.

## Frontend environment

Only browser-safe values belong in the Vercel frontend project:

```text
VITE_PUBLIC_SITE_URL=https://your-frontend.vercel.app
VITE_API_BASE_URL=https://your-backend.up.railway.app
```

Do not add admin credentials, API tokens, Gemini keys, or database paths to the frontend environment. Any `VITE_` value is bundled into browser-visible code.

## Backend environment

Set these values on the Railway backend service:

```text
FRAUDLENS_DB=/data/fraudlens.db
FRAUDLENS_DATA_DIR=/data
FRAUDLENS_UPLOAD_DIR=/data/uploads
FRAUDLENS_THUMB_DIR=/data/.thumbnails
CORS_ORIGINS=https://your-frontend.vercel.app,http://localhost:5173
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD_SHA256=<sha256-of-admin-password>
EVIDENCE_SERVICE_TOKEN=<optional-server-token>
GEMINI_API_KEY=<gemini-key>
GEMINI_MODEL=gemini-3.5-flash
LLM_PROVIDER=gemini
```

Mount the Railway volume at `/data`. Copy only a deployment snapshot of the SQLite database and uploaded evidence into that volume; do not point the production service at an active ablation database.

## API contract

The frontend calls the FastAPI service directly:

- Public: `GET /health`, `GET /v1/health`, `POST /v1/cases`, `GET /v1/track`, `GET /v1/jobs/{job_id}`.
- Admin protected: queue, case details, traces, images, reports, policies, stats, similar cases, reprocess, and human actions.

Admin requests send the entered admin password as a bearer credential. The backend compares only the SHA-256 digest against `ADMIN_PASSWORD_SHA256`.

## Verification

Before accepting traffic:

1. Confirm `GET /health` on the Railway URL returns `status: "ok"`.
2. Confirm the Vercel frontend has `VITE_API_BASE_URL` set to the Railway URL.
3. Submit a real vehicle image through the frontend and confirm a job id is returned.
4. Log in to `/admin`, open the case queue, view an image, and record a human action.
5. Confirm `CORS_ORIGINS` contains the final Vercel production origin.
