# Valorant Clips

Portfolio/CV demo: turn a short recording into kill clips using match timestamps and a manual video offset. Uploads are limited to **10 MB / 15 seconds**, with **72-hour media expiry**. Run locally for zero hosting/storage spend; production availability and paid deployment are out of scope. See [docs/PROJECT.md](docs/PROJECT.md) for scope and [docs/VALIDATION.md](docs/VALIDATION.md) for evidence.

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

This prompts for a new demo email/password, creates a clearly labelled synthetic match with kills at 3, 7 and 11 seconds, and refuses to run in production mode. Upload a 12–15 second recording no larger than 10 MB. It does not verify or impersonate a Riot account.

## Architecture

```mermaid
flowchart LR
    Browser[React browser UI] --> Proxy[Nginx /api proxy]
    Proxy --> API[FastAPI]
    API --> DB[(PostgreSQL)]
    API --> Redis[(Redis: auth limits and RQ)]
    API --> Riot[Riot API and approved RSO]
    API --> Storage[Local storage or optional private S3/R2]
    Worker[RQ worker] --> DB
    Worker --> Redis
    Worker --> FFmpeg[FFmpeg / ffprobe]
    Worker --> Storage
    Cron[Hourly cleanup] --> Storage
    Cron --> DB
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
docker compose -p vclips-smoke --env-file .env.example -f docker-compose.yml -f docker-compose.smoke.yml up -d --build --wait db redis api worker cleanup frontend
docker compose -p vclips-smoke --env-file .env.example -f docker-compose.yml -f docker-compose.smoke.yml exec -T api python -m tests.smoke_docker
docker compose -p vclips-smoke --env-file .env.example -f docker-compose.yml -f docker-compose.smoke.yml exec -T cleanup crontab -l
docker compose -p vclips-smoke --env-file .env.example -f docker-compose.yml -f docker-compose.smoke.yml exec -T cleanup python -m app.workers.cleanup --cron
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

Uploads have a strict **10 MB (10,000,000 bytes)** ceiling, with chunks up to 8 MiB. Middleware rejects oversized video request bodies with 413 before routing; declared total size and chunk offsets enforce the same ceiling across requests. `MAX_UPLOAD_BYTES` may lower the ceiling but cannot increase it. `ffprobe` rejects videos longer than **15 seconds** with 400 before publication/processing. All storage paths use generated keys.

The database generates `videos.expires_at = created_at + 72 hours`. API access and signed media URLs stop at expiry. The `cleanup` container runs cron at minute zero each hour: delete bucket objects (if configured), then local source/clip files, then the video row. Foreign keys delete its clips, shares and processing jobs. Failed storage deletion retains the row for retry. Accounts and shared match metadata remain for reuse. Physical removal can lag expiry by up to an hour, or longer if the stack is stopped. This is disposable demo media, not archival storage.

To run cleanup immediately: `docker compose exec cleanup python -m app.workers.cleanup`. Migration `0004` applies expiry to existing uploads using their original creation time, so old demo media will be removed on the next cleanup run. Signed playback links otherwise last at most 60 seconds; local playback rechecks revocation.

## Configuration and remaining work

`.env.example` lists Riot RSO credentials, public URLs and optional Spaces settings. Use a private Spaces bucket; never publish its access keys. Set `APP_ENV=production`, a strong JWT secret, and HTTPS `FRONTEND_URL`/`PUBLIC_API_URL` before production startup. Hosting and TLS provisioning are not included yet.

Run one RQ worker replica: one job at a time, capped at one CPU, with one FFmpeg codec thread. FFmpeg transcoding never runs in the API. A database lock keeps publication and cleanup from racing; polling sees queued jobs until the final ready/failure commit. Stream copy is keyframe-dependent. Failed jobs are recorded; restart recovery/retry remains outside this change. Peak-memory metrics are measured in Linux child processes. Native picker and cross-browser QA remain open; tiny fixture timings are not benchmarks.

## Free deployment limitations

Treat a free deployment as a **small, low-traffic portfolio demo**, not a promise of unrestricted public uploads or reliable production video processing. A free frontend or API tier alone does not cover this app's PostgreSQL, Redis/RQ worker, FFmpeg compute and recording storage requirements. Verify current provider limits, persistence, worker support, sleep behaviour and overage charges before choosing a host; no free hosting provider has been validated for this project yet.

The current upload pipeline assembles the full recording on local disk before validation and optional publication to S3-compatible storage. The worker also needs a local source file and space for temporary and completed clips. **Configuring Spaces or another object store does not remove local staging-disk requirements.** With the default Compose setup, the API and worker share `storage/`; splitting them across hosts requires a deliberate storage design, not just separate deployments.

The 10 MB / 15-second limits and hourly retention cleanup keep controlled demo use small. They do not cap aggregate traffic or guarantee a provider's free allowance. Per-user quotas are not implemented. Use local Compose and synthetic fixtures for zero-spend demonstrations; no remote bucket or paid infrastructure is provisioned.

DigitalOcean deployment and production availability are out of scope for this CV project. No remote free hosting provider has been validated.

## Riot access

Daily developer keys are insufficient to assume VALORANT access. Live linking needs Riot approval, RSO and explicit player opt-in. [Riot VALORANT policy](https://developer.riotgames.com/docs/valorant), [Riot FAQ](https://developer.riotgames.com/docs/faqs).

Valorant Clips is not endorsed by or affiliated with Riot Games.
