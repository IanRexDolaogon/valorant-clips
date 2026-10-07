# Valorant Clips

Turn your own match recording into kill clips using Riot match timestamps and a manual video offset. The local recording-to-share pipeline is implemented and validated. Live Riot approval, Spaces verification, benchmarks, complete security review and deployment remain open. See [docs/PROJECT.md](docs/PROJECT.md) for scope and [docs/VALIDATION.md](docs/VALIDATION.md) for the change report and evidence.

## Local setup (PowerShell)

```powershell
Copy-Item .env.example .env # first setup only; do not overwrite an existing .env
```

Replace `JWT_SECRET=change_me` in `.env` with a random value of at least 32 characters. For example, generate one with `py -3.12 -c "import secrets; print(secrets.token_urlsafe(48))"`. Keep it out of commits and chat.

```powershell
docker compose up -d --build
```

Frontend: http://localhost:8080. API: http://localhost:8000/docs. Health: `/health`, PostgreSQL readiness: `/health/db`. The frontend proxies `/api`; signed local media URLs use `PUBLIC_API_URL=http://localhost:8080/api`. API/worker share local `storage/` by default. PostgreSQL and Redis host ports bind only to localhost.

Requires Docker Compose 2.24.4 or newer for the disposable overlay's `!override` tags; local validation used Compose 5.5.1. The frontend Docker build uses Node 24 and the committed npm lockfile.

## User flow

Register or sign in, link an approved Riot account, import a match, select your recording and upload it. Align a known kill with the recording, then create clips. Choose re-encode for precise cuts or stream copy for faster cuts around keyframes. Clips default to three seconds before and two seconds after each kill, bounded by recording duration.

The RQ worker picks up committed queued jobs. The UI polls status and shows processing time. Preview ready clips or create an expiring unlisted share link. Private shares require the owner. Changing sync after clips exist is rejected; use a new recording to apply a different offset.

For local development without Riot approval, create synthetic match events:

```powershell
docker compose exec api python -m app.demo
```

This prompts for a new demo email/password, creates a clearly labelled synthetic match with kills at 5, 15 and 25 seconds, and refuses to run in production mode. Upload a recording of at least 30 seconds to that match. It does not verify or impersonate a Riot account.

## Architecture

```mermaid
flowchart LR
    Browser[React browser UI] --> Proxy[Nginx /api proxy]
    Proxy --> API[FastAPI]
    API --> DB[(PostgreSQL)]
    API --> Redis[(Redis: auth limits and RQ)]
    API --> Riot[Riot API and approved RSO]
    API --> Storage[Local storage or private Spaces]
    Worker[RQ worker] --> DB
    Worker --> Redis
    Worker --> FFmpeg[FFmpeg / ffprobe]
    Worker --> Storage
```

## Existing database adoption

The API runs `alembic upgrade head` before serving requests. A new database needs no manual setup. A database initialized by the old `schema.sql` already has tables and will fail the first migration rather than erase data.

Back up the existing database, verify **all columns, primary/foreign keys, unique/check constraints and indexes** match `backend/alembic/versions/0001_initial.sql`, then adopt that baseline once:

```powershell
docker compose run --rm --no-deps api alembic stamp 0001
docker compose up -d api
```

Do not stamp a modified or partially initialized schema. Never use `down -v` to solve migration errors on a database you need to keep. Root `schema.sql` is a historical reference; future changes belong in migrations. The initial migration has its own immutable SQL snapshot.

## Backend tests

```powershell
docker compose --profile test up -d --wait test-db
cd backend
py -3.12 -m venv .venv # first setup only
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:DATABASE_URL = "postgresql+psycopg://vclips_test:test-only@127.0.0.1:5433/vclips_test"
$env:TEST_DATABASE_URL = $env:DATABASE_URL
$env:JWT_SECRET = "test-secret-at-least-32-characters"
python -m alembic upgrade head
pytest -v
```

The test database is separate and ephemeral. Test writes roll back. Without `TEST_DATABASE_URL`, integration tests skip; CI always sets it, migrates PostgreSQL 16, and runs the full suite. Test database names must end in `_test` to protect development data.

## Disposable Docker pipeline check

From the repository root, using a distinct project and localhost ports 18080/18000:

```powershell
$env:SMOKE_JWT_SECRET = (& py -3.12 -c "import secrets; print(secrets.token_urlsafe(48))")
docker compose -p vclips-smoke --env-file .env.example -f docker-compose.yml -f docker-compose.smoke.yml up -d --build --wait db redis api worker frontend
docker compose -p vclips-smoke --env-file .env.example -f docker-compose.yml -f docker-compose.smoke.yml exec -T api python -m tests.smoke_docker
```

