-- Valorant Clips: PostgreSQL schema (draft v1)

CREATE TABLE users (
    id            BIGSERIAL PRIMARY KEY,
    email         VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    display_name  VARCHAR(50)  NOT NULL,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE TABLE riot_accounts (
    id         BIGSERIAL PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    puuid      VARCHAR(100) NOT NULL UNIQUE,
    game_name  VARCHAR(50)  NOT NULL,
    tag_line   VARCHAR(10)  NOT NULL,
    region     VARCHAR(10)  NOT NULL,
    created_at TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX idx_riot_accounts_user ON riot_accounts(user_id);

CREATE TABLE matches (
    id            BIGSERIAL PRIMARY KEY,
    riot_match_id VARCHAR(100) NOT NULL UNIQUE,
    map_id        VARCHAR(100) NOT NULL,
    queue_id      VARCHAR(50),
    started_at    TIMESTAMPTZ  NOT NULL,
    duration_ms   INTEGER      NOT NULL CHECK (duration_ms > 0),
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE INDEX idx_matches_started_at ON matches(started_at DESC);

-- Which of our users played in which match (a match has up to 10 players)
CREATE TABLE match_players (
    match_id   BIGINT NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    puuid      VARCHAR(100) NOT NULL,
    user_id    BIGINT REFERENCES users(id) ON DELETE SET NULL,
    agent_id   VARCHAR(100),
    team_id    VARCHAR(20),
    PRIMARY KEY (match_id, puuid)
);
CREATE INDEX idx_match_players_user ON match_players(user_id, match_id);

CREATE TABLE rounds (
    id             BIGSERIAL PRIMARY KEY,
    match_id       BIGINT  NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    round_number   SMALLINT NOT NULL CHECK (round_number >= 0),
    winning_team   VARCHAR(20),
    UNIQUE (match_id, round_number)
);

CREATE TABLE kill_events (
    id                       BIGSERIAL PRIMARY KEY,
    match_id                 BIGINT   NOT NULL REFERENCES matches(id) ON DELETE CASCADE,
    round_number             SMALLINT NOT NULL,
    killer_puuid             VARCHAR(100) NOT NULL,
    victim_puuid             VARCHAR(100) NOT NULL,
    weapon                   VARCHAR(100),
    time_since_game_start_ms INTEGER  NOT NULL CHECK (time_since_game_start_ms >= 0),
    time_since_round_start_ms INTEGER NOT NULL CHECK (time_since_round_start_ms >= 0),
    FOREIGN KEY (match_id, round_number) REFERENCES rounds(match_id, round_number) ON DELETE CASCADE
);
-- Primary access pattern: kills for a match, ordered by time
CREATE INDEX idx_kills_match_time ON kill_events(match_id, time_since_game_start_ms);
-- "All kills by player X" queries
CREATE INDEX idx_kills_killer ON kill_events(killer_puuid);

CREATE TABLE videos (
    id             BIGSERIAL PRIMARY KEY,
    user_id        BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    match_id       BIGINT REFERENCES matches(id) ON DELETE SET NULL,
    storage_key    VARCHAR(500) NOT NULL UNIQUE,
    original_name  VARCHAR(255) NOT NULL,
    size_bytes     BIGINT  NOT NULL CHECK (size_bytes > 0),
    duration_ms    INTEGER,
    -- ms into the video at which the match clock (time_since_game_start) = 0
    sync_offset_ms INTEGER NOT NULL DEFAULT 0,
    status         VARCHAR(20) NOT NULL DEFAULT 'uploading'
                   CHECK (status IN ('uploading','uploaded','validated','failed')),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_videos_user ON videos(user_id, created_at DESC);
CREATE INDEX idx_videos_match ON videos(match_id);

CREATE TABLE clips (
    id            BIGSERIAL PRIMARY KEY,
    video_id      BIGINT NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    kill_event_id BIGINT REFERENCES kill_events(id) ON DELETE SET NULL,
    start_ms      INTEGER NOT NULL CHECK (start_ms >= 0),
    end_ms        INTEGER NOT NULL,
    storage_key   VARCHAR(500) UNIQUE,
    encode_mode   VARCHAR(20) NOT NULL DEFAULT 'copy'
                  CHECK (encode_mode IN ('copy','reencode')),
    status        VARCHAR(20) NOT NULL DEFAULT 'queued'
                  CHECK (status IN ('queued','processing','ready','failed')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (end_ms > start_ms)
);
CREATE INDEX idx_clips_video ON clips(video_id);
CREATE INDEX idx_clips_status ON clips(status) WHERE status IN ('queued','processing');

CREATE TABLE shares (
    id         BIGSERIAL PRIMARY KEY,
    clip_id    BIGINT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    token      VARCHAR(64) NOT NULL UNIQUE,   -- unique index = fast public lookup
    visibility VARCHAR(20) NOT NULL DEFAULT 'unlisted'
               CHECK (visibility IN ('public','unlisted','private')),
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_shares_clip ON shares(clip_id);

-- Per-job metrics, doubles as benchmark data (Option B)
CREATE TABLE processing_jobs (
    id           BIGSERIAL PRIMARY KEY,
    clip_id      BIGINT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
    status       VARCHAR(20) NOT NULL DEFAULT 'queued',
    progress     SMALLINT NOT NULL DEFAULT 0 CHECK (progress BETWEEN 0 AND 100),
    encode_mode  VARCHAR(20) NOT NULL,
    duration_ms  INTEGER,        -- wall-clock processing time
    peak_mem_kb  INTEGER,
    error        TEXT,
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ
);
CREATE INDEX idx_jobs_clip ON processing_jobs(clip_id);
