import os
import sys
import json
import time
import uuid
import threading
import requests as ext_requests
from datetime import datetime, timezone

import redis
import pika
import psycopg2
from fastapi import FastAPI, Request, Response, Form, Cookie, Query
from fastapi.responses import (
    HTMLResponse, JSONResponse, RedirectResponse
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from prometheus_client import Counter, generate_latest

sys.path.insert(0, "/app/db")
from migrate import run_migrations
from auth import (
    create_access_token, decode_access_token,
    create_user_with_password, get_local_identity,
    verify_password, upsert_google_user,
    get_user_by_email, get_user_by_id
)

MIGRATIONS_DIR = "/app/db/migrations"

GOOGLE_CLIENT_ID     = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
GOOGLE_REDIRECT_URI  = os.environ["GOOGLE_REDIRECT_URI"]
GOOGLE_AUTH_URL      = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL     = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL  = "https://www.googleapis.com/oauth2/v3/userinfo"

NEWS_API_KEY = os.environ.get("NEWS_API_KEY", "")

app = FastAPI()

@app.on_event("startup")
def on_startup():
    run_migrations(MIGRATIONS_DIR)
    t = threading.Thread(target=_scheduled_cleanup, daemon=True)
    t.start()

# Redis client
r = redis.Redis(host="redis", port=6379, decode_responses=True)
templates = Jinja2Templates(directory="/app/templates")
app.mount("/static", StaticFiles(directory="/app/static"), name="static")
REQUEST_COUNT = Counter("api_request_count", "Total API Requests")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return RedirectResponse(url="/static/favicon.ico?v=20260318g", status_code=307)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_db():
    return psycopg2.connect(os.environ["DATABASE_URL"])

def get_current_user(request: Request) -> dict | None:
    token = request.cookies.get("access_token")
    if not token:
        return None
    return decode_access_token(token)

def enrich_user_profile(user: dict | None) -> dict | None:
    if not user:
        return None

    enriched = dict(user)
    user_id = enriched.get("id") or enriched.get("sub")

    if user_id and "id" not in enriched:
        enriched["id"] = user_id

    if not user_id:
        return enriched

    try:
        db_user = get_user_by_id(user_id)
        if db_user:
            enriched["email"] = db_user.get("email", enriched.get("email"))
            enriched["display_name"] = db_user.get("display_name") or enriched.get("display_name")
    except Exception as e:
        print(f"[user_profile] ERROR: {e}")

    return enriched

def require_user(request: Request) -> dict | None:
    user = get_current_user(request)
    if not user:
        return None
    # JWT uses "sub" for user ID — normalize to "id" for consistency
    if "sub" in user and "id" not in user:
        user["id"] = user["sub"]
    return user

def send_job_to_queue():
    connection = pika.BlockingConnection(pika.ConnectionParameters("rabbitmq"))
    channel = connection.channel()
    channel.queue_declare(queue="to_fetcher")
    job_id = str(uuid.uuid4())
    payload = {"job_id": job_id, "trigger": "api_request"}
    channel.basic_publish(exchange="", routing_key="to_fetcher", body=json.dumps(payload))
    connection.close()
    return job_id

def format_episode_row(row) -> dict:
    """Convert a Postgres episodes row to a clean dict."""
    return {
        "id":           str(row[0]),
        "title":        row[1],
        "published_at": row[2].isoformat() if row[2] else None,
        "gcs_url":      row[3],
        "headlines":    row[4] if row[4] else [],
    }

# ===========================================================================
# PUBLIC ROUTES (no auth required)
# ===========================================================================
@app.get("/", response_class=HTMLResponse)
def homepage(request: Request):
    REQUEST_COUNT.inc()
    user = enrich_user_profile(get_current_user(request))
    return templates.TemplateResponse("index.html", {"request": request, "user": user})

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})

@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    return templates.TemplateResponse("signup.html", {"request": request, "error": None})

@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type="text/plain")

# ===========================================================================
# AUTH ROUTES
# ===========================================================================
@app.post("/auth/signup")
def signup(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    display_name: str = Form(...)
):
    if len(password) < 8:
        return templates.TemplateResponse("signup.html", {
            "request": request,
            "error": "Password must be at least 8 characters."
        })

    existing = get_local_identity(email)
    if existing:
        return templates.TemplateResponse("signup.html", {
            "request": request,
            "error": "Email already registered. Please log in."
        })
    
    existing_user = get_user_by_email(email)
    if existing_user:
        return templates.TemplateResponse("signup.html", {
            "request": request,
            "error": "This email is linked to a Google account. Please sign in with Google."
        })
    
    try:
        user = create_user_with_password(email, display_name, password)
        token = create_access_token(user["id"], user["email"])
        response = RedirectResponse("/", status_code=302)
        response.set_cookie("access_token", token, httponly=True, max_age=3600)
        return response
    except Exception as e:
        print(f"[signup] ERROR: {str(e)}")
        return templates.TemplateResponse("signup.html", {
            "request": request,
            "error": "Something went wrong. Please try again."
        })

