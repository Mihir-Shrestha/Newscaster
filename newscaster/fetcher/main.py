import json, os, requests, pika, uuid

NEWS_API_KEY = os.getenv("NEWS_API_KEY")
RABBITMQ = os.getenv("RABBITMQ", "rabbitmq")

def get_headlines():
    url = f"https://newsapi.org/v2/top-headlines?country=us&pageSize=3&apiKey={NEWS_API_KEY}"
    r = requests.get(url)
    return r.json()["articles"]

def send_message(channel, queue, payload):
    channel.basic_publish(
        exchange="",
        routing_key=queue,
        body=json.dumps(payload)
    )

if __name__ == "__main__":
    conn = pika.BlockingConnection(pika.ConnectionParameters(RABBITMQ))
    channel = conn.channel()
    channel.queue_declare(queue="to_summarizer")

    articles = get_headlines()
    job_id = str(uuid.uuid4())

    for a in articles:
        msg = {
            "job_id": job_id,
            "title": a["title"],
            "content": a["description"] or "",
            "url": a["url"]
        }
        send_message(channel, "to_summarizer", msg)

    conn.close()
    print("Fetcher completed job:", job_id)
    