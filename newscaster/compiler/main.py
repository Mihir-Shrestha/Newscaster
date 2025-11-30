import pika, json, os
from pydub import AudioSegment

jobs = {}

def callback(ch, method, properties, body):
    data = json.loads(body)
    jid = data["job_id"]

    jobs.setdefault(jid, [])
    jobs[jid].append(data["audio_file"])

    # if we have 3 audio files, compile
    if len(jobs[jid]) == 3:
        final = AudioSegment.empty()
        for f in jobs[jid]:
            final += AudioSegment.from_mp3(f"/output/{f}")

        final.export(f"/output/{jid}_final.mp3", format="mp3")
        print("Compiled:", jid)

    ch.basic_ack(method.delivery_tag)

if __name__ == "__main__":
    conn = pika.BlockingConnection(pika.ConnectionParameters("rabbitmq"))
    ch = conn.channel()

    ch.basic_consume("to_compiler", callback)
    print("Compiler worker running...")
    ch.start_consuming()