@app.post("/auth/login")
def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...)
):
    identity = get_local_identity(email)
    if not identity or not verify_password(password, identity["password_hash"]):
        return templates.TemplateResponse("login.html", {
            "request": request,
            "error": "Invalid email or password."
        })
    token = create_access_token(identity["id"], identity["email"])
    response = RedirectResponse("/", status_code=302)
    response.set_cookie("access_token", token, httponly=True, max_age=3600)
    return response

@app.get("/auth/logout")
def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("access_token")
    return response

@app.get("/auth/google")
def google_login():
    params = (
        f"?client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={GOOGLE_REDIRECT_URI}"
        f"&response_type=code"
        f"&scope=openid%20email%20profile"
        f"&access_type=offline"
    )
    return RedirectResponse(GOOGLE_AUTH_URL + params)

@app.get("/auth/google/callback")
def google_callback(request: Request, code: str = None, error: str = None):
    if error or not code:
        return RedirectResponse("/login?error=google_denied")

    # Exchange code for token
    token_resp = ext_requests.post(GOOGLE_TOKEN_URL, data={
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code"
    })
    token_data = token_resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        return RedirectResponse("/login?error=google_token_failed")

    userinfo_resp = ext_requests.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"}
    )
    userinfo = userinfo_resp.json()
    email        = userinfo.get("email")
    display_name = userinfo.get("name", email)
    google_id    = userinfo.get("sub")

    if not email or not google_id:
        return RedirectResponse("/login?error=google_no_email")

    user = upsert_google_user(email, display_name, google_id)
    jwt_token = create_access_token(user["id"], user["email"])
    response = RedirectResponse("/", status_code=302)
    response.set_cookie("access_token", jwt_token, httponly=True, max_age=3600)
    return response

# ===========================================================================
# PROTECTED ROUTES (auth required)
# ===========================================================================
@app.get("/episodes")
def get_episodes(request: Request):
    """List all episodes from Postgres (source of truth)."""
    REQUEST_COUNT.inc()
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, title, published_at, gcs_url, headlines
            FROM episodes
            ORDER BY published_at DESC
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {"episodes": [format_episode_row(r) for r in rows]}
    except Exception as e:
        print(f"[episodes] ERROR: {e}")
        return JSONResponse({"error": "Failed to fetch episodes"}, status_code=500)

