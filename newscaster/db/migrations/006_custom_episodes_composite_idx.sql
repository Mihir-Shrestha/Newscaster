-- Composite index for the custom episodes query:
-- WHERE episode_type = 'custom' AND user_id = ? AND genre = ?
CREATE INDEX IF NOT EXISTS episodes_custom_user_genre_idx
    ON episodes (episode_type, user_id, genre, published_at DESC);

-- Composite index for the daily limit check:
-- WHERE episode_type = 'custom' AND user_id = ? AND DATE(created_at) = CURRENT_DATE
CREATE INDEX IF NOT EXISTS episodes_custom_user_created_idx
    ON episodes (episode_type, user_id, created_at DESC);