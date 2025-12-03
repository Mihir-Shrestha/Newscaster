#!/bin/bash

# Build all images with no cache
docker build --no-cache -t newscaster-api:latest api/
docker build --no-cache -t newscaster-fetcher:latest fetcher/
docker build --no-cache -t newscaster-summarizer:latest summarizer/
docker build --no-cache -t newscaster-tts:latest tts/