@app.get("/episodes/search")
def search_episodes(
    request: Request,
    q: str = Query(None, description="Search query"),
    from_date: str = Query(None, description="Start date YYYY-MM-DD"),
    to_date: str = Query(None, description="End date YYYY-MM-DD")
):
    """
    Full-text search across episode titles, transcripts and headlines.
    Supports optional date range filtering.
    GET /episodes/search?q=elections&from_date=2026-01-01&to_date=2026-02-22
    """
    REQUEST_COUNT.inc()
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    if not q and not from_date and not to_date:
        return JSONResponse({"error": "Provide at least one of: q, from_date, to_date"}, status_code=400)

    try:
        conn = get_db()
        cur = conn.cursor()

        # Build query dynamically based on filters provided
        conditions = []
        params = []

        if q:
            conditions.append("search_vector @@ plainto_tsquery('english', %s)")
            params.append(q)

        if from_date:
            conditions.append("published_at >= %s")
            params.append(from_date)

        if to_date:
            conditions.append("published_at <= %s")
            params.append(to_date)

        where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

        # If keyword search, rank by relevance; otherwise by date
        order_clause = (
            "ORDER BY ts_rank(search_vector, plainto_tsquery('english', %s)) DESC"
            if q else
            "ORDER BY published_at DESC"
        )
        if q:
            params.append(q)

        query = f"""
            SELECT id, title, published_at, gcs_url, headlines
            FROM episodes
            {where_clause}
            {order_clause}
        """

        cur.execute(query, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        return {
            "query": q,
            "from_date": from_date,
            "to_date": to_date,
            "total": len(rows),
            "results": [format_episode_row(r) for r in rows]
        }

    except Exception as e:
        print(f"[search] ERROR: {e}")
        return JSONResponse({"error": "Search failed"}, status_code=500)
    
def log_listen_event(episode_id: str, user_id: str):
    """Write a listen event and upsert the daily unique-listener aggregate."""
    try:
        conn = get_db()
        cur  = conn.cursor()

        # 1. Insert raw listen event
        cur.execute(
            """
            INSERT INTO episode_listen_events (episode_id, user_id)
            VALUES (%s::uuid, %s::uuid)
            """,
            (episode_id, user_id),
        )

        # 2. Upsert daily unique-listener count
        cur.execute(
            """
            INSERT INTO episode_daily_uniques (episode_id, date, unique_listeners)
            VALUES (%s::uuid, CURRENT_DATE, 1)
            ON CONFLICT (episode_id, date) DO UPDATE
            SET unique_listeners = (
                SELECT COUNT(DISTINCT user_id)
                FROM   episode_listen_events
                WHERE  episode_id = EXCLUDED.episode_id
                AND    listened_at::date = CURRENT_DATE
            )
            """,
            (episode_id,),
        )

        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[listen_event] ERROR: {e}")


@app.get("/episodes/{eid}/audio")
def get_audio(request: Request, eid: str):
    REQUEST_COUNT.inc()
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    # ── resolve audio URL ──────────────────────────────────────────────
    gcs_url = r.hget(f"episode:{eid}", "gcs_url")

    if not gcs_url:
        try:
            conn = get_db()
            cur  = conn.cursor()
            cur.execute("SELECT gcs_url FROM episodes WHERE id = %s", (eid,))
            row = cur.fetchone()
            cur.close()
            conn.close()
            if row:
                gcs_url = row[0]
        except Exception:
            pass

    if not gcs_url:
        return JSONResponse({"error": "Episode not found"}, status_code=404)

    # ── log the listen event (non-blocking best-effort) ────────────────
    log_listen_event(eid, user["id"])

    return RedirectResponse(gcs_url)

@app.get("/episodes/{eid}/transcript")
def get_transcript(request: Request, eid: str):
    """Returns transcript for a single episode."""
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute("SELECT transcript FROM episodes WHERE id = %s", (eid,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return JSONResponse({"transcript": row[0]})
    except Exception as e:
        print(f"[transcript] ERROR: {e}")
        return JSONResponse({"error": "Failed"}, status_code=500)

# ---------------------------------------------------------------------------
# DELETE /episodes/{eid} — delete a custom episode (owner only)
# ---------------------------------------------------------------------------
@app.delete("/episodes/{eid}")
def delete_episode(request: Request, eid: str):
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        conn = get_db()
        cur  = conn.cursor()

        # Verify the episode exists and belongs to this user
        cur.execute(
            """
            SELECT id, episode_type FROM episodes
            WHERE id = %s::uuid AND user_id = %s::uuid
            """,
            (eid, user["id"]),
        )
        row = cur.fetchone()

        if not row:
            cur.close()
            conn.close()
            return JSONResponse({"error": "Episode not found or access denied"}, status_code=404)

        if row[1] == "daily":
            cur.close()
            conn.close()
            return JSONResponse({"error": "Daily episodes cannot be deleted"}, status_code=403)

        # Remove from playlist_items first (foreign key)
        cur.execute("DELETE FROM playlist_items WHERE episode_id = %s::uuid", (eid,))

        # Delete the episode
        cur.execute("DELETE FROM episodes WHERE id = %s::uuid", (eid,))

        # Clean up Redis cache if present
        r.delete(f"episode:{eid}")
        latest = r.get("latest_episode")
        if latest == eid:
            r.delete("latest_episode")

        conn.commit()
        cur.close()
        conn.close()

        print(f"[delete_episode] deleted {eid} by user {user['id']}")
        return JSONResponse({"status": "deleted", "id": eid})

    except Exception as e:
        print(f"[delete_episode] ERROR: {e}")
        return JSONResponse({"error": "Failed to delete episode"}, status_code=500)      

# ---------------------------------------------------------------------------
# EPISODES — DAILY (auto-generated, common for all users)
# ---------------------------------------------------------------------------
@app.get("/episodes/daily")
def get_daily_episodes(request: Request, limit: int = 20):
    """Returns auto-generated daily episodes, newest first."""
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute(
            """
            SELECT id, title, gcs_url, genre, published_at, headlines
            FROM   episodes
            WHERE  episode_type = 'daily'
            ORDER  BY published_at DESC
            LIMIT  %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return JSONResponse([
            {
                "id":           str(r[0]),
                "title":        r[1],
                "gcs_url":      r[2],
                "genre":        r[3],
                "published_at": str(r[4]),
                "headlines":    r[5],
            }
            for r in rows
        ])
    except Exception as e:
        print(f"[episodes/daily] ERROR: {e}")
        return JSONResponse({"error": "Failed to fetch daily episodes"}, status_code=500)

# ---------------------------------------------------------------------------
# EPISODES — BY GENRE
# ---------------------------------------------------------------------------
@app.get("/episodes/genre/{genre}")
def get_episodes_by_genre(request: Request, genre: str, limit: int = 20):
    """Returns episodes filtered by genre."""
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute(
            """
            SELECT id, title, gcs_url, genre, published_at
            FROM   episodes
            WHERE  LOWER(genre) = LOWER(%s)
            ORDER  BY published_at DESC
            LIMIT  %s
            """,
            (genre, limit),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return JSONResponse([
            {
                "id":           str(r[0]),
                "title":        r[1],
                "gcs_url":      r[2],
                "genre":        r[3],
                "published_at": str(r[4]),
            }
            for r in rows
        ])
    except Exception as e:
        print(f"[episodes/genre] ERROR: {e}")
        return JSONResponse({"error": "Failed to fetch genre episodes"}, status_code=500)


# ---------------------------------------------------------------------------
# DAILY LIMIT CHECK
# ---------------------------------------------------------------------------
def check_daily_limit(user_id: str, limit: int = 5) -> bool:
    """Returns True if user is under the daily custom episode limit."""
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*) FROM episodes
            WHERE  episode_type = 'custom'
            AND    user_id      = %s::uuid
            AND    DATE(created_at AT TIME ZONE 'UTC') = CURRENT_DATE
            """,
            (user_id,),
        )
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return count < limit
    except Exception as e:
        print(f"[daily_limit] ERROR: {e}")
        return False


# ---------------------------------------------------------------------------
# GENERATE — CUSTOM EPISODE (replaces old /generate for user-triggered)
# ---------------------------------------------------------------------------
@app.get("/episodes/custom")
def get_custom_episodes(request: Request, limit: int = 20, genre: str = None):
    """Returns custom episodes generated by the logged-in user, optionally filtered by genre."""
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        conn = get_db()
        cur  = conn.cursor()

        if genre and genre != "custom":
            # Filter by specific genre (technology, sports, etc.)
            cur.execute(
                """
                SELECT id, title, gcs_url, genre, published_at, custom_params, transcript
                FROM   episodes
                WHERE  episode_type = 'custom'
                AND    user_id = %s::uuid
                AND    LOWER(genre) = LOWER(%s)
                ORDER  BY published_at DESC
                LIMIT  %s
                """,
                (user["id"], genre, limit),
            )
        else:
            # "custom" filter = keyword/domain based = genre stored as 'custom'
            cur.execute(
                """
                SELECT id, title, gcs_url, genre, published_at, custom_params, transcript
                FROM   episodes
                WHERE  episode_type = 'custom'
                AND    user_id = %s::uuid
                ORDER  BY published_at DESC
                LIMIT  %s
                """,
                (user["id"], limit),
            )

        rows = cur.fetchall()
        cur.close()
        conn.close()
        return JSONResponse([
            {
                "id":            str(r[0]),
                "title":         r[1],
                "gcs_url":       r[2],
                "genre":         r[3],
                "published_at":  str(r[4]),
                "custom_params": r[5] if r[5] else {},
                "transcript":    r[6],
            }
            for r in rows
        ])
    except Exception as e:
        print(f"[episodes/custom] ERROR: {e}")
        return JSONResponse({"error": "Failed to fetch custom episodes"}, status_code=500)

@app.post("/generate/custom")
async def generate_custom_episode(request: Request):
    """
    Generate a custom episode. 
    Mode 1 (custom): keywords/dates/domains → genre stored as 'custom'
    Mode 2 (genre):  predefined genre → genre stored as e.g. 'technology'
    """
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    if not check_daily_limit(user["id"]):
        return JSONResponse(
            {"error": "Daily limit reached. You can generate up to 5 custom podcasts per day."},
            status_code=429,
        )

    try:
        body = await request.json()
    except Exception:
        body = {}

    keywords        = body.get("keywords", "").strip()
    from_date       = body.get("from_date", "")
    to_date         = body.get("to_date", "")
    domains         = body.get("domains", "").strip()
    exclude_domains = body.get("exclude_domains", "").strip()
    genre           = body.get("genre", "custom").strip()

    # Determine NewsAPI endpoint and params
    has_custom_params = bool(keywords or domains or from_date or to_date)

    if has_custom_params:
        # Keyword/domain mode → /everything, genre = "custom"
        genre = "custom"
        params = {
            "apiKey":   NEWS_API_KEY,
            "pageSize": 10,
            "language": "en",
            "sortBy":   "publishedAt",
        }
        if keywords:        params["q"]              = keywords
        if from_date:       params["from"]           = from_date
        if to_date:         params["to"]             = to_date
        if domains:         params["domains"]        = domains
        if exclude_domains: params["excludeDomains"] = exclude_domains
        news_url = "https://newsapi.org/v2/everything"
    else:
        # Genre mode → /top-headlines, genre = selected genre
        if not genre or genre == "custom":
            genre = "general"
        params = {
            "apiKey":   NEWS_API_KEY,
            "pageSize": 10,
            "country":  "us",
        }
        if genre != "general":
            params["category"] = genre
        news_url = "https://newsapi.org/v2/top-headlines"

    job_id = str(uuid.uuid4())

    # Build a meaningful title
    if has_custom_params:
        ep_title = f"Custom: {keywords or domains or 'Search'} — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
    else:
        ep_title = f"{genre.capitalize()} — {datetime.now(timezone.utc).strftime('%Y-%m-%d')}"

    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute(
            """
            INSERT INTO episodes (id, title, gcs_url, episode_type, user_id, genre, custom_params, published_at)
            VALUES (%s::uuid, %s, '', 'custom', %s::uuid, %s, %s::jsonb, NOW())
            """,
            (
                job_id,
                ep_title,
                user["id"],
                genre,
                json.dumps({
                    "keywords":        keywords,
                    "from_date":       from_date,
                    "to_date":         to_date,
                    "domains":         domains,
                    "exclude_domains": exclude_domains,
                    "genre":           genre,
                }),
            ),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[generate/custom] DB insert ERROR: {e}")
        return JSONResponse({"error": "Failed to create episode record"}, status_code=500)

    try:
        conn_r = pika.BlockingConnection(pika.ConnectionParameters("rabbitmq"))
        ch     = conn_r.channel()
        ch.queue_declare(queue="to_fetcher")
        ch.basic_publish(
            exchange="",
            routing_key="to_fetcher",
            body=json.dumps({
                "job_id":       job_id,
                "news_url":     news_url,
                "news_params":  params,
                "episode_type": "custom",
                "user_id":      user["id"],
                "genre":        genre,
            }),
        )
        conn_r.close()
    except Exception as e:
        print(f"[generate/custom] RabbitMQ ERROR: {e}")
        return JSONResponse({"error": "Failed to queue generation job"}, status_code=500)

    return JSONResponse({
        "status":  "queued",
        "job_id":  job_id,
        "message": "Your podcast is being generated. This takes about 45–60 seconds.",
    })

# ---------------------------------------------------------------------------
# DAILY LIMIT STATUS — so frontend can show remaining count
# ---------------------------------------------------------------------------
@app.get("/generate/limit")
def get_daily_limit_status(request: Request):
    """Returns how many custom episodes the user has generated today."""
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute(
            """
            SELECT COUNT(*) FROM episodes
            WHERE  episode_type = 'custom'
            AND    user_id      = %s::uuid
            AND    DATE(created_at AT TIME ZONE 'UTC') = CURRENT_DATE
            """,
            (user["id"],),
        )
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return JSONResponse({
            "used":      count,
            "limit":     5,
            "remaining": max(0, 5 - count),
        })
    except Exception as e:
        print(f"[generate/limit] ERROR: {e}")
        return JSONResponse({"error": "Failed to fetch limit"}, status_code=500)

@app.post("/generate")
def generate_episode(request: Request):
    REQUEST_COUNT.inc()
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    job_id = send_job_to_queue()
    return {"status": "started", "job_id": job_id}

@app.get("/latest")
def latest_episode(request: Request):
    REQUEST_COUNT.inc()
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, title, published_at, gcs_url, headlines
            FROM episodes
            ORDER BY published_at DESC
            LIMIT 1
        """)
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row:
            return {"status": "no episodes yet"}
        return format_episode_row(row)
    except Exception as e:
        print(f"[latest] ERROR: {e}")
        return JSONResponse({"error": "Failed to fetch latest episode"}, status_code=500)

@app.get("/rss.xml")
def rss_feed(request: Request):
    REQUEST_COUNT.inc()
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT id, title, published_at, gcs_url, headlines
            FROM episodes
            ORDER BY published_at DESC
        """)
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[rss] ERROR: {e}")
        return JSONResponse({"error": "Failed to generate RSS"}, status_code=500)

    items = []
    for row in rows:
        ep = format_episode_row(row)
        pub_date = datetime.fromisoformat(ep["published_at"]).strftime(
            "%a, %d %b %Y %H:%M:%S GMT"
        ) if ep["published_at"] else ""
        audio_url = f"http://localhost:8000/episodes/{ep['id']}/audio"
        item = f"""
        <item>
            <title>{ep['title']}</title>
            <description>{json.dumps(ep['headlines'])}</description>
            <enclosure url="{audio_url}" type="audio/mpeg" />
            <guid>{ep['id']}</guid>
            <pubDate>{pub_date}</pubDate>
        </item>"""
        items.append(item)

    rss = f"""<rss version="2.0">
      <channel>
        <title>NewsCaster AI</title>
        <link>http://localhost:8000</link>
        <description>AI news podcast</description>
        {''.join(items)}
      </channel>
    </rss>"""
    return Response(content=rss, media_type="application/xml")

@app.post("/admin/cleanup")
def cleanup_broken_episodes(request: Request):
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    return _run_cleanup()

# ===========================================================================
# PLAYLIST ROUTES
# ===========================================================================

# ---------------------------------------------------------------------------
# GET /playlists — list all playlists for current user
# ---------------------------------------------------------------------------
@app.get("/playlists")
def get_playlists(request: Request):
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            SELECT p.id, p.name, p.created_at,
                   COUNT(pi.id) as episode_count
            FROM playlists p
            LEFT JOIN playlist_items pi ON pi.playlist_id = p.id
            WHERE p.user_id = %s
            GROUP BY p.id, p.name, p.created_at
            ORDER BY p.created_at DESC
        """, (user["id"],))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {"playlists": [
            {
                "id": str(r[0]),
                "name": r[1],
                "created_at": r[2].isoformat(),
                "episode_count": r[3]
            } for r in rows
        ]}
    except Exception as e:
        print(f"[playlists] ERROR: {e}")
        return JSONResponse({"error": "Failed to fetch playlists"}, status_code=500)


# ---------------------------------------------------------------------------
# POST /playlists — create a new playlist
# ---------------------------------------------------------------------------
@app.post("/playlists")
async def create_playlist(request: Request):
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        return JSONResponse({"error": "Playlist name is required"}, status_code=400)

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO playlists (user_id, name)
            VALUES (%s, %s)
            RETURNING id, name, created_at
        """, (user["id"], name))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return {
            "id": str(row[0]),
            "name": row[1],
            "created_at": row[2].isoformat(),
            "episode_count": 0
        }
    except Exception as e:
        print(f"[create_playlist] ERROR: {e}")
        return JSONResponse({"error": "Failed to create playlist"}, status_code=500)


# ---------------------------------------------------------------------------
# PATCH /playlists/{pid} — rename a playlist
# ---------------------------------------------------------------------------
@app.patch("/playlists/{pid}")
async def rename_playlist(request: Request, pid: str):
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        return JSONResponse({"error": "Playlist name is required"}, status_code=400)

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            UPDATE playlists SET name = %s, updated_at = now()
            WHERE id = %s AND user_id = %s
            RETURNING id
        """, (name, pid, user["id"]))
        if not cur.fetchone():
            return JSONResponse({"error": "Playlist not found"}, status_code=404)
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "ok", "name": name}
    except Exception as e:
        print(f"[rename_playlist] ERROR: {e}")
        return JSONResponse({"error": "Failed to rename playlist"}, status_code=500)


# ---------------------------------------------------------------------------
# DELETE /playlists/{pid} — delete a playlist
# ---------------------------------------------------------------------------
@app.delete("/playlists/{pid}")
def delete_playlist(request: Request, pid: str):
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM playlists WHERE id = %s AND user_id = %s
        """, (pid, user["id"]))
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "deleted"}
    except Exception as e:
        print(f"[delete_playlist] ERROR: {e}")
        return JSONResponse({"error": "Failed to delete playlist"}, status_code=500)


