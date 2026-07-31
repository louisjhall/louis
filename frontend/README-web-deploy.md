# CrewFit Coach Dashboard — Web Deployment (Cloudflare Pages)

This document describes how the **existing Expo Router coach dashboard** is
deployed as a standalone production web app at
**`https://coach.crewfit.net`** — while leaving the mobile app, backend and
Production database completely untouched.

## Architecture

```
┌─────────────────────────┐        ┌─────────────────────────┐
│  iOS / Android CrewFit  │        │  Coach Web (Cloudflare) │
│  (app.json v1.0.2)      │        │  coach.crewfit.net      │
└───────────┬─────────────┘        └───────────┬─────────────┘
            │                                  │
            └──────────────┬───────────────────┘
                           ▼
         ┌────────────────────────────────────┐
         │  Existing Production API           │
         │  https://flight-fit-plans          │
         │            .emergent.host          │
         │  ── FastAPI + MongoDB (unchanged)  │
         └────────────────────────────────────┘
```

Both frontends run the **same Expo codebase** and call the **same Production
API**. Mobile stores JWT in AsyncStorage; web stores JWT in localStorage
(AsyncStorage polyfills to localStorage on web automatically).

## What ships to Cloudflare Pages

Nothing bespoke — this is the standard Expo web export. The build command
runs `npx expo export --platform web` which produces a static `dist/`
directory containing HTML, JS, assets and the `_redirects` SPA fallback
from `public/_redirects`.

## Cloudflare Pages — one-time setup

1. **Sign in** at [dash.cloudflare.com](https://dash.cloudflare.com/) →
   Workers & Pages → **Pages** → **Create application** → **Connect to
   Git** → select the CrewFit repo.

2. **Set up builds and deployments** — copy these exact values:

   | Field | Value |
   |---|---|
   | Production branch | `main` (or whichever branch you deploy from) |
   | Framework preset | None |
   | Build command | `cd frontend && yarn install --frozen-lockfile && npx expo export --platform web --clear` |
   | Build output directory | `frontend/dist` |
   | Root directory | *(leave empty)* |

3. **Environment variables** (Production + Preview):

   | Variable | Value |
   |---|---|
   | `EXPO_PUBLIC_BACKEND_URL` | `https://flight-fit-plans.emergent.host` |
   | `NODE_VERSION` | `20` |
   | `YARN_VERSION` | `1.22.22` |

4. Click **Save and Deploy**. First build takes ~4–6 min. When it finishes
   you get a `https://<project-name>.pages.dev` URL — smoke-test it first.

5. **Smoke test** — open the `.pages.dev` URL in a browser:
   - Should render the CrewFit login screen.
   - Log in as coach → should redirect to `/(coach)/v2-home` on desktop
     widths.
   - Client list should match the Production data you see in the mobile
     app.

6. **Attach the custom domain** — in the Pages project → Custom domains →
   Add `coach.crewfit.net`.
   - If `crewfit.net` is on Cloudflare DNS, the CNAME is auto-created.
   - Otherwise, at your registrar create a CNAME:
     `coach → <project-name>.pages.dev`
   - SSL is issued automatically (Let's Encrypt). Takes 2–5 min.

## Redeploys

Every push to the production branch triggers a fresh build automatically.
No manual step. No coordination with the mobile publish flow.

## What this deployment intentionally does NOT do

- ❌ Does not create a second backend
- ❌ Does not create a second database
- ❌ Does not create a second auth system
- ❌ Does not touch `app.json`, bundle IDs, versionCode, buildNumber
- ❌ Does not require any change to the FastAPI backend (CORS already
     accepts `allow_origins=["*"]`)
- ❌ Does not trigger a mobile OTA update (no JS files under `/app/**` or
     `/src/**` were modified)
- ❌ Does not affect the installed CrewFit iOS/Android apps in any way

## Cost

Free — Cloudflare Pages free tier covers:
- 500 builds / month
- Unlimited requests
- Unlimited bandwidth
- Custom domain + SSL

For a coach dashboard used by a small team of coaches, this is never near
the ceiling. Even at 100 active coaches with heavy daily use, cost stays
at $0.

## Environment variable precedence — important gotcha

Expo loads `/app/frontend/.env` at build time, but **environment variables
set through Cloudflare Pages (or any parent process) take precedence over
`.env` values.** This is standard `@expo/env` behaviour.

- Local Preview build → uses `.env` (points at the container's preview URL).
- Cloudflare Pages build → uses Cloudflare's `EXPO_PUBLIC_BACKEND_URL`
  value (points at Production `flight-fit-plans.emergent.host`).

The `--clear` flag on the export command forces Metro to discard any
cached bundle from a previous build so the new env var is baked in
correctly. Cloudflare Pages starts from a clean filesystem on every build
so caching is a non-issue there — the flag is belt-and-braces.

## Rollback

Cloudflare Pages keeps every previous deployment. To roll back to the
last known-good version:
- Cloudflare dashboard → Pages project → Deployments → find the previous
  deployment → **Rollback to this deployment**. Takes < 30 s. No git
  changes required.

## Troubleshooting

- **Login works locally on Preview but fails on `coach.crewfit.net`** —
  Open browser devtools → Network → confirm requests go to
  `https://flight-fit-plans.emergent.host/api/...`. If they go to
  `coach.crewfit.net/api/...`, the `EXPO_PUBLIC_BACKEND_URL` env var
  wasn't picked up at build time.
- **404 on deep links like `coach.crewfit.net/coach/v2-home`** —
  `public/_redirects` is missing from the deploy or wasn't included in
  `dist/`. Confirm the file exists in the build output.
- **CORS error in console** — should never happen since backend uses
  `allow_origins=["*"]`. If it does, check that the FastAPI CORSMiddleware
  is still registered (see `server.py` bottom of file).

## Files that make this deployment possible

- `/app/frontend/public/_redirects` — SPA fallback so client-side routing
  works after refresh / paste / deep-link.
- `/app/frontend/README-web-deploy.md` — this file.

No other file in the repository was modified for this deployment.
