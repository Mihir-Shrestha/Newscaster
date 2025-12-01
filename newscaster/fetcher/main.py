import os
import json
import time
import uuid
import requests
import pika

NEWS_API_KEY = os.getenv("NEWS_API_KEY")
RABBIT = "rabbitmq"

def connect_rabbit():
    while True:
        try:
            conn = pika.BlockingConnection(pika.ConnectionParameters(RABBIT))
            print("Fetcher connected to RabbitMQ")
            return conn
        except:
            print("Fetcher waiting for RabbitMQ...")
            time.sleep(2)

def fetch_headlines():
    url = f"https://newsapi.org/v2/top-headlines?country=us&pageSize=10&apiKey={NEWS_API_KEY}"
    r = requests.get(url)
    data = r.json()
    return data.get("articles", [])[:10]

def callback(ch, method, props, body):
    data = json.loads(body)
    job_id = data["job_id"]

    print(f"Fetcher: received request to generate job {job_id}")

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

    # Send SINGLE message to summarizer
    ch.basic_publish(
        exchange="",
        routing_key="to_summarizer",
        body=json.dumps(payload)
    )

    print("Fetcher published articles for job:", job_id)
    ch.basic_ack(method.delivery_tag)

if __name__ == "__main__":
    conn = connect_rabbit()
    ch = conn.channel()

    ch.queue_declare(queue="to_fetcher")
    ch.queue_declare(queue="to_summarizer")

    print("Fetcher worker started.")
    ch.basic_qos(prefetch_count=1)
    ch.basic_consume(queue="to_fetcher", on_message_callback=callback)

    ch.start_consuming()