# ---------------------------------------------------------------------------
# GET /playlists/{pid}/items — get episodes in a playlist
# ---------------------------------------------------------------------------
@app.get("/playlists/{pid}/items")
def get_playlist_items(request: Request, pid: str):
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        conn = get_db()
        cur = conn.cursor()
        # Verify ownership
        cur.execute("SELECT id FROM playlists WHERE id = %s AND user_id = %s",
                    (pid, user["id"]))
        if not cur.fetchone():
            return JSONResponse({"error": "Playlist not found"}, status_code=404)

        cur.execute("""
            SELECT e.id, e.title, e.published_at, e.gcs_url, e.headlines,
                   pi.position, pi.id as item_id
            FROM playlist_items pi
            JOIN episodes e ON e.id = pi.episode_id
            WHERE pi.playlist_id = %s
            ORDER BY pi.position ASC
        """, (pid,))
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return {"items": [
            {
                "item_id":      str(r[6]),
                "id":           str(r[0]),
                "title":        r[1],
                "published_at": r[2].isoformat() if r[2] else None,
                "gcs_url":      r[3],
                "headlines":    r[4] if r[4] else [],
                "position":     r[5]
            } for r in rows
        ]}
    except Exception as e:
        print(f"[playlist_items] ERROR: {e}")
        return JSONResponse({"error": "Failed to fetch playlist items"}, status_code=500)


