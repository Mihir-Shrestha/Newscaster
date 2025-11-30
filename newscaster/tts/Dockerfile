FROM python:3.10-slim

WORKDIR /app

# for pydub audio export + Google libs
RUN apt-get update && apt-get install -y ffmpeg && apt-get clean

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

# mount secrets and output via volumes
CMD ["python", "main.py"]
