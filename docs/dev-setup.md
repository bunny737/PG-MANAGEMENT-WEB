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
