import os
import json
import time
import pika
import requests
from prometheus_client import Counter, start_http_server

RABBIT = "rabbitmq"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_TIMEOUT_SEC = int(os.getenv("OLLAMA_TIMEOUT_SEC", "120"))
JOBS_PROCESSED = Counter("jobs_processed_total", "Jobs processed")      

def connect_rabbit():
    while True:
        try:
            conn = pika.BlockingConnection(pika.ConnectionParameters(RABBIT))
            print("Summarizer connected to RabbitMQ")
            return conn
        except:
            print("Summarizer waiting for RabbitMQ...")
            time.sleep(2)

PODCAST_PROMPT = """
Create one continuous, ready-for-TTS podcast script that summarizes ALL provided news stories.

REQUIREMENTS:
- Begin with a warm 2-3 sentence introduction that explicitly names the podcast "Newscaster" in the first sentence and sounds natural for spoken audio.
- Cover every story clearly in flowing paragraph form (no bullets).
- Use smooth transitions so the script sounds like one episode.
- Keep a human, modern, daily-news tone.
- End with a short closing thank-you.
- No mention of being AI.

SOURCE ATTRIBUTION (MANDATORY):
- For each story, explicitly mention the outlet/source once.
- Use natural attribution in the sentence, e.g. "According to CBS News..." or "...reports from WHYY say..."
- Ensure all listed stories include their matching source attribution.

OUTPUT RULES:
- Output only the final narration text.
- No labels like "Host:".
- No bracketed markers like [INTRO]/[OUTRO].
- No stage directions, markdown, bullets, or numbering.

LENGTH:
- Target 360-460 words (roughly 2-3 minutes for TTS).

Return only the final script.
"""

def make_podcast_script(articles):
    combined_text = "\n\n".join(
        f"TITLE: {a['title']}\nCONTENT: {a['content']}" for a in articles
    )
    prompt = f"{PODCAST_PROMPT}\n\nNEWS STORIES:\n{combined_text}\n\nFINAL SCRIPT:"
    resp = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False
        },
        timeout=OLLAMA_TIMEOUT_SEC
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("response", "").strip()

def callback(ch, method, props, body):
    JOBS_PROCESSED.inc()
    data = json.loads(body)
    job_id = data["job_id"]
    articles = data["articles"]

    print(f"Summarizer: generating podcast script for job {job_id}...")

    try:
        script = make_podcast_script(articles)
        headlines = [art["title"] for art in articles]

        out = {
            "job_id": job_id,
            "podcast_script": script,
            "headlines": headlines
        }

        ch.basic_publish(exchange="", routing_key="to_tts", body=json.dumps(out))
        ch.basic_ack(method.delivery_tag)
        print(f"Summarizer: job {job_id} done OK")

    except Exception as e:
        print(f"Summarizer: ERROR on job {job_id}: {e}")
        # Discard the message — do NOT requeue so it doesn't loop forever
        ch.basic_nack(method.delivery_tag, requeue=False)

if __name__ == "__main__":
    start_http_server(9090)
    conn = connect_rabbit()
    ch = conn.channel()

    ch.queue_declare(queue="to_summarizer")
    ch.queue_declare(queue="to_tts")

    print("Summarizer worker started.")
    ch.basic_qos(prefetch_count=1)
    ch.basic_consume(queue="to_summarizer", on_message_callback=callback)

    ch.start_consuming()
