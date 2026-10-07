# PROJECT.md — Valorant Clips

Project reference for AI coding agents working in this repo: **what** we are building and the rules of the codebase. Read fully before making changes.

- `AGENTS.md` (repo root) is the entry point and points here.
- `.agents/skills/` holds the workflow skills (e.g. `ponytail.md`) that define **how** agents work.

> **Individual Project.** One developer owns this codebase and must be able to explain every part of it without AI help. Favor simple, readable code over clever code, and explain non-obvious decisions in your replies.

---

## 1. What we're building

A web app where Valorant players turn match recordings into shareable kill clips.

**CV demo constraints (override earlier production plans):** This is a portfolio demonstration, not a commercial or production-ready app. Keep architecture clear and operational spending at zero; use local Compose without paid hosting or storage. Demonstrate sync, a distributed queue and retention without high-availability or scaling work.

- Uploads are at most **10 MB (10,000,000 bytes)**, including total resumable upload size. API middleware rejects oversized request bodies with **413** before routing, including requests without Content-Length.
- `ffprobe` validates duration before publication or clip processing. Videos longer than **15 seconds** return **400**.
- `videos.expires_at` is database-generated from `created_at + 72 hours`, using UTC arithmetic. Source videos, clips, shares and processing jobs are one ephemeral media aggregate. Users and shared match/event data are not media records and remain available for the demo.
- API access and signed media links stop at expiry. **Hourly cron** queries `expires_at < now()`, deletes S3/R2 objects (when configured) and local files first, then deletes the video row, cascading to clips, shares and jobs. Storage failures retain rows for the next retry. Physical deletion can lag expiry by up to an hour while services are running; hourly cron cannot promise deletion at exactly 72 hours.
- All transcoding stays in RQ. Run exactly one worker replica; one job at a time, one CPU and one FFmpeg codec thread. API duration probing is validation, not transcoding, and runs outside the async event loop.
- Retention bounds per-upload lifetime; it does not guarantee a provider's free allowance under unlimited traffic. No paid infrastructure is provisioned. S3-compatible storage remains optional and mocked in tests until a free bucket is provided.

**User flow**
1. User signs up and links their Riot account.
2. App pulls a match from Riot's match API and stores its kill events (with timestamps).
3. User picks their locally recorded video (OBS, ShadowPlay, etc.) via the browser **File System Access API** and uploads it.
4. User sets a **sync offset** aligning the video to the match clock.
5. A background worker cuts one clip per kill with FFmpeg.
6. User shares a clip via an unguessable public link.

**Why this design**
- Valorant's in-game replay files (`.vrp`) are proprietary and tied to the game client/patch. We do **not** parse them and do **not** attempt to. Kill data comes from Riot's API; video comes from the user's own recording.
- A website cannot silently read local files. We use the File System Access API (Chromium only; fallback `<input type="file">` elsewhere). A desktop companion agent is explicitly **out of scope** for now.

**Core technical problems (the portfolio value)**
- Kill-to-video time sync (API timeline ↔ video offset).
- Async clip pipeline (FFmpeg stream-copy vs re-encode, job tracking).
- Measurable performance: clip time/memory by method, chunked vs single upload, query time with/without indexes on a large seeded `kill_events` table.
- Security: upload validation, signed URLs, share-link authorization, rate limiting.

**Clip math**
```
clip_start_ms = kill.time_since_game_start_ms + video.sync_offset_ms - PADDING_BEFORE
clip_end_ms   = kill.time_since_game_start_ms + video.sync_offset_ms + PADDING_AFTER
```
`sync_offset_ms` = milliseconds into the video at which the match clock equals 0.

---

## 2. Tech stack

| Layer | Choice |
|---|---|
| Frontend | React + Vite |
| Backend | FastAPI (Python 3.12) |
| DB | PostgreSQL 16 |
| Queue | Redis + RQ (or Celery) |
| Video | FFmpeg (worker) |
| Storage | Local `storage/` for the zero-spend demo; optional S3/R2-compatible bucket |
| Tests | pytest + httpx/TestClient |
| Containers | Docker + Docker Compose |
| CI/CD | GitHub Actions |
| Hosting | Local Docker Compose demo; no paid deployment |

Do not add dependencies without a clear reason; ask first.

---

## 3. Current status

