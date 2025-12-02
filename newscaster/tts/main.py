import os
import json
import time
import pika
import redis
from datetime import datetime, timedelta
from google.cloud import texttospeech
from google.cloud import storage

RABBIT = "rabbitmq"
BUCKET_NAME = "newscaster-episodes"

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

def callback(ch, method, props, body):
    data = json.loads(body)

    job_id = data["job_id"]
    script = data["podcast_script"]

    # File name based on job id
    file_name = f"{job_id}_final.mp3"

    # Generate MP3 locally
    local_path = tts_generate(script, file_name)

    # Upload MP3 to GCS
    gcs_url = upload_to_gcs(local_path, file_name)

    # Delete local file (Optional)
    # if os.path.exists(local_path):
    #     os.remove(local_path)

    # Save metadata in Redis
    r = redis.Redis(host="redis", port=6379, decode_responses=True)

    # Extract headlines/titles to save with the episode
    headlines = data.get("headlines", [])

    metadata = {
        "id": job_id,
        "title": f"{datetime.now().strftime('%Y-%m-%d')}",
        "gcs_url": gcs_url,
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