# Local Dev Tooling — DB Exploration & ERD

## 1. DBeaver — live schema/data exploration

Install DBeaver Community (free) separately — https://dbeaver.io/download/.
Create a PostgreSQL connection with:

```
Host:     localhost
Port:     5432          (mapped by docker-compose)
Database: pg_platform
```

Two accounts to connect as, depending on what you need:

| User | Password | Use for |
|------|----------|---------|
| `app_user` | `app_password` | Structure browsing, ER diagrams. This is the same non-superuser role the app connects as. |
| `postgres` | value of `POSTGRES_ADMIN_PASSWORD` in `.env` | Browsing actual **row data**. |

> **Why two accounts:** every business table has a Row-Level Security policy
> (see [modules/01-auth-tenancy.md](modules/01-auth-tenancy.md)). Connecting as
> `app_user` without a tenant context set means RLS-protected tables (e.g.
> `audit_logs`) will show **zero rows** even though data exists — DBeaver
> doesn't set the `app.tenant_id` / `app.is_super_admin` session GUCs the app
> sets per-request. For structure (ER Diagram, column browsing) this doesn't
> matter. For inspecting real rows, connect as `postgres` (bypasses RLS), or
> run this in a SQL editor session first:
> ```sql
> SELECT set_config('app.is_super_admin', 'true', false);
> ```

To view the diagram: right-click the `public` schema → **ER Diagram**.

## 2. django-extensions `graph_models` — committed ERD

Generates a diagram from the Django models themselves (relationships as
defined in code), not raw DB introspection. Already wired into this repo:

- `django-extensions` + `pydot` are in `requirements/dev.txt`, `graphviz`
  (the `dot` binary pydot needs) is installed in the Dockerfile, and
  `django_extensions` is added to `INSTALLED_APPS` in `config/settings/dev.py`
  only (dev tooling, not shipped to prod).

Regenerate after any model change:

```bash
docker compose exec backend python manage.py graph_models -a -o erd.png
mv backend/erd.png docs/erd.png
```

Commit the updated `docs/erd.png` in the same commit as the model change —
see the CLAUDE.md checklist.

Current diagram: [erd.png](erd.png).

## 3. Frontend PWA, BFF and push — local testing

- **API calls.** The browser only talks to the Next.js app (`/api/v1/...`); its route handlers call
  Django server-side at `INTERNAL_API_URL` (`http://backend:8000` in compose). `ALLOWED_HOSTS` in `.env`
  must include `backend` (see `.env.example`). After pulling this change, recreate the frontend
  container so it picks up the new env **and the new dependencies** (Serwist, Firebase):
  `docker compose up -d --build -V frontend`. The `-V` matters — `node_modules` lives in an anonymous
  volume, so without it the container keeps the old packages and crash-loops with
  `Cannot find module '@serwist/next'`. The image now runs Node 24 (Firebase 13 requires
  Node >= 24.12; the previous Node 20 image printed EBADENGINE warnings).
- **Service worker is production-only.** `npm run dev` neither builds nor registers it (and unregisters
  one left by an earlier production run on the same origin). To test offline, install and push:
  `npm run build && npm start` in `frontend/`, then open it in a browser. The build uses
  `next build --webpack`.
- **Push needs** the `NEXT_PUBLIC_FIREBASE_*` variables and VAPID key (`frontend/.env.local`), and a
  production build. Turn it on from **More -> Notifications**. Firebase setup:
  [push-notifications-integration.md](push-notifications-integration.md) §2.
- **iPhone testing** needs HTTPS (an ngrok tunnel or staging) and iOS 16.4+. In Safari use Share ->
  Add to Home Screen, then open the installed app; push is only offered from the installed app.
- **Icons** are generated: `node scripts/generate-pwa-icons.mjs` (in `frontend/`).
