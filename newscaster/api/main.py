import os
import sys
import json
import redis
import requests
import psycopg2
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
import pika
import uuid
from datetime import datetime, timezone
from prometheus_client import Counter, generate_latest

# ---------------------------------------------------------------------------
# DB migrations on startup
# ---------------------------------------------------------------------------
sys.path.insert(0, "/app/db")
from migrate import run_migrations

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "db", "migrations")

app = FastAPI()

@app.on_event("startup")
def on_startup():
    run_migrations(MIGRATIONS_DIR)

# Redis client
r = redis.Redis(host="redis", port=6379, decode_responses=True)

# Template/Static folders
templates = Jinja2Templates(directory="/app/templates")
app.mount("/static", StaticFiles(directory="/app/static"), name="static")

# Metrics
REQUEST_COUNT = Counter("api_request_count", "Total API Requests")

# ---------------------------------------------------------------------------
# DB connection helper
# ---------------------------------------------------------------------------
def get_db():
    return psycopg2.connect(os.environ["DATABASE_URL"])

# ---------------------------------------------------------------------------
# RabbitMQ connection helper
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

# WEB UI
@app.get("/", response_class=HTMLResponse)
def homepage(request: Request):
    REQUEST_COUNT.inc()
    return templates.TemplateResponse("index.html", {"request": request})

# API ENDPOINTS
@app.get("/metrics")
def metrics():
    REQUEST_COUNT.inc()
    return Response(generate_latest(), media_type="text/plain")

@app.get("/episodes")
def get_episodes():
    REQUEST_COUNT.inc()
    ids = r.lrange("episodes", 0, -1)
    episodes = [r.hgetall(f"episode:{eid}") for eid in ids]
    return {"episodes": episodes}

@app.get("/episodes/{eid}/audio")
def get_audio(eid: str):
    REQUEST_COUNT.inc()
    gcs_url = r.hget(f"episode:{eid}", "gcs_url")
    if not gcs_url:
        return JSONResponse({"error": "Episode not found"}, status_code=404)
    return RedirectResponse(gcs_url)

@app.post("/generate")
def generate_episode():
    REQUEST_COUNT.inc()
    job_id = send_job_to_queue()
    return {"status": "started", "job_id": job_id}

@app.get("/latest")
def latest_episode():
    REQUEST_COUNT.inc()
    eid = r.get("latest_episode")
    if not eid:
        return {"status": "no episodes yet"}
    return r.hgetall(f"episode:{eid}")

# RSS FEED
@app.get("/rss.xml")
def rss_feed():
    REQUEST_COUNT.inc()
    ids = r.lrange("episodes", 0, -1)
    items = []

    for eid in ids:
        ep = r.hgetall(f"episode:{eid}")
        if not ep:
            continue

        pub_date = datetime.fromtimestamp(int(ep["timestamp"]), tz=timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")
        audio_url = f"http://localhost:8000/episodes/{eid}/audio"

        item = f"""
        <item>
            <title>{ep['title']}</title>
            <description>{json.dumps(ep['headlines'])}</description>
            <enclosure url="{audio_url}" type="audio/mpeg" />
            <guid>{eid}</guid>
            <pubDate>{pub_date}</pubDate>
        </item>
        """
        items.append(item)

    rss = f"""
    <rss version="2.0">
      <channel>
        <title>NewsCaster AI</title>
        <link>http://localhost:8000</link>
        <description>Automatically generated AI news podcast</description>
        {''.join(items)}
      </channel>
    </rss>
    """
    return Response(content=rss, media_type="application/xml")

# ---------------------------------------------------------------------------
# GCS Health Check + Cleanup
# ---------------------------------------------------------------------------
@app.post("/admin/cleanup")
def cleanup_broken_episodes():
    """
    Checks every episode's GCS URL. Removes broken ones from Postgres + Redis.
    """
    removed = []
    kept = []

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, gcs_url FROM episodes")
        rows = cur.fetchall()

        for episode_id, gcs_url in rows:
            try:
                resp = requests.head(gcs_url, timeout=5)
                if resp.status_code == 200:
                    kept.append(str(episode_id))
                else:
                    # GCS file is gone or URL expired — remove everywhere
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
        return JSONResponse({"error": str(e)}, status_code=500)

    return {
        "removed": removed,
        "kept": kept,
        "total_checked": len(rows),
        "total_removed": len(removed)
    }

def _remove_episode(cur, episode_id: str):
    """Remove episode from Postgres and Redis."""
    # Postgres
    cur.execute("DELETE FROM episodes WHERE id = %s", (episode_id,))
    print(f"[cleanup] removed {episode_id} from Postgres")

    # Redis
    r.lrem("episodes", 0, episode_id)
    r.delete(f"episode:{episode_id}")

    # Clear latest_episode if it was this one
    latest = r.get("latest_episode")
    if latest == episode_id:
        r.delete("latest_episode")

    print(f"[cleanup] removed {episode_id} from Redis")