import os
import json
import time
import uuid
import requests
import pika

NEWS_API_KEY = os.getenv("NEWS_API_KEY")
RABBITMQ_HOST = "rabbitmq"

def connect_rabbit():
    while True:
        try:
            connection = pika.BlockingConnection(pika.ConnectionParameters(RABBITMQ_HOST))
            print("Fetcher connected to RabbitMQ")
            return connection
        except:
            print("Fetcher: waiting for RabbitMQ...")
            time.sleep(2)

def fetch_headlines():
    url = f"https://newsapi.org/v2/top-headlines?country=us&pageSize=10&apiKey={NEWS_API_KEY}"
    r = requests.get(url)
    data = r.json()
    return data.get("articles", [])[:10]

if __name__ == "__main__":
    print("Fetcher starting...")

    conn = connect_rabbit()
    channel = conn.channel()
    channel.queue_declare(queue="to_summarizer")

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

    # Publish ONE combined message
    channel.basic_publish(exchange="", routing_key="to_summarizer", body=json.dumps(payload))

    print("Fetcher completed job:", job_id)
    conn.close()
