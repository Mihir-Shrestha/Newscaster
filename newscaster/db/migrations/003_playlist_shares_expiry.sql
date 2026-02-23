-- Set default expiry to 7 days from creation
ALTER TABLE playlist_shares 
    ALTER COLUMN expires_at SET DEFAULT (now() + interval '7 days');

-- Simple index without predicate (no immutability issue)
CREATE INDEX IF NOT EXISTS playlist_shares_token_idx 
    ON playlist_shares(token);