The check generates a tiny recording, creates disposable synthetic match data, uploads through Nginx, verifies resumable offsets and validation, then waits for the **real Redis/RQ worker** to cut clips in both modes. It checks wall-time/memory metrics, signed playback, private-share rejection, expiry, revocation, cross-user access and the real Redis auth limit. It refuses any database except `vclips_smoke_test`. The smoke account credentials are test fixtures only.

The smoke script expects fresh data. To repeat or clean up, remove only this disposable project, then rerun the commands above:

```powershell
docker compose -p vclips-smoke --env-file .env.example -f docker-compose.yml -f docker-compose.smoke.yml down -v
```

This does not touch the development Compose project or `.env`. GitHub Actions runs both PostgreSQL-backed backend tests and this Docker check on PRs. Require green checks before merging.

## API entry points

Swagger at `/docs` documents request/response bodies. Protected routes use `Authorization: Bearer <JWT>`.

| Area | Routes |
|---|---|
| Authentication | `POST /auth/register`, `POST /auth/login`, `GET /auth/me` |
| Riot linking | `GET /riot/link`, `GET /riot/callback`, `GET /riot/accounts` |
| Matches | `POST /matches/import`, `GET /matches`, `GET /matches/{id}/kills` |
| Recordings | `POST /videos`, `GET /videos`, `GET /videos/{id}` |
| Upload/sync | `PUT /videos/{id}/chunks?offset=...`, `POST /videos/{id}/complete`, `PATCH /videos/{id}/sync` |
| Clip jobs | `POST /videos/{id}/clips`, `GET /videos/{id}/clips` |
| Preview/sharing | `GET /clips/{id}/media`, `POST /clips/{id}/shares`, `GET /shares/{token}`, `DELETE /shares/{token}` |

Uploads default to 20 GiB maximum, with chunks up to 8 MiB. All storage paths use server-generated keys. `ffprobe` validates the actual media. Local signed playback links expire after at most 60 seconds; refresh via Preview or the public page. Local playback rechecks share revocation on each request. Spaces URLs remain usable until their short signed expiry.

## Configuration and remaining work

`.env.example` lists Riot RSO credentials, public URLs and optional Spaces settings. Use a private Spaces bucket; never publish its access keys. Set `APP_ENV=production`, a strong JWT secret, and HTTPS `FRONTEND_URL`/`PUBLIC_API_URL` before production startup. Hosting and TLS provisioning are not included yet.

The default worker runs one job at a time; progress records stages rather than frame-level percentages. Stream copy is keyframe-dependent. Failed jobs are recorded, but user-facing retry/recovery for interrupted processing is still future work. Peak-memory metrics are measured in Linux worker child processes; Windows helper runs return no memory measurement. Large uploads, native picker behaviour and other browsers need broader manual QA. Tiny smoke-fixture timings are validation data, not performance benchmarks.

## Free deployment limitations

Treat a free deployment as a **small, low-traffic portfolio demo**, not a promise of unrestricted public uploads or reliable production video processing. A free frontend or API tier alone does not cover this app's PostgreSQL, Redis/RQ worker, FFmpeg compute and recording storage requirements. Verify current provider limits, persistence, worker support, sleep behaviour and overage charges before choosing a host; no free hosting provider has been validated for this project yet.

The current upload pipeline assembles the full recording on local disk before validation and optional publication to S3-compatible storage. The worker also needs a local source file and space for temporary and completed clips. **Configuring Spaces or another object store does not remove local staging-disk requirements.** With the default Compose setup, the API and worker share `storage/`; splitting them across hosts requires a deliberate storage design, not just separate deployments.

Before a public demo, lower the default 20 GiB upload limit to fit measured host capacity, add per-user storage quotas and retention/cleanup, and budget disk for recordings, clip output and concurrent work. Quotas and automatic cleanup are not implemented yet. Verify long-running worker support, container/CPU architecture compatibility, HTTPS, backups and recovery from restarts. Do not rely on free-tier availability or local disk as the only copy of important data.

DigitalOcean remains the planned production target. A free VM running the existing Compose stack may be evaluated as a demo alternative, but this is not a hosting migration or a verified deployment.

## Riot access

Daily developer keys are insufficient to assume VALORANT access. Live linking needs Riot approval, RSO and explicit player opt-in. [Riot VALORANT policy](https://developer.riotgames.com/docs/valorant), [Riot FAQ](https://developer.riotgames.com/docs/faqs).

Valorant Clips is not endorsed by or affiliated with Riot Games.
