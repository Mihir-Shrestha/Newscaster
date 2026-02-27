-- Update search trigger to include genre field added in migration 004
CREATE OR REPLACE FUNCTION update_episode_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', coalesce(NEW.title,            '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.transcript,       '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.headlines::text,  '')), 'C') ||
        setweight(to_tsvector('english', coalesce(NEW.genre,            '')), 'C');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- Backfill search_vector for any episodes missing it (including ones with new columns)
UPDATE episodes
SET search_vector =
    setweight(to_tsvector('english', coalesce(title,           '')), 'A') ||
    setweight(to_tsvector('english', coalesce(transcript,      '')), 'B') ||
    setweight(to_tsvector('english', coalesce(headlines::text, '')), 'C') ||
    setweight(to_tsvector('english', coalesce(genre,           '')), 'C')
WHERE search_vector IS NULL
   OR search_vector = ''::tsvector;