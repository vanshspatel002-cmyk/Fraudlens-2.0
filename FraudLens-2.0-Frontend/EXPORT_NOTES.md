# FraudLens 2.0 source export

Export date: 2026-09-24

## What is included

This repository contains the FraudLens 2.0 frontend: React/TypeScript product routes, TanStack Start SSR setup, bundled media, styles, icons, and Vercel deployment configuration. The production analysis API lives separately in `D:\Projects\fraudlens`.

## Development setup

Use Node.js 22 LTS, version 22.16 or later within the 22.x line.

```powershell
npm ci
Copy-Item .env.example .env
npm run dev
```

Open `http://localhost:5173`.

Useful commands:

```text
npm run typecheck
npm run lint
npm run build
npm run preview
npm run start
npm run admin:password
```

`npm run preview` serves the built Vite output locally on `http://localhost:4173`. `npm run start` runs the Nitro server output used by production-style TanStack Start hosting.

## Environment variables

Only public, browser-safe values belong in this frontend project:

| Name | Purpose |
| --- | --- |
| `VITE_PUBLIC_SITE_URL` | Public HTTPS origin used for canonical URLs, OG URLs, and sitemap generation. |
| `VITE_API_BASE_URL` | Public HTTPS base URL of the FastAPI backend. |

Never put admin passwords, password hashes, service tokens, Gemini keys, database paths, or other secrets in `VITE_` variables.

## Deployment

The frontend targets Vercel. Current TanStack Start deployment requires Nitro and the `tanstack-start` Vercel framework hint, both included here:

- `vite.config.ts` registers `nitro()`.
- `vercel.json` declares `"framework": "tanstack-start"`.
- `package.json` includes `npm run build` and `npm run start`.

Set `VITE_PUBLIC_SITE_URL` and `VITE_API_BASE_URL` in Vercel before production deployment.

## Backend integration

The browser talks to the FastAPI backend directly. See `INTEGRATION.md` for the endpoint and environment contract. The backend should be deployed with SQLite on a persistent Railway volume; this frontend does not require or use Cloudflare Workers, D1, or R2.

## Validation performed

- Fresh npm installation completed without force or legacy peer dependency flags.
- TypeScript check and production build passed locally.
- Lint completed with warnings only.
- Local development server served the application at `http://localhost:5173`.
- Production preview served the built application at `http://localhost:4173`.

Update this list after each deployment verification run with the actual frontend URL, backend URL, and smoke-test result.
