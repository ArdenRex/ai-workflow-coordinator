# Deploying from one GitHub repo to Vercel (Step F6)

One repository, **two Vercel projects**. Both import the same GitHub repo; they differ only in *Root Directory*.

| | Frontend project | API project |
|---|---|---|
| Root Directory | `frontend` | `.` (repo root) |
| Framework | Create React App (read from `frontend/vercel.json`) | Other (reads `vercel.json` and `api/index.py`) |
| Build | `npm run build` | none (Python function) |
| Ignored files | n/a | `.vercelignore` leaves out the frontend, tests, docs and migrations |

## 1. Database (before anything else)
The API needs PostgreSQL (Neon, Supabase or similar). SQLite is refused in production and Vercel's disk is read-only. Use the provider's **pooled** connection string. This must be a **new, separate database**, not the Coordinator's.

From your own machine, once, and after every release that adds a migration:
```
DATABASE_URL=postgresql://... alembic upgrade head
DATABASE_URL=postgresql://... alembic current        # must show 0020
```
Vercel does not run migrations. If the schema is behind, login and logout fail with database errors.

## 2. API project: environment variables
`APP_ENV=production`, `APP_SECRET_KEY` (32+ random characters; keep an offline copy), `DATABASE_URL`, `ALLOWED_ORIGINS=https://<your-frontend-domain>` (exact origin, no trailing slash, never `*`), `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_API_KEY`, `TRUSTED_PROXY_COUNT=1` (see below). The app refuses to start in production if one is wrong; the full list is in docs/PRODUCTION.md.

## 3. Frontend project: environment variable
`REACT_APP_API_URL=https://<your-api-domain>` (no trailing slash). It is baked in at build time, so redeploy the frontend after changing it. The same two values must agree: the API's `ALLOWED_ORIGINS` is the frontend's address, and the frontend's `REACT_APP_API_URL` is the API's address.

## 4. Check it
```
python scripts/preflight.py https://<your-api-domain> --smoke --check-migrations
```
(`--check-migrations` needs `DATABASE_URL` set on the machine running it.) Then open the frontend, register, create a workspace, and watch Account > recent activity: the address shown should be yours, not Vercel's. If it is wrong, change `TRUSTED_PROXY_COUNT`.

## Limits of running the API on Vercel (read before real customers)
- **Login throttling is weaker.** Counters live in each function instance's memory, and Vercel runs many instances. Lockout after failed logins will not be reliable until the counters move to shared storage. Treat this as a launch risk.
- **Nothing runs in the background.** Workflow schedules and event dispatch do not fire on their own. Drive them with a Vercel Cron call or a separate worker (not built).
- **Request time limit.** A function stops after `maxDuration` (60 s in `vercel.json`; your plan may cap it lower). A long AI plan run can be cut off.
- **Cold starts** make the first request after idle slower.
- **Not tested on Vercel here.** The entry point is tested only by importing it and calling `/health`; I could not deploy from the build sandbox.
- The Dockerfile and `docker-compose.yml` are unused on Vercel. A container host remains the better fit for the API if these limits matter.