# ---------------------------------------------------------------------------
# POST /playlists/{pid}/items — add episode to playlist
# ---------------------------------------------------------------------------
@app.post("/playlists/{pid}/items")
async def add_to_playlist(request: Request, pid: str):
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    body = await request.json()
    episode_id = body.get("episode_id")
    if not episode_id:
        return JSONResponse({"error": "episode_id is required"}, status_code=400)

    try:
        conn = get_db()
        cur = conn.cursor()
        # Verify ownership
        cur.execute("SELECT id FROM playlists WHERE id = %s AND user_id = %s",
                    (pid, user["id"]))
        if not cur.fetchone():
            return JSONResponse({"error": "Playlist not found"}, status_code=404)

        # Get next position
        cur.execute("""
            SELECT COALESCE(MAX(position) + 1, 0)
            FROM playlist_items WHERE playlist_id = %s
        """, (pid,))
        next_pos = cur.fetchone()[0]

        cur.execute("""
            INSERT INTO playlist_items (playlist_id, episode_id, position)
            VALUES (%s, %s, %s)
            ON CONFLICT (playlist_id, episode_id) DO NOTHING
            RETURNING id
        """, (pid, episode_id, next_pos))
        result = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()

        if not result:
            return JSONResponse({"error": "Episode already in playlist"}, status_code=409)
        return {"status": "added", "position": next_pos}
    except Exception as e:
        print(f"[add_to_playlist] ERROR: {e}")
        return JSONResponse({"error": "Failed to add episode"}, status_code=500)


