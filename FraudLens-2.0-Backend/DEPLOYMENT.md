# FraudLens backend deployment

Target: Railway FastAPI service with SQLite and evidence files on a persistent volume.

## Railway service

Use this repository root as the Railway service source. `railway.json` starts:

```text
uvicorn src.api:app --host 0.0.0.0 --port $PORT
```

Mount a persistent volume at `/data`.

## Environment

Set these Railway variables:

```text
FRAUDLENS_DB=/data/fraudlens.db
FRAUDLENS_DATA_DIR=/data
FRAUDLENS_UPLOAD_DIR=/data/uploads
FRAUDLENS_THUMB_DIR=/data/.thumbnails
CORS_ORIGINS=https://your-frontend.vercel.app
ADMIN_EMAIL=admin@example.com
ADMIN_PASSWORD_SHA256=<sha256-of-admin-password>
EVIDENCE_SERVICE_TOKEN=<optional-server-token>
GEMINI_API_KEY=<gemini-key>
GEMINI_MODEL=gemini-3.5-flash
LLM_PROVIDER=gemini
```

Do not store these values in git.

## Data snapshot

Before production traffic, copy a deployment snapshot into the mounted volume:

```text
/data/fraudlens.db
/data/uploads/
/data/curated/
/data/generated/
```

The API resolves existing SQLite image paths like `data/curated/...` through `FRAUDLENS_DATA_DIR`, so the same DB can run with `/data` as the production data root.

The current local DB plus `data/` directory is about 501 MB before filesystem overhead, so Railway free/trial 0.5 GB storage is too tight for the full snapshot.

## Verification

After deploy:

```text
GET https://your-backend/health
GET https://your-backend/v1/health
```

Then deploy the frontend with `VITE_API_BASE_URL=https://your-backend` and confirm case submission, admin login, image viewing, and human action recording from the Vercel URL.
