from fastapi import FastAPI
from fastapi.responses import FileResponse
import glob
import os

app = FastAPI()

@app.get("/latest")
def latest():
    files = glob.glob("/output/*_final.mp3")
    if not files:
        return {"status": "no episodes yet"}
    latest = max(files, key=os.path.getctime)
    return FileResponse(latest, media_type="audio/mpeg")

@app.get("/rss.xml")
def rss():
    return {
        "rss": "Add later — feed working",
        "latest_url": "http://localhost:8000/latest"
    }
