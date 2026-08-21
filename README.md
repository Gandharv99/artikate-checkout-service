# Artikate — Field Asset Check-Out Service

A Django REST API for tracking physical equipment checked out to and returned by employees, built for Artikate Private Limited's Backend Developer (Python/Django) take-home assessment.

## Tech stack

- Django + Django REST Framework
- PostgreSQL 15
- JWT authentication (`djangorestframework-simplejwt`)
- Celery + Celery Beat (Redis broker) for the hourly overdue-notice task
- Docker / docker-compose
- pytest + pytest-django

## Setup — exact commands, clone to working API

```bash
git clone https://github.com/Gandharv99/artikate-checkout-service.git
cd artikate-checkout-service

cp .env.example .env
# .env already contains working defaults for local docker-compose use —
# no values need to be changed to get the stack running.

docker compose up --build
```

Wait for all four services (`db`, `redis`, `web`, `worker`, `beat`) to start — `db` needs to report healthy before `web`/`worker`/`beat` will proceed (this is enforced via `depends_on: condition: service_healthy` in `docker-compose.yml`).

In a **second terminal**, once the stack is up:

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
docker compose exec web python manage.py seed_demo_data
```

The API is now live at `http://localhost:8000/`.

### Authenticating

```bash
curl -X POST http://localhost:8000/api/v1/auth/token/ \
  -H "Content-Type: application/json" \
  -d '{"username": "<your-superuser-username>", "password": "<your-superuser-password>"}'
```

Copy the `access` token from the response and send it on every other request:

```
Authorization: Bearer <access_token>
```

Refresh with `POST /api/v1/auth/token/refresh/` and your `refresh` token when the access token expires.

### Running the test suite

```bash
docker compose exec web pytest -v
```

(or locally, outside Docker, with your venv active and `.env` pointed at `localhost:5433` — see the port note under Assumptions below)

### Manually triggering the Celery task

The task normally runs hourly via Celery Beat. To trigger it on demand:

```bash
docker compose exec web python manage.py shell -c "from checkouts.tasks import flag_overdue_checkouts; flag_overdue_checkouts.delay()"
```

Check `docker compose logs worker` to confirm it picked up and executed the task.

## API overview

All endpoints are under `/api/v1/` and require a JWT bearer token except `/health/`.

| Method & path | Description |
|---|---|
| `POST /auth/token/` | Obtain access + refresh tokens |
| `POST /auth/token/refresh/` | Refresh an access token |
| `GET /health/` | Unauthenticated health check, reports DB connectivity |
| `POST /assets/` | Create an asset |
| `GET /assets/` | List assets — filterable by `status`, `category`, and `search` (matches name or asset_tag) |
| `GET /assets/{id}/` | Retrieve one asset, including `current_holder` |
| `POST /employees/` | Create an employee |
| `GET /employees/` | List employees |
| `POST /checkouts/` | Check out an asset — body: `{asset_tag, employee_code, due_at}` |
| `POST /checkouts/{id}/return/` | Return a checked-out asset — body: `{condition_note, needs_maintenance}` |
| `GET /employees/{employee_code}/summary/` | Lifetime count, currently held, currently overdue, mean hold duration (days) |
| `GET /reports/overdue/` | All open, overdue checkouts, most overdue first |

## Assumptions

- **JWT chosen over token/session auth** — `djangorestframework-simplejwt`. There's no user-registration endpoint in the spec, so authentication is against Django's built-in `User` model, created manually via `createsuperuser`. Access tokens live 1 hour, refresh tokens 1 day — reasonable defaults for an assessment API, not something the spec dictates.
- **Postgres exposed on host port `5433` instead of `5432`** in `docker-compose.yml`, to avoid a conflict with a locally-installed Postgres service already occupying `5432` on the development machine. This only affects the host-side port mapping; inside the Docker network, `web`/`worker`/`beat` reach Postgres via the service name `db` on the standard port `5432`, so this has no effect on how the containers talk to each other.
- **`return_asset()` applies the same `select_for_update()` locking pattern as `check_out()`**, closing an equivalent check-then-act race condition on double-return that isn't explicitly required by rule 7 (which only calls out the checkout race) but is the same class of bug.
- **`Asset.status` is read-only in `AssetSerializer`** — it only ever changes as a side effect of the checkout/return service functions, never via direct client edit, to preserve the invariant that a `CheckOut` row never exists alongside an incorrectly-reported asset status.
- **`mean_hold_duration_days` in the employee summary is computed only over returned checkouts** (`returned_at` not null), per the spec's explicit wording ("mean hold duration in days across returned items"). It returns `null` if an employee has no returned checkouts yet, rather than `0`, since `0` would misleadingly imply a real duration was measured.
- **Seed data (`seed_demo_data`) is safely re-runnable**: it clears and rebuilds checkout state for its own fixed set of 8 assets/4 employees on every run, rather than accumulating duplicates.

## Known gaps

- No API documentation generator (e.g. drf-spectacular/Swagger) is wired in — endpoints are documented in this README instead, given the time budget.
- No CI pipeline (GitHub Actions) is included, since it wasn't part of Part A's required deliverables — reasoning about what such a pipeline *should* look like is covered in Part D3 of `ANSWERS.md`.
- Test coverage focuses on the business-rule and concurrency requirements explicitly listed in A5; it isn't exhaustive of every serializer/validation edge case.

## Repository structure

See `checkouts/` for the domain app (models, services, selectors, views, tasks, seed command, tests) and `config/` for Django project wiring (settings, Celery app, URLs). Business write-logic lives in `checkouts/services.py`; read-side aggregation lives in `checkouts/selectors.py` — kept separate from `views.py` so both are testable and reusable independent of the HTTP layer (e.g. the Celery task and the checkout endpoint both build on the same underlying model logic without duplicating rule checks).
