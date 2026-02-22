-- Full text search index on episodes
ALTER TABLE episodes ADD COLUMN IF NOT EXISTS search_vector tsvector;

-- Update search_vector from title + transcript + headlines
UPDATE episodes SET search_vector = 
    setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(transcript, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(headlines::text, '')), 'C');

-- GIN index for fast full text search
CREATE INDEX IF NOT EXISTS episodes_search_idx ON episodes USING GIN(search_vector);

-- Index for date range queries
CREATE INDEX IF NOT EXISTS episodes_published_at_idx ON episodes(published_at);

-- Auto update search_vector on insert/update
CREATE OR REPLACE FUNCTION update_episode_search_vector()
RETURNS TRIGGER AS $$
BEGIN
    NEW.search_vector :=
        setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(NEW.transcript, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(NEW.headlines::text, '')), 'C');
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS episode_search_vector_update ON episodes;
CREATE TRIGGER episode_search_vector_update
    BEFORE INSERT OR UPDATE ON episodes
    FOR EACH ROW EXECUTE FUNCTION update_episode_search_vector();