# ---------------------------------------------------------------------------
# DELETE /playlists/{pid}/items/{item_id} — remove episode from playlist
# ---------------------------------------------------------------------------
@app.delete("/playlists/{pid}/items/{item_id}")
def remove_from_playlist(request: Request, pid: str, item_id: str):
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM playlist_items
            WHERE id = %s AND playlist_id = %s
            AND playlist_id IN (
                SELECT id FROM playlists WHERE user_id = %s
            )
        """, (item_id, pid, user["id"]))
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "removed"}
    except Exception as e:
        print(f"[remove_from_playlist] ERROR: {e}")
        return JSONResponse({"error": "Failed to remove episode"}, status_code=500)


# ---------------------------------------------------------------------------
# PUT /playlists/{pid}/items/reorder — reorder episodes in playlist
# ---------------------------------------------------------------------------
@app.put("/playlists/{pid}/items/reorder")
async def reorder_playlist(request: Request, pid: str):
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    body = await request.json()
    # Expects: {"items": ["item_id_1", "item_id_2", ...]} in new order
    item_ids = body.get("items", [])
    if not item_ids:
        return JSONResponse({"error": "items list is required"}, status_code=400)

    try:
        conn = get_db()
        cur = conn.cursor()
        # Verify ownership
        cur.execute("SELECT id FROM playlists WHERE id = %s AND user_id = %s",
                    (pid, user["id"]))
        if not cur.fetchone():
            return JSONResponse({"error": "Playlist not found"}, status_code=404)

        # Update positions
        for position, item_id in enumerate(item_ids):
            cur.execute("""
                UPDATE playlist_items SET position = %s
                WHERE id = %s AND playlist_id = %s
            """, (position, item_id, pid))

        conn.commit()
        cur.close()
        conn.close()
        return {"status": "reordered"}
    except Exception as e:
        print(f"[reorder_playlist] ERROR: {e}")
        return JSONResponse({"error": "Failed to reorder playlist"}, status_code=500)


# ---------------------------------------------------------------------------
# POST /playlists/{pid}/share — generate share token
# ---------------------------------------------------------------------------
@app.post("/playlists/{pid}/share")
def create_share_token(request: Request, pid: str):
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        conn = get_db()
        cur = conn.cursor()
        # Verify ownership
        cur.execute("SELECT id FROM playlists WHERE id = %s AND user_id = %s",
                    (pid, user["id"]))
        if not cur.fetchone():
            return JSONResponse({"error": "Playlist not found"}, status_code=404)

        # Revoke any existing share tokens for this playlist
        cur.execute("DELETE FROM playlist_shares WHERE playlist_id = %s", (pid,))

        # Create new token expiring in 7 days
        cur.execute("""
            INSERT INTO playlist_shares (playlist_id, expires_at)
            VALUES (%s, now() + interval '7 days')
            RETURNING token, expires_at
        """, (pid,))
        row = cur.fetchone()
        conn.commit()
        cur.close()
        conn.close()
        return {
            "token":      row[0],
            "expires_at": row[1].isoformat(),
            "share_url":  f"/shared/{row[0]}"
        }
    except Exception as e:
        print(f"[create_share] ERROR: {e}")
        return JSONResponse({"error": "Failed to create share token"}, status_code=500)


# ---------------------------------------------------------------------------
# DELETE /playlists/{pid}/share — revoke share token
# ---------------------------------------------------------------------------
@app.delete("/playlists/{pid}/share")
def revoke_share_token(request: Request, pid: str):
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            DELETE FROM playlist_shares
            WHERE playlist_id = %s
            AND playlist_id IN (
                SELECT id FROM playlists WHERE user_id = %s
            )
        """, (pid, user["id"]))
        conn.commit()
        cur.close()
        conn.close()
        return {"status": "revoked"}
    except Exception as e:
        print(f"[revoke_share] ERROR: {e}")
        return JSONResponse({"error": "Failed to revoke share token"}, status_code=500)


