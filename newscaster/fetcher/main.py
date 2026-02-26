import os
import json
import time
import uuid
import requests
import pika
from prometheus_client import Counter, start_http_server

NEWS_API_KEY = os.getenv("NEWS_API_KEY")
RABBIT = "rabbitmq"
JOBS_PROCESSED = Counter("jobs_processed_total", "Jobs processed")

def connect_rabbit():
    while True:
        try:
            conn = pika.BlockingConnection(pika.ConnectionParameters(RABBIT))
            print("Fetcher connected to RabbitMQ")
            return conn
        except:
            print("Fetcher waiting for RabbitMQ...")
            time.sleep(2)

def fetch_headlines(news_url=None, news_params=None):
    """Fetch from NewsAPI — uses custom URL+params if provided, else default top-headlines."""
    if news_url and news_params:
        r = requests.get(news_url, params=news_params)
    else:
        r = requests.get(
            "https://newsapi.org/v2/top-headlines",
            params={"country": "us", "pageSize": 10, "apiKey": NEWS_API_KEY},
        )
    data = r.json()
    if data.get("status") != "ok":
        print(f"Fetcher: NewsAPI error: {data.get('message')}")
    return data.get("articles", [])[:10]

def callback(ch, method, props, body):
    JOBS_PROCESSED.inc()
    data        = json.loads(body)
    job_id      = data["job_id"]
    news_url    = data.get("news_url")
    news_params = data.get("news_params")
    genre       = data.get("genre", "general")
    episode_type = data.get("episode_type", "daily")
    user_id     = data.get("user_id")

    print(f"Fetcher: received request to generate job {job_id} type={episode_type}")

    articles = fetch_headlines(news_url, news_params)

    payload = {
        "job_id":       job_id,
        "episode_type": episode_type,
        "user_id":      user_id,
        "genre":        genre,
        "articles": [
            {
                "title":   art["title"],
                "content": art.get("content") or art.get("description") or "",
                "url":     art["url"],
            }
            for art in articles
        ],
    }

    ch.basic_publish(
        exchange="",
        routing_key="to_summarizer",
        body=json.dumps(payload),
    )

    print("Fetcher published articles for job:", job_id)
    ch.basic_ack(method.delivery_tag)

if __name__ == "__main__":
    start_http_server(9090)
    mode = os.getenv("FETCHER_MODE", "worker")

    if mode == "cron":
        # CronJob mode → run once then exit
        print("Fetcher running in CRON MODE")
        job_id = str(uuid.uuid4())
        articles = fetch_headlines()

        payload = {
            "job_id": job_id,
            "articles": [
                {
                    "title": art["title"],
                    "content": art.get("content") or art.get("description") or "",
                    "url": art["url"]
                }
                for art in articles
            ]
        }

        conn = connect_rabbit()
        ch = conn.channel()
        ch.queue_declare(queue="to_summarizer")
        ch.basic_publish(exchange="", routing_key="to_summarizer", body=json.dumps(payload))

        print("Fetcher CRON job finished for job:", job_id)
        exit(0)

    else:
        # Worker mode → listen to RabbitMQ forever
        print("Fetcher running in WORKER MODE")

        conn = connect_rabbit()
        ch = conn.channel()

        ch.queue_declare(queue="to_fetcher")
        ch.queue_declare(queue="to_summarizer")

        ch.basic_qos(prefetch_count=1)
        ch.basic_consume(queue="to_fetcher", on_message_callback=callback)

        print("Fetcher worker started.")
        ch.start_consuming()