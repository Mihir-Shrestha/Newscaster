FROM python:3.10-slim

WORKDIR /app

COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy DB migrations
COPY db/ /app/db/

# Copy API files
COPY api/main.py .
COPY api/auth.py .
COPY api/templates/ /app/templates/
COPY api/static/ /app/static/

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