# ---------------------------------------------------------------------------
# GET /shared/{token} — view shared playlist (must be logged in)
# ---------------------------------------------------------------------------
@app.get("/shared/{token}", response_class=HTMLResponse)
def view_shared_playlist(request: Request, token: str):
    user = require_user(request)
    if not user:
        return RedirectResponse(f"/login?next=/shared/{token}", status_code=302)

    try:
        conn = get_db()
        cur = conn.cursor()
        # Validate token and check expiry
        cur.execute("""
            SELECT ps.playlist_id, p.name, ps.expires_at
            FROM playlist_shares ps
            JOIN playlists p ON p.id = ps.playlist_id
            WHERE ps.token = %s AND ps.expires_at > now()
        """, (token,))
        row = cur.fetchone()
        if not row:
            cur.close()
            conn.close()
            return templates.TemplateResponse("shared_playlist.html", {
                "request": request,
                "error": "This share link is invalid or has expired.",
                "user": user,
                "playlist": None,
                "items": []
            })

        playlist_id = row[0]
        playlist_name = row[1]
        expires_at = row[2]

        cur.execute("""
            SELECT e.id, e.title, e.published_at, e.gcs_url, e.headlines,
                   pi.position
            FROM playlist_items pi
            JOIN episodes e ON e.id = pi.episode_id
            WHERE pi.playlist_id = %s
            ORDER BY pi.position ASC
        """, (playlist_id,))
        episodes = cur.fetchall()
        cur.close()
        conn.close()

        return templates.TemplateResponse("shared_playlist.html", {
            "request": request,
            "user": user,
            "error": None,
            "playlist": {
                "id": str(playlist_id),
                "name": playlist_name,
                "expires_at": expires_at.isoformat()
            },
            "items": [
                {
                    "id":           str(e[0]),
                    "title":        e[1],
                    "published_at": e[2].isoformat() if e[2] else None,
                    "headlines":    e[4] if e[4] else [],
                    "position":     e[5]
                } for e in episodes
            ]
        })
    except Exception as e:
        print(f"[shared] ERROR: {e}")
        return JSONResponse({"error": "Failed to load shared playlist"}, status_code=500)