- [x] Repo, `.gitignore`, `.env.example`
- [x] Docker Compose: PostgreSQL, Redis, API, RQ worker and React/Nginx frontend; isolated full-pipeline smoke check
- [x] PostgreSQL baseline (10 tables); Alembic now manages initialization
- [x] FastAPI skeleton with `GET /health`, first pytest passing
- [x] `backend/Dockerfile` (`python:3.12-slim`)
- [x] GitHub Actions CI — PostgreSQL backend tests and the Docker pipeline passed on PR #4; require green checks before merge
- [x] Settings (`pydantic-settings`) + SQLAlchemy session
- [x] Alembic migrations (replace raw `schema.sql` auto-load), schema constraints/index checks, real DB health test
- [x] Auth: register/login, Argon2 password hashing, JWT, ownership checks, Redis rate limiting and tests
- [x] Riot client + transactional match/kill ingestion, tested with mocked upstream responses
- [ ] Live Riot production-key/RSO approval and verification
- [x] Video upload: resumable chunks, limits, generated storage keys and ffprobe validation
- [x] CV limits: 10 MB middleware/total upload ceiling, 15-second validation, 72-hour generated expiry and storage-first hourly cleanup
- [x] Sync offset + bounded, repeat-safe kill clip planning
- [x] FFmpeg/RQ worker, durable queued jobs, safe failures, wall-time and Linux peak-memory tracking
- [x] Shares: random tokens, expiry, private access, revocation, signed media URLs and public page
- [x] React frontend: folder/file picker, uploader, sync controls, clip status, preview and share UI; production build and browser playback checked
- [ ] Broader frontend QA: native picker, refresh/resume and non-Chromium browsers within demo limits
- [ ] DigitalOcean Spaces integration verification (optional S3 support implemented; local storage tested)
- [x] README and major-change/validation report (`docs/VALIDATION.md`)
- [ ] Demo benchmarks and portfolio screenshots; production deployment/availability work is out of scope

Prior pipeline verification: **49 pytest tests passed on Windows and Linux**, production frontend build and browser playback passed. CV constraint retest: **58 pytest tests passed on Windows and Linux**; updated Docker pipeline, expiry cleanup, cron runtime command and frontend build passed. See `docs/VALIDATION.md`. This is a portfolio demo.

Update this checklist when you finish an item.

---

## 4. Repo layout

```
valorant-clips/
├── backend/
│   ├── app/
│   │   ├── api/          # routers: auth, matches, videos, clips, shares
│   │   ├── core/         # config, security, dependencies
│   │   ├── models/       # SQLAlchemy models
│   │   ├── schemas/      # Pydantic request/response models
│   │   ├── services/     # riot_client, sync, clip_planner, storage
│   │   ├── workers/      # RQ tasks (FFmpeg jobs)
│   │   └── main.py
│   ├── alembic/          # versioned migrations
│   ├── tests/
│   ├── Dockerfile
│   ├── pytest.ini
│   └── requirements.txt
├── frontend/             # React + Vite, production Nginx container
│   └── src/              # main.jsx and style.css; split only when needed
├── .github/workflows/ci.yml
├── docker-compose.yml
├── docker-compose.smoke.yml # disposable validation overlay
├── schema.sql            # initial schema; becomes reference doc after Alembic
├── .env.example          # committed; real .env is NOT
├── .agents/skills/       # agent workflow skills (ponytail.md, ...)
├── docs/PROJECT.md       # this file
└── AGENTS.md             # entry point; links skills + this file
```

Keep routers thin (parse/validate → call service → return). Business logic lives in `services/`. Database access stays out of routers where practical.

---

## 5. Database

Tables: `users`, `riot_accounts`, `matches`, `match_players`, `rounds`, `kill_events`, `videos`, `clips`, `shares`, `processing_jobs`. Root `schema.sql` is the historical baseline. Authoritative migrations: `0001` baseline, `0002` case-insensitive emails, `0003` upload offsets and clip/job constraints, `0004` generated media expiry and its cleanup index. Existing uploads receive expiry from their original creation time; migration alone does not delete files.

Key relationships
- `users 1—N riot_accounts`, `users 1—N videos`
- `matches 1—N rounds 1—N kill_events` (composite FK `kill_events(match_id, round_number) → rounds`)
- `videos 1—N clips`; `clips.kill_event_id → kill_events` (nullable, SET NULL)
- `clips 1—N shares` (public lookup by unique `shares.token`)
- `processing_jobs` stores per-job wall time and peak memory (benchmark data)

Important indexes
- `kill_events(match_id, time_since_game_start_ms)` — main access pattern
- `shares(token)` unique — public link lookup
- partial index on `clips(status)` for queued/processing

