# NewsCaster AI - Automated Podcast Generation System

A production-style cloud-native application that automatically generates daily podcasts summarizing trending world news.

## Project Overview

NewsCaster AI is an automated system that:
- Fetches trending articles via **NewsAPI**
- Summarizes content using **OpenAI API**
- Converts summaries to audio via **Google Cloud TTS**
- Delivers episodes through an **RSS feed**

Built as a distributed microservices architecture demonstrating message queues, workers, orchestration, and cloud storage.

## System Architecture

### Core Components

| Component | Purpose | Why Chosen |
|-----------|---------|-----------|
| FastAPI | Public API + RSS feed | Fast, async, ideal for microservices |
| RabbitMQ | Message queue | Reliable AMQP, durable queues, K8s-ready |
| Redis | Job state tracking | High-speed KV store for metadata |
| OpenAI | Text summarization | High-quality summaries |
| Google Cloud TTS | Text-to-speech | Natural voice synthesis |
| Docker | Containerization | Portable, consistent environments |
| Kubernetes | Orchestration | Production-grade deployment |
| Prometheus + Grafana | Monitoring | Metrics and visualization |
| Google Cloud Storage | MP3 storage | Scalable object storage |

### Data Flow

![Newscaster Data Flow](./assets/NewsCaster%20AI.png)

```
1. Trigger (manual or 6 AM CronJob)
   ↓
2. RabbitMQ (to_fetcher)
   ↓
3. Fetcher → NewsAPI → Extract articles
   ↓
4. RabbitMQ (to_summarizer)
   ↓
5. Summarizer → OpenAI → Generate script
   ↓
6. RabbitMQ (to_tts)
   ↓
7. TTS → Google Cloud TTS → MP3 file
   ↓
8. Upload to Google Cloud Storage
   ↓
9. Save metadata to Redis
   ↓
10. API serves RSS feed & episodes
```

## Microservices Workflows

### Episode Generation

**Manual Trigger:**
- User clicks "Generate New Episode" in FastAPI UI
- API publishes message → `to_fetcher` queue

**Automatic Trigger:**
- Kubernetes CronJob launches at 6 AM
- Fetcher automatically fetches from NewsAPI

### Fetcher Service
1. Receives job_id from queue
2. Calls NewsAPI for top 10 articles
3. Extracts: title, content, URL
4. Publishes to `to_summarizer` queue

### Summarizer Service
1. Receives articles from queue
2. Uses OpenAI API for podcast-style summarization
3. Generates: full script + headline list
4. Publishes to `to_tts` queue

### TTS Service
1. Receives script from queue
2. Initializes Google Cloud TTS client
3. Generates MP3 file (`/output/<job_id>_final.mp3`)
4. Uploads to GCS bucket
5. Stores metadata in Redis

## API Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /episodes` | List all episodes |
| `GET /episodes/{id}/audio` | Redirect to GCS signed URL |
| `GET /latest` | Latest episode metadata |
| `GET /rss.xml` | RSS feed |
| `POST /generate` | Trigger manual episode generation |

## Kubernetes Deployment

**Deployments:**
- API Service
- Fetcher Worker
- Summarizer
- TTS Worker
- Redis
- RabbitMQ
- Prometheus + Grafana

**Services:**
- `api.newscaster.svc.cluster.local`
- `redis.newscaster.svc.cluster.local`
- `rabbitmq.newscaster.svc.cluster.local`

## Monitoring

Prometheus scrapes metrics for:
- Pod restart frequency
- Queue throughput
- Worker latency
- Container resource usage

Grafana dashboards visualize performance in real-time.

## Capabilities & Limitations

### Capabilities
- Fully automated daily podcast generation (6 AM + manual)  
- Modular microservices architecture  
- Cloud-native with K8s auto-scaling  
- Observable with Prometheus/Grafana  

### Known Limitations

| Bottleneck | Reason | Possible Fix |
|-----------|--------|-------------|
| Summarizer latency | LLM API response time | Scale worker replicas; use faster model |
| TTS cost | Per-character pricing | Cache phrases; compress speech |
| Credentials management | Hardcoded secrets | Use External Secrets Manager |

---

**Built for:** CSCI 5253 - Cloud Computing Project (Fall 2025)