# Newscaster

Newscaster is a production-style, microservice-driven platform that turns live news into short podcast episodes.

It combines article retrieval, LLM summarization, text-to-speech generation, cloud storage, and a full web product experience (search, playlists, sharing, and authentication).

## Demo

Live app (temporary domain): https://34-8-253-132.sslip.io

Product snapshot:

![Newscaster UI](assets/NewsCaster%20AI.png)

Recommended demo format (best for GitHub + interviews):

1. 60 to 120 second walkthrough video (Loom or YouTube unlisted)
2. Show this sequence in order:
  - Login with Google OAuth
  - Daily episodes list and playback
  - Custom generation with keywords or genre
  - Add episode to playlist and open shared playlist link
3. Add one line in the video description explaining architecture:
  - FastAPI + RabbitMQ + Fetcher + Summarizer + TTS + GCS + Postgres + Redis on GKE

What to keep in the demo section:

- One live URL
- One product screenshot
- One short walkthrough video
- One architecture sentence

This is enough for both technical and non-technical viewers without overwhelming them.

## Why this project

Following the news through social feeds is fast, but noisy. Newscaster was built to convert high-volume news into a structured listening experience that is easy to consume.

This project also serves as an end-to-end systems exercise: asynchronous workflows, cloud deployment, reliability hardening, and user-facing product design in one platform.

## Core capabilities

- Daily and custom podcast episode generation
- Search by query and date range
- Episode playback with transcript support
- Playlist creation, sharing, and management
- Google OAuth login
- Cloud-hosted audio persistence and retrieval

## System architecture

Request flow:

User request
-> FastAPI API
-> RabbitMQ queue
-> Fetcher service (NewsAPI)
-> Summarizer service (Ollama)
-> TTS service (Google Cloud TTS)
-> Google Cloud Storage + PostgreSQL + Redis
-> API serves episodes, playlists, and analytics

Service responsibilities:

- api: auth, frontend, search, playlists, analytics, orchestration
- fetcher: article ingestion and queue handoff
- summarizer: script generation using local LLM runtime
- tts: speech synthesis, object upload, and episode persistence
- postgres, redis, rabbitmq, ollama: data, caching, messaging, model runtime

## Notable engineering updates

- Migrated audio persistence to stable object references (gs://...) and now signs playback URLs at request time to avoid expired links for older episodes.
- Added startup migration retry logic to improve resilience during service/database startup races.
- Added health probes and resource limits/requests across Kubernetes workloads.
- Added API Horizontal Pod Autoscaler and enabled cluster/node autoscaling to reduce idle cost.
- Enabled HTTPS ingress with managed certificate for OAuth-compatible public access.

## Tech stack

- Backend: FastAPI, Python
- Messaging: RabbitMQ
- Data: PostgreSQL, Redis
- LLM summarization: Ollama
- TTS and object storage: Google Cloud Text-to-Speech, Google Cloud Storage
- Containers and orchestration: Docker, Kubernetes (GKE)
- Observability manifests: Prometheus, Grafana

## Run locally (Docker)

1. Copy newscaster/.env_example to newscaster/.env
2. Fill environment values (NewsAPI, DB, JWT, OAuth)
3. Add Google service account key at newscaster/secrets/gcp-key.json
4. From the newscaster directory, run:

  docker compose up --build

5. Open http://localhost:8000

## Deploy updates to GKE

Important: frontend assets are served by the API container, so UI changes require rebuilding and redeploying the API image.

From newscaster:

1. Build and push API image (use a new tag each time):

  docker buildx build --platform linux/amd64 -f api/Dockerfile -t us-central1-docker.pkg.dev/newscaster-487321/newscaster-repo/newscaster-api:<new-tag> --push .

2. Roll the API deployment:

  kubectl -n newscaster set image deployment/api api=us-central1-docker.pkg.dev/newscaster-487321/newscaster-repo/newscaster-api:<new-tag>
  kubectl -n newscaster rollout status deployment/api

Key Kubernetes manifests are in newscaster/k8s.

## Current deployment snapshot

- Public ingress with HTTPS: newscaster/k8s/ingress.yaml
- API autoscaling policy: newscaster/k8s/autoscaling.yaml
- Core service deployments: newscaster/k8s/*.yaml

## Roadmap

- Move secrets to a managed secret solution (for example, Secret Manager integration)
- Split node pools for stateful vs elastic workloads to improve cost/performance isolation
- Add stronger queue retry and dead-letter handling
- Expand integration and end-to-end pipeline tests