Rules
- Never edit the schema ad hoc. Once Alembic exists, every change is a migration.
- Use constraints (CHECK, FK, UNIQUE) rather than relying on app code alone.
- Wrap multi-step writes (e.g. match + rounds + kills ingestion) in a transaction.
- Use parameterized queries / ORM only. No string-built SQL.

---

## 6. Environment and commands

Developer machine is **Windows + PowerShell**. Give PowerShell commands, not bash.

```powershell
# Start / stop / reset
docker compose up -d --build
docker compose ps
docker compose logs api
docker compose down          # stop
docker compose down -v       # DESTRUCTIVE: wipes dev DB; API re-runs migrations on startup

# DB shell
docker compose exec db psql -U vclips -d vclips -c "\dt"

# Backend tests (from backend/, venv active)
cd backend
.\.venv\Scripts\Activate.ps1
pytest -v

# Integration tests use an isolated database, never development data.
# Run the following Docker command from the repository root:
docker compose --profile test up -d --wait test-db
# Then from backend/:
$env:DATABASE_URL = "postgresql+psycopg://vclips_test:test-only@127.0.0.1:5433/vclips_test"
$env:TEST_DATABASE_URL = $env:DATABASE_URL
python -m alembic upgrade head
pytest -v
```

- Local venv uses Python 3.12 (`py -3.12 -m venv .venv`). Containers and CI also use 3.12.
- Fresh databases initialize with `alembic upgrade head`. Existing databases created by the original `schema.sql` must have their columns, constraints and indexes checked against baseline `0001` before running `alembic stamp 0001`; never stamp an unknown schema or reset a populated volume. See README.
- API runs at `http://localhost:8000` (Swagger at `/docs`).
- Docker frontend runs at `http://localhost:8080`; it proxies `/api`. `PUBLIC_API_URL` should use that origin plus `/api` so signed local media works with the frontend content security policy.
- Authentication requires a random `JWT_SECRET` of at least 32 characters. Do not use the `.env.example` placeholder.
- For repeatable full-stack verification, use the disposable Compose overlay and `python -m tests.smoke_docker` commands in README. The check refuses to run outside `vclips_smoke_test` and uses synthetic match events instead of live Riot calls.
- `.env` is gitignored. Add new variables to `.env.example` with placeholder values.
- Project root contains a space in a parent folder name; quote paths in scripts.

### Free deployment limitations

- **Free hosting is a constrained portfolio-demo option, not a production guarantee.** A frontend/API-only tier does not cover the full PostgreSQL, Redis/RQ, long-running FFmpeg worker and video-storage stack. No free provider has been validated for this project; check current resource limits, persistence, worker support, sleep/reclamation behaviour and overage charges before deployment. Do not hard-code changing provider allowances as project guarantees.
- **Object storage does not eliminate local disk needs.** Uploads are assembled locally before ffprobe validation and optional S3 publication. Workers need local source files plus temporary/output clip space. The default API/worker share `storage/`; deploying them on separate hosts requires an explicit staging/storage design.
- The **10 MB / 15-second ceiling and 72-hour retention** are demo limits. Hourly cleanup is implemented; per-user quotas are not. Use controlled demo traffic and account for temporary/output files as well as source uploads.
- Validate worker compute/memory, CPU architecture compatibility, HTTPS, backups and restart recovery. Free-tier availability and local disk must not be the only protection for important data. Unrestricted public uploads and reliable video processing must not be advertised as free-tier capabilities without evidence.
- Paid DigitalOcean deployment is out of scope. Local Compose has no hosting bill. No remote free provider has been verified for this stack.

---

## 7. Conventions

**Code**
- Clear names, small functions, no duplication, no dead code.
- Type hints on Python functions. Pydantic schemas for all request/response bodies.
- Consistent error handling: raise `HTTPException` with correct status codes; never leak stack traces or internals to clients.
- No hard-coded secrets, URLs, or magic numbers; use settings.

**Git**
- Branch per feature: `feat/<name>`, `fix/<name>`, `chore/<name>`, `ci/<name>`.
- Conventional commit messages (`feat(api): ...`, `fix(db): ...`).
- Open a PR into `main`; merge only when CI is green.
- Never commit `.env`, API keys, credentials, videos, or `.venv`.

**Diffs**
- Prefer small, targeted changes over rewrites. Show only what changed and why.
- One concern per commit/PR.

---

## 8. Testing requirements

Every feature ships with tests. Minimum coverage areas: authentication, key endpoints, validation errors, business logic (especially sync/clip math), and failure cases.

