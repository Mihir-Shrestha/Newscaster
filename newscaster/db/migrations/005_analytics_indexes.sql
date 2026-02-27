-- Index for fast per-user listen lookups (used in analytics/total)
CREATE INDEX IF NOT EXISTS listen_events_user_idx
    ON episode_listen_events (user_id, listened_at DESC);

-- Index for date-range queries on daily uniques (used in analytics/timeseries)
CREATE INDEX IF NOT EXISTS episode_daily_uniques_date_idx
    ON episode_daily_uniques (episode_id, date DESC);

-- Index for top episodes query (used in analytics/top)
CREATE INDEX IF NOT EXISTS episode_daily_uniques_listeners_idx
    ON episode_daily_uniques (unique_listeners DESC);