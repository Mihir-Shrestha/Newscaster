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
from fastapi import FastAPI, Request, Response, Form, Cookie
from fastapi.responses import (
    HTMLResponse, JSONResponse, RedirectResponse
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from prometheus_client import Counter, generate_latest

# ---------------------------------------------------------------------------
# DB migrations on startup
# ---------------------------------------------------------------------------
sys.path.insert(0, "/app/db")
from migrate import run_migrations
from auth import (
    create_access_token, decode_access_token,
    create_user_with_password, get_local_identity,
    verify_password, upsert_google_user, get_user_by_id
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
    # Auto cleanup every 6 hours
    t = threading.Thread(target=_scheduled_cleanup, daemon=True)
    t.start()

# Redis client
r = redis.Redis(host="redis", port=6379, decode_responses=True)

templates = Jinja2Templates(directory="/app/templates")
app.mount("/static", StaticFiles(directory="/app/static"), name="static")

REQUEST_COUNT = Counter("api_request_count", "Total API Requests")

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# DB connection helper
# ---------------------------------------------------------------------------
def get_db():
    return psycopg2.connect(os.environ["DATABASE_URL"])

# ---------------------------------------------------------------------------
# RabbitMQ helper
# ---------------------------------------------------------------------------
def send_job_to_queue():
    connection = pika.BlockingConnection(pika.ConnectionParameters("rabbitmq"))
    channel = connection.channel()
    channel.queue_declare(queue="to_fetcher")
    job_id = str(uuid.uuid4())
    payload = {"job_id": job_id, "trigger": "api_request"}
    channel.basic_publish(exchange="", routing_key="to_fetcher", body=json.dumps(payload))
    connection.close()
    return job_id

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
    try:
        user = create_user_with_password(email, display_name, password)
        token = create_access_token(user["id"], user["email"])
        response = RedirectResponse("/", status_code=302)
        response.set_cookie("access_token", token, httponly=True, max_age=3600)
        return response
    except Exception as e:
        return templates.TemplateResponse("signup.html", {
            "request": request,
            "error": f"Signup failed: {str(e)}"
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

    # Get user info from Google
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
    REQUEST_COUNT.inc()
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    ids = r.lrange("episodes", 0, -1)
    episodes = [r.hgetall(f"episode:{eid}") for eid in ids]
    return {"episodes": episodes}

@app.get("/episodes/{eid}/audio")
def get_audio(request: Request, eid: str):
    REQUEST_COUNT.inc()
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    gcs_url = r.hget(f"episode:{eid}", "gcs_url")
    if not gcs_url:
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
    eid = r.get("latest_episode")
    if not eid:
        return {"status": "no episodes yet"}
    return r.hgetall(f"episode:{eid}")

@app.get("/rss.xml")
def rss_feed(request: Request):
    REQUEST_COUNT.inc()
    user = require_user(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    ids = r.lrange("episodes", 0, -1)
    items = []
    for eid in ids:
        ep = r.hgetall(f"episode:{eid}")
        if not ep:
            continue
        pub_date = datetime.fromtimestamp(
            int(ep["timestamp"]), tz=timezone.utc
        ).strftime("%a, %d %b %Y %H:%M:%S GMT")
        audio_url = f"http://localhost:8000/episodes/{eid}/audio"
        item = f"""
        <item>
            <title>{ep['title']}</title>
            <description>{json.dumps(ep['headlines'])}</description>
            <enclosure url="{audio_url}" type="audio/mpeg" />
            <guid>{eid}</guid>
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