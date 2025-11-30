from fastapi import FastAPI
from fastapi.responses import FileResponse

import glob, os

app = FastAPI()

@app.get("/latest")
def latest_episode():
    files = glob.glob("/output/*_final.mp3")
    if not files:
        return {"status": "no episodes yet"}

    latest = max(files, key=os.path.getctime)
    return FileResponse(latest, media_type="audio/mpeg")

@app.get("/rss.xml")
def rss():
    # you can expand this later
    xml = f"""
    <rss version="2.0">
      <channel>
        <title>NewsCaster AI</title>
        <item>
          <title>Latest Episode</title>
          <enclosure url="http://localhost:8000/latest" type="audio/mpeg"/>
        </item>
      </channel>
    </rss>
    """
    return xml