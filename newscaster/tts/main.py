import os
import json
import time
import pika
from google.cloud import texttospeech
import redis
from datetime import datetime

RABBIT = "rabbitmq"

def connect_rabbit():
    while True:
        try:
            conn = pika.BlockingConnection(pika.ConnectionParameters(RABBIT))
            print("TTS worker connected to RabbitMQ")
            return conn
        except:
            print("TTS waiting for RabbitMQ...")
            time.sleep(2)

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

def callback(ch, method, props, body):
    data = json.loads(body)

    job_id = data["job_id"]
    script = data["podcast_script"]
    
    # File name based on job id
    file_name = f"{job_id}_final.mp3"

    # Generate TTS audio
    tts_generate(script, file_name)

    # Store metadata in Redis
    r = redis.Redis(host="redis", port=6379, decode_responses=True)

    # Extract headlines/titles to save with the episode
    headlines = data.get("headlines", [])

    metadata = {
        "id": job_id,
        "title": f"Daily News - {datetime.now().strftime('%Y-%m-%d')}",
        "audio_file": file_name,
        "headlines": json.dumps(headlines),
        "timestamp": int(time.time())
    }
    
    # Save metadata hash
    r.hset(f"episode:{job_id}", mapping=metadata)
    
    # Push into episode list
    r.lpush("episodes", job_id)

    # Update latest episode pointer
    r.set("latest_episode", job_id)
    print("Metadata stored in Redis for episode:", job_id)

    # Acknowledge message
    ch.basic_ack(method.delivery_tag)

if __name__ == "__main__":
    if not os.path.exists("/secrets/gcp-key.json"):
        raise FileNotFoundError("Missing /secrets/gcp-key.json for Google credentials")

    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/secrets/gcp-key.json"

    conn = connect_rabbit()
    ch = conn.channel()

    ch.queue_declare(queue="to_tts")

    print("TTS worker started.")
    ch.basic_qos(prefetch_count=1)
    ch.basic_consume("to_tts", callback)

    ch.start_consuming()