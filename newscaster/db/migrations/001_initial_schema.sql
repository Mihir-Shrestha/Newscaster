-- Users
CREATE TABLE IF NOT EXISTS users (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email       TEXT UNIQUE NOT NULL,
    password_hash TEXT,                        -- NULL for OAuth-only users
    display_name TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- OAuth identities (Google, etc.)
CREATE TABLE IF NOT EXISTS identities (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider    TEXT NOT NULL,                 -- e.g. 'google'
    provider_id TEXT NOT NULL,                 -- provider's user id
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (provider, provider_id)
);

-- Sessions / refresh tokens
CREATE TABLE IF NOT EXISTS sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash  TEXT UNIQUE NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Episodes (written by TTS)
CREATE TABLE IF NOT EXISTS episodes (
    id              UUID PRIMARY KEY,          -- same job_id from RabbitMQ
    title           TEXT NOT NULL,
    gcs_url         TEXT NOT NULL,
    transcript      TEXT,
    headlines       JSONB,
    published_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Full-text search index on transcript
CREATE INDEX IF NOT EXISTS episodes_transcript_fts
    ON episodes USING GIN (to_tsvector('english', COALESCE(transcript, '')));

-- Index for date-range queries
CREATE INDEX IF NOT EXISTS episodes_published_at_idx
    ON episodes (published_at DESC);

-- Playlists (written by API)
CREATE TABLE IF NOT EXISTS playlists (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT,
    is_public   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Playlist items with custom ordering
CREATE TABLE IF NOT EXISTS playlist_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    playlist_id     UUID NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    episode_id      UUID NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    position        INTEGER NOT NULL DEFAULT 0,
    added_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (playlist_id, episode_id)
);

CREATE INDEX IF NOT EXISTS playlist_items_order_idx
    ON playlist_items (playlist_id, position);

-- Unlisted share links for playlists
CREATE TABLE IF NOT EXISTS playlist_shares (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    playlist_id UUID NOT NULL REFERENCES playlists(id) ON DELETE CASCADE,
    token       TEXT UNIQUE NOT NULL DEFAULT gen_random_uuid()::TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at  TIMESTAMPTZ                            -- NULL = no expiry
);

-- Raw listen events (authenticated playback)
CREATE TABLE IF NOT EXISTS episode_listen_events (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    episode_id  UUID NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    listened_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS listen_events_episode_idx
    ON episode_listen_events (episode_id, listened_at DESC);

-- Daily unique listener aggregates (maintained by API)
CREATE TABLE IF NOT EXISTS episode_daily_uniques (
    episode_id  UUID NOT NULL REFERENCES episodes(id) ON DELETE CASCADE,
    date        DATE NOT NULL,
    unique_listeners INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (episode_id, date)
);