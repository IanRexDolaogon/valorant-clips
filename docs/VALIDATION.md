# Local pipeline change and validation report

## CV demo constraints update — 2026-10-08

| Major change | Reason / affected areas | Validation |
|---|---|---|
| Strict upload ceiling | `core/uploads.py` middleware bounds video requests before routing, including streamed bodies without Content-Length. Settings and upload metadata enforce at most 10,000,000 bytes across chunks. | Header rejection, streamed overflow, exact 10 MB boundary and oversized declared total passed. Existing chunk and offset tests still pass. |
| Short demo footage | `storage.probe` rejects duration above 15 seconds with 400 before publication. UI describes limits; synthetic demo events fit a 12–15 second video. | Real ffprobe tests accept 15 seconds and reject 15.1 seconds; rejected media is never published. Frontend Docker build passed. |
| 72-hour media aggregate expiry | Migration `0004` adds indexed, UTC-generated `videos.expires_at`. Video/clip/share/media access rejects expired uploads; signed URLs are capped at media expiry. | Database calculation is exactly 72 hours. Expired owner preview, video listing, share playback and clip planning are rejected; expired queued clips are not encoded. |
| Storage-first hourly cleanup | Native cron runs `app.workers.cleanup` at minute zero each hour. Optional bucket deletes and local-file removal precede the video row deletion; existing FKs cascade to clips, shares and processing jobs. | Tests verify bucket deletion occurs while the row exists, local files and dependent rows are removed, unexpired media survives, deletion failure retains the row, and retry is idempotent. Real Docker smoke cleanup passed. Installed hourly crontab and cron environment restoration were verified by running its command. |
| Bounded asynchronous worker | Existing RQ worker processes one job at a time; Compose limits it to one CPU, FFmpeg codec threads to one. Parent-row locking serializes publication with cleanup. No API transcoding. | Actual separate RQ worker produced copy and reencode clips with positive processing/RSS metrics. Linux and Windows suites passed. |
| Portfolio scope / zero spend | README and PROJECT now define a CV demo, local storage/Compose and no paid deployment requirement. Existing authentication/ownership stays in place. | No paid service was provisioned, no new Python dependency added, and no development DB migration/reset or `.env` edit performed. |

Results: **58 passed, 1 non-failing Starlette deprecation warning**, on both Windows and Linux; frontend production Docker build passed; complete disposable Docker pipeline, expiry cleanup and cron command passed. CI includes the cleanup service and cron command in its Docker job; require green checks on the new PR before merging.

Limits: media becomes inaccessible at 72 hours, but hourly physical deletion can lag by up to an hour while the stack runs, or longer when stopped/unavailable. Associated media records are videos, clips, shares and processing jobs; accounts and reusable shared match metadata remain. A real S3/R2 bucket is unverified (deletion order/failure tests use a fake client). Local Compose incurs no hosting/storage subscription; TTL alone cannot guarantee a remote free allowance under unlimited traffic. This is not production availability work. The publication lock keeps job status changes in one transaction, so UI polling sees queued until ready/failed.

The earlier report below records the original pipeline implementation and remains historical; its production deployment/security roadmap is superseded by the CV scope above.

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
- GitHub Actions: **backend-tests** and **docker-pipeline** passed for implementation commit `5a5e5a7` on [PR #4](https://github.com/IanRexDolaogon/valorant-clips/pull/4). Subsequent documentation commits must also retain green PR checks.

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

No development database reset or `.env` edit was performed during this close-out. Only the isolated `vclips-smoke` project was reset for repeat verification, then removed with its test storage. The PR remains open and unmerged for review.
