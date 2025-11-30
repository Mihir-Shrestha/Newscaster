import os, json, pika
from google.cloud import texttospeech

client = texttospeech.TextToSpeechClient()

def synthesize(text, filename):
    input = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(language_code="en-US")
    audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)

    response = client.synthesize_speech(
        input=input, voice=voice, audio_config=audio_config
    )

    with open(f"/output/{filename}", "wb") as f:
        f.write(response.audio_content)

def callback(ch, method, properties, body):
    data = json.loads(body)
    fname = f"{data['job_id']}_{data['title'][:20].replace(' ','_')}.mp3"
    synthesize(data["summary"], fname)

    data["audio_file"] = fname
    ch.basic_publish("", "to_compiler", json.dumps(data))
    ch.basic_ack(method.delivery_tag)

if __name__ == "__main__":
    os.makedirs("/output", exist_ok=True)
    conn = pika.BlockingConnection(pika.ConnectionParameters("rabbitmq"))
    ch = conn.channel()

    ch.queue_declare(queue="to_compiler")
    ch.basic_consume("to_tts", callback)

    print("TTS worker running...")
    ch.start_consuming()
