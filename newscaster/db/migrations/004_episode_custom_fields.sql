-- 1. Add genre column
ALTER TABLE episodes ADD COLUMN IF NOT EXISTS genre TEXT DEFAULT 'general';

-- 2. Add type column to distinguish daily auto-generated vs user-custom
ALTER TABLE episodes ADD COLUMN IF NOT EXISTS episode_type TEXT NOT NULL DEFAULT 'daily';

-- 3. Add user_id — NULL means auto-generated daily episode, UUID means custom by that user
ALTER TABLE episodes ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE SET NULL;

-- 4. Add custom query params so we know what the user searched for
ALTER TABLE episodes ADD COLUMN IF NOT EXISTS custom_params JSONB;

-- 5. Index for fast lookup by type and user
CREATE INDEX IF NOT EXISTS episodes_type_idx ON episodes(episode_type);
CREATE INDEX IF NOT EXISTS episodes_user_idx ON episodes(user_id);
CREATE INDEX IF NOT EXISTS episodes_genre_idx ON episodes(genre);

-- 6. daily limit tracking view (convenience)
CREATE OR REPLACE VIEW user_daily_custom_counts AS
SELECT 
    user_id,
    DATE(created_at AT TIME ZONE 'UTC') AS day,
    COUNT(*) AS count
FROM episodes
WHERE episode_type = 'custom'
  AND user_id IS NOT NULL
GROUP BY user_id, DATE(created_at AT TIME ZONE 'UTC');