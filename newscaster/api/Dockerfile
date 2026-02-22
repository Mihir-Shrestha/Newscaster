FROM python:3.10-slim

WORKDIR /app
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY db /app/db
COPY api/main.py .
COPY api/templates ./templates
COPY api/static ./static

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
