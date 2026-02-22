import os
import sys
import json
import time
import pika
import redis
import psycopg2
from datetime import datetime, timedelta
from google.cloud import texttospeech
from google.cloud import storage
from prometheus_client import Counter, start_http_server

# ---------------------------------------------------------------------------
# DB migrations on startup
# ---------------------------------------------------------------------------
sys.path.insert(0, "/app/db")
from migrate import run_migrations

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "db", "migrations")

RABBIT = "rabbitmq"
BUCKET_NAME = "newscaster-episodes"
JOBS_PROCESSED = Counter("jobs_processed_total", "Jobs processed")

def connect_rabbit():
    while True:
        try:
            conn = pika.BlockingConnection(pika.ConnectionParameters(RABBIT))
            print("TTS worker connected to RabbitMQ")
            return conn
        except:
            print("TTS waiting for RabbitMQ...")
            time.sleep(2)

def upload_to_gcs(local_path, gcs_filename):
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    blob = bucket.blob(gcs_filename)
    blob.upload_from_filename(local_path)
    url = blob.generate_signed_url(version="v4", expiration=timedelta(days=7), method="GET")
    print("Uploaded to GCS. Singed URL: ", url)
    return url

def tts_generate(text, filename):
    client = texttospeech.TextToSpeechClient()
    synthesis_input = texttospeech.SynthesisInput(text=text)
    voice_params = texttospeech.VoiceSelectionParams(
        language_code="en-US",
        ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL
    )
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.MP3
    )
    response = client.synthesize_speech(
        input=synthesis_input, voice=voice_params, audio_config=audio_config
    )
    out_path = f"/output/{filename}"
    with open(out_path, "wb") as f:
        f.write(response.audio_content)
    print("TTS created:", out_path)
    return out_path

# ---------------------------------------------------------------------------
# Postgres write helper
# ---------------------------------------------------------------------------
def persist_episode_to_postgres(job_id, title, gcs_url, transcript, headlines):
    try:
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO episodes (id, title, gcs_url, transcript, headlines, published_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            ON CONFLICT (id) DO UPDATE
                SET gcs_url      = EXCLUDED.gcs_url,
                    transcript   = EXCLUDED.transcript,
                    headlines    = EXCLUDED.headlines,
                    published_at = EXCLUDED.published_at
        """, (
            job_id,
            title,
            gcs_url,
            transcript,
            json.dumps(headlines)
        ))
        conn.commit()
        cur.close()
        conn.close()
        print(f"[postgres] episode {job_id} persisted OK")
    except Exception as e:
        print(f"[postgres] ERROR persisting episode {job_id}: {e}")
        # Do NOT raise — Redis already wrote, don't fail the job

def callback(ch, method, props, body):
    JOBS_PROCESSED.inc()
    data = json.loads(body)
    job_id = data["job_id"]
    script = data["podcast_script"]
    file_name = f"{job_id}_final.mp3"
    local_path = tts_generate(script, file_name)
    gcs_url = upload_to_gcs(local_path, file_name)

    headlines = data.get("headlines", [])
    title     = datetime.now().strftime("%Y-%m-%d")

    r = redis.Redis(host="redis", port=6379, decode_responses=True)
    metadata = {
        "id": job_id,
        "title": title,
        "gcs_url": gcs_url,
        "headlines": json.dumps(headlines),
        "timestamp": int(time.time())
    }
    r.hset(f"episode:{job_id}", mapping=metadata)
    r.lpush("episodes", job_id)
    r.set("latest_episode", job_id)
    print("Metadata stored in Redis for episode:", job_id)

    # ── Postgres (new, source of truth) ─────────────────────────────────────
    persist_episode_to_postgres(
        job_id    = job_id,
        title     = title,
        gcs_url   = gcs_url,
        transcript = script,   # podcast_script is the full transcript
        headlines  = headlines
    )

    ch.basic_ack(method.delivery_tag)
    
if __name__ == "__main__":
    start_http_server(9090)
    if not os.path.exists("/var/secrets/google/gcp-key.json"):
        raise FileNotFoundError("Missing /var/secrets/google/gcp-key.json")

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/var/secrets/google/gcp-key.json"

    # Run DB migrations before consuming
    run_migrations(MIGRATIONS_DIR)

    conn = connect_rabbit()
    ch = conn.channel()
    ch.queue_declare(queue="to_tts")
    print("TTS worker started.")
    ch.basic_qos(prefetch_count=1)
    ch.basic_consume("to_tts", callback)
    ch.start_consuming()