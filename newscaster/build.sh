#!/bin/bash

# docker build --no-cache -t newscaster-api:latest newscaster/api/
# docker build --no-cache -t newscaster-fetcher:latest newscaster/fetcher/
# docker build --no-cache -t newscaster-summarizer:latest newscaster/summarizer/
# docker build --no-cache -t newscaster-tts:latest newscaster/tts/

# Build all images with no cache
docker build -t newscaster-api:latest newscaster/api/
docker build -t newscaster-fetcher:latest newscaster/fetcher/
docker build -t newscaster-summarizer:latest newscaster/summarizer/
docker build -t newscaster-tts:latest newscaster/tts/