# ---------------------------------------------------------------------------
# ANALYTICS ENDPOINTS
# ---------------------------------------------------------------------------

@app.get("/analytics/episodes/{eid}/timeseries")
def episode_timeseries(request: Request, eid: str, days: int = 30):
    """
    Returns daily unique-listener counts for the last `days` days.
    Query param: ?days=30  (default 30, max 365)
    """
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    days = min(days, 365)

    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute(
            """
            SELECT date, unique_listeners
            FROM   episode_daily_uniques
            WHERE  episode_id = %s::uuid
            AND    date >= CURRENT_DATE - (%s || ' days')::interval
            ORDER  BY date ASC
            """,
            (eid, days),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return JSONResponse({
            "episode_id": eid,
            "days":       days,
            "timeseries": [
                {"date": str(row[0]), "unique_listeners": row[1]}
                for row in rows
            ],
        })
    except Exception as e:
        print(f"[analytics/timeseries] ERROR: {e}")
        return JSONResponse({"error": "Failed to fetch analytics"}, status_code=500)


@app.get("/analytics/episodes/{eid}/total")
def episode_total_listens(request: Request, eid: str):
    """
    Returns total raw listen events and total unique listeners (all time).
    """
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute(
            """
            SELECT
                COUNT(*)                     AS total_listens,
                COUNT(DISTINCT user_id)      AS unique_listeners
            FROM episode_listen_events
            WHERE episode_id = %s::uuid
            """,
            (eid,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        return JSONResponse({
            "episode_id":       eid,
            "total_listens":    row[0],
            "unique_listeners": row[1],
        })
    except Exception as e:
        print(f"[analytics/total] ERROR: {e}")
        return JSONResponse({"error": "Failed to fetch analytics"}, status_code=500)


@app.get("/analytics/top")
def top_episodes(request: Request, days: int = 7, limit: int = 10):
    """
    Returns top episodes by unique listeners over the last `days` days.
    Query params: ?days=7&limit=10
    """
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    days  = min(days, 365)
    limit = min(limit, 50)

    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute(
            """
            SELECT
                e.id,
                e.title,
                e.published_at,
                COALESCE(SUM(u.unique_listeners), 0) AS total_unique
            FROM episodes e
            LEFT JOIN episode_daily_uniques u
                ON u.episode_id = e.id
                AND u.date >= CURRENT_DATE - (%s || ' days')::interval
            GROUP BY e.id, e.title, e.published_at
            ORDER BY total_unique DESC
            LIMIT %s
            """,
            (days, limit),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return JSONResponse({
            "days":  days,
            "limit": limit,
            "episodes": [
                {
                    "id":             str(row[0]),
                    "title":          row[1],
                    "published_at":   str(row[2]) if row[2] else None,
                    "unique_listeners": row[3],
                }
                for row in rows
            ],
        })
    except Exception as e:
        print(f"[analytics/top] ERROR: {e}")
        return JSONResponse({"error": "Failed to fetch analytics"}, status_code=500)

# ---------------------------------------------------------------------------
# Cleanup internals
# ---------------------------------------------------------------------------
def _run_cleanup():
    removed = []
    kept = []
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, gcs_url FROM episodes")
        rows = cur.fetchall()
        for episode_id, gcs_url in rows:
            try:
                resp = ext_requests.head(gcs_url, timeout=5)
                if resp.status_code == 200:
                    kept.append(str(episode_id))
                else:
                    _remove_episode(cur, str(episode_id))
                    removed.append(str(episode_id))
            except Exception as e:
                print(f"[cleanup] ERROR checking {episode_id}: {e}")
                _remove_episode(cur, str(episode_id))
                removed.append(str(episode_id))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        return {"error": str(e)}
    return {
        "removed": removed,
        "kept": kept,
        "total_checked": len(rows),
        "total_removed": len(removed)
    }

def _remove_episode(cur, episode_id: str):
    cur.execute("DELETE FROM episodes WHERE id = %s", (episode_id,))
    r.lrem("episodes", 0, episode_id)
    r.delete(f"episode:{episode_id}")
    latest = r.get("latest_episode")
    if latest == episode_id:
        r.delete("latest_episode")
    print(f"[cleanup] removed {episode_id}")

def _scheduled_cleanup():
    while True:
        time.sleep(6 * 60 * 60)
        print("[cleanup] running scheduled cleanup...")
        _run_cleanup()
