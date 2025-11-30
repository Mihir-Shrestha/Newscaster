import pika, json, os
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

def summarize(text):
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": f"Summarize this news in 3 sentences:\n{text}"}]
    )
    return resp.choices[0].message.content

def callback(ch, method, properties, body):
    data = json.loads(body)
    summary = summarize(data["content"])
    data["summary"] = summary

    ch.basic_publish("", "to_tts", json.dumps(data))
    ch.basic_ack(method.delivery_tag)

if __name__ == "__main__":
    conn = pika.BlockingConnection(pika.ConnectionParameters("rabbitmq"))
    ch = conn.channel()
    ch.queue_declare(queue="to_tts")

    ch.basic_qos(prefetch_count=1)
    ch.basic_consume("to_summarizer", callback)

    print("Summarizer worker running...")
    ch.start_consuming()
