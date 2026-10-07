# Local pipeline change and validation report

Date: 2026-10-08 (Asia/Shanghai). Scope: close out backend retesting and the local Docker recording-to-share MVP. This report does not claim production deployment or live Riot/Spaces verification.

## Major changes

| Change | Purpose and affected files | Verification / limitations |
|---|---|---|
| Database migrations | `backend/alembic/`, `alembic.ini`, settings/session code. Freeze the ten-table baseline, enforce case-insensitive emails, persist upload offsets and prevent duplicate clip/jobs. | Fresh Docker database reached `0003`. Schema/index/constraint tests passed. Earlier legacy adoption compared all ten development tables with `0001` before stamping; development data was not reset. |
| Auth and safe errors | `app/api/auth.py`, `core/security.py`, `core/rate_limit.py`, `services/auth.py`, auth schemas, `main.py`. Argon2, JWTs, real-user checks, Redis limits, password-safe validation and sanitized database errors. | Valid/invalid auth, duplicate emails, token failures, rate-limiter failure, validation redaction and production startup tests passed. Real Redis auth limit passed in Docker. |
| Riot linking and ingestion | `app/api/matches.py`, `services/riot_client.py`, `services/matches.py`, `app/demo.py`. Approved RSO flow, browser-bound single-use state, transactional/cached ingestion and synthetic local demo. | Mocked upstream errors and state tests passed. Callback cookie rejection, successful account linking, cookie cleanup and repeat ingestion passed. Live Riot production access is still required. |
| Recording upload and sync | Video API/schemas, `services/videos.py`, `clip_planner.py`, `storage.py`. Bounded resumable chunks, server-generated paths, ffprobe validation and kill/video alignment. | Real chunk upload, stale-offset rejection, incomplete upload, invalid media, size limits, ownership and boundary math tests passed. Large recordings and native picker QA remain open. |
| Async clipping | `app/workers/`, worker container and shared storage. Durable queued DB jobs dispatched through Redis/RQ, FFmpeg copy/reencode, status/failure handling and processing metrics. | Actual separate Docker worker produced both modes and positive Linux memory/time metrics. Duplicate delivery and safe failure tests passed. General crash recovery and user-facing failed-job retries remain future work. |
| Sharing and media | Share API/schemas/service, React public page. Random tokens, expiry, private access, revocation and short signed media URLs. | Owner preview and anonymous public-page playback verified in the browser. Private rejection, past expiry, revocation and cross-user access passed. Spaces signing is implemented but unverified against a real bucket. |
| Frontend and proxy | React/Vite source, npm lockfile, frontend Dockerfile and Nginx config. Login, match/recording selection, upload, sync, job polling, preview and shares. | Production build passed locally and in Docker. Browser sign-in, uploaded recording selection, ready clip rendering, preview, share creation and anonymous share playback passed. Full cross-browser/native-picker testing is pending. |
| Repeatable validation | `tests/test_security_boundaries.py`, `tests/smoke_docker.py`, `docker-compose.smoke.yml`, Compose health checks and CI. Isolate tests from development data and automate the real pipeline. | 49 backend tests passed on Windows and Linux. Full Docker smoke check passed. CI runs backend and Docker jobs; see the PR checks for remote status. |

Added project-approved dependencies: Alembic, Argon2, PyJWT, Redis, RQ and boto3; React/Vite frontend dependencies are resolved in the npm lockfile. Docker installs FFmpeg. Schema changes are versioned migrations. No live keys, recordings, `.env`, virtual environments or dependency directories belong in the PR.

## Retest results

- Windows Python 3.12: **49 passed, 1 warning**.
- Linux API container Python 3.12: **49 passed, 1 warning**.
- Warning: Starlette deprecates its current httpx TestClient integration. It does not fail tests; dependency migration is deferred.
- React/Vite production build: passed locally and in the Node 24 Docker build.
- Fresh Docker stack: PostgreSQL, Redis, API and frontend health checks passed; separate worker stayed running and completed actual RQ jobs.
- Docker smoke pipeline: passed through the Nginx proxy with synthetic match events and a three-second generated MP4, including both FFmpeg modes, playable signed media, shares and authorization failures.
- Browser media state after the fix: duration **3 seconds**, `readyState=4`, `error=null`, for both owner preview and anonymous public-page playback.

## Issues found and fixed during verification

1. PostgreSQL inferred conflicting types for a reused match-ingestion PUUID parameter. The shared ingestion insert now casts it to the column type; both ingestion and repeat-import tests pass.
2. Nginx's media policy hard-coded API port 8000. The smoke stack used port 18000, so HTTP downloads worked while browser playback was blocked. Signed local media now uses the frontend's own `/api` origin; the hard-coded port was removed and browser playback passed.
3. Direct TestClient tests inherited the Docker reverse-proxy `/api` prefix and failed media requests in Linux. The test fixture now gives the in-process API its own `http://testserver` media origin; both Windows and Linux suites pass.
4. Startup originally waited only for the API process. Compose now waits for actual PostgreSQL/Redis/API health before starting dependent services.

## Remaining project work

- Approved Riot production key/RSO and live API verification.
- Private Spaces bucket integration checks.
- Native file/folder picker, large upload and refresh/resume QA across browsers.
- Complete security review, failed/interrupted-job recovery and storage lifecycle cleanup.
- Measured encoding/upload/query benchmarks on representative datasets.
- DigitalOcean hosting, HTTPS and operational logging.
- Portfolio screenshots and final production documentation.

No development database reset or `.env` edit was performed during this close-out. Only the isolated `vclips-smoke` project was reset for repeat verification. The PR is for review; it must not be merged until its CI checks pass.
