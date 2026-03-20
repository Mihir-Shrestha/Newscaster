# Newscaster

## What it does
Newscaster is a microservice-based app that turns live news into short podcast episodes. It fetches current headlines, summarizes them into a spoken script, converts that script into audio, and lets users play, search, save, and share episodes through a web app.

## Why this was built
Newscaster grew from a simple, familiar habit: enjoying podcasts as an easy way to stay informed. Keeping up with the news often takes more time and focus than a busy day allows, and while social media can surface updates quickly, it can also be distracting, noisy, and fragmented. The goal here was to create a better middle ground, a way to turn important news into something easier to follow through listening.

It also became an opportunity to explore what it takes to build a complete software system end to end. Rather than stopping at one piece of functionality, this project connects live news retrieval, summarization, audio generation, storage, and a real user-facing application. The result is a project shaped by a personal use case, but built with the structure of a practical production-style system.

## How it works
- API layer: A FastAPI app handles authentication, episode browsing, search, custom generation requests, playlists, analytics, and the frontend UI.
- Database: PostgreSQL stores users, episodes, playlists, shares, and listen analytics. Redis is used as a lightweight cache for episode metadata and latest-audio lookups.
- Processing logic: The API queues jobs in RabbitMQ, the fetcher pulls articles from NewsAPI, the summarizer uses Ollama to generate a podcast-style script, and the TTS worker converts that script to MP3 with Google Cloud Text-to-Speech before storing metadata and audio locations.

## Architecture

```text
User request
  -> FastAPI API
  -> RabbitMQ queue
  -> Fetcher service
  -> Summarizer service
  -> TTS service
  -> Google Cloud Storage + PostgreSQL + Redis
  -> API serves episodes, transcripts, playlists, and analytics
```

Services in the project:

- `api`: authentication, UI, search, playlists, analytics, RSS
- `fetcher`: article collection from NewsAPI
- `summarizer`: podcast script generation with Ollama
- `tts`: audio generation, upload, and persistence
- `postgres`, `redis`, `rabbitmq`, `ollama`: supporting infrastructure

## Run locally
1. Make sure Docker and Docker Compose are installed.
2. Copy `newscaster/.env_example` to `newscaster/.env`.
3. Fill in your NewsAPI key, database settings, JWT secret, and Google OAuth values.
4. Add your Google Cloud service account key at `newscaster/secrets/gcp-key.json`.
5. Make sure your Google Cloud Storage bucket matches the one expected by the app, or update the code/config.
6. From `newscaster/`, run:

```bash
docker compose up --build
```

7. Open `http://localhost:8000`.

## Key learnings
- How to design and coordinate a distributed workflow across multiple services instead of putting all processing into a single application.
- How to work with asynchronous pipelines, message queues, and background workers to make the system more modular and easier to extend.
- How much engineering work goes into product features beyond the core pipeline, especially authentication, search, playlists, analytics, and persistence.
- How important clean service boundaries, database migrations, configuration management, and deployment setup are when building software that is meant to feel production-ready.

## Future improvements
- Scaling: add better worker autoscaling, retries, and dead-letter handling for failed jobs.
- Monitoring: expand dashboards and alerting around queue health, worker latency, and audio generation failures.
- Configuration: make storage bucket names and provider settings fully configurable.
- Testing: add automated integration tests for the end-to-end generation pipeline.
- Security: move secrets to a proper secret manager and tighten production auth/config handling.
