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

def require_user(request: Request) -> dict | None:
    user = get_current_user(request)
    if not user:
        return None
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
    user = get_current_user(request)
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
    
@app.get("/episodes/{eid}/audio")
def get_audio(request: Request, eid: str):
    REQUEST_COUNT.inc()
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    gcs_url = r.hget(f"episode:{eid}", "gcs_url")
    if not gcs_url:
        # Fallback to Postgres if not in Redis
        try:
            conn = get_db()
            cur = conn.cursor()
            cur.execute("SELECT gcs_url FROM episodes WHERE id = %s", (eid,))
            row = cur.fetchone()
            cur.close()
            conn.close()
            if row:
                return RedirectResponse(row[0])
        except Exception:
            pass
        return JSONResponse({"error": "Episode not found"}, status_code=404)
    return RedirectResponse(gcs_url)

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