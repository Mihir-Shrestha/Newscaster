import os
import json
import time
import pika
from openai import OpenAI
from prometheus_client import Counter, start_http_server

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
RABBIT = "rabbitmq"
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
You are an engaging podcast host. Create a single cohesive podcast script summarizing ALL the news stories below.
Requirements:
- Start with a warm, conversational INTRO (2-3 sentences)
- Explain each story clearly (no bullets)
- Use smooth transitions between topics
- Keep tone human, modern, similar to NPR or The Daily
- End with a short OUTRO thanking the listener
- No mention of being AI
- Output only the final script
"""

def make_podcast_script(articles):
    combined_text = "\n\n".join(
        f"TITLE: {a['title']}\nCONTENT: {a['content']}" for a in articles
    )

    res = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": PODCAST_PROMPT},
            {"role": "user", "content": combined_text}
        ]
    )

    return res.choices[0].message.content

def callback(ch, method, props, body):
    JOBS_PROCESSED.inc()
    data = json.loads(body)
    job_id = data["job_id"]
    articles = data["articles"]

    print(f"Summarizer: generating podcast script for job {job_id}...")

    script = make_podcast_script(articles)
    headlines = [art["title"] for art in articles]

    out = {
        "job_id": job_id,
        "podcast_script": script,
        "headlines": headlines
    }

    ch.basic_publish(exchange="", routing_key="to_tts", body=json.dumps(out))
    ch.basic_ack(method.delivery_tag)

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
