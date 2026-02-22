import os
import uuid
import psycopg2
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
from jose import jwt, JWTError
import hashlib

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_ALGORITHM = os.environ.get("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_MINUTES = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# ---------------------------------------------------------------------------
# Password helpers — pre-hash with sha256 to avoid bcrypt 72-byte limit
# ---------------------------------------------------------------------------
def _prehash(plain: str) -> str:
    """SHA-256 hex digest keeps input well under bcrypt's 72-byte limit."""
    return hashlib.sha256(plain.encode()).hexdigest()

def hash_password(plain: str) -> str:
    return pwd_context.hash(_prehash(plain))

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(_prehash(plain), hashed)

# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------
def create_access_token(user_id: str, email: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)
    payload = {
        "sub": str(user_id),
        "email": email,
        "exp": expire
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None

# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------
def get_db():
    return psycopg2.connect(os.environ["DATABASE_URL"])

# ---------------------------------------------------------------------------
# User helpers
# ---------------------------------------------------------------------------
def get_user_by_email(email: str) -> dict | None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, email, display_name FROM users WHERE email = %s", (email,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {"id": str(row[0]), "email": row[1], "display_name": row[2]}

def get_user_by_id(user_id: str) -> dict | None:
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, email, display_name FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {"id": str(row[0]), "email": row[1], "display_name": row[2]}

def create_user_with_password(email: str, display_name: str, plain_password: str) -> dict:
    conn = get_db()
    cur = conn.cursor()
    user_id = str(uuid.uuid4())
    hashed = hash_password(plain_password)

    # schema has password_hash directly on users table
    cur.execute(
        "INSERT INTO users (id, email, display_name, password_hash) VALUES (%s, %s, %s, %s)",
        (user_id, email, display_name, hashed)
    )
    # identities row for local provider - uses provider_id not provider_user_id
    cur.execute(
        """INSERT INTO identities (id, user_id, provider, provider_id)
           VALUES (%s, %s, 'local', %s)""",
        (str(uuid.uuid4()), user_id, email)
    )
    conn.commit()
    cur.close()
    conn.close()
    return {"id": user_id, "email": email, "display_name": display_name}

def get_local_identity(email: str) -> dict | None:
    # password_hash is on users table, not identities
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """SELECT u.id, u.email, u.display_name, u.password_hash
           FROM users u
           JOIN identities i ON i.user_id = u.id
           WHERE u.email = %s AND i.provider = 'local'""",
        (email,)
    )
    row = cur.fetchone()
    cur.close()
    conn.close()
    if not row:
        return None
    return {
        "id": str(row[0]),
        "email": row[1],
        "display_name": row[2],
        "password_hash": row[3]
    }

def upsert_google_user(email: str, display_name: str, google_id: str) -> dict:
    """Create or return existing user from Google OAuth."""
    conn = get_db()
    cur = conn.cursor()

    # Check if Google identity already exists — use provider_id not provider_user_id
    cur.execute(
        "SELECT user_id FROM identities WHERE provider = 'google' AND provider_id = %s",
        (google_id,)
    )
    row = cur.fetchone()

    if row:
        user_id = str(row[0])
    else:
        # Check if user exists by email
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        user_row = cur.fetchone()

        if user_row:
            user_id = str(user_row[0])
        else:
            user_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO users (id, email, display_name) VALUES (%s, %s, %s)",
                (user_id, email, display_name)
            )

        # Create Google identity — use provider_id
        cur.execute(
            """INSERT INTO identities (id, user_id, provider, provider_id)
               VALUES (%s, %s, 'google', %s)""",
            (str(uuid.uuid4()), user_id, google_id)
        )
        conn.commit()

    cur.close()
    conn.close()
    return {"id": user_id, "email": email, "display_name": display_name}