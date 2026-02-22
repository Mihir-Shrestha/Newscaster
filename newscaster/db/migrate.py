import os
import glob
import psycopg2

def get_connection():
    url = os.environ["DATABASE_URL"]
    return psycopg2.connect(url)

def run_migrations(migrations_dir: str):
    conn = get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    # Create tracking table if not exists
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            filename TEXT PRIMARY KEY,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    conn.commit()

    # Find all .sql files sorted by name
    pattern = os.path.join(migrations_dir, "*.sql")
    files = sorted(glob.glob(pattern))

    for filepath in files:
        filename = os.path.basename(filepath)

        cur.execute("SELECT 1 FROM schema_migrations WHERE filename = %s", (filename,))
        if cur.fetchone():
            print(f"[migrate] skipping {filename} (already applied)")
            continue

        print(f"[migrate] applying {filename} ...")
        with open(filepath, "r") as f:
            sql = f.read()

        try:
            cur.execute(sql)
            cur.execute(
                "INSERT INTO schema_migrations (filename) VALUES (%s)", (filename,)
            )
            conn.commit()
            print(f"[migrate] {filename} applied OK")
        except Exception as e:
            conn.rollback()
            print(f"[migrate] ERROR applying {filename}: {e}")
            raise

    cur.close()
    conn.close()

if __name__ == "__main__":
    migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")
    run_migrations(migrations_dir)