- Framework: pytest, FastAPI `TestClient`.
- Use a separate test database (Postgres service container in CI); do not test against dev data.
- Test names describe behavior (`test_register_rejects_duplicate_email`).
- Pure logic (sync offset, clip window calculation) gets unit tests with no DB.
- FFmpeg tests use tiny generated fixtures, not real recordings.

---

## 9. Security rules (non-negotiable)

- Passwords hashed with a modern algorithm (argon2 or bcrypt). Never log or return hashes.
- JWT auth; check ownership on every video/clip/share operation (authorization, not just authentication).
- Validate all input with Pydantic; enforce size/type limits on uploads and confirm with `ffprobe` (do not trust extension or MIME header).
- Never pass user-controlled strings into a shell. Call FFmpeg with an argument list (`subprocess.run([...])`), never `shell=True`. Generate storage keys server-side; ignore client filenames for paths.
- Share tokens: cryptographically random (`secrets.token_urlsafe`), unique, optionally expiring. Private clips served via signed URLs.
- Rate-limit auth, upload, and share endpoints.
- Riot API key lives in env only; never in code, logs, tests, or commits.

---

## 10. Riot API and legal notes

- Match/kill data comes from Riot's Valorant match API (VAL-MATCH-V1). Verify current endpoints and fields in Riot's docs before coding against them.
- VALORANT has no personal keys. Daily-expiring development keys do not establish VALORANT access. Live account linking requires an approved production key and Riot Sign On (RSO), including explicit player opt-in. Build and test with mock data until access is approved; isolate the client in `services/riot_client.py`. Sources: https://developer.riotgames.com/docs/valorant and https://developer.riotgames.com/docs/faqs.
- Respect rate limits; cache responses; never hammer the API in loops.
- The site needs a disclaimer that it is **not endorsed by or affiliated with Riot Games**. Do not use Riot logos or branding as if official.
- Do not build features that read game memory, hook the client, or touch anti-cheat territory.

---

## 11. Out of scope (for now)

- Desktop companion agent / auto-upload
- Parsing `.vrp` replay files
- Automatic kill detection from video (computer vision)
- AI features (only add if it solves a real problem and is documented)
- Social features (comments, feeds, follows)

---

## 12. Working agreement for agents

**Skills and precedence**
- `AGENTS.md` is the Ponytail skill (lazy senior dev mode) and is the entry point. Follow it for *how* to work: climb the ladder, reuse before writing, fix root causes, shortest correct diff, mark corner-cutting with a `ponytail:` comment naming the ceiling and upgrade path.
- This file decides project facts, schema, security, and scope. Where the two conflict, the overrides below apply.

**Project overrides to Ponytail**
1. **Tests.** Ponytail's "one small check" is the floor for internal helpers. Features must ship pytest tests per section 8 (auth, validation, failure cases, business logic). pytest and fixtures (`conftest.py`) are the project standard here.
2. **Structure.** Section 4 is the target layout, not a to-do list. Create a folder or file only when its first real code arrives. No empty placeholder modules, no service layer until there is logic to put in it.
3. **Dependencies.** The stack in section 2 is pre-approved. Expected additions (password hashing, JWT, Alembic, RQ, S3 client) are fine when the feature needs them. Anything else: try ladder rung 5 first, then ask.
4. **Questioning requests.** Challenge scope inside a feature. Do not relitigate decisions already settled in sections 1, 2 and 11 (stack, architecture, out of scope).
5. **Benchmarks.** Measurement code (timing, memory, seeded datasets) is a project deliverable, not gold plating.
6. **Never skipped, even for a smaller diff:** input validation at trust boundaries, auth/ownership checks, upload validation, error handling that prevents data loss (Ponytail agrees, section 9 lists the specifics).

**Rules**

1. Read this file and the relevant code before changing anything.
2. State your plan briefly; ask when requirements are ambiguous rather than guessing.
3. Make the smallest change that works. Don't refactor unrelated code.
4. Run `pytest` before declaring work done. Report real output, not assumptions.
5. Don't add dependencies, change the schema, or alter CI/Docker config without saying so explicitly.
6. Explain *why* for non-obvious choices so the owner can defend them in an interview.
7. Update the status checklist in section 3 when an item is completed.

---

## 13. Definition of done (project level)

Functional CV demo; responsive frontend; working API and PostgreSQL; auth/ownership and validation; 10 MB / 15-second uploads; 72-hour expiry with hourly cleanup; one asynchronous worker; Docker and tests pass; no committed secrets; CI green; zero-spend local operation; README with architecture, API docs and portfolio screenshots; owner can explain the system unaided. Production deployment and high availability are not required.
